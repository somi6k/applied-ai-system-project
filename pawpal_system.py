"""PawPal+ domain model.

Class skeletons generated from diagrams/uml.mmd. Method bodies are stubs
(`raise NotImplementedError`) to be filled in incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import IntEnum


class Priority(IntEnum):
    """Task priority. IntEnum so tasks sort naturally (HIGH > MEDIUM > LOW)."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass
class Owner:
    name: str
    # Total minutes the owner has available today for pet care.
    available_minutes: int = 0
    preferences: dict = field(default_factory=dict)
    pets: list[Pet] = field(default_factory=list)

    def change_name(self, new_name: str) -> None:
        raise NotImplementedError

    def update_availability(self, available_minutes: int) -> None:
        raise NotImplementedError

    def update_preferences(self, preferences: dict) -> None:
        raise NotImplementedError

    def add_pet(self, pet: Pet) -> None:
        raise NotImplementedError


@dataclass
class Pet:
    name: str
    breed: str
    medications: list[str] = field(default_factory=list)
    allergies: list[str] = field(default_factory=list)
    preferred_food: str = ""
    appointments: list[str] = field(default_factory=list)

    def change_name(self, new_name: str) -> None:
        raise NotImplementedError

    def update_medication(self, medication: str) -> None:
        raise NotImplementedError

    def update_appointment(self, appointment: str) -> None:
        raise NotImplementedError

    def update_allergies(self, allergy: str) -> None:
        raise NotImplementedError

    def update_food_preference(self, food: str) -> None:
        raise NotImplementedError


@dataclass
class Task:
    name: str
    duration: int  # minutes
    priority: Priority = Priority.MEDIUM
    deadline: time | None = None
    # start is None until the scheduler places the task in the plan.
    start: time | None = None
    status: str = "pending"  # pending | done | skipped
    pet: Pet | None = None

    def change_time(self, duration: int) -> None:
        raise NotImplementedError

    def change_deadline(self, deadline: time) -> None:
        raise NotImplementedError

    def update_status(self, status: str) -> None:
        raise NotImplementedError


@dataclass
class Schedule:
    owner: Owner | None = None
    pets: list[Pet] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)

    def assign_owner(self, owner: Owner) -> None:
        raise NotImplementedError

    def add_pet(self, pet: Pet) -> None:
        raise NotImplementedError

    def add_task(self, task: Task) -> None:
        raise NotImplementedError

    def generate_plan(self) -> list[Task]:
        """Return tasks in planned order, each with `start` populated.

        Considers owner availability (available_minutes) and task priority;
        lower-priority tasks are skipped when time runs out.
        """
        raise NotImplementedError
