from datetime import date, time

import streamlit as st

from pawpal_system import Owner, Pet, Task, Scheduler, Priority, Recurrence

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

st.title("🐾 PawPal+")

st.markdown(
    """
Welcome to the PawPal+ starter app.

This file is intentionally thin. It gives you a working Streamlit app so you can start quickly,
but **it does not implement the project logic**. Your job is to design the system and build it.

Use this app as your interactive demo once your backend classes/functions exist.
"""
)

with st.expander("Scenario", expanded=True):
    st.markdown(
        """
**PawPal+** is a pet care planning assistant. It helps a pet owner plan care tasks
for their pet(s) based on constraints like time, priority, and preferences.

You will design and implement the scheduling logic and connect it to this Streamlit UI.
"""
    )

with st.expander("What you need to build", expanded=True):
    st.markdown(
        """
At minimum, your system should:
- Represent pet care tasks (what needs to happen, how long it takes, priority)
- Represent the pet and the owner (basic info and preferences)
- Build a plan/schedule for a day that chooses and orders tasks based on constraints
- Explain the plan (why each task was chosen and when it happens)
"""
    )

st.divider()

# Map the UI's priority strings to the Priority enum used by the scheduler.
PRIORITY_MAP = {"low": Priority.LOW, "medium": Priority.MEDIUM, "high": Priority.HIGH}
RECURRENCE_MAP = {
    "none": Recurrence.NONE,
    "daily": Recurrence.DAILY,
    "weekly": Recurrence.WEEKLY,
}

# Create the domain objects ONCE and keep them in session_state so they persist
# across reruns. Guarded with `not in` so reruns don't wipe them out.
if "owner" not in st.session_state:
    owner = Owner("Jordan", available_minutes=120)
    owner.add_pet(Pet("Mochi", "dog"))
    st.session_state.owner = owner
if "scheduler" not in st.session_state:
    st.session_state.scheduler = Scheduler(st.session_state.owner)

owner = st.session_state.owner
scheduler = st.session_state.scheduler

st.subheader("Owner")
owner_name = st.text_input("Owner name", value=owner.name)
available_minutes = st.number_input(
    "Time available today (minutes)", min_value=0, max_value=1440, value=owner.available_minutes
)
# Keep the stored owner in sync with the inputs on every rerun.
owner.change_name(owner_name)
owner.update_availability(int(available_minutes))

st.subheader("Pets")
with st.form("add_pet", clear_on_submit=True):
    new_pet_name = st.text_input("Pet name")
    new_species = st.selectbox("Species", ["dog", "cat", "other"])
    if st.form_submit_button("Add pet"):
        if new_pet_name.strip():
            owner.add_pet(Pet(new_pet_name.strip(), new_species))
        else:
            st.warning("Enter a pet name.")

if not owner.pets:
    st.info("Add a pet to get started.")
    st.stop()

st.caption("Current pets: " + ", ".join(f"{p.name} ({len(p.tasks)} tasks)" for p in owner.pets))

done_pets = owner.filter_pets(completed=True)
if done_pets:
    st.success("All done: " + ", ".join(p.name for p in done_pets))

pet_query = st.text_input("Search pets by name", placeholder="type a name to filter…")
if pet_query.strip():
    matches = owner.filter_pets(name=pet_query.strip())
    if matches:
        st.caption(
            "Matches: "
            + ", ".join(
                f"{p.name} — {'all done' if p.is_complete() else f'{len(p.tasks)} tasks'}"
                for p in matches
            )
        )
    else:
        st.caption(f"No pets match “{pet_query.strip()}”.")

st.markdown("### Tasks")
pet_index = st.selectbox(
    "Add tasks for",
    range(len(owner.pets)),
    format_func=lambda i: owner.pets[i].name,
)
pet = owner.pets[pet_index]

with st.form("add_task", clear_on_submit=True):
    task_title = st.text_input("Task title", value="Morning walk")
    col1, col2 = st.columns(2)
    with col1:
        duration = st.number_input("Duration (minutes)", min_value=1, max_value=240, value=20)
    with col2:
        priority = st.selectbox("Priority", ["low", "medium", "high"], index=2)
    use_deadline = st.checkbox("Set a deadline")
    deadline_val = st.time_input("Deadline (time of day)", value=time(9, 0))
    repeats = st.selectbox("Repeats", ["none", "daily", "weekly"])
    if st.form_submit_button("Add task"):
        deadline = deadline_val if use_deadline else None
        pet.add_task(
            Task(
                task_title,
                int(duration),
                PRIORITY_MAP[priority],
                deadline=deadline,
                recurrence=RECURRENCE_MAP[repeats],
            )
        )

if pet.tasks:
    row = st.columns([3, 1.5])
    row[0].write(f"{pet.name}'s tasks:")
    if row[1].button("Mark all done", key=f"all_done_{pet_index}"):
        # Snapshot the list first: complete() appends the next occurrence of a
        # recurring task, and we must not complete those freshly-spawned tasks.
        for t in list(pet.tasks):
            t.complete(date.today())
        # Clear per-task checkbox state so the boxes re-render as ticked.
        for i in range(len(pet.tasks)):
            st.session_state.pop(f"done_{pet_index}_{i}", None)
        st.rerun()
    header = st.columns([0.7, 3, 1.3, 1.3, 1.3])
    for col, label in zip(header, ["done", "title", "duration", "priority", "deadline"]):
        col.caption(label)
    spawned_recurring = False
    # Iterate a snapshot so a spawned occurrence isn't processed mid-loop.
    for i, t in list(enumerate(pet.tasks)):
        cols = st.columns([0.7, 3, 1.3, 1.3, 1.3])
        is_done = cols[0].checkbox(
            "done",
            value=(t.status == "done"),
            key=f"done_{pet_index}_{i}",
            label_visibility="collapsed",
        )
        # Toggle completion. Only act on a real transition so we don't re-spawn
        # a recurring task's next occurrence on every rerun.
        if is_done and t.status != "done":
            if t.complete(date.today()) is not None:
                spawned_recurring = True
        elif not is_done and t.status == "done":
            t.update_status("pending")
        label = t.name
        if t.recurrence is not Recurrence.NONE:
            label += f" 🔁 {t.recurrence.value}"
        title = f"~~{label}~~" if t.status == "done" else label
        cols[1].markdown(title)
        cols[2].write(f"{t.duration} min")
        cols[3].write(t.priority.name.lower())
        cols[4].write(t.deadline.strftime("%H:%M") if t.deadline else "—")
    if spawned_recurring:
        # Redraw so the newly-created next occurrence shows up immediately.
        st.rerun()
else:
    st.info(f"No tasks for {pet.name} yet. Add one above.")

st.divider()

st.subheader("Build Schedule")
st.caption("Orders tasks by priority and deadline, then fits them into your available time.")

if st.button("Generate schedule"):
    plan = scheduler.generate_plan()
    if plan:
        st.markdown(
            f"**Today's Schedule for {owner.name}** ({owner.available_minutes} min available)"
        )
        for t in plan:
            due = f" (by {t.deadline.strftime('%H:%M')})" if t.deadline else ""
            st.write(
                f"{t.start.strftime('%H:%M')} — {t.name} "
                f"({t.duration} min) [priority: {t.priority.name.lower()}]{due} — {t.pet.name}"
            )
    else:
        st.info("Nothing could be scheduled. Add tasks or increase your available time.")

    skipped = [t for t in owner.all_tasks() if t.status == "skipped"]
    if skipped:
        st.warning(
            "Skipped (not enough time): "
            + ", ".join(f"{t.name} ({t.pet.name})" for t in skipped)
        )
