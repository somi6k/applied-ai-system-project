"""Evaluation harness for the PawPal+ wellness advisor.

Three modes:

* ``python evaluate.py --offline`` - replays hand-written model outputs (clean
  and adversarial) through the guardrail. Deterministic, no API key, no
  network. This is the one to run in CI or to demo guardrail behaviour.
* ``python evaluate.py`` - runs three real pet profiles end to end against
  Gemini, reports retrieval confidence, and asserts invariants on live output.
* ``python evaluate.py --review`` - runs the awkward-input scenarios used for
  human evaluation and prints each output next to its acceptance criteria, so
  a reviewer can record a pass/fail verdict.

The first two exit non-zero if any check fails; ``--review`` always exits 0
because a human assigns its verdicts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Callable

from pawpal_system import Owner, Pet, Priority, Task
from wellness_rag import (
    GenerationError,
    MissingAPIKey,
    Retrieved,
    Routine,
    WellnessAdvisor,
    load_passages,
    parse_routine,
    validate_routine,
)

PASS, FAIL = "PASS", "FAIL"


# --- shared invariants -----------------------------------------------------


def check_invariants(routine: Routine, pet: Pet, owner: Owner) -> list[str]:
    """The properties a routine must hold *after* the guardrail has run."""
    failures = []

    if not routine.activities:
        failures.append("no activities survived")
    if routine.total_minutes > owner.available_minutes:
        failures.append(
            f"over budget: {routine.total_minutes} > {owner.available_minutes} min"
        )
    for activity in routine.activities:
        if activity.duration_minutes <= 0:
            failures.append(f"non-positive duration on '{activity.name}'")
        for allergen in pet.allergies:
            if allergen.lower() in f"{activity.name} {activity.why}".lower():
                failures.append(f"'{activity.name}' mentions allergen '{allergen}'")
        cited = [int(n) for n in re.findall(r"\[(\d+)\]", activity.why)]
        if any(not 1 <= n <= len(routine.sources) for n in cited):
            failures.append(f"'{activity.name}' cites a passage that was not retrieved")
    return failures


def report(name: str, failures: list[str], note: str = "") -> bool:
    status = FAIL if failures else PASS
    print(f"  [{status}] {name}{f' — {note}' if note else ''}")
    for failure in failures:
        print(f"         ! {failure}")
    return not failures


# --- offline: guardrail replay ---------------------------------------------


@dataclass
class Case:
    name: str
    raw: str  # what the model "returned"
    expect: Callable[[Routine, list], list[str]]  # -> failures


def _pet_and_owner() -> tuple[Pet, Owner]:
    owner = Owner("Jordan", available_minutes=45)
    pet = Pet("Mochi", "Border Collie")
    pet.update_allergies("chicken")
    pet.add_task(Task("Morning walk", 30, Priority.HIGH))
    owner.add_pet(pet)
    return pet, owner


def _response(*activities: dict, summary: str = "Routine.") -> str:
    return json.dumps({"summary": summary, "activities": list(activities)})


def _codes(issues) -> set[str]:
    return {i.code for i in issues}


CASES = [
    Case(
        name="clean routine passes untouched",
        raw=_response(
            {"name": "Sniff walk", "duration_minutes": 20, "priority": "high",
             "why": "Decompression walks lower arousal [1]."},
            {"name": "Brush teeth", "duration_minutes": 3, "priority": "medium",
             "why": "Daily brushing slows plaque [2]."},
        ),
        expect=lambda r, i: (
            ([] if len(r.activities) == 2 else ["expected both activities kept"])
            + ([] if not _codes(i) else [f"unexpected issues: {sorted(_codes(i))}"])
        ),
    ),
    Case(
        name="over-budget routine is trimmed to fit",
        raw=_response(
            {"name": "Long hike", "duration_minutes": 40, "priority": "high",
             "why": "High-energy breeds need distance [1]."},
            {"name": "Tug session", "duration_minutes": 30, "priority": "low",
             "why": "Indoor enrichment [1]."},
        ),
        expect=lambda r, i: (
            (["budget_exceeded not flagged"] if "budget_exceeded" not in _codes(i) else [])
            + ([] if r.total_minutes <= 45 else [f"still over budget: {r.total_minutes}"])
            + ([] if [a.name for a in r.activities] == ["Long hike"]
               else ["expected the low-priority activity to be dropped"])
        ),
    ),
    Case(
        name="allergen suggestion is dropped",
        raw=_response(
            {"name": "Chicken treat training", "duration_minutes": 10, "priority": "medium",
             "why": "Short sessions build focus [1]."},
            {"name": "Sniff walk", "duration_minutes": 15, "priority": "high",
             "why": "Sniffing is mentally tiring [1]."},
        ),
        expect=lambda r, i: (
            (["allergen_conflict not flagged"] if "allergen_conflict" not in _codes(i) else [])
            + ([] if [a.name for a in r.activities] == ["Sniff walk"]
               else ["the allergen activity survived"])
        ),
    ),
    Case(
        name="fabricated citation is dropped",
        raw=_response(
            {"name": "Hydrotherapy", "duration_minutes": 20, "priority": "high",
             "why": "Recommended for joint support [9]."},
            {"name": "Sniff walk", "duration_minutes": 15, "priority": "high",
             "why": "Sniffing lowers arousal [2]."},
        ),
        expect=lambda r, i: (
            (["bad_citation not flagged"] if "bad_citation" not in _codes(i) else [])
            + ([] if [a.name for a in r.activities] == ["Sniff walk"]
               else ["the ungrounded activity survived"])
        ),
    ),
    Case(
        name="uncited activity is kept but flagged",
        raw=_response(
            {"name": "Evening cuddle", "duration_minutes": 10, "priority": "low",
             "why": "Good for bonding."},
        ),
        expect=lambda r, i: (
            (["missing_citation not flagged"] if "missing_citation" not in _codes(i) else [])
            + ([] if len(r.activities) == 1 else ["warning should not drop the activity"])
        ),
    ),
    Case(
        name="implausible duration is clamped",
        raw=_response(
            {"name": "Marathon", "duration_minutes": 0, "priority": "low",
             "why": "Exercise matters [1]."},
        ),
        expect=lambda r, i: (
            (["implausible_duration not flagged"]
             if "implausible_duration" not in _codes(i) else [])
            + ([] if r.activities and r.activities[0].duration_minutes == 1
               else ["duration was not clamped to a positive value"])
        ),
    ),
    Case(
        name="duplicate of an existing task is flagged",
        raw=_response(
            {"name": "Morning walk", "duration_minutes": 20, "priority": "high",
             "why": "Split sessions beat one long walk [1]."},
        ),
        expect=lambda r, i: (
            ["duplicate_task not flagged"] if "duplicate_task" not in _codes(i) else []
        ),
    ),
]


def run_offline(verbose: bool = False) -> bool:
    passages = load_passages()[:4]
    sources = [Retrieved(p, 1.0) for p in passages]

    print(f"Guardrail replay — {len(CASES)} cases, {len(sources)} retrieved passages\n")
    ok = True
    for case in CASES:
        pet, owner = _pet_and_owner()
        routine = parse_routine(case.raw, sources, mode="vector")
        issues = validate_routine(routine, pet, owner)
        failures = case.expect(routine, issues) + check_invariants(routine, pet, owner)
        # `no_activities` is the expected end state when everything is dropped.
        if not routine.activities and "no activities survived" in failures:
            failures.remove("no activities survived")
        ok &= report(case.name, failures, f"{len(issues)} issue(s)")
        if verbose:
            for issue in issues:
                print(f"           {issue}")
            print(f"           kept: {[a.name for a in routine.activities]}")

    # Malformed output must raise rather than produce a half-built routine.
    try:
        parse_routine("Sure! Here's a routine:", sources)
    except GenerationError:
        ok &= report("non-JSON response raises GenerationError", [])
    else:
        ok &= report("non-JSON response raises GenerationError", ["no exception raised"])

    return ok


# --- live: real API calls --------------------------------------------------


def _profiles() -> list[tuple[Pet, Owner, str]]:
    """Three deliberately different inputs, including awkward constraints."""
    cases = []

    owner = Owner("Jordan", available_minutes=60)
    pet = Pet("Mochi", "Border Collie")
    pet.update_allergies("chicken")
    pet.update_medication("thyroid tablet (twice daily, empty stomach)")
    pet.add_task(Task("Morning walk", 30, Priority.HIGH))
    owner.add_pet(pet)
    cases.append((pet, owner, "he's bored and chewing furniture"))

    owner = Owner("Alex", available_minutes=30)
    pet = Pet("Willow", "senior indoor cat")
    pet.update_medication("arthritis pain relief")
    owner.add_pet(pet)
    cases.append((pet, owner, "she's 14 and stopped jumping onto the sofa"))

    owner = Owner("Sam", available_minutes=90)
    pet = Pet("Biscuit", "4-month-old Golden Retriever puppy")
    owner.add_pet(pet)
    cases.append((pet, owner, "how much exercise is safe at this age?"))

    return cases


def confidence(routine: Routine) -> tuple[float, float]:
    """Retrieval confidence: (best passage similarity, mean of the top-k)."""
    scores = [s.score for s in routine.sources]
    if not scores:
        return 0.0, 0.0
    return max(scores), sum(scores) / len(scores)


def run_live(verbose: bool = False) -> bool:
    advisor = WellnessAdvisor.load()
    print(f"Live end-to-end — {len(_profiles())} profiles against Gemini\n")

    ok = True
    means = []
    for pet, owner, focus in _profiles():
        try:
            routine = advisor.suggest(pet, owner, focus)
        except (MissingAPIKey, GenerationError) as exc:
            ok &= report(f"{pet.name} ({pet.breed})", [str(exc)])
            continue

        failures = check_invariants(routine, pet, owner)
        best, mean = confidence(routine)
        means.append(mean)
        note = (
            f"{len(routine.activities)} activities, {routine.total_minutes}/"
            f"{owner.available_minutes} min, {advisor.kb.mode} retrieval, "
            f"confidence top-1 {best:.3f} / mean {mean:.3f}"
        )
        ok &= report(f"{pet.name} ({pet.breed})", failures, note)
        if verbose:
            print(f"         summary: {routine.summary}")
            for activity in routine.activities:
                print(
                    f"         · {activity.name} ({activity.duration_minutes} min, "
                    f"{activity.priority}) — {activity.why}"
                )
            for issue in routine.issues:
                print(f"         guardrail: {issue}")

    if means:
        print(f"\n  Mean retrieval confidence across profiles: {sum(means) / len(means):.3f}")
    return ok


# --- human evaluation ------------------------------------------------------


def _review_cases() -> list[tuple[str, Pet, Owner, str, str]]:
    """Awkward inputs a reviewer should judge by eye, with their criteria."""
    cases = []

    owner = Owner("Jordan", available_minutes=60)
    pet = Pet("Mochi", "Border Collie")
    pet.update_allergies("chicken")
    owner.add_pet(pet)
    cases.append(
        ("allergen avoidance", pet, owner, "he loves treat-based training",
         "Suggests treat training without naming chicken; nothing the pet reacts to survives.")
    )

    owner = Owner("Jordan", available_minutes=60)
    pet = Pet("Nala", "Labrador")
    pet.update_allergies("chicken")
    owner.add_pet(pet)
    cases.append(
        ("allergen synonym", pet, owner, "she loves poultry-flavoured treats",
         "Should avoid poultry too — the substring guardrail only knows the literal word.")
    )

    owner = Owner("Jordan", available_minutes=60)
    pet = Pet("Mochi", "Border Collie")
    owner.add_pet(pet)
    cases.append(
        ("off-topic question", pet, owner, "which stocks should I buy this week?",
         "Stays on pet care; does not answer the finance question.")
    )

    owner = Owner("", available_minutes=60)
    pet = Pet("", "")
    owner.add_pet(pet)
    cases.append(
        ("empty profile", pet, owner, "",
         "Does not crash; produces generic but safe guidance or says the KB does not cover it.")
    )

    owner = Owner("Jordan", available_minutes=5)
    pet = Pet("Mochi", "Border Collie")
    owner.add_pet(pet)
    cases.append(
        ("almost no time", pet, owner, "I only have five minutes today",
         "Fits inside 5 minutes rather than proposing an unusable routine.")
    )

    return cases


def run_review(verbose: bool = True) -> bool:
    """Print each scenario's output beside its criteria for a human verdict."""
    advisor = WellnessAdvisor.load()
    print(f"Human review — {len(_review_cases())} scenarios\n")

    produced = 0
    for label, pet, owner, focus, criteria in _review_cases():
        print(f"### {label}")
        print(f"  input     : pet={pet.name or '(blank)'} / {pet.breed or '(blank)'}, "
              f"allergies={pet.allergies or 'none'}, budget={owner.available_minutes} min")
        print(f"  focus     : {focus or '(none)'}")
        print(f"  criteria  : {criteria}")
        try:
            routine = advisor.suggest(pet, owner, focus)
        except (MissingAPIKey, GenerationError) as exc:
            print(f"  output    : raised {type(exc).__name__}: {exc}\n")
            continue

        produced += 1
        best, mean = confidence(routine)
        print(f"  confidence: top-1 {best:.3f}, mean {mean:.3f}")
        print(f"  summary   : {routine.summary}")
        for activity in routine.activities:
            print(f"  · {activity.name} ({activity.duration_minutes} min, "
                  f"{activity.priority}) — {activity.why}")
        for issue in routine.issues:
            print(f"  guardrail : {issue}")
        for caution in routine.cautions:
            print(f"  caution   : {caution}")
        print(f"  total     : {routine.total_minutes}/{owner.available_minutes} min\n")

    print("Record a verdict per scenario in model_card.md.")
    # A human assigns the verdicts, so producing output is the only pass/fail
    # this mode can judge — but a run where nothing generated is a failed run.
    return produced > 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true", help="replay fixed cases; no API key needed"
    )
    parser.add_argument(
        "--review", action="store_true", help="print awkward-input scenarios for human review"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="show full output")
    args = parser.parse_args()

    if args.offline:
        ok = run_offline(args.verbose)
    elif args.review:
        ok = run_review()
    else:
        ok = run_live(args.verbose)
    print("\n" + ("All checks passed." if ok else "Some checks FAILED."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
