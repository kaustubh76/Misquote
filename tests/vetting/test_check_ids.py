"""A finding needs a name other code can hold on to.

Until `CHECK_IDS` existed, a finding was `(pool, check["name"])` — free text,
duplicated at thirty call sites. Nothing could join to one: not a Foundry
proof-of-concept, not a page anchor, not a comparison between two runs. Rewording
a check for clarity broke every reference to it and nothing failed, because there
were no references to break.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from misquote.vetting.badge import CHECK_IDS, Badge, UndeclaredCheck

REPO = Path(__file__).resolve().parents[2]


def test_an_undeclared_check_cannot_reach_an_artifact() -> None:
    """The property that keeps the map honest as checks are added.

    A generated slug would put the id back where the name was — derived from
    prose somebody can reword — so `add()` refuses instead.
    """
    badge = Badge(pool="0x" + "11" * 20, chain_id=56)
    with pytest.raises(UndeclaredCheck, match="stable id"):
        badge.add("a check nobody declared", "PASS", "detail", "P-1")


def test_every_id_is_unique_and_slug_shaped() -> None:
    """Two checks sharing an id would silently merge two findings into one."""
    assert len(set(CHECK_IDS.values())) == len(CHECK_IDS)
    for name, key in CHECK_IDS.items():
        assert key == key.lower().strip(), key
        assert " " not in key and "_" not in key, f"{key} is not a slug"
        assert key.replace("-", "").isalnum(), key
        assert name.strip(), key


def test_the_map_covers_exactly_the_nine_checks_the_badge_runs() -> None:
    """Nine on the page, nine in the map.

    A tenth id with no check is a dangling reference; a tenth check with no id
    cannot be constructed, which the test above covers. This is the other
    direction, and it reads the committed badges rather than the source so it
    fails if the emitter and the artifacts disagree.
    """
    badges = sorted((REPO / "vetting" / "badges").glob("*.json"))
    if not badges:
        pytest.skip("no badge has been recorded; run `make vet`")

    names: set[str] = set()
    for path in badges:
        record = json.loads(path.read_text())
        for check in record["checks"]:
            names.add(check["name"])

    assert names <= set(CHECK_IDS), f"badges carry checks with no id: {names - set(CHECK_IDS)}"
    assert len(CHECK_IDS) == 9, "nine checks is what the page and the ledger both claim"


def test_recorded_badges_carry_their_ids() -> None:
    """The artifact is where a joiner actually looks."""
    badges = sorted((REPO / "vetting" / "badges").glob("*.json"))
    if not badges:
        pytest.skip("no badge has been recorded; run `make vet`")

    for path in badges:
        record = json.loads(path.read_text())
        for check in record["checks"]:
            assert "id" in check, (
                f"{path.name} predates the stable ids — regenerate it with "
                f"`make vet`, or a proof-of-concept has nothing to join on"
            )
            assert CHECK_IDS[check["name"]] == check["id"]
