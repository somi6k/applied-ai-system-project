# PawPal+ Project Reflection

## 1. System Design

**a. Initial design**

- Briefly describe your initial UML design.
- What classes did you include, and what responsibilities did you assign to each?

User should be able to add a pet with name, breed, hair, allergy, medication, etc attributes. User should be able to schedule specific tasks (walking, bathing, medication, vet visits) within time constraints. User should be able to have assistant plan tasks and provide a daily list, preferbly with justification.

Classes: Pet (attributes: name, breed, medications, allergies, preferred food, upcoming appointemnts) (methods: change name, update medication, update appointment, update allergies, update food preference)
Owner (attributes: name, availability, preferences, pets) (methods: change name, update availability, update preferences, update pets)
Task (attributes: task name, time allocated, deadline) (methods: add task, change time, change deadline)
Schedule (attributes: owner, pet, task, time, status) (methods: assign owner, assign pet, assign task, assign time, update status)

**b. Design changes**

- Did your design change during implementation?
- If yes, describe at least one change and why you made it.

Based on AI feedback, I changed priority from strings to an enum to make sorting easier, we added a start/end time field for Tasks to determine overlapping, added a pets field to the Owner to fix the relationship, and moved status from Schedule to Task. Then further updates moved tasks to Pets, with Owner gaining method all_tasks.

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

- What constraints does your scheduler consider (for example: time, priority, preferences)?
- How did you decide which constraints mattered most?

Scheduler considers time and priority contraints, with priority taking precedence over maximizing time allocation. For example several low priority tasks could fill an available time slot versus a single high priority task. Ai helped decide to use priority allocation as the preferred method as the Owner has already determined which has the highest priority.

**b. Tradeoffs**

- Describe one tradeoff your scheduler makes.
- Why is that tradeoff reasonable for this scenario?

The scheduler places highest priority tasks back to back and stops as soon as then next one doesnt fit. It does not search for smaller tasks that could potentially fill the remaining time. This is reasonable because it assumes the owner wants the tasks completed in order of priority vs quantity.

---

## 3. AI Collaboration

**a. How you used AI**

- How did you use AI tools during this project (for example: design brainstorming, debugging, refactoring)?
- What kinds of prompts or questions were most helpful?

I used AI for all stages of the project other than the initial brainstorming of objects and relationships. Prompts asking the AI to implement and refactor sections were most helpful, as well as asking it to explain why it made certain decisions in the implementation.

**b. Judgment and verification**

- Describe one moment where you did not accept an AI suggestion as-is.
- How did you evaluate or verify what the AI suggested?

The initial schedule object suggested by AI did not allow for multiple pets within a single schedule. Evaluating from the perspective of the user, I asked it to allow for multiple pets as a normal multi-pet owner would want to schedule for all their pets.

---

## 4. Testing and Verification

**a. What you tested**

- What behaviors did you test?
- Why were these tests important?

Tests were written against the major functions and algorithms, including sorting, filtering, conflict detection and edge cases. These tests are important in that they verify the more complex sections of code and odd cases which the user may encounter.

**b. Confidence**

- How confident are you that your scheduler works correctly?
- What edge cases would you test next if you had more time?

I have great confidence the scheduler works correctly given the test suite and step by step implementation process with spot checks along the way. Given more time, I would implement robustness tests to guarantee large amounts of data process correctly in the app.


---

## 5. Reflection

**a. What went well**

- What part of this project are you most satisfied with?

I am satisfied with the code quality and organized structure of the project, as well as the test suite.

**b. What you would improve**

- If you had another iteration, what would you improve or redesign?

I would like to imporove the UI significantly, providing nicer elements and flow guiding the user along step-by-step.

**c. Key takeaway**

- What is one important thing you learned about designing systems or working with AI on this project?

I learned that AI is a powerful partner in designing sytems but still requires user input during critical implementation decision times. The suggestions it makes, if accepted, can significantly cause previous code to be refactored, requiring the developer to review those sections to verify they still reflect the desired implementation.
 
