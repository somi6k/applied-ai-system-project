"""PawPal+ domain model.

Responsibilities:
- Task     : a single pet-care activity.
- Pet      : stores pet details and its own list of Tasks.
- Owner    : manages multiple Pets and can reach all their Tasks.
- Scheduler: the "brain" that retrieves tasks across pets, orders them by
             priority/deadline, and fits them into the owner's available time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time, timedelta
from enum import Enum, IntEnum


class Priority(IntEnum):
    """Task priority. IntEnum so tasks sort naturally (HIGH > MEDIUM > LOW)."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3


class Recurrence(Enum):
    """How often a task repeats after it is completed."""

    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"

    @property
    def step(self) -> timedelta | None:
        """How far to advance the due date for the next occurrence."""
        return {
            Recurrence.DAILY: timedelta(days=1),
            Recurrence.WEEKLY: timedelta(weeks=1),
        }.get(self)


def _to_minutes(t: time) -> int:
    """Minutes since midnight for a time-of-day."""
    return t.hour * 60 + t.minute


def _from_minutes(total: int) -> time:
    """Time-of-day from minutes since midnight (wraps at 24h)."""
    total %= 24 * 60
    return time(hour=total // 60, minute=total % 60)


def _pet_name(task: Task) -> str:
    """The name of the pet a task belongs to, or '?' if unattached."""
    return task.pet.name if task.pet else "?"


@dataclass
class Task:
    name: str
    duration: int  # minutes
    priority: Priority = Priority.MEDIUM
    deadline: time | None = None
    recurrence: Recurrence = Recurrence.NONE
    due_date: date | None = None  # calendar day this task is due
    # start/status are set by the scheduler when it builds a plan.
    start: time | None = None
    status: str = "pending"  # pending | scheduled | skipped | done
    pet: Pet | None = None  # back-reference, set by Pet.add_task

    def change_time(self, duration: int) -> None:
        """Set the task's duration in minutes."""
        self.duration = duration

    def change_deadline(self, deadline: time) -> None:
        """Set the time of day by which the task should be done."""
        self.deadline = deadline

    def update_status(self, status: str) -> None:
        """Set the task's status (e.g. pending, scheduled, skipped, done)."""
        self.status = status

    def complete(self, today: date | None = None) -> Task | None:
        """Mark this task done and, if it recurs, spawn the next occurrence.

        For a daily task the next task is due today + 1 day; for a weekly task,
        today + 1 week (via ``timedelta``). The new task copies this task's
        details, resets to "pending", and is attached to the same pet. Returns
        the newly created task, or ``None`` for a non-recurring task.

        ``today`` defaults to the current date; pass it explicitly for
        deterministic tests.
        """
        self.status = "done"

        step = self.recurrence.step
        if step is None:  # Recurrence.NONE — nothing to repeat.
            return None

        base = today if today is not None else date.today()
        next_task = Task(
            name=self.name,
            duration=self.duration,
            priority=self.priority,
            deadline=self.deadline,
            recurrence=self.recurrence,
            due_date=base + step,
        )
        if self.pet is not None:
            self.pet.add_task(next_task)
        return next_task


@dataclass
class Pet:
    name: str
    breed: str
    medications: list[str] = field(default_factory=list)
    allergies: list[str] = field(default_factory=list)
    preferred_food: str = ""
    appointments: list[str] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)

    def change_name(self, new_name: str) -> None:
        """Rename the pet."""
        self.name = new_name

    def update_medication(self, medication: str) -> None:
        """Add a medication to the pet's list."""
        self.medications.append(medication)

    def update_appointment(self, appointment: str) -> None:
        """Add an upcoming appointment to the pet's list."""
        self.appointments.append(appointment)

    def update_allergies(self, allergy: str) -> None:
        """Add an allergy to the pet's list."""
        self.allergies.append(allergy)

    def update_food_preference(self, food: str) -> None:
        """Set the pet's preferred food."""
        self.preferred_food = food

    def add_task(self, task: Task) -> None:
        """Attach a task to this pet and set its back-reference."""
        task.pet = self
        self.tasks.append(task)

    def is_complete(self) -> bool:
        """True if the pet has tasks and all of them are marked "done"."""
        return bool(self.tasks) and all(t.status == "done" for t in self.tasks)


@dataclass
class Owner:
    name: str
    # Total minutes the owner has available today for pet care.
    available_minutes: int = 0
    preferences: dict = field(default_factory=dict)
    pets: list[Pet] = field(default_factory=list)

    def change_name(self, new_name: str) -> None:
        """Rename the owner."""
        self.name = new_name

    def update_availability(self, available_minutes: int) -> None:
        """Set how many minutes the owner has available today."""
        self.available_minutes = available_minutes

    def update_preferences(self, preferences: dict) -> None:
        """Merge the given preferences into the owner's preferences."""
        self.preferences.update(preferences)

    def add_pet(self, pet: Pet) -> None:
        """Add a pet to the owner."""
        self.pets.append(pet)

    def all_tasks(self) -> list[Task]:
        """Every task across all of this owner's pets."""
        return [task for pet in self.pets for task in pet.tasks]

    def filter_pets(
        self, name: str | None = None, completed: bool | None = None
    ) -> list[Pet]:
        """Return the pets matching the given filters.

        - name: case-insensitive substring match on the pet's name.
        - completed: if True, keep only pets whose tasks are all done; if
          False, keep only pets with at least one outstanding task; if None,
          don't filter on completion.

        Filters combine with AND. Passing no filters returns all pets.
        """
        needle = name.lower() if name else None
        return [
            pet
            for pet in self.pets
            if (needle is None or needle in pet.name.lower())
            and (completed is None or pet.is_complete() == completed)
        ]


