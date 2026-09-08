"""A divergence that names the test catching it must name one that exists.

`/venue` introduces its six divergences with *"Each row cost something before it
was written down. The last column is what catches it now"*, and every row of
`venue.json` carries `where` — the module handling it — and `caught_by` — the
test or check that holds it. Both are now rendered.

Nothing checked either. Twelve file paths published as provenance on the page
this project's PancakeSwap entry is judged on, and a rename would have left a
row citing a test that does not exist, silently, because prose does not fail.

This is `tests/web/test_comment_references.py` for an artifact instead of a
comment, and `tests/web/test_citations.py` for a file path instead of an
assumption id. Both of those exist because the same defect shipped in their own
domain first; this one is written before rather than after, which is the only
reason it arrives green.

## Why `caught_by` is split rather than matched whole

Two of the six carry a clause naming the check inside the module —
`packages/misquote/vetting/badge.py — check 'factory resolves it'` — because the
file alone would drop the half that says which of the nine checks it is. So the
path is the leading token and the rest is prose the page renders verbatim.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ARTIFACT = REPO / "apps" / "web" / "public" / "artifacts" / "venue.json"


@pytest.fixture(scope="module")
def divergences() -> list[dict]:
    if not ARTIFACT.exists():
        pytest.skip("no venue report; run `make venue`")
    rows = json.loads(ARTIFACT.read_text())["divergences"]
    assert rows, "venue.json carries no divergences"
    return rows


def cited_path(value: str) -> str:
    """The file half of a `where` or `caught_by`, before any explanatory clause."""
    return value.split("—")[0].strip().split(" ")[0].strip()


def test_every_module_a_divergence_names_exists(divergences: list[dict]) -> None:
    missing = [d["where"] for d in divergences if not (REPO / cited_path(d["where"])).is_file()]

    assert not missing, (
        f"`/venue` says these divergences are handled in files that do not exist: {missing}"
    )


def test_every_test_a_divergence_claims_catches_it_exists(divergences: list[dict]) -> None:
    """The load-bearing half.

    "Each one is caught by a test that runs" is the sentence the whole section
    rests on. A path here that has been renamed turns it into a claim about a
    file nobody can open.
    """
    missing = [
        d["caught_by"] for d in divergences if not (REPO / cited_path(d["caught_by"])).is_file()
    ]

    assert not missing, (
        f"`/venue` claims these divergences are caught by files that do not exist: {missing}"
    )


def test_the_citations_are_paths_rather_than_prose(divergences: list[dict]) -> None:
    """A guard that matched nothing would pass every assertion above it.

    If `caught_by` ever became a sentence rather than a path, `cited_path` would
    return its first word, that word would not be a file, and the tests above
    would fail loudly — which is the right direction. This pins the shape so the
    failure is read as "the emitter changed" rather than "the file moved".
    """
    for d in divergences:
        for key in ("where", "caught_by"):
            path = cited_path(d[key])
            assert "/" in path and path.endswith(".py"), (
                f"{key} is {d[key]!r}, whose leading token {path!r} is not a Python path"
            )


def test_a_named_test_file_is_a_test_and_a_named_module_is_not(divergences: list[dict]) -> None:
    """`where` handles the divergence; `caught_by` holds it. Not interchangeable.

    Four of the six name something under `tests/`. The other two name
    `vetting/badge.py`, which is a *check* rather than a test file and is
    correct — the badge is what runs against chain. So this asserts the weaker,
    true thing: `where` is never a test, because a divergence handled inside its
    own test would mean the code does not handle it at all.
    """
    for d in divergences:
        assert not cited_path(d["where"]).startswith("tests/"), (
            f"{d['what']!r} says it is handled in {d['where']}, which is a test — "
            "a divergence handled only in its own test is not handled"
        )
