"""A route named in a judge's document must be a route that exists.

`docs/DEMO_SCRIPT.md` is read aloud while recording and `docs/SUBMISSION.md` is
the table a judge is handed. Both are prose, and until now nothing checked
either against the site — which is how the script came to be "narrating the
state of two days ago" once already, and how `/simulate` shipped, went live, and
appeared in neither.

This does not check the prose. It checks the one thing in it that is mechanical
and that fails silently: a path.

## Why the backtick is the anchor

The same argument `tests/web/test_make_targets.py` makes at length about a
backticked make target, and it holds for the same reason: a bare slash-word
pattern matches dates, ratios and the middle of any URL, while a backticked path
is always a deliberate reference to a route. Measured before this was written,
the two documents name seven paths between them and all seven resolve — so the
guard arrives passing and with no allowlist to maintain.

Full URLs are covered too, because `https://misquote.vercel.app/simulate` in the
submission table is exactly the claim worth holding: a judge clicking it is the
whole point of the row.

An anchor cuts both ways, and this docstring proved it. Written with the
placeholder in backticks, the guard next door read it as a target named x and
went red — which is the same self-reference `test_make_targets.py` records about
its own docstring quoting "make sure". The placeholder is prose here for that
reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ROUTES_TS = REPO / "apps" / "web" / "src" / "lib" / "routes.ts"
DOCS = ("DEMO_SCRIPT.md", "SUBMISSION.md")

#: `href: "/venue"` in the route list, which is the site's own answer to what
#: exists. Read rather than duplicated: a second list here would be a second
#: thing to keep in step, and it would drift the day a route is renamed.
_HREF = re.compile(r'href:\s*"(/[a-z0-9-]*)"')

#: A backticked path, or one on the deployed origin.
_BACKTICKED = re.compile(r"`(/[a-z0-9-]+)(?:/|#[a-z0-9-]+)?`")
_DEPLOYED = re.compile(r"https://misquote\.vercel\.app(/[a-z0-9-]+)")


def routes() -> set[str]:
    if not ROUTES_TS.is_file():
        pytest.skip("no routes.ts")
    return set(_HREF.findall(ROUTES_TS.read_text()))


def named(doc: str) -> set[str]:
    path = REPO / "docs" / doc
    if not path.is_file():
        return set()
    text = path.read_text()
    return set(_BACKTICKED.findall(text)) | set(_DEPLOYED.findall(text))


@pytest.mark.parametrize("doc", DOCS)
def test_every_route_a_judge_is_pointed_at_exists(doc: str) -> None:
    known = routes()
    missing = sorted(p for p in named(doc) if p not in known)

    assert not missing, (
        f"docs/{doc} sends a judge to {missing}, which is not in routes.ts. "
        "Either the route was renamed and the document was not, or the document "
        "is describing a page that was never built."
    )


@pytest.mark.parametrize("doc", DOCS)
def test_the_guard_is_actually_looking_at_something(doc: str) -> None:
    """A regex that matches nothing passes every assertion above it.

    The failure this guards against is not hypothetical for this repository:
    `test_make_targets.py` records that the obvious pattern produced
    twenty-eight false positives, and the fix — requiring an anchor — is exactly
    the kind of change that can quietly reduce the match set to zero.
    """
    assert named(doc), f"docs/{doc} named no routes at all — the pattern has stopped matching"


def test_the_deliverable_is_on_the_path_a_judge_is_given() -> None:
    """`/simulate` is the page the PancakeSwap track is judged on.

    It was in the nav, linked from `/venue` and counted on the landing rail, and
    a judge following the guided route reached none of those — the demo script
    and the submission table are the guided route, and neither mentioned it.
    """
    for doc in DOCS:
        assert "/simulate" in named(doc), (
            f"docs/{doc} does not send a judge to /simulate, which is the page "
            "built for the track this project's PancakeSwap entry is judged on"
        )
