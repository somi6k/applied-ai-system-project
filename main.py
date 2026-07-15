"""PawPal+ demo: build an owner with pets and tasks, then print today's plan."""

from datetime import time

from pawpal_system import Owner, Pet, Task, Scheduler, Priority


def build_owner() -> Owner:
    owner = Owner("Sam", available_minutes=120)

    biscuit = Pet("Biscuit", "Golden Retriever")
    biscuit.add_task(Task("Morning walk", 30, Priority.HIGH, deadline=time(9, 0)))
    biscuit.add_task(Task("Breakfast", 10, Priority.HIGH, deadline=time(8, 30)))
    biscuit.add_task(Task("Enrichment play", 20, Priority.LOW))
    biscuit.add_task(Task("Grooming", 25, Priority.MEDIUM))

    max_ = Pet("Max", "Beagle")
    max_.add_task(Task("Medication", 5, Priority.HIGH, deadline=time(8, 15)))
    max_.add_task(Task("Short walk", 20, Priority.MEDIUM))
    max_.add_task(Task("Feeding", 10, Priority.HIGH, deadline=time(9, 0)))

    owner.add_pet(biscuit)
    owner.add_pet(max_)
    return owner


def print_schedule(owner: Owner, plan: list[Task]) -> None:
    print(f"Today's Schedule for {owner.name}")
    print(f"(available time: {owner.available_minutes} min)")
    print("-" * 40)

    if not plan:
        print("  Nothing scheduled.")
    for task in plan:
        print(
            f"  {task.start.strftime('%H:%M')} - {task.name} "
            f"({task.duration} min) [priority: {task.priority.name.lower()}] "
            f"- {task.pet.name}"
        )

    skipped = [t for t in owner.all_tasks() if t.status == "skipped"]
    if skipped:
        print("-" * 40)
        print("Skipped (not enough time):")
        for task in skipped:
            print(f"  - {task.name} ({task.pet.name})")


def main() -> None:
    owner = build_owner()
    scheduler = Scheduler(owner)
    plan = scheduler.generate_plan()
    print_schedule(owner, plan)


if __name__ == "__main__":
    main()
