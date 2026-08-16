"""A heading level is a property of the tree, so nothing may hardcode one.

`apps/web/src/components/Heading.tsx` makes the level follow nesting depth, and
`Section` provides that nesting. It shipped with zero importers, so for a while
the abstraction existed and did nothing: `useHeadingLevel()` always returned its
default and every heading rendered `<h2>`, which is exactly what it was written
to replace. Seventeen card headings ended up as siblings of the section heading
that introduced them.

Adopting `Section` fixed those seventeen. This stops the eighteenth, because the
way that regression arrives is not a bad refactor — it is one person typing
`<h2>` because it was quicker, in a file where it happens to look right.

`<h1>` stays raw and explicit. There is one per rendered view and it is the
document title, so deriving it would add indirection to the one level that never
varies. Everything below it is relative to something, and relative levels are
what `Heading` exists for.

Counting `<h1>` is deliberately *not* done here. `AgentDetail.tsx` contains
three — loading, error, and loaded — and they are mutually exclusive early
returns, which a static scan cannot see. `apps/web/src/app/headings.test.tsx`
counts the ones that actually render, which is the only count that means
anything.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "apps" / "web" / "src"

# `<h2 …` through `<h6 …`, opening tags only.
RAW_HEADING = re.compile(r"<h([2-6])[\s>]")

# The component that renders them is allowed to name them; it is the thing doing
# the deriving. Tests may assert on concrete levels — that is their job.
ALLOWED = {"Heading.tsx"}


def sources() -> list[Path]:
    return [
        path
        for path in SRC.rglob("*.tsx")
        if path.name not in ALLOWED and not path.name.endswith(".test.tsx")
    ]


def strip_comments(source: str) -> str:
    """`Heading.tsx`'s own prose aside, comments discuss `<h2>` legitimately."""
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", " ", source)


def test_no_view_hardcodes_a_heading_level() -> None:
    offenders: list[str] = []

    for path in sources():
        text = strip_comments(path.read_text())
        for match in RAW_HEADING.finditer(text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(REPO)}:{line} <h{match.group(1)}>")

    assert not offenders, (
        "these hardcode a heading level; use `<Heading>` (level follows the tree) "
        f"or wrap the region in `<Section>`: {offenders}"
    )
