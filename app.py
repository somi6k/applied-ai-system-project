"""PawPal+ Streamlit UI.

Page order follows how the day actually gets planned: pick a pet, ask the
wellness advisor what it needs, turn those suggestions into tasks, then let the
Scheduler time-box everything and flag conflicts.
"""

from datetime import date, time

import streamlit as st

from pawpal_system import Owner, Pet, Priority, Recurrence, Scheduler, Task
from wellness_rag import GenerationError, MissingAPIKey, WellnessAdvisor, api_key

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="wide")

# Map the UI's strings to the enums the scheduler uses.
PRIORITY_MAP = {"low": Priority.LOW, "medium": Priority.MEDIUM, "high": Priority.HIGH}
RECURRENCE_MAP = {
    "none": Recurrence.NONE,
    "daily": Recurrence.DAILY,
    "weekly": Recurrence.WEEKLY,
}
PRIORITY_COLOR = {Priority.HIGH: "red", Priority.MEDIUM: "orange", Priority.LOW: "gray"}


def priority_badge(priority: Priority) -> str:
    """Inline markdown badge, e.g. ``:red-badge[high]``."""
    return f":{PRIORITY_COLOR[priority]}-badge[{priority.name.lower()}]"


def invalidate_plan() -> None:
    """Drop a stored schedule once the tasks behind it have changed."""
    st.session_state.pop("plan", None)


@st.cache_resource(show_spinner=False)
def get_advisor() -> WellnessAdvisor | None:
    """Load the knowledge base once per session, not on every rerun."""
    try:
        return WellnessAdvisor.load()
    except FileNotFoundError:
        return None


def start_session(*, demo: bool) -> None:
    """Put a fresh owner and scheduler into session_state.

    ``demo=True`` seeds the walkthrough data; ``demo=False`` leaves the app
    blank so a new user can enter their own name and pets.
    """
    owner = Owner("Jordan" if demo else "", available_minutes=120)
    if demo:
        owner.add_pet(Pet("Mochi", "dog"))
    st.session_state.owner = owner
    st.session_state.scheduler = Scheduler(owner)


def reset_session(*, demo: bool) -> None:
    """Hand the app to a new user: clear every entry and all widget state.

    ``clear()`` also drops the widget keys (checkboxes, per-pet text inputs,
    the pet selector), so nothing from the previous owner survives the rerun.
    """
    st.session_state.clear()
    start_session(demo=demo)


# Create the domain objects ONCE and keep them in session_state so they persist
# across reruns. Guarded with `not in` so reruns don't wipe them out.
if "owner" not in st.session_state:
    start_session(demo=True)

owner = st.session_state.owner
scheduler = st.session_state.scheduler


# --- sidebar: who we're planning for ---------------------------------------

with st.sidebar:
    st.header("🐾 PawPal+")

    owner_name = st.text_input("Owner name", value=owner.name, placeholder="Your name")
    available_minutes = st.slider(
        "Time available today",
        min_value=0,
        max_value=480,
        value=owner.available_minutes,
        step=15,
        format="%d min",
    )
    # Keep the stored owner in sync with the inputs on every rerun.
    owner.change_name(owner_name)
    if int(available_minutes) != owner.available_minutes:
        owner.update_availability(int(available_minutes))
        invalidate_plan()

    st.divider()

    with st.form("add_pet", clear_on_submit=True):
        st.markdown("**Add a pet**")
        new_pet_name = st.text_input("Name", placeholder="e.g. Biscuit")
        new_species = st.selectbox("Species", ["dog", "cat", "other"])
        if st.form_submit_button("Add pet", use_container_width=True):
            if new_pet_name.strip():
                owner.add_pet(Pet(new_pet_name.strip(), new_species))
                st.rerun()
            else:
                st.warning("Enter a pet name.")

    # Filtering demo — Owner.filter_pets by name and/or completion state.
    pet_query = st.text_input("Search pets", placeholder="filter by name…")
    if pet_query.strip():
        matches = owner.filter_pets(name=pet_query.strip())
        if matches:
            for match in matches:
                state = "all done" if match.is_complete() else f"{len(match.tasks)} tasks"
                st.caption(f"· {match.name} — {state}")
        else:
            st.caption(f"No pets match “{pet_query.strip()}”.")

    st.divider()

    advisor = get_advisor()
    st.caption("**Wellness advisor**")
    if advisor is None:
        st.caption("⚠️ `knowledge/` folder not found.")
    elif api_key():
        st.caption(f"✅ Gemini connected · {len(advisor.kb.passages)} passages indexed")
    else:
        st.caption(
            f"🔑 No API key · {len(advisor.kb.passages)} passages, keyword search only. "
            "Set `GEMINI_API_KEY` in `.env`."
        )

    st.divider()

    with st.popover("↩︎ Start over", use_container_width=True):
        st.caption(
            "Clears the owner, pets, tasks, and any suggested routines so "
            "someone else can start fresh. This can't be undone."
        )
        if st.button("Clear everything", type="primary", use_container_width=True):
            reset_session(demo=False)
            st.rerun()
        if st.button("Restore demo data", use_container_width=True):
            reset_session(demo=True)
            st.rerun()


