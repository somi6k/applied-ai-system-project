"""Tests for the RAG layer. No network: a fake embedder stands in for Gemini."""

import json

import pytest

from pawpal_system import Owner, Pet, Priority, Task
from wellness_rag import (
    Activity,
    GenerationError,
    KnowledgeBase,
    MissingAPIKey,
    Passage,
    Retrieved,
    Routine,
    WellnessAdvisor,
    _client,
    build_profile,
    cosine_similarity,
    format_context,
    keyword_similarity,
    load_passages,
    parse_routine,
    split_document,
    validate_routine,
)

DOC = """# Dog exercise

Preamble that belongs to no section.

## Daily walks

Most adult dogs need two walks a day totalling about sixty minutes.

## Empty section

## Dental care

Brush the dog's teeth daily with enzymatic pet toothpaste.
"""


@pytest.fixture
def knowledge_dir(tmp_path):
    (tmp_path / "dog.md").write_text(DOC, encoding="utf-8")
    (tmp_path / "cat.md").write_text(
        "# Cat enrichment\n\n## Play sessions\n\nCats hunt in short bursts.\n",
        encoding="utf-8",
    )
    return tmp_path


class FakeEmbedder:
    """Deterministic 3-dim vectors keyed by topic words; records its calls."""

    def __init__(self):
        self.calls = []

    def embed(self, texts, *, task_type):
        self.calls.append((list(texts), task_type))
        vectors = []
        for text in texts:
            lowered = text.lower()
            vectors.append(
                [
                    float(lowered.count("walk") + lowered.count("exercise")),
                    float(lowered.count("teeth") + lowered.count("dental")),
                    float(lowered.count("cat") + lowered.count("play")),
                ]
            )
        return vectors


# --- chunking --------------------------------------------------------------


def test_split_document_creates_one_passage_per_heading():
    passages = split_document(DOC, "dog.md")

    # Preamble is not a passage, and the empty heading is dropped.
    assert [p.title for p in passages] == ["Daily walks", "Dental care"]
    assert all(p.doc_title == "Dog exercise" for p in passages)
    assert passages[0].label == "Dog exercise - Daily walks"


def test_passage_content_includes_titles_for_retrieval():
    passage = split_document(DOC, "dog.md")[0]

    assert passage.content.startswith("Dog exercise\nDaily walks\n")


def test_load_passages_reads_every_markdown_file(knowledge_dir):
    passages = load_passages(knowledge_dir)

    assert {p.source for p in passages} == {"dog.md", "cat.md"}


def test_load_passages_rejects_a_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_passages(tmp_path / "nope")


def test_bundled_knowledge_base_is_non_empty():
    # Guards against a chunking regression against the real corpus.
    passages = load_passages()

    assert len(passages) > 10
    assert all(p.text for p in passages)


# --- similarity ------------------------------------------------------------


def test_cosine_similarity_of_identical_vectors_is_one():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_ignores_magnitude():
    assert cosine_similarity([1.0, 0.0], [5.0, 0.0]) == pytest.approx(1.0)


def test_cosine_similarity_of_zero_vector_is_zero():
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_keyword_similarity_prefers_the_matching_passage():
    dental, walks = split_document(DOC, "dog.md")[1], split_document(DOC, "dog.md")[0]

    query = "brushing teeth and dental hygiene"

    assert keyword_similarity(query, dental) > keyword_similarity(query, walks)


def test_keyword_similarity_of_an_empty_query_is_zero():
    passage = split_document(DOC, "dog.md")[0]

    assert keyword_similarity("", passage) == 0.0


# --- retrieval -------------------------------------------------------------


def _kb(knowledge_dir, tmp_path, embedder=None):
    return KnowledgeBase.load(
        knowledge_dir, embedder=embedder, cache_path=tmp_path / "cache.json"
    )


