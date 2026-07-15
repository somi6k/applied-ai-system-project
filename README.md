# PawPal+ (Module 2 Project)

You are building **PawPal+**, a Streamlit app that helps a pet owner plan care tasks for their pet.

## Scenario

A busy pet owner needs help staying consistent with pet care. They want an assistant that can:

- Track pet care tasks (walks, feeding, meds, enrichment, grooming, etc.)
- Consider constraints (time available, priority, owner preferences)
- Produce a daily plan and explain why it chose that plan

Your job is to design the system first (UML), then implement the logic in Python, then connect it to the Streamlit UI.

## What you will build

Your final app should:

- Let a user enter basic owner + pet info
- Let a user add/edit tasks (duration + priority at minimum)
- Generate a daily schedule/plan based on constraints and priorities
- Display the plan clearly (and ideally explain the reasoning)
- Include tests for the most important scheduling behaviors

## Getting started

### Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Suggested workflow

1. Read the scenario carefully and identify requirements and edge cases.
2. Draft a UML diagram (classes, attributes, methods, relationships).
3. Convert UML into Python class stubs (no logic yet).
4. Implement scheduling logic in small increments.
5. Add tests to verify key behaviors.
6. Connect your logic to the Streamlit UI in `app.py`.
7. Refine UML so it matches what you actually built.

## 🖥️ Sample Output

Paste a sample of your app's CLI or Streamlit output here so a reader can see what a generated plan looks like:

```
Today's Schedule for Sam
(available time: 120 min)
----------------------------------------
  08:00 - Medication (5 min) [priority: high] - Max
  08:05 - Breakfast (10 min) [priority: high] - Biscuit
  08:15 - Feeding (10 min) [priority: high] - Max
  08:25 - Morning walk (30 min) [priority: high] - Biscuit
  08:55 - Short walk (20 min) [priority: medium] - Max
  09:15 - Grooming (25 min) [priority: medium] - Biscuit
  09:40 - Enrichment play (20 min) [priority: low] - Biscuit
```

## 🧪 Testing PawPal+

```bash
# Run the full test suite:
python -m pytest

# Run verbosely (one line per test):
python -m pytest -v

# Run with coverage:
python -m pytest --cov
```

Test output:

```
============================= test session starts =============================
platform win32 -- Python 3.14.5, pytest-9.1.1, pluggy-1.6.0
collected 16 items

tests\test_pawpal.py ................                                    [100%]

============================= 16 passed in 0.03s ==============================
```

### What the tests cover

The suite in `tests/test_pawpal.py` exercises the scheduler's trickiest behaviors:

- **Sorting & plan ordering** — deadline tasks sort ahead of deadline-less ones
  (24:00 sentinel), ties fall back to insertion order, oversized tasks are
  skipped, and the greedy `break` in `generate_plan` skips a later task that
  would otherwise have fit (the documented priority-first tradeoff).
- **Recurring tasks** — completing a daily/weekly task spawns exactly one next
  occurrence with the correct due date (including across a month boundary),
  non-recurring tasks spawn nothing, and the domain `complete()` has no
  re-completion guard (spawns on every call — the UI guards instead).
- **Conflict detection** — the sort-then-sweep flags chained overlaps against
  the furthest-reaching task, treats back-to-back tasks as non-conflicting
  (half-open `[start, end)` intervals), and ignores unscheduled tasks.
- **Boundary cases** — a zero-minute budget skips everything, and a scheduler
  with no owner raises `ValueError` (or returns empty for conflict detection).

### Confidence level

Based on the test suite I give a confidence level of 4/5. In order to achieve full confidence I would prefer to add dozens more tests handling as many other methods and scenarios as possible.


## ✨ Features

The scheduling logic lives in `pawpal_system.py`; the `Scheduler` class reads
across the owner's pets and their tasks to produce a daily plan.

- **Sorting.** `Scheduler.sort_by_time()` returns all of the owner's tasks
  ordered chronologically by deadline (earliest first); tasks without a
  deadline sort to the end via a 24:00 sentinel, and the pets' own task lists
  are left untouched. When building the actual plan, `generate_plan()` instead
  sorts by a three-part key — **priority (high first) → earliest deadline →
  shortest duration** — via `Scheduler._sort_key`.
- **Filtering.** Two kinds. `generate_plan()` filters by the owner's time
  budget: it walks the priority-sorted tasks, placing them back-to-back from
  `day_start` (08:00) until a task no longer fits `available_minutes`, then
  stops and marks the remaining tasks `"skipped"` (a deliberate strict-priority
  greedy tradeoff — it stops at the first task that doesn't fit rather than
  squeezing in smaller lower-priority ones). Separately, `Owner.filter_pets()`
  filters the pet list by name (case-insensitive substring) and/or completion
  state (via `Pet.is_complete()`), combined with AND.
