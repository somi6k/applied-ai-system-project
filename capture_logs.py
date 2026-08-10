"""Regenerate every execution log in `logs/`.

Each log is the verbatim stdout/stderr of one command, with a header recording
the command and the exit code, so anyone can reproduce it:

    python capture_logs.py              # everything (needs GEMINI_API_KEY)
    python capture_logs.py --offline    # only the commands that need no API key

Offline logs are deterministic. The live ones depend on the model and on the
free tier's daily request cap, so they are dated snapshots of a real run.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"

# (filename, argv, needs_api_key, what it demonstrates)
COMMANDS = [
    ("tests.txt", [sys.executable, "-m", "pytest", "-v"], False,
     "The full automated test suite (scheduler + RAG + guardrail)."),
    ("evaluate-offline.txt", [sys.executable, "evaluate.py", "--offline", "-v"], False,
     "Guardrail replay: one clean and six adversarial model outputs."),
    ("scheduler-cli.txt", [sys.executable, "main.py"], False,
     "The original Module 2 scheduler: sorting, planning, recurrence, conflicts."),
    ("evaluate-live.txt", [sys.executable, "evaluate.py", "-v"], True,
     "Three pet profiles end to end against Gemini, with invariants asserted."),
    ("evaluate-review.txt", [sys.executable, "evaluate.py", "--review"], True,
     "Awkward-input scenarios used for human evaluation."),
    ("app-walkthrough.md", [sys.executable, "capture_walkthrough.py"], True,
     "A click-by-click interaction log of the Streamlit UI, in place of screenshots."),
]


def run(name: str, argv: list[str], description: str) -> int:
    """Run one command and write its output to logs/<name>. Returns the exit code."""
    printable = " ".join(["python"] + [str(a) for a in argv[1:]])
    # Force UTF-8 both ways: on Windows the child would otherwise emit UTF-8
    # while the parent decoded it as cp1252, turning every em dash into mojibake.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        argv, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env
    )
    body = (result.stdout or "") + (result.stderr or "")

    target = LOGS / name
    if result.returncode != 0 and target.exists():
        # Don't let a transient failure (usually the daily API quota) destroy a
        # good capture. The kept log records its own date in its header.
        print(f"  [KEPT] logs/{name:<24} run failed; previous capture left in place")
        return result.returncode

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    if name.endswith(".md"):
        # The walkthrough is already markdown; only prepend provenance.
        header = f"<!-- captured {stamp} by `{printable}` (exit {result.returncode}) -->\n\n"
        text = header + body
    else:
        text = (
            f"$ {printable}\n"
            f"# captured {stamp} · exit code {result.returncode}\n"
            f"# {description}\n"
            f"{'-' * 78}\n\n{body}"
        )

    target.write_text(text, encoding="utf-8")
    status = "ok " if result.returncode == 0 else "FAIL"
    print(f"  [{status}] logs/{name:<24} {printable}")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true", help="skip the commands that call the API"
    )
    args = parser.parse_args()

    LOGS.mkdir(exist_ok=True)
    selected = [c for c in COMMANDS if not (args.offline and c[2])]
    print(f"Capturing {len(selected)} log(s) into {LOGS.relative_to(ROOT)}/\n")

    failures = 0
    for name, argv, _needs_key, description in selected:
        failures += bool(run(name, argv, description))

    print(f"\n{len(selected) - failures}/{len(selected)} command(s) exited 0.")
    if failures:
        print("A non-zero exit is still captured — check the log for why.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