def test_vector_retrieval_ranks_by_cosine_similarity(knowledge_dir, tmp_path):
    kb = _kb(knowledge_dir, tmp_path, FakeEmbedder())

    results = kb.retrieve("dental teeth", k=1)

    assert kb.mode == "vector"
    assert results[0].passage.title == "Dental care"


def test_retrieve_returns_at_most_k_and_drops_zero_scores(knowledge_dir, tmp_path):
    kb = _kb(knowledge_dir, tmp_path, FakeEmbedder())

    assert len(kb.retrieve("walk", k=2)) <= 2
    # Nothing in the corpus shares a topic word with this query.
    assert kb.retrieve("quantum tensor algebra") == []


def test_query_uses_the_retrieval_query_task_type(knowledge_dir, tmp_path):
    embedder = FakeEmbedder()
    kb = _kb(knowledge_dir, tmp_path, embedder)

    kb.retrieve("walk")

    assert embedder.calls[0][1] == "RETRIEVAL_DOCUMENT"
    assert embedder.calls[-1][1] == "RETRIEVAL_QUERY"


def test_embeddings_are_cached_across_knowledge_bases(knowledge_dir, tmp_path):
    first = FakeEmbedder()
    _kb(knowledge_dir, tmp_path, first).ensure_embeddings()
    assert first.calls  # cold: embedded the corpus

    second = FakeEmbedder()
    assert _kb(knowledge_dir, tmp_path, second).ensure_embeddings() is True
    assert second.calls == []  # warm: served entirely from the cache file


def test_edited_passage_is_re_embedded(knowledge_dir, tmp_path):
    _kb(knowledge_dir, tmp_path, FakeEmbedder()).ensure_embeddings()

    (knowledge_dir / "cat.md").write_text(
        "# Cat enrichment\n\n## Play sessions\n\nRewritten guidance.\n", encoding="utf-8"
    )
    embedder = FakeEmbedder()
    _kb(knowledge_dir, tmp_path, embedder).ensure_embeddings()

    # Only the changed passage misses the cache.
    assert [len(texts) for texts, _ in embedder.calls] == [1]


def test_corrupt_cache_falls_back_to_re_embedding(knowledge_dir, tmp_path):
    (tmp_path / "cache.json").write_text("{not json", encoding="utf-8")
    embedder = FakeEmbedder()

    assert _kb(knowledge_dir, tmp_path, embedder).ensure_embeddings() is True
    assert embedder.calls


def test_missing_embedder_degrades_to_keyword_search(knowledge_dir, tmp_path):
    # Constructed directly, not via load(): passing embedder=None to load()
    # means "use Gemini if a key is configured", which depends on the env.
    kb = KnowledgeBase(
        passages=load_passages(knowledge_dir),
        embedder=None,
        cache_path=tmp_path / "cache.json",
    )

    results = kb.retrieve("cats playing", k=1)

    assert kb.mode == "keyword"
    assert "keyword" in kb.warning
    assert results[0].passage.title == "Play sessions"


def test_embedder_failure_degrades_instead_of_raising(knowledge_dir, tmp_path):
    class BrokenEmbedder:
        def embed(self, texts, *, task_type):
            raise RuntimeError("network down")

    kb = _kb(knowledge_dir, tmp_path, BrokenEmbedder())

    results = kb.retrieve("dental teeth", k=1)

    assert kb.mode == "keyword"
    assert "network down" in kb.warning
    assert results[0].passage.title == "Dental care"


def test_empty_knowledge_base_retrieves_nothing(tmp_path):
    assert KnowledgeBase(passages=[]).retrieve("anything") == []


# --- prompt building -------------------------------------------------------


def _pet_and_owner():
    owner = Owner("Jordan", available_minutes=45)
    pet = Pet("Mochi", "Beagle")
    pet.update_allergies("chicken")
    pet.update_medication("thyroid tablet")
    pet.add_task(Task("Morning walk", 30, Priority.HIGH))
    owner.add_pet(pet)
    return pet, owner