# --- header: the day at a glance -------------------------------------------

st.title("Today's pet care")
st.caption(
    f"Planning for **{owner.name}** · {date.today():%A %d %B}"
    if owner.name
    else f"{date.today():%A %d %B}"
)

if not owner.pets:
    st.info("Add a pet in the sidebar to get started.")
    st.stop()

open_tasks = [t for t in owner.all_tasks() if t.status != "done"]
needed = sum(t.duration for t in open_tasks)
slack = owner.available_minutes - needed

metrics = st.columns(4)
metrics[0].metric("Pets", len(owner.pets))
metrics[1].metric("Open tasks", len(open_tasks))
metrics[2].metric("Care time needed", f"{needed} min")
metrics[3].metric(
    "Time available",
    f"{owner.available_minutes} min",
    delta=f"{slack:+d} min spare" if owner.available_minutes else None,
)
if owner.available_minutes:
    st.progress(min(needed / owner.available_minutes, 1.0))

done_pets = owner.filter_pets(completed=True)
if done_pets:
    st.success("All caught up: " + ", ".join(p.name for p in done_pets))

st.divider()


# --- pet selector ----------------------------------------------------------

pet_index = st.segmented_control(
    "Pet",
    options=range(len(owner.pets)),
    format_func=lambda i: owner.pets[i].name,
    default=0,
    key="active_pet",
    label_visibility="collapsed",
)
if pet_index is None:  # the control allows deselecting; fall back to the first pet
    pet_index = 0
pet = owner.pets[pet_index]

name_col, profile_col = st.columns([4, 1], vertical_alignment="center")
name_col.subheader(f"{pet.name} · {pet.breed}")
with profile_col.popover("Health profile", use_container_width=True):
    # These text boxes own the whole list, so they assign rather than append —
    # the update_* methods add one item at a time and can't remove.
    allergies = st.text_input(
        "Allergies (comma-separated)",
        value=", ".join(pet.allergies),
        key=f"allergies_{pet_index}",
    )
    medications = st.text_input(
        "Medications (comma-separated)",
        value=", ".join(pet.medications),
        key=f"meds_{pet_index}",
    )
    preferred_food = st.text_input(
        "Preferred food", value=pet.preferred_food, key=f"food_{pet_index}"
    )
    st.caption("The wellness advisor uses these when it retrieves guidance.")
    pet.allergies = [a.strip() for a in allergies.split(",") if a.strip()]
    pet.medications = [m.strip() for m in medications.split(",") if m.strip()]
    pet.update_food_preference(preferred_food.strip())

profile_bits = []
if pet.allergies:
    profile_bits.append("allergic to " + ", ".join(pet.allergies))
if pet.medications:
    profile_bits.append("on " + ", ".join(pet.medications))
if profile_bits:
    st.caption(" · ".join(profile_bits))


# --- 1. wellness routine (RAG) ---------------------------------------------


def render_sources(results) -> None:
    """Show which passages were retrieved, so a suggestion is auditable."""
    with st.expander(f"📚 Retrieved guidance ({len(results)} passages)"):
        for i, r in enumerate(results, 1):
            st.markdown(f"**[{i}] {r.passage.label}** · similarity `{r.score:.3f}`")
            st.caption(f"knowledge/{r.passage.source}")
            st.write(r.passage.text)
            if i < len(results):
                st.divider()


st.markdown("#### 🧠 Wellness routine")
st.caption(
    "Searches the local pet-care knowledge base for guidance matching this pet, "
    "then asks Gemini to build a routine grounded in what it found."
)

routine_key = f"routine_{pet.name}"

