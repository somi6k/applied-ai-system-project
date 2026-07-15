"""PawPal+ demo: build an owner with pets and tasks, then print today's plan."""

from datetime import date, time

from pawpal_system import Owner, Pet, Task, Scheduler, Priority, Recurrence


def build_owner() -> Owner:
    owner = Owner("Sam", available_minutes=120)

    # Tasks are intentionally added out of order (deadlines and priorities are
    # scrambled) to show that the scheduler, not the input order, decides the
    # plan. A deadline-less low-priority task sits first, an early-deadline
    # high-priority one sits last, etc.
    biscuit = Pet("Biscuit", "Golden Retriever")
    biscuit.add_task(Task("Enrichment play", 20, Priority.LOW))
    biscuit.add_task(Task("Morning walk", 30, Priority.HIGH, deadline=time(9, 0)))
    biscuit.add_task(Task("Grooming", 25, Priority.MEDIUM, recurrence=Recurrence.WEEKLY))
    biscuit.add_task(Task("Breakfast", 10, Priority.HIGH, deadline=time(8, 30)))

    max_ = Pet("Max", "Beagle")
    max_.add_task(Task("Short walk", 20, Priority.MEDIUM))
    max_.add_task(Task("Feeding", 10, Priority.HIGH, deadline=time(9, 0)))
    max_.add_task(
        Task("Medication", 5, Priority.HIGH, deadline=time(8, 15), recurrence=Recurrence.DAILY)
    )

    owner.add_pet(biscuit)
    owner.add_pet(max_)
    return owner


def _fmt_deadline(task: Task) -> str:
    """Deadline as HH:MM, or a dash when the task has no deadline."""
    return task.deadline.strftime("%H:%M") if task.deadline else "--:--"


def print_tasks(title: str, tasks: list[Task]) -> None:
    """Print a labeled list of tasks with deadline, priority, and pet."""
    print(title)
    print("-" * 40)
    if not tasks:
        print("  (none)")
    for task in tasks:
        print(
            f"  deadline {_fmt_deadline(task)}  {task.name} "
            f"({task.duration} min) [priority: {task.priority.name.lower()}] "
            f"- {task.pet.name}"
        )
    print()


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

    # Show the tasks in the (scrambled) order they were added...
    print_tasks("Tasks as added (out of order):", owner.all_tasks())
    # ...then sorted chronologically by deadline...
    print_tasks("Sorted by time (earliest deadline first):", scheduler.sort_by_time())

    # ...and finally the schedule the scheduler actually builds.
    plan = scheduler.generate_plan()
    print_schedule(owner, plan)

    # Completing a recurring task auto-creates its next occurrence.
    print()
    today = date(2026, 7, 15)
    print(f"Completing recurring tasks (today = {today}):")
    print("-" * 40)
    for task in list(owner.all_tasks()):
        if task.recurrence is Recurrence.NONE:
            continue
        nxt = task.complete(today)
        print(
            f"  {task.name} ({task.recurrence.value}) done "
            f"-> next occurrence due {nxt.due_date}"
        )

    # Conflict detection: two tasks pinned to overlapping times (here for
    # different pets) can't both happen — the owner is one person. The
    # scheduler warns instead of crashing.
    print()
    print("Checking for schedule conflicts:")
    print("-" * 40)
    vet = Task("Vet appointment", 45, Priority.HIGH)
    vet.start = time(9, 0)  # 09:00–09:45
    vet.pet = owner.pets[0]  # Biscuit
    bath = Task("Bath", 30, Priority.MEDIUM)
    bath.start = time(9, 30)  # 09:30–10:00 — overlaps the vet visit
    bath.pet = owner.pets[1]  # Max
    conflicts = scheduler.detect_conflicts([vet, bath])
    if not conflicts:
        print("  No conflicts.")
    else:
        print(f"  Program still running - {len(conflicts)} conflict(s) reported, not crashed.")


if __name__ == "__main__":
    main()
