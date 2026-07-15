from pawpal_system import Pet, Task


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