- **Conflict detection.** `Scheduler.detect_conflicts()` flags tasks whose
  scheduled times overlap. It looks only at tasks that have a `start`, sorts
  them by start time, and sweeps left-to-right tracking the furthest end seen
  so far — any task beginning before that end overlaps an earlier one. This is
  O(n log n) rather than an O(n²) all-pairs check, treats intervals as
  half-open `[start, start + duration)` (so back-to-back tasks don't conflict),
  and warns (prints + returns the pairs) instead of crashing.
- **Recurring tasks.** Completing a task with `Task.complete()` marks it done
  and, for a daily/weekly `Recurrence`, auto-creates the next occurrence on the
  same pet (daily = `today + 1 day`, weekly = `today + 1 week`).

## 📐 Smarter Scheduling

The scheduling logic lives in `pawpal_system.py`. Each algorithm below has its
own method with a docstring describing its strategy.

| Feature | Method(s) | Notes |
|---------|-----------|-------|
| Task sorting | `Scheduler.sort_by_time`, `Scheduler._sort_key` (used by `Scheduler.generate_plan`) | `sort_by_time` orders tasks chronologically by deadline (deadline-less tasks sort last via a 24:00 sentinel). `generate_plan` sorts by priority → deadline → duration. |
| Filtering | `Owner.filter_pets`, `Pet.is_complete` | `filter_pets` filters pets by name (case-insensitive substring) and/or task-completion state, combined with AND. `generate_plan` also filters out tasks once the time budget runs out (marks them `skipped`). |
| Conflict handling | `Scheduler.detect_conflicts` | Lightweight O(n log n) sort-then-sweep over scheduled start times; flags overlapping tasks (same or different pets) with a printed warning instead of crashing. |
| Recurring tasks | `Task.complete` (see the `Recurrence` enum) | Completing a daily/weekly task auto-creates its next occurrence — daily is `today + 1 day`, weekly is `today + 1 week` (via `timedelta`). |

## 📸 Demo Walkthrough

### What you can do

- Set the **owner's** name and daily time budget (available minutes).
- **Add multiple pets** (name + species); a caption tracks each pet's task count.
- **Search/filter pets** by name, and see which pets are fully done.
- **Add tasks** to a chosen pet with a title, duration, priority, an optional
  deadline, and a recurrence (none/daily/weekly).
- **Mark tasks done** individually or all at once; completing a recurring task
  spawns its next occurrence.
- **Preview** all tasks sorted by deadline before scheduling.
- **Generate today's schedule**, then see start times, tasks filtered out for
  lack of time, and any conflict warnings.

### Example workflow

set owner + available minutes -> add a pet -> select the pet and add a task
(duration + priority, optional deadline) -> preview tasks sorted by time ->
click **Generate schedule** -> view today's plan (and any skipped/conflicting
tasks).

### Key Scheduler behaviors shown

- **Sorting** — tasks are ordered by deadline for the "sorted by time" view; the
  plan itself orders by priority → deadline → duration.
- **Filtering** — tasks that don't fit the time budget are dropped from the plan
  and reported as skipped / "Filtered out (not enough time)".
- **Conflict warnings** — overlapping start times are flagged (e.g. the CLI's
  `WARNING: schedule conflict ... overlap at 09:30`) instead of crashing.
- **Recurring tasks** — completing a daily/weekly task auto-creates its next
  occurrence with the correct due date.

### Sample CLI output (`python main.py`)

```
Tasks as added (out of order):
----------------------------------------
  deadline --:--  Enrichment play (20 min) [priority: low] - Biscuit
  deadline 09:00  Morning walk (30 min) [priority: high] - Biscuit
  deadline --:--  Grooming (25 min) [priority: medium] - Biscuit
  deadline 08:30  Breakfast (10 min) [priority: high] - Biscuit
  deadline --:--  Short walk (20 min) [priority: medium] - Max
  deadline 09:00  Feeding (10 min) [priority: high] - Max
  deadline 08:15  Medication (5 min) [priority: high] - Max

Sorted by time (earliest deadline first):
----------------------------------------
  deadline 08:15  Medication (5 min) [priority: high] - Max
  deadline 08:30  Breakfast (10 min) [priority: high] - Biscuit
  deadline 09:00  Morning walk (30 min) [priority: high] - Biscuit
  deadline 09:00  Feeding (10 min) [priority: high] - Max
  deadline --:--  Enrichment play (20 min) [priority: low] - Biscuit
  deadline --:--  Grooming (25 min) [priority: medium] - Biscuit
  deadline --:--  Short walk (20 min) [priority: medium] - Max

Today's Schedule for Sam
(available time: 120 min)
----------------------------------------
  08:00 - Medication (5 min) [priority: high] - Max
  08:05 - Breakfast (10 min) [priority: high] - Biscuit
  08:15 - Feeding (10 min) [priority: high] - Max
  08:25 - Morning walk (30 min) [priority: high] - Biscuit
  08:55 - Short walk (20 min) [priority: medium] - Max
  09:15 - Grooming (25 min) [priority: medium] - Biscuit
  09:40 - Enrichment play (20 min) [priority: low] - Biscuit

Completing recurring tasks (today = 2026-07-15):
----------------------------------------
  Grooming (weekly) done -> next occurrence due 2026-07-22
  Medication (daily) done -> next occurrence due 2026-07-16

Checking for schedule conflicts:
----------------------------------------
WARNING: schedule conflict - 'Vet appointment' (Biscuit) and 'Bath' (Max) overlap at 09:30.
  Program still running - 1 conflict(s) reported, not crashed.
```
