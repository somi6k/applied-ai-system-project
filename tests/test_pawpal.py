from datetime import date, time

import pytest

from pawpal_system import (
    Owner,
    Pet,
    Priority,
    Recurrence,
    Scheduler,
    Task,
)


def test_marking_task_done_changes_status():
    task = Task("Morning walk", 30)
    assert task.status == "pending"

    task.update_status("done")

    assert task.status == "done"


def test_adding_task_to_pet_increases_task_count():
    pet = Pet("Biscuit", "Golden Retriever")
    assert len(pet.tasks) == 0

    pet.add_task(Task("Feeding", 10))

    assert len(pet.tasks) == 1


# --- helpers ---------------------------------------------------------------


def _owner_with(*tasks: Task, available_minutes: int = 120) -> Owner:
    """An owner with a single pet holding the given tasks."""
    owner = Owner("Jordan", available_minutes=available_minutes)
    pet = Pet("Mochi", "dog")
    owner.add_pet(pet)
    for task in tasks:
        pet.add_task(task)
    return owner


# --- sorting & plan ordering -----------------------------------------------


def test_deadline_task_sorts_before_deadline_less_task():
    late = Task("Late", 10, deadline=time(23, 59))
    whenever = Task("Whenever", 10)  # no deadline -> 24:00 sentinel
    owner = _owner_with(whenever, late)
    scheduler = Scheduler(owner)

    ordered = scheduler.sort_by_time()

    assert [t.name for t in ordered] == ["Late", "Whenever"]


def test_sort_is_stable_on_full_tie():
    # Identical priority/deadline/duration -> insertion order preserved.
    first = Task("First", 10, Priority.MEDIUM, deadline=time(9, 0))
    second = Task("Second", 10, Priority.MEDIUM, deadline=time(9, 0))
    scheduler = Scheduler(_owner_with(first, second))

    ordered = scheduler.generate_plan()

    assert [t.name for t in ordered] == ["First", "Second"]


def test_greedy_break_skips_a_later_task_that_would_have_fit():
    # Documented greedy tradeoff: generate_plan stops at the FIRST task that
    # doesn't fit. With a 65-min budget the 60-min HIGH task is scheduled, the
    # 20-min MEDIUM task doesn't fit and triggers the break, so the 5-min LOW
    # task is skipped even though 60 + 5 <= 65 would have fit.
    big = Task("Vet meds", 60, Priority.HIGH)
    medium = Task("Grooming", 20, Priority.MEDIUM)
    tiny = Task("Quick treat", 5, Priority.LOW)
    owner = _owner_with(big, medium, tiny, available_minutes=65)
    scheduler = Scheduler(owner)

    plan = scheduler.generate_plan()

    assert [t.name for t in plan] == ["Vet meds"]
    assert medium.status == "skipped"
    assert tiny.status == "skipped"


def test_task_longer_than_budget_is_skipped():
    too_long = Task("Marathon walk", 200, Priority.HIGH)
    scheduler = Scheduler(_owner_with(too_long, available_minutes=120))

    plan = scheduler.generate_plan()

    assert plan == []
    assert too_long.status == "skipped"


# --- recurring tasks -------------------------------------------------------


def test_daily_task_spawns_single_next_occurrence():
    daily = Task("Feed", 10, recurrence=Recurrence.DAILY)
    pet = Pet("Mochi", "dog")
    pet.add_task(daily)

    nxt = daily.complete(today=date(2026, 7, 15))

    assert daily.status == "done"
    assert nxt is not None
    assert nxt.due_date == date(2026, 7, 16)
    assert nxt.status == "pending"
    # Exactly one new task added, attached to the same pet.
    assert len(pet.tasks) == 2
    assert nxt.pet is pet


def test_weekly_task_advances_across_month_boundary():
    weekly = Task("Bath", 30, recurrence=Recurrence.WEEKLY)
    Pet("Mochi", "dog").add_task(weekly)

    nxt = weekly.complete(today=date(2026, 7, 29))

    assert nxt.due_date == date(2026, 8, 5)


def test_non_recurring_complete_returns_none_and_spawns_nothing():
    once = Task("Nail trim", 15, recurrence=Recurrence.NONE)
    pet = Pet("Mochi", "dog")
    pet.add_task(once)

    assert once.complete(today=date(2026, 7, 15)) is None
    assert len(pet.tasks) == 1


def test_completing_twice_spawns_two_occurrences():
    # The domain method does not guard against re-completion; each call spawns.
    # (The UI guards on the pending->done transition instead.)
    daily = Task("Feed", 10, recurrence=Recurrence.DAILY)
    pet = Pet("Mochi", "dog")
    pet.add_task(daily)

    daily.complete(today=date(2026, 7, 15))
    daily.complete(today=date(2026, 7, 15))

    assert len(pet.tasks) == 3  # original + two spawned


# --- conflict detection ----------------------------------------------------


def test_chained_overlap_reports_furthest_reaching_task():
    # A(8:00-9:00), B(8:30-8:45), C(8:50-9:10): C overlaps A, not B.
    a = Task("A", 60, deadline=None)
    a.start = time(8, 0)
    b = Task("B", 15)
    b.start = time(8, 30)
    c = Task("C", 20)
    c.start = time(8, 50)
    scheduler = Scheduler(_owner_with())

    conflicts = scheduler.detect_conflicts([a, b, c])

    names = {(x.name, y.name) for x, y in conflicts}
    assert ("A", "B") in names
    assert ("A", "C") in names


def test_back_to_back_tasks_do_not_conflict():
    a = Task("A", 60)
    a.start = time(8, 0)
    b = Task("B", 30)
    b.start = time(9, 0)  # starts exactly when A ends
    scheduler = Scheduler(_owner_with())

    assert scheduler.detect_conflicts([a, b]) == []


def test_unscheduled_tasks_are_ignored_in_conflicts():
    scheduled = Task("Scheduled", 30)
    scheduled.start = time(8, 0)
    floating = Task("Floating", 30)  # no start
    scheduler = Scheduler(_owner_with())

    assert scheduler.detect_conflicts([scheduled, floating]) == []


# --- boundary / degenerate inputs ------------------------------------------


def test_zero_budget_skips_everything():
    task = Task("Walk", 20, Priority.HIGH)
    scheduler = Scheduler(_owner_with(task, available_minutes=0))

    plan = scheduler.generate_plan()

    assert plan == []
    assert task.status == "skipped"


def test_scheduler_without_owner_raises():
    scheduler = Scheduler()

    with pytest.raises(ValueError):
        scheduler.sort_by_time()
    with pytest.raises(ValueError):
        scheduler.generate_plan()


def test_detect_conflicts_with_no_owner_returns_empty():
    assert Scheduler().detect_conflicts() == []
