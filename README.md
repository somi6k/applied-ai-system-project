# PawPal+ — a pet-care planner that knows *what* to schedule, not just *when*

**PawPal+** is a Streamlit application that plans a pet owner's day. It holds
the owner's pets, their care tasks, and how much time the owner actually has,
then builds a time-boxed schedule and flags conflicts. This project extends it
with a **retrieval-augmented wellness advisor**: the app now retrieves guidance
from a curated pet-care knowledge base, grounds a Gemini model in what it
found, checks the result against a code-level guardrail, and turns the surviving
suggestions into real scheduled tasks.

**Why it matters.** A scheduler can only plan tasks you already knew to enter.
Most people don't know that a 4-month-old puppy shouldn't jog on pavement
because its growth plates are open, or that fifteen minutes of sniffing tires a
dog about as much as an hour of brisk walking. That knowledge is what turns a
to-do list into actual care — and it's exactly the kind of knowledge where a
confident hallucination does harm, which is why every suggestion here is traced
to a retrieved passage and re-validated in code before it reaches the user.

### The original project (Modules 1–3)

The base project is **PawPal+**, the pet-care scheduler I designed in Module 2
from a UML class model and implemented in
`pawpal_system.py`. Its goal was to let an owner register pets and their care
tasks — each with a duration, priority, deadline, and optional daily/weekly
recurrence — and have a `Scheduler` build a realistic daily plan under a fixed
time budget. It could sort tasks chronologically or by priority, drop tasks once
the budget ran out, detect overlapping appointments without crashing, filter
pets by name or completion state, and spawn the next occurrence of a recurring
task on completion. All of that still works and is still the backbone of the
system; the advisor feeds it.

