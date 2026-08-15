"""A comment that names a file must name a file that exists.

`tests/web/test_citations.py` already asserts that every assumption a card cites
resolves to something a reader can open. This is that test's counterpart for
source references: a comment saying "asserted by `test_assets.py`" when there is
no `test_assets.py` is the same defect, one layer down. It reads as evidence, it
is checkable, and it is wrong.

Both failures this was written against were mine, and both were confident:

    src/lib/artifacts.ts:44   "`test_assets.py` now asserts the leading slash"
    src/lib/artifacts.ts:159  "`tests/web/test_typed_contract.py` compares the
                               field names here against the keys the emitters
                               actually write"

The first names a file that was planned and never written; the guard it
describes is real but lives in TypeScript. The second is a rename the comment
never followed — the file is `test_artifact_contract.py`.

Deliberately suffix-matching rather than resolving from the commenting file:
comments refer to things by whatever prefix is locally legible ("Band.tsx",
"src/test/harness.tsx", "tests/web/test_citations.py"), and demanding a
repo-root path would make the test annoying enough to be worked around.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEB = REPO / "apps" / "web"

SCANNED = (WEB / "src", WEB / "scripts")
SUFFIXES = (".ts", ".tsx", ".mjs")

# Directory *names* that are never source, wherever they appear.
#
# Deliberately does not include "lib": vendored Foundry dependencies live at
# `vetting/forge/lib`, but `apps/web/src/lib` is first-class source — and
# skipping by bare name excluded it, which hid `artifacts.ts` (the file holding
# both real defects) from the scan entirely. Name-matching is the wrong tool for
# a path-specific exclusion; the vendored trees are listed by path below.
SKIP_DIRS = frozenset({"node_modules", ".next", "out", ".venv", "__pycache__", ".git"})

# Vendored or generated trees, by path relative to the repo root.
SKIP_TREES = ("vetting/forge/lib", "vetting/forge/out", "vetting/forge/cache")


def _skipped(relative: Path) -> bool:
    posix = relative.as_posix()
    return bool(SKIP_DIRS & set(relative.parts)) or posix.startswith(SKIP_TREES)


# A path-shaped token: at least one dot-extension we care about.
REFERENCE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:py|tsx|ts|mjs)\b")

BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT = re.compile(r"//[^\n]*")

# Adding to this is an admission, not a fix. It exists so that a legitimately
# hypothetical reference ("a future follow.py would…") has somewhere to go
# without disabling the test. It is empty, and should stay that way.
ALLOW: frozenset[str] = frozenset()


def comment_text(source: str) -> str:
    """Only the comments. Import specifiers and string literals are not claims."""
    return "\n".join([*BLOCK_COMMENT.findall(source), *LINE_COMMENT.findall(source)])


def repo_paths() -> set[str]:
    """Every real file, as a POSIX path relative to the repo root."""
    found: set[str] = set()
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(REPO)
        if _skipped(relative):
            continue
        found.add(relative.as_posix())
    return found


def references() -> dict[str, list[str]]:
    """Every path-shaped token in a comment, mapped to where it was written."""
    out: dict[str, list[str]] = {}
    for root in SCANNED:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in SUFFIXES or not path.is_file():
                continue
            if _skipped(path.relative_to(REPO)):
                continue
            for token in REFERENCE.findall(comment_text(path.read_text())):
                out.setdefault(token.lstrip("./"), []).append(path.relative_to(REPO).as_posix())
    return out


def test_every_file_named_in_a_comment_exists() -> None:
    known = repo_paths()
    dangling: dict[str, list[str]] = {}

    for token, sites in references().items():
        if token in ALLOW:
            continue
        # A comment may name a file by any legible suffix of its path.
        if any(real == token or real.endswith(f"/{token}") for real in known):
            continue
        dangling[token] = sorted(set(sites))

    assert not dangling, (
        "comments name files that do not exist — the reference reads as evidence "
        f"and is not: { {k: v for k, v in sorted(dangling.items())} }"
    )


def test_the_guard_is_actually_looking_at_something() -> None:
    """A guard that finds nothing to check is not a guard.

    If a refactor moves these files or strips their comments, this fails loudly
    rather than passing vacuously.
    """
    found = references()
    assert len(found) >= 5, f"only found {len(found)} references to check: {sorted(found)}"
    # Two known-good anchors, so a broken extractor cannot pass by finding none.
    assert any(t.endswith("check-pages.mjs") for t in found)
    assert any(t.endswith("showcase.py") for t in found)
