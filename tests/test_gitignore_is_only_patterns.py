r""".gitignore must contain ignore patterns, and nothing that fell into it.

This exists because 103 lines of Makefile recipe text and `next build` output
were appended to it by a stray shell redirect and committed. Nothing noticed:
git reads unmatched patterns as patterns that match nothing, so the file kept
working while being mostly wrong, and the only symptom was `ruff` refusing to
parse `cd apps/web && node scripts/check-pages.mjs ; \` as a glob — three
commits later, in unrelated work.

The damage a silent one would have done is the point. A line like `out/` sitting
in the middle of pasted prose still ignores `out/`; a *missing* line does not,
and the way you find out is a build directory or a keystore in a commit.

So: every line is a comment, blank, or something shaped like a path.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GITIGNORE = REPO / ".gitignore"

# A pattern, per gitignore(5): an optional `!` negation and `/` anchor, then
# path characters and globs. Deliberately narrow — a pattern *may* contain an
# escaped space, and none here does, so allowing one would only widen the hole.
PATTERN = re.compile(r"^!?/?[\w.*/@?\[\]-]+/?$")


def test_every_line_is_a_comment_a_blank_or_a_pattern() -> None:
    offenders = [
        (n, line)
        for n, line in enumerate(GITIGNORE.read_text().splitlines(), 1)
        if line.strip() and not line.lstrip().startswith("#") and not PATTERN.match(line)
    ]
    assert not offenders, "not ignore patterns:\n" + "\n".join(
        f"  {n}: {line!r}" for n, line in offenders
    )


def test_the_ignores_that_protect_a_secret_or_a_build_are_present() -> None:
    """Named individually, because the failure above deletes by truncation.

    A guard that only checks *shape* passes on a file cut in half. These are the
    entries whose absence costs something: a raw key in a commit, or 100MB of
    build output in a diff.
    """
    lines = {line.strip() for line in GITIGNORE.read_text().splitlines()}
    for required in (".env", "*.keystore", ".venv/", "node_modules/", ".next/", "out/"):
        assert required in lines, f"{required} is no longer ignored"
