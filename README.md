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

Describe your app in numbered steps so a reader can follow along without watching a video:

1. <!-- Describe this step -->
2. <!-- Describe this step -->
3. <!-- Describe this step -->
4. <!-- Describe this step -->
5. <!-- Add more steps as needed -->

**Screenshot or video** *(optional)*: <!-- Insert a screenshot or link to a demo video here -->
