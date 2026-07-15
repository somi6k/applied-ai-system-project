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

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

- What constraints does your scheduler consider (for example: time, priority, preferences)?
- How did you decide which constraints mattered most?

**b. Tradeoffs**

- Describe one tradeoff your scheduler makes.
- Why is that tradeoff reasonable for this scenario?

---

## 3. AI Collaboration

**a. How you used AI**

- How did you use AI tools during this project (for example: design brainstorming, debugging, refactoring)?
- What kinds of prompts or questions were most helpful?

**b. Judgment and verification**

- Describe one moment where you did not accept an AI suggestion as-is.
- How did you evaluate or verify what the AI suggested?

---

## 4. Testing and Verification

**a. What you tested**

- What behaviors did you test?
- Why were these tests important?

**b. Confidence**

- How confident are you that your scheduler works correctly?
- What edge cases would you test next if you had more time?

---

## 5. Reflection

**a. What went well**

- What part of this project are you most satisfied with?

**b. What you would improve**

- If you had another iteration, what would you improve or redesign?

**c. Key takeaway**

- What is one important thing you learned about designing systems or working with AI on this project?