@dataclass
class Scheduler:
    """The brain: organizes an owner's tasks into a time-boxed daily plan."""

    owner: Owner | None = None
    day_start: time = time(8, 0)  # when the plan's first task begins

    def assign_owner(self, owner: Owner) -> None:
        """Set the owner whose tasks this scheduler will plan."""
        self.owner = owner

    def sort_by_time(self) -> list[Task]:
        """Return the owner's tasks sorted by time of day (earliest first).

        Tasks are ordered by their deadline. Tasks with no deadline have no
        fixed time, so they sort to the end (using 24:00 as a sentinel). The
        original task lists on each pet are left untouched.
        """
        if self.owner is None:
            raise ValueError("Scheduler has no owner assigned.")

        # Lambda key: deadline in minutes since midnight, or end-of-day for
        # deadline-less tasks so they fall after every timed task.
        return sorted(
            self.owner.all_tasks(),
            key=lambda task: _to_minutes(task.deadline) if task.deadline else 24 * 60,
        )

    def generate_plan(self, available_minutes: int | None = None) -> list[Task]:
        """Build a daily plan from all of the owner's tasks.

        Ordering: highest priority first, then earliest deadline, then
        shortest duration. Tasks are placed back-to-back starting at
        `day_start`; once the time budget is exhausted, remaining tasks are
        marked "skipped".

        Tradeoff: this is greedy by priority, so a high-priority task can
        crowd out several quick low-priority ones even if they'd collectively
        fit. That keeps the most important care guaranteed, which suits a busy
        owner who can't do everything.

        Returns the scheduled tasks in order (each with `start` populated).
        Skipped tasks stay on their pets with status "skipped".
        """
        if self.owner is None:
            raise ValueError("Scheduler has no owner assigned.")

        budget = (
            available_minutes
            if available_minutes is not None
            else self.owner.available_minutes
        )

        tasks = self.owner.all_tasks()
        # Reset any prior planning so re-running is idempotent, but leave
        # already-completed tasks untouched — a done task isn't replanned.
        for task in tasks:
            if task.status == "done":
                continue
            task.start = None
            task.status = "pending"

        ordered = sorted(
            (t for t in tasks if t.status != "done"), key=self._sort_key
        )

        plan: list[Task] = []
        cursor = _to_minutes(self.day_start)
        used = 0
        for task in ordered:
            if used + task.duration <= budget:
                task.start = _from_minutes(cursor)
                task.status = "scheduled"
                cursor += task.duration
                used += task.duration
                plan.append(task)
            else:
                # Strict priority: stop at the first task that doesn't fit so a
                # lower-priority task never displaces a skipped higher one.
                task.status = "skipped"
                break
        # Anything after the break is also skipped.
        for task in ordered[len(plan) :]:
            if task.status != "skipped":
                task.status = "skipped"
        return plan

    def detect_conflicts(
        self, tasks: list[Task] | None = None
    ) -> list[tuple[Task, Task]]:
        """Warn (don't crash) about tasks whose scheduled times overlap.

        A conflict is any pair of tasks whose [start, start + duration)
        intervals intersect — whether they belong to the same pet or different
        pets. The owner can only do one thing at a time, so overlaps are a
        planning problem worth flagging.

        Strategy (lightweight, O(n log n)): consider only tasks that have a
        `start`, sort them by start time, then sweep left-to-right keeping the
        latest end seen so far. Any task that begins before that end overlaps
        something earlier. This avoids the O(n^2) all-pairs comparison.

        Prints a warning line per conflicting pair and returns the pairs.
        Returns an empty list when there are no conflicts.
        """
        source = tasks if tasks is not None else (
            self.owner.all_tasks() if self.owner else []
        )
        timed = [t for t in source if t.start is not None]
        timed.sort(key=lambda t: _to_minutes(t.start))

        conflicts: list[tuple[Task, Task]] = []
        # `last` is the task with the furthest end seen so far.
        last: Task | None = None
        last_end = -1
        for task in timed:
            start = _to_minutes(task.start)
            end = start + task.duration
            if last is not None and start < last_end:
                conflicts.append((last, task))
                print(
                    f"WARNING: schedule conflict - "
                    f"'{last.name}' ({_pet_name(last)}) and "
                    f"'{task.name}' ({_pet_name(task)}) overlap "
                    f"at {task.start.strftime('%H:%M')}."
                )
            # Keep whichever task reaches furthest so we catch chained overlaps.
            if end > last_end:
                last, last_end = task, end
        return conflicts

    @staticmethod
    def _sort_key(task: Task) -> tuple[int, int, int]:
        """Order tasks by priority (high first), then deadline, then duration."""
        # Negative priority -> HIGH sorts first. No deadline -> sorts last.
        deadline_min = _to_minutes(task.deadline) if task.deadline else 24 * 60
        return (-int(task.priority), deadline_min, task.duration)
