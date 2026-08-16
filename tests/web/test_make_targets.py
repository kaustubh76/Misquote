"""A `make x` written in prose must be a `make x` you can run.

`docs/FOR_JUDGES.md` tells a judge to run commands, error messages tell an
operator to run commands, and docstrings tell the next reader to run commands.
Each is a claim of the same kind as a cited assumption or a named file, and it
fails the same way: silently, long after the target was renamed.

## Why the backtick is load-bearing

The obvious pattern, `\\bmake\\s+(\\w+)`, is unusable. Measured across this repo it
produces thirteen phantom targets out of ordinary English — "make sure", "make
it", "make the", "make one", "make every", "make this" — twenty-eight false
positives against forty-four true mentions. A guard that noisy gets an
allowlist, and an allowlist that large stops being a guard.

Requiring a backtick or a shell prompt drops that to zero false positives, and
that is not a coincidence: prose says *make sure*, documentation says
`` `make sure` `` never. The anchor is the signal.

## What is deliberately not guarded

A companion survey checked every backticked *identifier* in every Python
docstring: 222 distinct tokens, 191 resolving, and of the 31 that did not, only
two were genuine defects. The other 29 were legitimate references to Solidity
contracts (`NonfungiblePositionManager`, `TickMath`), JSON-RPC methods
(`eth_getLogs`) and notation from `warden_spec.md` (`P_k`, `imb_t`). Gating on
that would need a 29-entry allowlist that grows whenever someone names an
external contract, so it is not gated — the two real findings were fixed by
hand instead. The numbers are recorded here so the decision stays checkable
rather than merely remembered.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MAKEFILE = REPO / "Makefile"

# This file, excluded from its own scan. Its docstring quotes `make sure` as the
# false positive it exists to reject, so scanning itself would fail on its own
# counter-example. The same self-reference appears in
# `test_comment_references.py` for the same reason: a guard that documents its
# failure modes has to quote them.
SELF = Path(__file__).resolve()

SCANNED_SUFFIXES = (".md", ".py", ".ts", ".tsx", ".mjs")
SKIP_DIRS = frozenset({"node_modules", ".next", "out", ".venv", "__pycache__", ".git", "lib"})

# `make x` inside backticks, or after a shell prompt. Never bare.
INVOKED = re.compile(r"(?:`|\$ )make\s+([a-z][a-z0-9-]*)")

# `target:` at the start of a line, which is what `make` itself recognises.
RULE = re.compile(r"^([a-zA-Z][\w.-]*):", re.MULTILINE)
PHONY = re.compile(r"^\.PHONY:(.*)$", re.MULTILINE)


def real_targets() -> set[str]:
    return set(RULE.findall(MAKEFILE.read_text())) - {".PHONY"}


def sources() -> list[Path]:
    out: list[Path] = []
    for path in REPO.rglob("*"):
        if path.suffix not in SCANNED_SUFFIXES or not path.is_file():
            continue
        if SKIP_DIRS & set(path.relative_to(REPO).parts) or path == SELF:
            continue
        out.append(path)
    return out


def test_every_make_target_named_in_prose_exists() -> None:
    targets = real_targets()
    assert targets, "no rules found — has the Makefile moved?"

    missing: dict[str, list[str]] = {}
    for path in sources():
        for name in INVOKED.findall(path.read_text()):
            if name not in targets:
                missing.setdefault(name, []).append(path.relative_to(REPO).as_posix())

    assert not missing, (
        "prose names make targets that do not exist: "
        f"{ {k: sorted(set(v)) for k, v in sorted(missing.items())} }"
    )


def test_phony_lists_every_target() -> None:
    """`.PHONY` and the rules must not drift apart.

    None of these targets produces a file of its own name, so all of them are
    phony. A target left off the list keeps working right up until someone
    creates a file that happens to share its name, and then stops — silently,
    and for a reason nobody would guess from the symptom.
    """
    text = MAKEFILE.read_text()
    declared = set(" ".join(PHONY.findall(text)).split())
    missing = sorted(real_targets() - declared)

    assert not missing, f"real targets absent from .PHONY: {missing}"


def test_the_guard_is_actually_looking_at_something() -> None:
    """A guard that matches nothing passes for the wrong reason."""
    found: set[str] = set()
    for path in sources():
        found.update(INVOKED.findall(path.read_text()))

    assert len(found) >= 10, f"only found {len(found)} invocations: {sorted(found)}"
    assert "test" in found and "web-check" in found
