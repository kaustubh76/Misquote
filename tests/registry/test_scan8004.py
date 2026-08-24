"""8004scan answers wrongly rather than failing, in three documented ways.

Each of these was found by probing the live API, and each is silent: a wrong
parameter name, an oversized page and a mismatched envelope all return HTTP 200
with a body that parses. None of them would raise. All three produce a number
that looks like BSC's registry and is not, which is the failure mode this whole
repository is named after — so each one is pinned here rather than trusted.

Offline by construction. `_get` and the async client are the only places that
touch the network and neither is called: the traps live in the parameter
building, the envelope normalising and the chain checking, which are pure.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from misquote.registry import scan8004
from misquote.registry.scan8004 import (
    MAX_LIMIT,
    PRO_BASE,
    PUBLIC_BASE,
    ForeignChain,
    Tier,
    _check_chain,
    _normalise,
    _params,
    _Signals,
    tier,
)

KEYED = Tier("keyed", PRO_BASE, "chain_id", {"X-API-Key": "k"}, 600, can_census=True)
ANON = Tier("anonymous", PUBLIC_BASE, "chainId", {}, 10, can_census=False)


# ── trap 1: the two tiers do not share a parameter name ──────────────────────


def test_each_tier_asks_for_the_chain_by_the_name_that_tier_understands() -> None:
    """`chain_id` on the keyed API, `chainId` on the public one.

    The keyed endpoint does not reject `chainId`. It ignores it and returns
    every chain it indexes, so the wrong spelling here does not fail a build —
    it files Base and Abstract agents in an artifact labelled BSC.
    """
    assert _params(KEYED, 56, 100, 0, False)["chain_id"] == 56
    assert "chainId" not in _params(KEYED, 56, 100, 0, False)

    assert _params(ANON, 56, 100, 0, False)["chainId"] == 56
    assert "chain_id" not in _params(ANON, 56, 100, 0, False)


def test_a_page_holding_another_chain_is_refused_rather_than_filtered() -> None:
    """The rows and the total fail together.

    Dropping the foreign rows and keeping the total would leave the wrong
    denominator — a share of BSC computed over every chain's population, which
    is worse than no answer because it is shaped like one.
    """
    with pytest.raises(ForeignChain) as error:
        _check_chain([{"chain_id": 56}, {"chain_id": 8453}], 56)
    assert "8453" in str(error.value)

    _check_chain([{"chain_id": 56}, {"chain_id": 56}], 56)  # the clean case does not raise


# ── trap 2: an oversized page comes back empty, not clamped and not refused ──


@pytest.mark.parametrize("asked", [101, 200, 500, 1000])
def test_no_request_may_ask_for_more_rows_than_the_api_will_serve(asked: int) -> None:
    """`limit=500` returns `items: []` with HTTP 200.

    Unclamped, a census would walk 2,784 empty pages and record a registry
    population of zero — an emptiness indistinguishable, in the artifact, from a
    chain on which nobody has ever registered an agent.
    """
    assert _params(KEYED, 56, asked, 0, False)["limit"] == MAX_LIMIT


# ── trap 3: the envelopes differ ─────────────────────────────────────────────


def test_both_envelopes_normalise_to_the_same_pair() -> None:
    keyed = {"items": [{"chain_id": 56}], "total": 278353, "limit": 1, "offset": 0}
    anonymous = {
        "data": [{"chain_id": 56}],
        "meta": {"pagination": {"page": 1, "limit": 1, "total": 278353}},
    }
    assert _normalise(keyed) == _normalise(anonymous) == ([{"chain_id": 56}], 278353)


def test_a_missing_total_is_none_rather_than_zero() -> None:
    """`population()` refuses on a `None` total. A zero would be published."""
    rows, total = _normalise({"data": [], "meta": {}})
    assert rows == [] and total is None


# ── paging a table that grows while you walk it ──────────────────────────────


def test_a_census_pages_ascending_and_a_one_off_read_does_not() -> None:
    """The registry grows while the walk is walking it.

    Newest-first, every row shifts toward the tail between requests: some agents
    are counted twice and others are never reached. Ascending, the new ones land
    past the offsets the walk asked for, so the prefix it counts is stable.
    Measured on the first full run: 72 BSC agents minted across 68 minutes of
    paging — a small number that is not zero, spread over 2,784 pages.

    `sort_order` is the parameter that works. `sort`, `sort_by`, `order` and
    `order_by` are all accepted and all silently ignored, which is why this
    asserts the spelling rather than merely the intent.
    """
    assert _params(KEYED, 56, 100, 0, True)["sort_order"] == "asc"
    assert "sort_order" not in _params(KEYED, 56, 1, 0, False)


# ── the tier is a claim about what may be said, not a performance setting ────


def test_without_a_key_the_census_refuses_instead_of_counting_a_hundred_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure that would matter most, because it would look like success.

    A census that quietly fell back to one page would publish `counted: 100`
    beside a population of 278,353 under key names promising a whole-population
    count. Refusing is the only honest answer the anonymous tier has.
    """
    monkeypatch.delenv("SCAN8004_API_KEY", raising=False)
    assert tier().name == "anonymous"
    assert tier().can_census is False

    result = scan8004.census(56)
    assert result["available"] is False
    assert "counted" not in result
    assert "SCAN8004_API_KEY" in result["reason"]