ask_col, focus_col = st.columns([1.2, 3], vertical_alignment="bottom")
focus = focus_col.text_input(
    "Anything specific to focus on?",
    placeholder="e.g. she's gaining weight, or he hates nail trims",
    key=f"focus_{pet.name}",
)
suggest = ask_col.button(
    f"✨ Suggest for {pet.name}", type="primary", use_container_width=True
)

if suggest:
    st.session_state.pop(routine_key, None)
    if advisor is None:
        st.error("No `knowledge/` folder found — nothing to retrieve from.")
    else:
        with st.spinner("Retrieving guidance and drafting a routine…"):
            try:
                st.session_state[routine_key] = advisor.suggest(pet, owner, focus)
            except MissingAPIKey as exc:
                # Retrieval still works without a key — show what it found.
                st.warning(str(exc))
                results = advisor.retrieve(pet, owner, focus)
                if results:
                    st.info("Showing retrieved guidance only — no routine generated.")
                    render_sources(results)
                else:
                    st.info("No matching guidance found for this pet.")
            except GenerationError as exc:
                st.error(str(exc))

routine = st.session_state.get(routine_key)
if routine:
    with st.container(border=True):
        if routine.retrieval_mode != "vector":
            st.caption("⚠️ Keyword retrieval (embeddings unavailable) — results may be rougher.")

        st.markdown(routine.summary)
        st.caption(
            f"{len(routine.activities)} activities · {routine.total_minutes} min "
            f"of {owner.available_minutes} min available"
        )

        for activity in routine.activities:
            with st.container(border=True):
                head, meta = st.columns([3, 1.4], vertical_alignment="center")
                head.markdown(f"**{activity.name}**")
                meta.markdown(
                    f"{activity.duration_minutes} min · "
                    f":{PRIORITY_COLOR[PRIORITY_MAP.get(activity.priority.lower(), Priority.MEDIUM)]}"
                    f"-badge[{activity.priority}]"
                    + (f" · {activity.time_of_day}" if activity.time_of_day else "")
                )
                if activity.why:
                    st.caption(activity.why)

        for caution in routine.cautions:
            st.warning(caution, icon="⚕️")

        # Guardrail transparency: what was dropped or flagged before display.
        if routine.issues:
            dropped = sum(1 for i in routine.issues if i.severity == "error")
            with st.expander(
                f"🛡️ Guardrail: {len(routine.issues)} finding(s), {dropped} repaired"
            ):
                for issue in routine.issues:
                    icon = "❌" if issue.severity == "error" else "⚠️"
                    st.markdown(f"{icon} `{issue.code}` — {issue.detail}")

        render_sources(routine.sources)

        add_col, skip_col = st.columns([1.4, 1])
        if add_col.button(
            f"➕ Add {len(routine.activities)} activities to {pet.name}'s tasks",
            type="primary",
            use_container_width=True,
        ):
            for task in routine.to_tasks():
                pet.add_task(task)
            st.session_state.pop(routine_key, None)
            invalidate_plan()
            st.rerun()
        if skip_col.button("Dismiss", use_container_width=True):
            st.session_state.pop(routine_key, None)
            st.rerun()

        st.caption("AI-generated from the local knowledge base. Not veterinary advice.")

st.divider()


# --- 2. tasks --------------------------------------------------------------

st.markdown(f"#### ✅ {pet.name}'s tasks")

with st.expander("Add a task", expanded=not pet.tasks):
    with st.form("add_task", clear_on_submit=True):
        task_title = st.text_input("Task title", value="Morning walk")
        col1, col2, col3 = st.columns(3)
        duration = col1.number_input("Duration (min)", min_value=1, max_value=240, value=20)
        priority = col2.selectbox("Priority", ["low", "medium", "high"], index=2)
        repeats = col3.selectbox("Repeats", ["none", "daily", "weekly"])
        use_deadline = st.checkbox("Set a deadline")
        deadline_val = st.time_input("Deadline (time of day)", value=time(9, 0))
        if st.form_submit_button("Add task", type="primary"):
            pet.add_task(
                Task(
                    task_title,
                    int(duration),
                    PRIORITY_MAP[priority],
                    deadline=deadline_val if use_deadline else None,
                    recurrence=RECURRENCE_MAP[repeats],
                )
            )
            invalidate_plan()
            st.rerun()