def test_profile_includes_health_details_and_budget():
    pet, owner = _pet_and_owner()

    profile = build_profile(pet, owner, focus="she's gaining weight")

    assert "Mochi" in profile and "Beagle" in profile
    assert "chicken" in profile and "thyroid tablet" in profile
    assert "Morning walk (30 min, high)" in profile
    assert "45 minutes" in profile
    assert "gaining weight" in profile


def test_profile_omits_empty_fields():
    profile = build_profile(Pet("Ghost", "cat"))

    assert "Allergies" not in profile
    assert "Owner time available" not in profile


def test_format_context_numbers_passages_for_citation():
    passages = split_document(DOC, "dog.md")
    results = [Retrieved(p, 0.9) for p in passages]

    context = format_context(results)

    assert context.startswith("[1] Dog exercise - Daily walks")
    assert "[2] Dog exercise - Dental care" in context


# --- parsing the model's JSON ----------------------------------------------


RESPONSE = json.dumps(
    {
        "summary": "Mochi needs weight-focused activity.",
        "activities": [
            {
                "name": "Sniff walk",
                "duration_minutes": 20,
                "priority": "high",
                "time_of_day": "morning",
                "why": "Decompression walks lower arousal [1].",
            },
            {"name": "Brush teeth", "duration_minutes": 3, "priority": "low", "why": "[2]"},
        ],
        "cautions": ["Sudden exercise intolerance warrants a vet visit."],
    }
)


def test_parse_routine_reads_activities_and_cautions():
    routine = parse_routine(RESPONSE, sources=[], mode="vector")

    assert routine.summary.startswith("Mochi")
    assert [a.name for a in routine.activities] == ["Sniff walk", "Brush teeth"]
    assert routine.activities[0].time_of_day == "morning"
    assert routine.total_minutes == 23
    assert len(routine.cautions) == 1


def test_parse_routine_skips_a_malformed_activity():
    raw = json.dumps(
        {
            "summary": "s",
            "activities": [
                {"name": "Good", "duration_minutes": 10, "priority": "low"},
                {"name": "No duration"},
                {"name": "Bad duration", "duration_minutes": "twenty"},
            ],
        }
    )

    routine = parse_routine(raw, sources=[])

    assert [a.name for a in routine.activities] == ["Good"]


def test_parse_routine_rejects_non_json():
    with pytest.raises(GenerationError):
        parse_routine("Sure! Here's a routine:", sources=[])


# --- handing results back to the scheduler ---------------------------------


def test_activities_convert_to_schedulable_tasks():
    routine = parse_routine(RESPONSE, sources=[])

    tasks = routine.to_tasks()

    assert [t.name for t in tasks] == ["Sniff walk", "Brush teeth"]
    assert tasks[0].duration == 20
    assert tasks[0].priority is Priority.HIGH
    assert tasks[1].priority is Priority.LOW
    assert all(t.status == "pending" for t in tasks)


def test_unknown_priority_falls_back_to_medium():
    assert Activity("X", 10, priority="urgent").to_task().priority is Priority.MEDIUM


def test_zero_duration_is_clamped_to_one_minute():
    # Scheduler.generate_plan assumes a positive duration.
    assert Activity("X", 0).to_task().duration == 1


def test_suggested_tasks_can_be_scheduled(knowledge_dir, tmp_path):
    from pawpal_system import Scheduler

    pet, owner = _pet_and_owner()
    for task in parse_routine(RESPONSE, sources=[]).to_tasks():
        pet.add_task(task)

    plan = Scheduler(owner).generate_plan()

    assert "Sniff walk" in [t.name for t in plan]


# --- API-key handling ------------------------------------------------------


def test_generation_without_an_api_key_raises_missing_key(
    knowledge_dir, tmp_path, monkeypatch
):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr("wellness_rag._load_dotenv", lambda *a, **k: None)
    pet, owner = _pet_and_owner()
    advisor = WellnessAdvisor(kb=_kb(knowledge_dir, tmp_path))

    with pytest.raises(MissingAPIKey):
        advisor.suggest(pet, owner)


