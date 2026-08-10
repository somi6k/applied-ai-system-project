# Execution logs

Reproducible evidence that PawPal+ runs, in place of demo screenshots. Every
file here is the verbatim stdout/stderr of one command, with a header recording
the command, the capture time, and the exit code.

Regenerate everything:

```bash
python capture_logs.py             # all logs (live ones need GEMINI_API_KEY)
python capture_logs.py --offline   # only the deterministic, no-key logs
```

A failed run never overwrites a good capture — `capture_logs.py` leaves the
previous file in place and reports `[KEPT]`, so a transient API failure cannot
destroy evidence.

## What each log shows

| File | Command | Needs a key? | Deterministic? |
|---|---|---|---|
| [`tests.txt`](tests.txt) | `python -m pytest -v` | no | yes |
| [`evaluate-offline.txt`](evaluate-offline.txt) | `python evaluate.py --offline -v` | no | yes |
| [`scheduler-cli.txt`](scheduler-cli.txt) | `python main.py` | no | yes |
| [`evaluate-live.txt`](evaluate-live.txt) | `python evaluate.py -v` | **yes** | no — model output varies |
| [`evaluate-review.txt`](evaluate-review.txt) | `python evaluate.py --review` | **yes** | no — model output varies |
| [`app-walkthrough.md`](app-walkthrough.md) | `python capture_walkthrough.py` | **yes**, for step 3 only | partly |

**`tests.txt`** — the full suite: 16 scheduler tests plus 48 covering chunking,
retrieval, the embedding cache, degradation paths, the guardrail, and parsing.
No network; a fake embedder stands in for Gemini.

**`evaluate-offline.txt`** — the guardrail replayed against one clean and six
adversarial model outputs (fabricated citation, allergen, over budget, zero
duration, uncited, duplicate) plus a non-JSON response. This is the log to read
first if you want to see the reliability mechanism actually working.

**`scheduler-cli.txt`** — the original Module 2 scheduler with no AI involved:
sorting, priority-first planning under a time budget, recurrence, and a conflict
warning that does not crash the program.

**`evaluate-live.txt`** — three pet profiles (a bored Border Collie with a
chicken allergy, a senior cat, a puppy) end to end against Gemini, with
retrieval confidence reported and output invariants asserted.

**`evaluate-review.txt`** — the five awkward-input scenarios used for human
evaluation: allergen avoidance, an allergen synonym, an off-topic question, a
blank pet profile, and a five-minute budget. Verdicts are recorded in
[`../assets/model_card.md`](../assets/model_card.md#human-evaluation).

**`app-walkthrough.md`** — a click-by-click interaction log of the Streamlit UI,
produced by driving `app.py` through Streamlit's `AppTest` harness: open the
app, enter a new owner and pet, record an allergy, ask the advisor, accept the
routine, build the schedule, then reset for the next user. Each step prints what
the page rendered plus the resulting domain state.

## Note on the live logs

Generation runs on the Gemini free tier, which caps requests per day. A full
`python capture_logs.py` makes nine API calls; once the daily cap is reached,
the live commands fail and their logs record the quota error instead of a
routine.

That failure mode is itself documented behaviour — the system reports
`Gemini quota exhausted …` in one line rather than crashing or dumping a raw
429 body, and retrieval keeps working — but if you want the live logs to show
successful generations, run `python capture_logs.py` once the quota resets.
The offline logs above are unaffected and always reproducible.
