"""PawPal+ domain model.

Class skeletons generated from diagrams/uml.mmd. Method bodies are stubs
(`raise NotImplementedError`) to be filled in incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Owner:
    name: str
    availability: list[str] = field(default_factory=list)
    preferences: dict = field(default_factory=dict)

    def change_name(self, new_name: str) -> None:
        raise NotImplementedError

    def update_availability(self, availability: list[str]) -> None:
        raise NotImplementedError

    def update_preferences(self, preferences: dict) -> None:
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
    duration: int
    priority: str
    deadline: str = ""
    pet: Pet | None = None

    def change_time(self, duration: int) -> None:
        raise NotImplementedError

    def change_deadline(self, deadline: str) -> None:
        raise NotImplementedError


@dataclass
class Schedule:
    owner: Owner | None = None
    pets: list[Pet] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    time: str = ""
    status: str = ""

    def assign_owner(self, owner: Owner) -> None:
        raise NotImplementedError

    def add_pet(self, pet: Pet) -> None:
        raise NotImplementedError

    def add_task(self, task: Task) -> None:
        raise NotImplementedError

    def assign_time(self, time: str) -> None:
        raise NotImplementedError

    def update_status(self, status: str) -> None:
        raise NotImplementedError

    def generate_plan(self) -> list[Task]:
        raise NotImplementedError
