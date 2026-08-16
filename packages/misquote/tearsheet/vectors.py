"""What is in `tests/core/vectors/`, read off disk and nothing more.

`docs/FOR_JUDGES.md` opens its "what is actually proven" table with *19,546
comparisons against the real Solidity, exact integer equality, zero mismatches*.
Nothing on the website has ever mentioned it.

Publishing that sentence is not as simple as counting the files, and the
distinction this module exists to hold is the reason:

**The vectors are recorded answers, not comparisons.** `scripts/gen_vectors.py`
deploys `vetting/forge/src/Exposer.sol` — a thin wrapper over upstream v3-core
and v3-periphery at the commits pinned in `ops/forge_deps.txt` — to a local
chain, asks it thousands of questions, and writes down what it said. It refuses
to write anything at all if a single answer disagreed with ours. So the presence
of these files establishes exactly one thing: *a differential run, at seed
20260813, agreed*.

What it does **not** establish is that today's Python still agrees. That is a
claim about a test run — `tests/core/test_vectors.py` — and a module that read
the files and reported "zero mismatches" would be asserting a result it never
observed. Which is the failure this project is named after.

So this module returns the corpus and says nothing about verification. The
run's outcome is recorded separately, by something that actually watched it.

The whole thing is a pure function of files on disk, which makes it a
projection under the rule in `tests/web/test_artifact_projections.py`: cheap
enough to call in a test, so the published artifact can be checked against it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
VECTOR_DIR = REPO / "tests" / "core" / "vectors"
FORGE_DEPS = REPO / "ops" / "forge_deps.txt"

#: `name  <40-hex sha>  <date>`, ignoring the comment block above it.
_PIN = re.compile(r"^(\S+)\s+([0-9a-f]{40})\s+(\S+)\s*$")


def pins(path: Path = FORGE_DEPS) -> list[dict[str, str]]:
    """The upstream commits the vectors were recorded against.

    Worth publishing beside the counts, because "checked against Uniswap" is
    the kind of claim that decays silently: the sentence stays true-sounding
    while the code it referred to moves on. A commit is checkable.

    None of the vector files records a commit itself — they name
    `ops/forge_deps.txt` and leave it there — so this is the only place the two
    halves get joined.
    """
    if not path.is_file():
        return []
    found = []
    for line in path.read_text().splitlines():
        match = _PIN.match(line)
        if match:
            found.append(
                {"name": match.group(1), "commit": match.group(2), "pinned": match.group(3)}
            )
    return found


def corpus(directory: Path = VECTOR_DIR) -> dict[str, Any]:
    """Every recorded vector group, with its provenance and its digest.

    The digest is the load-bearing field. `make vectors` can regenerate these
    files at any time, and a replay recorded before that ran is a statement
    about files that no longer exist. Publishing the digest lets the emitter
    compare what a run saw against what is on disk now, so a stale receipt
    reads as stale rather than as a pass.
    """
    groups: list[dict[str, Any]] = []

    for path in sorted(directory.glob("*.json")):
        raw = path.read_bytes()
        data = json.loads(raw)
        cases = data.get("cases", [])
        groups.append(
            {
                "group": path.stem,
                "cases": len(cases),
                "seed": data.get("seed"),
                "source": data.get("source"),
                "recorded_by": data.get("generated_by"),
                "path": str(path.relative_to(REPO)),
                # Truncated: this identifies a file, it does not defend against
                # anyone. A full digest in a table column is a wall of hex that
                # nobody reads and that pushes every other column off-screen.
                "sha256": hashlib.sha256(raw).hexdigest()[:16],
            }
        )

    return {
        "dir": str(directory.relative_to(REPO)),
        "cases": sum(g["cases"] for g in groups),
        "groups": groups,
        "pins": pins(),
    }
