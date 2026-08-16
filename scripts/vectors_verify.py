"""Replay the vectors, and write down what happened.

    python scripts/vectors_verify.py

This is the only thing in the repo permitted to say that the vectors were
replayed, because it is the only thing that watches the replay. Everything
downstream — `scripts/vectors_report.py`, the `/vectors` page — reads the
receipt this leaves behind and reports what it says, including "nothing has been
recorded" when there is no receipt at all.

## Why the digests are recorded alongside the outcome

`make vectors` regenerates `tests/core/vectors/`. A receipt written before that
ran describes files that no longer exist, and "9 passed" against a corpus that
has since changed is worth nothing while looking exactly like a pass. So the
receipt records the digest of each file it replayed, and `vectors_report.py`
re-digests at publish time and compares. The receipt cannot vouch for itself.

## Why it shells out to pytest

The alternative is importing `tests/core/test_vectors.py` and calling its
functions, which would produce a number this script derived rather than one
pytest reported — and the count that matters to a reader is the one they would
get by running the suite themselves. `scripts/sync_docs.py` takes the same view
of the collection count for the same reason.

The exit code is the verdict. Everything else on the receipt is description.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from misquote.tearsheet import provenance, vectors

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "vetting" / "runs" / "vectors-replay.json"
REPLAY = "tests/core/test_vectors.py"

#: pytest's own tail line: "10 passed, 1 warning in 1.03s".
_COUNT = re.compile(r"(\d+) (passed|failed|error|errors|skipped)")

#: The tail line itself. Under `-q` pytest prints it bare, with no `====`
#: banner around it, so the banner pattern that works for a verbose run matches
#: nothing here — and a fallback returning `splitlines()[-1:]` put a *list* on
#: the receipt where the page expects a sentence.
_TAIL = re.compile(r"^\s*(\d+ (?:passed|failed|error).*)$", re.M)


def run(replay: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", replay, "-q", "-p", "no:cacheprovider"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    text = f"{result.stdout}\n{result.stderr}"
    counts = {kind: int(n) for n, kind in _COUNT.findall(text)}
    tails = _TAIL.findall(text)

    return {
        "command": f"pytest {replay}",
        "exit_code": result.returncode,
        # The exit code is the verdict; the counts are description. A run that
        # exits non-zero is a FAIL whatever the numbers say about it, and a
        # failing replay is the single most valuable thing this page can show.
        "outcome": "PASS" if result.returncode == 0 else "FAIL",
        "tests_passed": counts.get("passed", 0),
        "tests_failed": counts.get("failed", 0) + counts.get("error", 0),
        # Always a string. Verbatim from pytest when it can be found, and the
        # last line of output when it cannot — pytest changing its summary
        # format should degrade to a rougher sentence, never to a shape the
        # page was not written for.
        "summary_line": (
            tails[-1].strip()
            if tails
            else next((line for line in reversed(text.splitlines()) if line.strip()), "").strip()
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--replay", default=REPLAY)
    args = parser.parse_args()

    corpus = vectors.corpus()
    observed = run(args.replay)

    receipt = {
        **observed,
        # What was replayed, in the terms the page reports it. Never
        # "comparisons made": this script did not watch the assertion loops. It
        # watched nine named tests exit zero, and those tests are the ones that
        # load these groups, which hold this many cases. That is the claim.
        "groups_replayed": [g["group"] for g in corpus["groups"]],
        "cases_covered": corpus["cases"],
        "digests": {g["group"]: g["sha256"] for g in corpus["groups"]},
        **provenance.build_stamp(
            f"pytest {args.replay}",
            source="the committed vectors, replayed",
        ),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    print(f"  {receipt['outcome']}  {receipt['summary_line']}")
    print(f"  covered   {receipt['cases_covered']:,} cases in {len(receipt['digests'])} groups")
    print(f"  -> {out}")
    # Non-zero when the replay failed. A recorder that always exits 0 turns a
    # broken proof into a quiet file change nobody notices in CI.
    return 0 if receipt["exit_code"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
