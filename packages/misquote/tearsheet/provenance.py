"""Where a number came from, stamped onto the artifact that carries it.

`Readme.md` rule 6 says every displayed number must trace to a chain query or to
a published assumption. That is a claim about the *number*; this module handles
the claim about the *file* — which command produced it, from which commit, and
when. Without it a stale artifact is indistinguishable from a fresh one, and the
site would keep confidently rendering figures whose inputs changed hours ago.

Deliberately not a hash of the content: the question a reader asks is not "has
this file been edited" but "is this the current answer", and only the commit and
the timestamp can speak to that.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]


def git_sha(short: bool = True) -> str | None:
    """The commit the artifacts were generated from, or None outside a checkout.

    Returns None rather than raising or inventing a placeholder. A build stamp
    that says "unknown" is honest; one that says "dev" looks like a real answer.
    """
    args = ["git", "rev-parse", *(["--short"] if short else []), "HEAD"]
    try:
        out = subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


#: What this pipeline writes. Uncommitted changes here are not evidence of an
#: unreproducible build — they are evidence that an emitter just ran, which is
#: the one thing a build stamp already tells you.
#:
#: Every path is an emitter's *output*. `docs/ASSUMPTIONS.md` and
#: `docs/REQUIREMENTS_MATRIX.md` are deliberately absent: they are hand-written
#: inputs to `make assumptions`, and editing one genuinely does make the artifact
#: it produced unreproducible from its commit.
GENERATED: tuple[str, ...] = (
    "apps/web/public/artifacts/",  # every artifact the site reads
    "docs/FOR_JUDGES.md",  # make judges
    "docs/TEARSHEET.md",  # make tearsheet
    "docs/AGENT_ADVANTAGE.md",  # make advantage
    "docs/AGENT_ADVANTAGE_SHORT.md",  # make advantage-short
    "MISQUOTE_FLOW.excalidraw",  # make diagram
)


def _touched(porcelain: str) -> list[str]:
    """Paths from `git status --porcelain`, ignoring this pipeline's own output.

    Porcelain is `XY path`, two status columns and a space. A rename is
    `XY old -> new`, and the destination is the one that matters — a file
    renamed *into* the artifacts directory is still an artifact.
    """
    paths = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if not path.startswith(GENERATED):
            paths.append(path)
    return paths


def git_dirty() -> bool | None:
    """Whether the working tree had uncommitted *input* changes at generation time.

    Published because an artifact generated from a dirty tree cannot be
    reproduced from its own commit sha, and a reader checking the sha deserves
    to be told that before they try.

    ## Why the emitters' own output does not count

    This asked `git status --porcelain` and returned `bool(output)`, which made
    the answer **structurally always true**. `make artifacts` runs thirteen
    emitters in sequence: the first writes on a clean tree and stamps
    `git_dirty: false`, and from that moment the tree contains an uncommitted
    artifact, so every emitter after it stamps `true` — because the one before it
    ran. Measured directly: regenerating five artifacts in a row produced one
    false and four trues, in emitter order, on a tree with no source edits at all.

    A flag that cannot be false is not a flag. And it is not decorative:
    `BuildStamp` renders it on every page, `/artifacts` aggregates the dirty ones
    into a census, and `service.py` sends it as `X-Misquote-Dirty`. All three were
    reporting "this cannot be reproduced from its commit" about files whose only
    uncommitted neighbours were other files from the same run.

    The question the field exists to answer is whether the *inputs* were
    committed. So the outputs are excluded and everything else still counts — an
    uncommitted change to an estimator, a chain address or a hand-written
    assumption makes the artifact unreproducible exactly as before.
    """
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return bool(_touched(out.stdout))


def build_stamp(command: str, *, source: str, **extra: Any) -> dict[str, Any]:
    """The provenance block every generated artifact carries.

    `source` is the one field that changes what the numbers *mean*: "chain" and
    "synthetic" are not two qualities of the same result, they are two different
    claims, and the UI is required to say which one it is showing.
    """
    return {
        "command": command,
        "source": source,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "git_dirty": git_dirty(),
        **extra,
    }