if pet.tasks:
    top = st.columns([3, 1])
    remaining = sum(t.duration for t in pet.tasks if t.status != "done")
    top[0].caption(f"{len(pet.tasks)} tasks · {remaining} min outstanding")
    if top[1].button("Mark all done", key=f"all_done_{pet_index}", use_container_width=True):
        # Snapshot the list first: complete() appends the next occurrence of a
        # recurring task, and we must not complete those freshly-spawned tasks.
        for t in list(pet.tasks):
            t.complete(date.today())
        # Clear per-task checkbox state so the boxes re-render as ticked.
        for i in range(len(pet.tasks)):
            st.session_state.pop(f"done_{pet_index}_{i}", None)
        invalidate_plan()
        st.rerun()

    spawned_recurring = False
    # Iterate a snapshot so a spawned occurrence isn't processed mid-loop.
    for i, t in list(enumerate(pet.tasks)):
        with st.container(border=True):
            check, title, meta = st.columns([0.5, 3.5, 2], vertical_alignment="center")
            is_done = check.checkbox(
                "done",
                value=(t.status == "done"),
                key=f"done_{pet_index}_{i}",
                label_visibility="collapsed",
            )
            # Toggle completion. Only act on a real transition so we don't
            # re-spawn a recurring task's next occurrence on every rerun.
            if is_done and t.status != "done":
                if t.complete(date.today()) is not None:
                    spawned_recurring = True
                invalidate_plan()
            elif not is_done and t.status == "done":
                t.update_status("pending")
                invalidate_plan()

            label = f"~~{t.name}~~" if t.status == "done" else f"**{t.name}**"
            if t.recurrence is not Recurrence.NONE:
                label += f" 🔁 {t.recurrence.value}"
            title.markdown(label)

            deadline = f" · by {t.deadline:%H:%M}" if t.deadline else ""
            meta.markdown(
                f"{t.duration} min · {priority_badge(t.priority)}{deadline}"
            )
    if spawned_recurring:
        # Redraw so the newly-created next occurrence shows up immediately.
        st.rerun()
else:
    st.info(f"No tasks for {pet.name} yet — add one above, or ask for a wellness routine.")

st.divider()


# --- 3. schedule -----------------------------------------------------------

st.markdown("#### 📅 Today's schedule")
st.caption(
    "Sorts every pet's tasks by priority then deadline, fits them into your "
    "available time, and checks for overlaps."
)

build_col, preview_col = st.columns([1.2, 3], vertical_alignment="bottom")
if build_col.button("Generate schedule", type="primary", use_container_width=True):
    st.session_state.plan = scheduler.generate_plan()

# Sorting preview — chronological timeline via Scheduler.sort_by_time().
with preview_col.popover("Preview: sorted by time", use_container_width=True):
    ordered = scheduler.sort_by_time()
    if ordered:
        for t in ordered:
            due = f"{t.deadline:%H:%M}" if t.deadline else "no deadline"
            st.markdown(f"`{due}` {t.name} · {t.duration} min · {t.pet.name}")
    else:
        st.caption("No tasks yet.")

plan = st.session_state.get("plan")
if plan is not None:
    if plan:
        used = sum(t.duration for t in plan)
        st.caption(f"{len(plan)} tasks · {used} of {owner.available_minutes} min used")
        for t in plan:
            end = (t.start.hour * 60 + t.start.minute + t.duration) % (24 * 60)
            with st.container(border=True):
                slot, body, meta = st.columns([1, 3, 2], vertical_alignment="center")
                slot.markdown(f"**{t.start:%H:%M}**")
                slot.caption(f"→ {end // 60:02d}:{end % 60:02d}")
                body.markdown(f"**{t.name}**")
                body.caption(t.pet.name)
                deadline = f" · by {t.deadline:%H:%M}" if t.deadline else ""
                meta.markdown(f"{t.duration} min · {priority_badge(t.priority)}{deadline}")
    else:
        st.info("Nothing could be scheduled. Add tasks or increase your available time.")

    # Filtering — tasks dropped because the time budget ran out.
    skipped = [t for t in owner.all_tasks() if t.status == "skipped"]
    if skipped:
        st.warning(
            "Didn't fit in the time available: "
            + ", ".join(f"{t.name} ({t.pet.name})" for t in skipped),
            icon="⏳",
        )

    # Conflict detection — flag any overlapping start times in the plan.
    conflicts = scheduler.detect_conflicts(plan)
    if conflicts:
        st.error("Schedule conflicts detected:", icon="⚠️")
        for a, b in conflicts:
            st.markdown(
                f"- **{a.name}** ({a.pet.name}) overlaps **{b.name}** "
                f"({b.pet.name}) at {b.start:%H:%M}"
            )
    elif plan:
        st.success("No conflicts — tasks are scheduled back-to-back.", icon="✅")