| Rubric requirement | Where |
|---|---|
| Original project & scope | [above](#the-original-project-modules-13) |
| New AI feature (RAG) | [What's new](#whats-new-a-retrieval-augmented-wellness-advisor) · `wellness_rag.py` |
| Architecture diagram | [Architecture Overview](#architecture-overview) · `diagrams/architecture.mmd` |
| Setup instructions | [Setup](#setup-instructions) |
| Sample interactions | [Sample Interactions](#sample-interactions) |
| Design decisions & trade-offs | [Design Decisions](#design-decisions) |
| Reliability / guardrail | [Reliability and Guardrails](#reliability-and-guardrails) · `evaluate.py` |
| Testing summary | [Testing Summary](#testing-summary) |
| Responsible-AI reflection | [`assets/model_card.md`](assets/model_card.md) |
| Reproducible execution evidence | [`logs/`](logs/) |

---

## What's new: a retrieval-augmented wellness advisor

`wellness_rag.py` adds a full RAG pipeline that suggests care activities for one
specific pet, grounded in a local knowledge base rather than model memory.

| Step | Implementation | Detail |
|---|---|---|
| **Load** | `load_passages`, `split_document` | Reads `knowledge/*.md` and splits each file at its `##` headings, so one chunk is one self-contained topic. 6 documents → 32 passages. |
| **Embed** | `GeminiEmbedder`, `KnowledgeBase.ensure_embeddings` | `gemini-embedding-001` at 768 dimensions. Vectors cached in `.wellness_cache.json` keyed by a hash of the passage, so editing one section re-embeds only that section. |
| **Retrieve** | `build_profile`, `KnowledgeBase.retrieve` | The query is a profile of the pet: breed, allergies, medications, existing tasks, the owner's remaining minutes, and an optional free-text question. Top-4 by cosine similarity. Documents embed as `RETRIEVAL_DOCUMENT`, the query as `RETRIEVAL_QUERY`. |
| **Generate** | `WellnessAdvisor.suggest` | Numbered passages + profile → `gemini-3.6-flash` with a JSON response schema, so activities come back as structured data, not prose. |
| **Validate** | `validate_routine` | Code-level guardrail — [see below](#reliability-and-guardrails). |
| **Integrate** | `Routine.to_tasks` | Each surviving activity becomes a real `Task`, which the **original** `Scheduler` then sorts, time-boxes, and conflict-checks like any other. |

The feature reads and writes live domain state in both directions: the pet's
allergies, medications, and existing tasks shape the query and the prompt, and
accepted activities become `Task` objects that the existing scheduler plans. A
suggestion that doesn't fit the day gets `skipped` by the same budget logic as a
hand-entered task.

**The knowledge base** (`knowledge/`, 6 documents → 32 passages): dog exercise;
cat enrichment; nutrition, hydration and allergies; grooming and dental care;
medication and vet routines; senior and behavioural wellness. To extend it, drop
in another `.md` file with `#` for the title and `##` per topic — new sections
are picked up and embedded on the next run.

---

## Architecture Overview

Data flows left-to-right through four stages. **Input** is two independent
sources: what the user types into the Streamlit UI, and the markdown knowledge
base on disk. **Retrieval** turns both into vectors — the corpus once (cached to
disk), the pet profile on every request — and keeps the four passages closest to
the profile by cosine similarity. **Generation** hands those numbered passages
plus the profile to Gemini under a JSON schema, and the reply passes through
tolerant parsing and then the guardrail, which drops anything ungrounded,
unsafe, or over budget. **Integration** is the part that makes this a system
rather than a chatbot: surviving activities become `Task` objects and re-enter
the original Module 2 domain model, where `generate_plan` time-boxes them and
`detect_conflicts` checks for overlaps. **Output** is two things — the schedule
itself, and an audit trail (which passages were used, at what similarity, and
what the guardrail changed) so any suggestion can be traced to its source.

The one branch worth noticing is the dotted line: if there's no API key or the
embedding call fails, retrieval falls back to keyword scoring and the system
keeps working with degraded quality instead of failing.

Diagram source: [`diagrams/architecture.mmd`](diagrams/architecture.mmd).

```mermaid
flowchart TB
    subgraph input["Input"]
        UI["Streamlit UI (app.py)<br/>owner, pets, tasks, focus question"]
        KNOW[("knowledge/*.md<br/>6 docs, 32 sections")]
    end

    subgraph rag["Retrieval-Augmented Generation (wellness_rag.py)"]
        direction TB
        SPLIT["load_passages / split_document<br/>chunk at ## headings"]
        EMBED["GeminiEmbedder.embed<br/>gemini-embedding-001, 768-dim"]
        CACHE[(".wellness_cache.json<br/>vectors keyed by content hash")]
        PROFILE["build_profile<br/>breed + allergies + meds +<br/>existing tasks + time budget"]
        RETRIEVE["KnowledgeBase.retrieve<br/>cosine similarity, top-k = 4"]
        KEYWORD["keyword_similarity<br/>fallback when embeddings fail"]
        PROMPT["format_context<br/>numbered passages + profile"]
        LLM{{"gemini-3.6-flash<br/>JSON response schema"}}
        PARSE["parse_routine<br/>tolerant JSON to activities"]
        GUARD["validate_routine (guardrail)<br/>citations, allergens,<br/>durations, time budget"]
    end

    subgraph domain["Scheduling domain (pawpal_system.py)"]
        TASKS["Routine.to_tasks makes Task<br/>Pet.add_task"]
        SORT["Scheduler.generate_plan<br/>priority, then deadline, then duration"]
        CONFLICT["Scheduler.detect_conflicts<br/>sort-then-sweep overlap check"]
    end

    subgraph output["Output"]
        PLAN["Time-boxed daily plan<br/>+ skipped tasks + conflict warnings"]
        AUDIT["Cited passages + similarity scores<br/>+ guardrail findings"]
    end

    KNOW --> SPLIT --> EMBED
    EMBED --> CACHE
    CACHE --> EMBED
    EMBED --> RETRIEVE
    UI --> PROFILE --> RETRIEVE
    RETRIEVE -.->|"no API key or embed error"| KEYWORD
    KEYWORD --> PROMPT
    RETRIEVE --> PROMPT --> LLM --> PARSE --> GUARD
    GUARD --> TASKS
    UI --> TASKS
    TASKS --> SORT --> CONFLICT --> PLAN
    GUARD --> AUDIT
    RETRIEVE --> AUDIT
    PLAN --> UI
    AUDIT --> UI
```

---

## Setup Instructions

```bash
# 1. Enter the project
cd applied-ai-system-project

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies (streamlit, pytest, google-genai)
pip install -r requirements.txt

# 4. Add a Gemini API key
cp .env.example .env               # Windows: copy .env.example .env
# paste your key into .env — free key from https://aistudio.google.com/apikey
```

`.env` should end up looking like:

```
GEMINI_API_KEY=AIza...your-key...
```

`GEMINI_API_KEY` (or `GOOGLE_API_KEY`) also works as a normal environment
variable. `.env` is gitignored — never commit a real key.

**Run it:**

```bash
streamlit run app.py          # the app, at http://localhost:8501
python main.py                # scheduler CLI demo (no API key needed)
python -m pytest              # 64 automated tests (no API key needed)
python evaluate.py --offline  # guardrail evaluation (no API key needed)
python evaluate.py            # live end-to-end evaluation (needs a key)
python evaluate.py --review   # awkward-input scenarios for human review
```

**Without an API key the app still runs.** Retrieval falls back to keyword
scoring and the UI shows the retrieved guidance; only the generated routine is
unavailable.

**Using the app.** The page follows the order the day gets planned:

1. **Sidebar** — owner name, minutes available today, add and search pets, the
   advisor's status, and **↩︎ Start over** to hand the app to a new user
   (*Clear everything* wipes all entries and widget state; *Restore demo data*
   puts the walkthrough back).
2. **Today's pet care** — pets, open tasks, care time needed vs available.
3. **🧠 Wellness routine** — pick a pet, optionally add a focus question, press
   *Suggest*. You get the routine, each activity's cited reason, cautions, the
   guardrail's findings, and every retrieved passage with its similarity score.
   One button adds the whole routine to the pet's tasks.
4. **✅ Tasks** — add and complete tasks; recurring ones spawn their next occurrence.
5. **📅 Today's schedule** — the original scheduler: time-boxed plan, tasks that
   didn't fit, conflict warnings.

---

## Sample Interactions

Three real runs, captured from `python evaluate.py -v`. Note that each `why`
cites the numbered passage it came from — the puppy's "5 minutes per month of
age" is verbatim from `knowledge/dog-exercise.md`, not model memory.

### Example 1 — a bored working dog

**Input**

```
Pet:        Mochi, Border Collie
Allergies:  chicken
Medication: thyroid tablet (twice daily, empty stomach)
Existing:   Morning walk (30 min, high)
Available:  60 minutes
Question:   "he's bored and chewing furniture"
```

**Output** — retrieval confidence: top-1 0.716, mean top-4 0.705

```
summary: Mochi is a high-energy Border Collie needing structured work and mental
exercise to prevent boredom and destructive behaviors like chewing [1]. Since he
already has a 30-minute morning walk, this 60-minute routine adds a decompression
sniff walk [2] and indoor enrichment [3] to keep him mentally tired.

· Decompression sniff walk (20 min, high)
    A late-afternoon sniff-led walk lowers arousal and mentally tires dogs far
    more efficiently than standard walking [2].
· Conduct indoor training session (15 min, high)
    High-energy working breeds need structured work, and a 10-15 minute training
    session provides mental stimulation to combat boredom [1][3].
· Set up scatter feeding (15 min, medium)
    Scatter feeding is an effective indoor enrichment activity that engages the
    dog's brain and prevents boredom [3].
· Play stair recalls or tug (10 min, medium)
    Structured indoor physical play provides extra physical output [1][3].

total: 60/60 min · sources: dog-exercise.md ×3, cat-enrichment.md ×1
```

### Example 2 — a senior cat

**Input**

```
Pet:        Willow, senior indoor cat
Medication: arthritis pain relief
Available:  30 minutes
Question:   "she's 14 and stopped jumping onto the sofa"
```

**Output**

```
summary: Willow's difficulty jumping onto the sofa is a typical indication of
joint stiffness and arthritis in senior cats. This 30-minute routine incorporates
gentle warm-ups, cooperative handling, quiet rest, and mental enrichment while
respecting her physical limitations.

· Gentle warm-up walk (5 min, high)
    Five minutes of slow walking warms up muscles and helps manage joint
    stiffness before play or movement [1].
· Practice cooperative handling (5 min, medium)
    Short reward-based handling sessions build mental exercise and reduce stress
    during future handling [4].
· Protect quiet rest block (15 min, high)
    Cats require 12-16 hours of daily sleep, so an uninterrupted rest block
    maintains mood and impulse control [2].
· Prepare food puzzle (5 min, low)
    A food puzzle provides mental stimulation and rewards quiet independent
    time [3].

total: 30/30 min
```

### Example 3 — a puppy, where getting it wrong would hurt

**Input**

```
Pet:        Biscuit, 4-month-old Golden Retriever puppy
Available:  90 minutes
Question:   "how much exercise is safe at this age?"
```

**Output**

```
summary: For a 4-month-old Golden Retriever puppy, safe formal exercise is about
20 minutes twice daily (5 minutes per month of age). Because large breed growth
plates remain open until 12-18 months, avoid high-impact activities like pavement
jogging, stair sprints, or jumping.

· Morning soft-ground walk (20 min, high)
    At 4 months old, Biscuit should have 20 minutes of formal exercise twice
    daily to protect growing joints [1].
· Evening soft-ground walk (20 min, high)
    Splitting daily activity into two shorter sessions provides bathroom breaks
    and avoids overexertion [1][2].
· Self-paced yard play (15 min, medium)
    Free play on soft grass where the puppy sets its own pace is safer for open
    growth plates than distance walking [1].
· Indoor training session (10 min, medium)
    A 10-minute session offers mental enrichment without physical impact [4].

total: 65/90 min
```

Each of these activities becomes a `Task` on the pet with one button press, and
the original scheduler then places them: `08:00 Decompression sniff walk`,
`08:20 Conduct indoor training session`, and so on, skipping anything that no
longer fits the day and warning about overlaps.

---

## Design Decisions

**RAG instead of a bare prompt.** Pet care is a domain where a fluent, wrong
answer causes harm, and where the model's training data is a mix of veterinary
guidance and forum folklore with no way to tell them apart at inference time.
Retrieval makes the source inspectable: every claim points at a passage the user
can read, and the guardrail can verify the pointer is real. *Trade-off:* the
system is now capped by the quality and coverage of 30 hand-written passages. It
will refuse or flounder on anything outside them — which I consider the correct
failure mode for this domain, but it is a real ceiling.

**Structured JSON output instead of prose.** The model returns activities under
a response schema (`name`, `duration_minutes`, `priority`, `why`) rather than a
paragraph. This is what makes the feature *integrated* rather than a chat box:
`Routine.to_tasks()` produces real `Task` objects that the Module 2 scheduler
plans, and constraints like "does this fit in 45 minutes" become checkable
arithmetic. *Trade-off:* slightly stiffer prose, and a schema I have to maintain
as the feature grows.

**A code-level guardrail after generation, not a longer prompt.** The prompt
asks the model to stay grounded, respect the budget, and avoid allergens; the
guardrail re-checks all three in Python. This was not theoretical caution —
during evaluation the model proposed a chicken-based reward for a
chicken-allergic dog whose allergy was in the prompt. *Trade-off:* the guardrail
is lexical and can be wrong in both directions. Its first version deleted a
perfectly safe *"chicken-free kibble"* suggestion, which took a fix and two
regression tests (see [`assets/model_card.md`](assets/model_card.md)).

**Drop lowest-priority-first when over budget.** When the model overshoots the
time budget, the guardrail removes activities in ascending priority until it
fits, mirroring the greedy priority-first tradeoff the Module 2 scheduler
already makes. *Trade-off:* like the scheduler, it may drop two quick useful
items to protect one long high-priority one.

**Fabricated citations drop the activity; missing citations only warn.** A
citation pointing at a passage that was never retrieved means the claim has no
source, so the activity goes. An activity with no citation at all is more often
connective tissue than a fabrication, so it is kept and flagged. *Trade-off:*
this is a judgement call, and the stricter reading — drop anything uncited —
would be defensible.

**Degrade instead of failing.** No key, a failed embedding call, a corrupt
cache, or malformed JSON each fall back rather than raise: keyword retrieval,
re-embedding, skipping one bad activity. The app is a demo that others will run
without my `.env`. *Trade-off:* keyword retrieval is noticeably worse and the
user must be told, so the UI flags degraded mode rather than hiding it.

**Disk-cached embeddings keyed by content hash.** Streamlit reruns the entire
script on every interaction; re-embedding 32 passages per click would be slow
and wasteful. Hashing the passage content means an edited document re-embeds
only its changed section. *Trade-off:* one more file to gitignore, and a stale
cache if the embedding model changes — mitigated by keying on model and
dimension too.

**Top-4 with no relevance threshold.** Four passages fit comfortably in context
and gave the best results in testing. *Trade-off:* a weak match still enters the
prompt as if it were evidence, and a fifth good passage is dropped. Measured
similarity scores turned out too compressed (0.66–0.71 across wildly different
queries) to threshold on safely — documented in the model card.

---

## Reliability and Guardrails

`validate_routine()` re-checks every constraint after generation, repairs what
it can, and records what it did on `routine.issues` — shown in the UI under
*🛡️ Guardrail*.

| Check | Severity | Action |
|---|---|---|
| `bad_citation` — cites a passage number never retrieved | error | **drop the activity** (fabricated source = unsupported claim) |
| `allergen_conflict` — would expose the pet to a recorded allergen | error | **drop the activity** |
| `budget_exceeded` — total exceeds the owner's available minutes | error | **drop lowest-priority activities** until it fits |
| `implausible_duration` — ≤ 0 or > 240 minutes | error | **clamp** into range |
| `missing_citation` — no `[n]` anywhere in the reason | warning | keep, flag as untraceable |
| `duplicate_task` — repeats a task the pet already has | warning | keep, flag |
| `no_activities` — nothing survived | error | report; UI shows the retrieved passages instead |

The allergen check is deliberately narrow about *context*: a mention in the
activity name is always a conflict, but a mention in the reason is only a
conflict when it isn't part of an avoidance instruction — so "reward with
chicken strips" is dropped while "use chicken-free kibble" survives.

Two more layers sit around it: a **JSON response schema** on the API call so the
model cannot return prose, and **tolerant parsing** that skips a single
malformed activity rather than losing the whole response.

### Guardrail behaviour, demonstrated

`python evaluate.py --offline -v` replays seven hand-written model outputs — one
clean, six adversarial — through the guardrail. Deterministic, no API key:

```
Guardrail replay — 7 cases, 4 retrieved passages

  [PASS] clean routine passes untouched — 0 issue(s)
           kept: ['Sniff walk', 'Brush teeth']
  [PASS] over-budget routine is trimmed to fit — 1 issue(s)
           [error] budget_exceeded: 70 min suggested, 45 min available
           kept: ['Long hike']
  [PASS] allergen suggestion is dropped — 1 issue(s)
           [error] allergen_conflict: 'Chicken treat training' mentions allergen 'chicken'
           kept: ['Sniff walk']
  [PASS] fabricated citation is dropped — 1 issue(s)
           [error] bad_citation: 'Hydrotherapy' cites [9] but only 4 passages were retrieved
           kept: ['Sniff walk']
  [PASS] uncited activity is kept but flagged — 1 issue(s)
           [warning] missing_citation: 'Evening cuddle' cites no passage
           kept: ['Evening cuddle']
  [PASS] implausible duration is clamped — 1 issue(s)
           [error] implausible_duration: 'Marathon' had 0 min
           kept: ['Marathon']
  [PASS] duplicate of an existing task is flagged — 1 issue(s)
           [warning] duplicate_task: 'Morning walk' is already a task
           kept: ['Morning walk']
  [PASS] non-JSON response raises GenerationError

All checks passed.
```

**Worked example — a hallucinated source.** Four passages were retrieved. The
model returned:

```json
{"name": "Hydrotherapy", "duration_minutes": 20, "priority": "high",
 "why": "Recommended for joint support [9]."}
```

`[9]` is outside the four retrieved passages, so nothing in the knowledge base
supports it. **Result:** activity dropped, `bad_citation` recorded, the rest of
the routine kept. The user never sees the ungrounded suggestion.

### Graceful degradation

| Failure | Behaviour |
|---|---|
| No API key / SDK not installed | `MissingAPIKey`; UI still shows retrieved guidance |
| Embedding call fails mid-session | Falls back to `keyword_similarity`; UI flags degraded mode |
| Daily API quota exhausted | One-line "quota exhausted" message, not a 430-character JSON blob |
| Model returns non-JSON | `GenerationError` with the first 200 characters, shown in the UI |
| One malformed activity in valid JSON | Skipped; the rest of the routine survives |
| Corrupt embedding cache | Re-embeds instead of crashing |
| Read-only checkout | Embeds each run instead of crashing |

---

## Testing Summary

> **64 of 64 automated tests pass** (16 scheduler, 48 RAG/guardrail) in under
> 3 seconds with no network. **8 of 8 guardrail replay cases pass.** **3 of 3
> live profiles** came back fully grounded and inside the owner's time budget.
> Across the five human-review scenarios, mean top-4 retrieval confidence was
> **0.689** (range 0.662–0.707). In human
> review of 6 awkward inputs, **4 passed outright**, 1 exposed an open
> limitation (lexical allergen matching misses "poultry" for a chicken
> allergy), and 1 exposed a bug that was fixed (unreadable quota errors).

```
tests\test_pawpal.py ................                                    [ 25%]
tests\test_wellness_rag.py ............................................. [ 95%]
============================= 64 passed in 2.96s ==============================
```

**What worked.** The layered approach paid off in a way I didn't anticipate:
the automated tests caught structural bugs, the offline guardrail replay caught
policy bugs, and human review caught the things neither could — that the model
assumes "dog" when the species is blank, and that it correctly refuses
off-topic questions. Faking the embedder in tests kept the whole suite offline
and fast, so it actually gets run. Degradation paths are tested as first-class
behaviour, not afterthoughts, which is why the free-tier quota running out
mid-evaluation was an annoyance rather than a crash.

**What didn't.** Three real failures, all found by running the system rather
than reading it:

1. **A confidently wrong model ID.** `gemini-2.5-flash` returned
   `404 … no longer available to new users` on the first live call. Fixed by
   querying `client.models.list()` for what the key can actually reach.
2. **The guardrail's first version was too blunt.** Matching the allergen as a
   raw substring deleted *"use her regular chicken-free kibble as rewards"* —
   the safest suggestion in the routine — for containing the word "chicken".
   Fixed with avoidance-context detection and two regression tests.
3. **Quota errors were unreadable.** Hitting the free tier's daily cap surfaced
   a 430-character JSON body. Now a single sentence.

**What I learned.** Constraints in a prompt are requests, not guarantees — the
model offered a chicken-based reward for a chicken-allergic dog whose allergy
was two lines above in the same prompt. Anything that matters has to be
re-checked in code, where it can't be talked out of. And the inverse: a safety
check that matches words rather than meaning will punish the model for being
careful, so guardrails need testing in *both* directions — that they catch the
unsafe thing, and that they let the safe thing through.

Full human-evaluation table, including the two failures above:
[`assets/model_card.md` → Human evaluation](assets/model_card.md#human-evaluation).

### Reproducible execution evidence

Every output quoted in this README is captured verbatim in [`logs/`](logs/) —
command output and interaction logs rather than screenshots, so a reader can
re-run the exact command and compare. Regenerate the whole folder with:

```bash
python capture_logs.py             # all logs (the live ones need GEMINI_API_KEY)
python capture_logs.py --offline   # only the logs that need no API key
```

| Log | Command | Shows |
|---|---|---|
| [`logs/tests.txt`](logs/tests.txt) | `python -m pytest -v` | All 64 tests, named individually |
| [`logs/evaluate-offline.txt`](logs/evaluate-offline.txt) | `python evaluate.py --offline -v` | Guardrail replay, 8/8 cases |
| [`logs/scheduler-cli.txt`](logs/scheduler-cli.txt) | `python main.py` | The Module 2 scheduler end to end |
| [`logs/evaluate-live.txt`](logs/evaluate-live.txt) | `python evaluate.py -v` | Three pet profiles against Gemini |
| [`logs/evaluate-review.txt`](logs/evaluate-review.txt) | `python evaluate.py --review` | The human-evaluation scenarios |
| [`logs/app-walkthrough.md`](logs/app-walkthrough.md) | `python capture_walkthrough.py` | A click-by-click log of the Streamlit UI |

`capture_walkthrough.py` drives `app.py` through Streamlit's `AppTest` harness —
the same clicks a user would make — and prints what each step rendered. That is
what replaces demo screenshots here: a screenshot proves the UI looked a certain
way once, while the walkthrough log can be regenerated and diffed.

Each log's header records the command, the capture time, and the exit code. See
[`logs/README.md`](logs/README.md) for what to expect from each, including which
ones depend on the API's daily free-tier quota.

---

## Project structure

```
applied-ai-system-project/
├── app.py                     # Streamlit UI (wellness → tasks → schedule)
├── pawpal_system.py           # original Module 2 domain model + Scheduler
├── wellness_rag.py            # NEW: RAG pipeline + guardrail
├── evaluate.py                # NEW: evaluation harness (offline / live / review)
├── main.py                    # scheduler CLI demo
├── capture_logs.py            # NEW: regenerates everything in logs/
├── capture_walkthrough.py     # NEW: drives the UI headlessly, emits an interaction log
├── knowledge/                 # NEW: 6 markdown docs → 32 retrievable passages
├── diagrams/
│   └── architecture.mmd       # NEW: system data-flow diagram (Mermaid source)
├── assets/
│   └── model_card.md          # NEW: limitations, misuse, reliability, AI collaboration
├── logs/                      # NEW: reproducible command output & interaction logs
│   ├── README.md              #      index: which command produced which file
│   ├── tests.txt              #      python -m pytest -v
│   ├── evaluate-offline.txt   #      python evaluate.py --offline -v
│   ├── evaluate-live.txt      #      python evaluate.py -v
│   ├── evaluate-review.txt    #      python evaluate.py --review
│   ├── scheduler-cli.txt      #      python main.py
│   └── app-walkthrough.md     #      python capture_walkthrough.py
├── tests/
│   ├── test_pawpal.py         # 16 scheduler tests
│   └── test_wellness_rag.py   # NEW: 48 RAG + guardrail tests
├── .env.example               # copy to .env and add your key
└── requirements.txt
```

---

## Reflection

Building this changed how I think about where intelligence belongs in a system.
My instinct was that the model *is* the feature — that a good enough prompt
would produce a good enough answer, and the engineering around it was plumbing.
The opposite turned out to be true. The model is the least reliable component,
and nearly all the useful work was in the structure around it: choosing what
goes into its context, constraining the shape of what comes back, and verifying
the result against rules it never gets to negotiate with. The most valuable line
of code in this project is a `continue` statement that throws away an activity
citing a passage that doesn't exist.

The second lesson was about problem-solving generally. Every real bug here —
the dead model ID, the over-eager allergen check, the illegible quota error —
was invisible in the code and obvious within one second of execution. Reading
carefully found none of them. Building the evaluation harness felt like a detour
from building the feature; it was the thing that found the feature's actual
defects, including one in the safety mechanism I'd written specifically to be
trustworthy.

My graded responsible-AI reflection — how I collaborated with AI, a helpful and
a flawed suggestion, and the system's limitations, biases, and misuse potential
— is in **[`assets/model_card.md`](assets/model_card.md)**.

---

*AI-generated wellness routines are grounded in the bundled knowledge base and
are not veterinary advice.*
