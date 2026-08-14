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


def git_dirty() -> bool | None:
    """Whether the working tree had uncommitted changes at generation time.

    Published because an artifact generated from a dirty tree cannot be
    reproduced from its own commit sha, and a reader checking the sha deserves
    to be told that before they try.
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
    return bool(out.stdout.strip())


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