def test_client_without_a_key_raises_before_importing_the_sdk(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr("wellness_rag._load_dotenv", lambda *a, **k: None)

    with pytest.raises(MissingAPIKey, match="aistudio.google.com"):
        _client()


def test_retrieval_still_works_without_an_api_key(knowledge_dir, tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr("wellness_rag._load_dotenv", lambda *a, **k: None)
    pet, owner = _pet_and_owner()
    advisor = WellnessAdvisor(kb=_kb(knowledge_dir, tmp_path))

    assert advisor.retrieve(pet, owner, focus="teeth")


# --- guardrail -------------------------------------------------------------


def _sources(n: int = 4) -> list[Retrieved]:
    return [
        Retrieved(Passage("k.md", "Doc", f"Section {i}", "body"), 1.0)
        for i in range(1, n + 1)
    ]


def _routine(*activities: Activity, sources: int = 4) -> Routine:
    return Routine(summary="s", activities=list(activities), sources=_sources(sources))


def _codes(issues) -> set[str]:
    return {i.code for i in issues}


def test_clean_routine_passes_with_no_issues():
    pet, owner = _pet_and_owner()  # 45 min budget, allergic to chicken
    routine = _routine(
        Activity("Sniff walk", 20, "high", why="Lowers arousal [1]."),
        Activity("Brush teeth", 3, "medium", why="Slows plaque [2]."),
    )

    assert validate_routine(routine, pet, owner) == []
    assert len(routine.activities) == 2


def test_activity_naming_an_allergen_is_dropped():
    pet, owner = _pet_and_owner()
    routine = _routine(
        Activity("Chicken treat training", 10, "medium", why="Builds focus [1]."),
        Activity("Sniff walk", 15, "high", why="Mentally tiring [1]."),
    )

    issues = validate_routine(routine, pet, owner)

    assert "allergen_conflict" in _codes(issues)
    assert [a.name for a in routine.activities] == ["Sniff walk"]


def test_allergen_named_only_in_an_avoidance_phrase_is_kept():
    # Regression: the first guardrail matched the raw substring, so an activity
    # that mentioned the allergen *in order to avoid it* was wrongly dropped.
    pet, owner = _pet_and_owner()
    routine = _routine(
        Activity("Kibble reward training", 10, "medium",
                 why="Use her regular chicken-free kibble as rewards [1]."),
        Activity("Portion meals", 5, "low",
                 why="Measure portions, respecting her chicken allergy [2]."),
    )

    assert validate_routine(routine, pet, owner) == []
    assert len(routine.activities) == 2


def test_allergen_offered_as_a_reward_is_still_dropped():
    pet, owner = _pet_and_owner()
    routine = _routine(
        Activity("Reward training", 10, "medium", why="Reward with chicken strips [1].")
    )

    assert "allergen_conflict" in _codes(validate_routine(routine, pet, owner))


def test_citation_past_the_retrieved_passages_is_dropped():
    pet, owner = _pet_and_owner()
    routine = _routine(
        Activity("Hydrotherapy", 10, "high", why="Good for joints [9]."),
        Activity("Sniff walk", 15, "high", why="Lowers arousal [2]."),
    )

    issues = validate_routine(routine, pet, owner)

    assert "bad_citation" in _codes(issues)
    assert [a.name for a in routine.activities] == ["Sniff walk"]


def test_uncited_activity_is_warned_but_kept():
    pet, owner = _pet_and_owner()
    routine = _routine(Activity("Evening cuddle", 10, "low", why="Nice for bonding."))

    issues = validate_routine(routine, pet, owner)

    assert [i.severity for i in issues] == ["warning"]
    assert len(routine.activities) == 1


def test_over_budget_routine_drops_lowest_priority_first():
    pet, owner = _pet_and_owner()  # 45 minutes available
    routine = _routine(
        Activity("Long hike", 40, "high", why="Distance work [1]."),
        Activity("Tug session", 30, "low", why="Indoor enrichment [1]."),
    )

    issues = validate_routine(routine, pet, owner)

    assert "budget_exceeded" in _codes(issues)
    assert [a.name for a in routine.activities] == ["Long hike"]
    assert routine.total_minutes <= owner.available_minutes


def test_budget_trim_keeps_original_ordering():
    owner = Owner("Jordan", available_minutes=25)
    pet = Pet("Mochi", "dog")
    owner.add_pet(pet)
    routine = _routine(
        Activity("First", 10, "high", why="[1]"),
        Activity("Dropped", 30, "low", why="[1]"),
        Activity("Third", 10, "high", why="[1]"),
    )

    validate_routine(routine, pet, owner)

    assert [a.name for a in routine.activities] == ["First", "Third"]


def test_implausible_durations_are_clamped():
    pet, owner = _pet_and_owner()
    routine = _routine(
        Activity("Zero", 0, "low", why="[1]"), Activity("Huge", 9999, "low", why="[1]")
    )

    issues = validate_routine(routine, pet, owner)

    assert list(_codes(issues)) != []
    assert routine.activities[0].duration_minutes == 1


def test_duplicate_of_an_existing_task_is_flagged_not_dropped():
    pet, owner = _pet_and_owner()  # already has "Morning walk"
    routine = _routine(Activity("morning walk", 20, "high", why="Split sessions [1]."))

    issues = validate_routine(routine, pet, owner)

    assert "duplicate_task" in _codes(issues)
    assert len(routine.activities) == 1


def test_empty_result_reports_no_activities():
    pet, owner = _pet_and_owner()
    routine = _routine(Activity("Chicken feast", 10, "low", why="[1]"))

    issues = validate_routine(routine, pet, owner)

    assert "no_activities" in _codes(issues)
    assert routine.activities == []


def test_repair_false_reports_without_mutating():
    pet, owner = _pet_and_owner()
    routine = _routine(Activity("Chicken treats", 60, "low", why="[9]"))

    issues = validate_routine(routine, pet, owner, repair=False)

    assert _codes(issues) >= {"bad_citation", "allergen_conflict"}
    assert len(routine.activities) == 1  # untouched
    assert routine.issues == []


def test_guardrail_findings_are_recorded_on_the_routine():
    pet, owner = _pet_and_owner()
    routine = _routine(Activity("Chicken treats", 10, "low", why="[1]"))

    validate_routine(routine, pet, owner)

    assert [i.code for i in routine.issues] == ["allergen_conflict", "no_activities"]


def test_pet_with_no_allergies_is_unaffected():
    owner = Owner("Jordan", available_minutes=60)
    pet = Pet("Ghost", "cat")
    owner.add_pet(pet)
    routine = _routine(Activity("Chicken treat training", 10, "low", why="[1]"))

    assert validate_routine(routine, pet, owner) == []


def test_quota_error_is_reported_in_plain_language(knowledge_dir, tmp_path):
    pytest.importorskip("google.genai")

    class QuotaClient:
        class models:
            @staticmethod
            def generate_content(**kwargs):
                raise RuntimeError("429 RESOURCE_EXHAUSTED. {'error': {...}}")

    pet, owner = _pet_and_owner()
    advisor = WellnessAdvisor(kb=_kb(knowledge_dir, tmp_path), _cached_client=QuotaClient())

    with pytest.raises(GenerationError, match="quota exhausted"):
        advisor.suggest(pet, owner)


def test_suggest_raises_when_nothing_is_retrieved(tmp_path):
    pet, owner = _pet_and_owner()
    advisor = WellnessAdvisor(kb=KnowledgeBase(passages=[]))

    with pytest.raises(GenerationError, match="No relevant guidance"):
        advisor.suggest(pet, owner)