def test_the_key_the_module_names_is_the_key_it_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """`KEY_ENV` and the literal inside `tier()` are two spellings of one name.

    They are two spellings because the template guard walks the AST for string
    constants and cannot see a variable. This is what stops the pair from
    drifting: setting the variable `KEY_ENV` names must actually reach the tier.
    """
    monkeypatch.setenv(scan8004.KEY_ENV, "a-key")
    assert tier().name == "keyed"
    assert tier().base == PRO_BASE
    assert tier().headers["X-API-Key"] == "a-key"


def test_a_blank_key_is_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """`SCAN8004_API_KEY=` in a filled-in .env is the common case, and it must
    read as absent rather than as a key the API will reject on every request."""
    monkeypatch.setenv("SCAN8004_API_KEY", "   ")
    assert tier().name == "anonymous"


def test_the_env_template_names_the_key_this_module_reads() -> None:
    """Belt to `tests/test_env_template.py`'s braces, from this side."""
    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    assert re.search(rf"^{scan8004.KEY_ENV}=", text, re.M)


def test_the_read_site_uses_a_literal_the_template_guard_can_see() -> None:
    """The reason `tier()` does not read through `KEY_ENV`, pinned.

    `test_env_template.py` collects `ast.Constant` names inside `os.environ`
    accesses. Rewriting this to `os.environ.get(KEY_ENV)` is a tidier-looking
    change that would blind that guard, and nothing else would notice.
    """
    source = Path(scan8004.__file__).read_text()
    tree = ast.parse(source)
    literals = {
        node.value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "get"
        and isinstance(call.func.value, ast.Attribute)
        and call.func.value.attr == "environ"
        for node in ast.walk(call)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert scan8004.KEY_ENV in literals


# ── the counters ─────────────────────────────────────────────────────────────


def test_signals_count_the_same_way_over_a_hundred_rows_and_over_a_census() -> None:
    """One accumulator serves both readings, so `sample` and `census` cannot
    drift into counting `with_feedback` by different rules."""
    signals = _Signals()
    signals.add(
        [
            {
                "chain_id": 56,
                "is_verified": True,
                "total_feedbacks": 3,
                "total_score": 12.01,
                "x402_supported": True,
                "star_count": 2,
                "description": "  a real description  ",
                "owner_address": "0xAbC",
                "supported_protocols": ["A2A", "Web"],
            },
            {
                "chain_id": 56,
                "total_feedbacks": 0,
                "total_score": 0,
                "description": "",
                "owner_address": "0xabc",  # same owner, different case
                "supported_protocols": ["Web"],
            },
        ]
    )
    counted = signals.as_dict()
    assert signals.rows == 2
    assert counted["verified"] == 1
    assert counted["with_feedback"] == 1
    assert counted["feedbacks_claimed"] == 3
    assert counted["with_score"] == 1
    assert counted["x402_supported"] == 1
    assert counted["starred"] == 1
    assert counted["described"] == 1
    # An owner registering twice is one owner. Addresses arrive in mixed case
    # from this API, so counting them raw would inflate the figure that says how
    # concentrated the registry is.
    assert counted["distinct_owners"] == 1
    assert counted["protocols"] == {"Web": 2, "A2A": 1}


def test_a_census_holds_counters_rather_than_the_rows_it_counted() -> None:
    """278,353 records go through this and none are kept.

    Retaining descriptions to count the distinct ones would make the strings the
    largest thing in the process; they are counted by digest instead.
    """
    signals = _Signals()
    signals.add([{"chain_id": 56, "description": "x" * 4096} for _ in range(50)])
    assert signals.rows == 50
    assert signals.as_dict()["distinct_descriptions"] == 1
    assert all(len(digest) == 8 for digest in signals.descriptions)
