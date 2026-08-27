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
import base64
import json
import re
from pathlib import Path
from typing import Any

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

KEYED = Tier("keyed", PRO_BASE, "chain_id", {"X-API-Key": "k"}, 3_000, 3_000_000, can_census=True)
ANON = Tier("anonymous", PUBLIC_BASE, "chainId", {}, 180, 20_000, can_census=False)


# ── the limits, which are measurements and not documentation ─────────────────


def test_the_tier_reports_the_limits_the_headers_report() -> None:
    """8004scan's published limits and 8004scan's actual limits are different
    numbers, and this module records the second kind.

    The docs say the keyed tier answers 600 requests a minute and 100,000 a day.
    `x-ratelimit-limit-minute` and `x-ratelimit-limit-day` on a live keyed
    response say **3,000 and 3,000,000**. The anonymous tier's headers say 180
    and 20,000 against a docstring that said 10 a minute for the life of this
    file.

    Pinned because the failure is silent in the worst direction: every one of
    these constants is read by prose that reasons about what is affordable, and
    a stale one produces a paragraph that is wrong without being wrong-looking.
    Re-measure before changing these, and change the prose in the same commit.
    """
    monkeypatched = scan8004._anonymous_tier()
    assert (monkeypatched.requests_per_minute, monkeypatched.requests_per_day) == (180, 20_000)
    assert (KEYED.requests_per_minute, KEYED.requests_per_day) == (3_000, 3_000_000)


def test_a_higher_anonymous_rate_does_not_earn_the_anonymous_tier_a_census() -> None:
    """The correction that could have quietly granted a capability.

    `can_census` used to be argued from the rate: 10 requests a minute is 4.6
    hours, which is not a build step. The rate turned out to be 180, and the
    same argument now concludes twenty minutes — so a constant becoming more
    accurate would have handed the anonymous tier a census, and the refusal
    string that computed its own hours would have advertised it.

    The real reason never involved time: a different chain parameter, a
    different envelope, and a `total` nothing here has checked.
    """
    assert scan8004._anonymous_tier().can_census is False
    assert scan8004._anonymous_tier().requests_per_minute > 100


def test_the_user_agent_is_pinned_on_both_tiers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The header that made the key work, which nobody chose.

    `X-API-Key` alone under `Python-urllib/3.x` is HTTP 403; the same key with a
    browser-shaped agent is 200. httpx sends its own and is let through, so this
    module has always depended on a default belonging to a library rather than
    on anything it declares. A 403 from a missing User-Agent is indistinguishable
    from a 403 for a bad key, which is the wrong thing to debug.
    """
    monkeypatch.setenv("SCAN8004_API_KEY", "a-key")
    assert tier().headers["User-Agent"] == scan8004.USER_AGENT
    monkeypatch.delenv("SCAN8004_API_KEY")
    assert tier().headers["User-Agent"] == scan8004.USER_AGENT


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


# ── trap 4: a filter it does not implement is accepted, ignored, and answered ─
#
# The worst of the four, because trap 1 is visible in the rows and this is not.
# A wrong chain shows up as Base agents in a BSC page; a wrong denominator shows
# up as nothing at all — 25 correct-looking rows beside a total describing the
# whole registry. Every test here is offline: `_prove` is pure, which is the
# point of splitting it from the fetching in `proven_count`.


X402 = scan8004.FILTERS[0]
WITH_FEEDBACK = scan8004.FILTERS[1]

#: Rows that satisfy `x402_supported=true`, in the quantity the prover asks for.
X402_ROWS = [{"x402_supported": True, "chain_id": 56}] * scan8004.PROOF_ROWS


def test_a_filter_that_returns_the_whole_population_is_not_believed() -> None:
    """The defect this section exists for.

    `x402_supported=true` answering 284,712 against a population of 284,712 is
    not "every agent supports x402" and it is not an error either — it is the
    filter having been accepted and dropped. The rows beside it are real rows
    and every one of them satisfies the predicate, because an unfiltered page
    contains x402 agents too.
    """
    result = scan8004._prove(X402, X402_ROWS, total=284_712, baseline=284_712)

    assert result["applied"] is False
    assert result["differs_from_baseline"] is False
    assert "population" in result["reason"]


def test_a_refused_filter_publishes_no_share_at_all() -> None:
    """Absent, not zero, and not None.

    The general rule, asserted on every refusing branch rather than on one of
    them. A caller that forgets `if result["applied"]` must find nothing to
    divide by — a `share` of 0.0 or None would flow into an artifact and render
    as a measurement, which is how a refusal becomes a claim.
    """
    refusals = [
        scan8004._prove(X402, X402_ROWS, total=284_712, baseline=284_712),
        scan8004._prove(X402, X402_ROWS, total=None, baseline=284_712),
        scan8004._prove(X402, [{"x402_supported": False}], total=66_489, baseline=284_712),
        scan8004._prove(X402, X402_ROWS, 66_489, 284_712, complement_total=284_712),
    ]
    for result in refusals:
        assert result["applied"] is False, result
        assert "total" not in result, result
        assert "share" not in result, result
        assert result["reason"]


def test_a_filter_whose_own_rows_break_its_predicate_is_not_believed() -> None:
    """One row in twenty-five is enough to refuse.

    Not a majority vote. If the API is returning even one agent that does not
    satisfy the filter, the set it counted is not the set that was asked for,
    and the total beside it describes something nobody named.
    """
    rows = [*X402_ROWS[:-1], {"x402_supported": False, "chain_id": 56}]
    result = scan8004._prove(X402, rows, total=66_489, baseline=284_712)

    assert result["applied"] is False
    assert result["rows_satisfying"] == scan8004.PROOF_ROWS - 1
    assert "do not satisfy" in result["reason"]


def test_a_filtered_count_and_its_complement_must_reach_the_population() -> None:
    """The third check, and the one that catches a filter neither other check can.

    Measured: 66,489 + 218,270 = 284,759 against a baseline of 284,712, read
    seconds apart while the chain kept minting. That 47 is growth and passes.
    A complement that came back as the population misses by the population, and
    the reason says so in those words — because "out of tolerance" alone cannot
    tell a busy afternoon from a dropped filter, and the two call for opposite
    responses.
    """
    drifted = scan8004._prove(X402, X402_ROWS, 66_489, 284_712, complement_total=218_270)
    assert drifted["applied"] is True
    assert drifted["sum_vs_baseline"] == 47
    assert drifted["within_tolerance"] is True

    ignored = scan8004._prove(X402, X402_ROWS, 66_489, 284_712, complement_total=284_712)
    assert ignored["applied"] is False
    assert "ignored" in ignored["reason"]


def test_a_filter_matching_everything_is_refused_the_same_as_one_ignored() -> None:
    """The honest ambiguity, resolved against publishing.

    Nothing in the response separates "this filter matched every agent" from
    "this filter was dropped". Refusing costs a true share in a case that has
    never occurred here; publishing costs the population mislabelled, which is
    the defect the repository is named after. The reason says both readings
    rather than asserting the unflattering one.
    """
    result = scan8004._prove(X402, X402_ROWS, total=284_712, baseline=284_712)
    assert result["applied"] is False
    assert "matched every agent" in result["reason"]


def test_the_parameters_this_api_ignores_are_never_asked_for() -> None:
    """The recorded list and the asked-for list must not intersect.

    `IGNORED_PARAMS` exists so that a parameter which looks obviously useful —
    `is_verified`, `has_feedback` — is documented as tried-and-dropped rather
    than merely absent. This is the half that stops one being reintroduced.
    """
    asked = {k for f in scan8004.FILTERS for k in f.params}
    asked |= {k for f in scan8004.FILTERS if f.complement for k in f.complement}

    assert not (asked & set(scan8004.IGNORED_PARAMS))


def test_min_feedbacks_is_never_asked_above_the_value_that_answers() -> None:
    """`min_feedbacks=1` answers in a second; 5 and 100 hang for ~94s and return
    an envelope with no `total` in it.

    Not a timeout that a retry converts into success — a response that arrives
    and is missing the only field the caller wanted. So a higher threshold is a
    bug rather than a slow query, and the ceiling is pinned rather than trusted
    to whoever next wants a stricter cut.
    """
    assert scan8004.MIN_FEEDBACKS_CEILING == 1
    assert WITH_FEEDBACK.params["min_feedbacks"] <= scan8004.MIN_FEEDBACKS_CEILING


def test_only_the_sorts_that_sort_are_ever_asked_for() -> None:
    """`sort_by=star_count` and `sort_by=health_score` are accepted and ignored.

    Both return the newest-first page unchanged, which is a ranking that looks
    like a ranking. Held disjoint from the three that work.
    """
    assert not (set(scan8004.WORKING_SORTS) & set(scan8004.IGNORED_SORTS))
    assert "total_score" in scan8004.WORKING_SORTS


def test_the_proof_reads_more_than_one_row() -> None:
    """One row is not evidence.

    About a quarter of BSC's agents support x402, so a single row satisfying
    `x402_supported=true` is what an *unfiltered* page produces a quarter of the
    time. The proof would pass on the exact reading it exists to refuse.
    """
    assert scan8004.PROOF_ROWS >= 20


# ── the feedback table: what is decoded, and what is never fetched ───────────


def _uri(payload: object) -> str:
    return "data:application/json;base64," + base64.b64encode(json.dumps(payload).encode()).decode()


@pytest.mark.parametrize(
    "uri",
    [
        "https://evil.example/feedback.json",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "ftp://example.invalid/x",
        "ipfs://QmSomething",
    ],
)
def test_a_feedback_uri_is_decoded_and_never_fetched(uri: str) -> None:
    """The reason this decoder has no network path at all.

    `erc8004._assert_fetchable` guards card URIs because a stranger chooses
    them, and following one turns a read into a request this process makes on
    that stranger's behalf. A feedback URI is the same primitive multiplied by
    11,719 — one attacker-chosen URL per row, walked by a build, on a schedule.
    The guards that make a few hundred card fetches defensible do not survive
    that multiplication, so nothing here fetches: a non-`data:` scheme is
    counted as undecodable and the scheme is named in the reason.

    The 169.254.169.254 case is the one that matters. It is the cloud metadata
    endpoint, it is what an SSRF is usually aimed at, and here it is simply a
    string that does not start with `data:`.
    """
    payload, reason = scan8004._decode_feedback_uri(uri)

    assert payload is None
    assert "not a data: URI" in reason


def test_an_oversized_feedback_uri_is_counted_rather_than_decoded() -> None:
    """The row still counts. Only its decode fails.

    A 16KB cap on one row is not a reason to lose the feedback — the row is
    anchored, it has a rater and a tag, and all of that is countable. Dropping
    the row would shrink the denominator for a reason unrelated to feedback.
    """
    payload, reason = scan8004._decode_feedback_uri(
        "data:application/json;base64," + "A" * (scan8004.MAX_FEEDBACK_URI_BYTES + 1)
    )

    assert payload is None
    assert "cap" in reason


def test_a_feedback_graph_holds_counters_rather_than_the_rows_it_counted() -> None:
    """Mirror of the `_Signals` rule, for the larger table.

    11,719 rows are read and none are needed afterwards. What survives is
    counters, two identity sets bounded by their distinct counts, and a
    per-agent index bounded by the few hundred agents anyone has ever rated.
    """
    graph = scan8004._FeedbackGraph()
    graph.add(
        [
            {
                "user_address": "0xAAA",
                "transaction_hash": "0xtx",
                "block_number": 10,
                "tag1": "uptime",
                "agent": {"token_id": "7", "name": "Seven"},
                "feedback_uri": _uri({"method": {"measuredBy": "GEBO", "knownDefects": ["one"]}}),
            }
        ]
        * 3
    )

    assert graph.rows == 3
    assert not hasattr(graph, "_rows")
    assert graph.as_dict()["distinct_raters"] == 1
    assert graph.agents()["7"]["rows"] == 3
    assert graph.as_dict()["declaring_known_defects"] == 3


def test_the_per_agent_index_counts_every_rater_and_carries_a_few() -> None:
    """Both numbers, because they answer different questions.

    "Thirty feedbacks from three addresses" and "thirty from thirty" are
    different objects and a hiring decision turns on which one it is, so
    `distinct_raters` must be exact. The addresses themselves are there so a
    reader can go and look, and five is enough to look — keeping all of them
    cost 352KB across 547 agents.
    """
    graph = scan8004._FeedbackGraph()
    graph.add(
        [
            {"user_address": f"0x{n:040x}", "agent": {"token_id": "7", "name": "Seven"}}
            for n in range(25)
        ]
    )
    entry = graph.agents()["7"]

    assert entry["distinct_raters"] == 25
    assert len(entry["raters"]) == scan8004._FeedbackGraph.RATERS_PER_AGENT


def test_the_per_agent_index_never_leaks_the_accumulator_scratch_set() -> None:
    """`_raters` is a `set`, which `json.dumps` refuses.

    It exists so `distinct_raters` stays exact while the walk runs, and an
    artifact emitter that met it would fail at write time — after the two
    minutes of walking, which is the worst moment to discover it.
    """
    graph = scan8004._FeedbackGraph()
    graph.add([{"user_address": "0xA", "agent": {"token_id": "7"}}])

    assert json.dumps(graph.agents())
    assert not any(k.startswith("_") for k in graph.agents()["7"])


def test_an_incomplete_walk_divides_by_what_it_walked() -> None:
    """`rows`, never `total_reported`.

    A walk that lost pages still has honest shares — of the smaller reading it
    actually took. Dividing by the total it *failed* to reach would understate
    every share by exactly the coverage it is hiding, which is the one direction
    a missing page must never move a number.
    """
    graph = scan8004._FeedbackGraph()
    graph.add([{"user_address": "0xA", "agent": {"token_id": "7"}}] * 900)

    assert graph.as_dict()["top_rater_share"] == 1.0


# ── the categories, and the fuzzy search that fills them wrongly ─────────────


def test_a_row_that_does_not_contain_its_own_needle_is_dropped() -> None:
    """`search` matches stems, and the evidence is unambiguous.

    `search=liquidity` and `search=liquidation` both return 311 agents on BSC
    with an identical head. Whatever the parameter does, it is not substring
    matching — so a Health category built by trusting `liquidation` lists every
    agent whose description mentions *liquidity*, and the first two rows of that
    page are `sus.agent` and `ChainIntel Ai`.
    """
    liquidity = {"name": "sus.agent", "description": "provides deep liquidity"}
    liquidation = {"name": "Rescue", "description": "prevents liquidation events"}

    assert scan8004._matches(liquidation, "liquidation") is True
    assert scan8004._matches(liquidity, "liquidation") is False


def test_the_needle_is_matched_against_the_name_as_well_as_the_description() -> None:
    """`BNB Grid Trader (test)` has an empty description and belongs in a category."""
    assert scan8004._matches({"name": "BNB Grid Trader", "description": None}, "grid") is True


def test_the_needles_cover_the_categories_the_index_publishes() -> None:
    """Four categories, four needle sets, and no fifth taxonomy.

    `apps/web/src/lib/categories.ts` argues the vocabulary must be derived
    rather than declared, because a literal list is one more copy to drift. This
    map cannot be derived — which words find an agent on somebody else's index
    is a fact about their corpus — so instead it is held against the source.

    `index.json` is the source: what it publishes is what the site routes
    between. A category gaining a needle set nothing routes to, or losing one it
    does, both fail here.
    """
    index = json.loads(
        (Path(__file__).resolve().parents[2] / "apps/web/public/artifacts/index.json").read_text()
    )
    published = {agent["category"] for agent in index.get("agents") or ()}

    assert published, "index.json published no categories to check against"
    assert published <= set(scan8004.CATEGORY_NEEDLES), (
        f"categories with no search needles: {sorted(published - set(scan8004.CATEGORY_NEEDLES))}"
    )


def test_a_category_carries_no_number_this_project_did_not_measure() -> None:
    """Every third-party figure is prefixed, and the whitelist is the guard.

    `registry_report.LISTING_KEYS` forbids performance fields outright, because
    a listing there says what *we* read and we cannot replay a stranger's
    policy. This is a different claim — what a named index publishes — so it
    gets a different whitelist, and the numbers on it are prefixed `scan_` so no
    grep of any artifact can mistake one for ours.
    """
    row = scan8004._scan_listing(
        {
            "token_id": "1",
            "name": "N",
            "total_score": 30.4,
            "total_feedbacks": 2,
            "x402_supported": True,
        },
        "grid",
        "https://8004scan.io/api/v1",
    )

    assert set(row) <= scan8004.SCAN_LISTING_KEYS
    assert row["attributed_to"]
    for key, value in row.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            assert key.startswith("scan_"), f"{key} is a number that does not name its source"


def test_no_scan_key_collides_with_the_on_chain_listing_whitelist() -> None:
    """The two shapes must stay separable.

    If a key appeared on both, a row could be moved between `identity.agents`
    and a category listing without any guard noticing — and the whole point of
    two whitelists is that the two carry different claims.
    """
    import importlib.util
    import sys

    repo = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("rr", repo / "scripts" / "registry_report.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["rr"] = module
    spec.loader.exec_module(module)

    overlap = scan8004.SCAN_LISTING_KEYS & module.LISTING_KEYS
    assert overlap <= {"token_id", "name", "description"}, (
        f"a performance-shaped key is on both whitelists: {sorted(overlap)}"
    )


def test_one_minter_cannot_fill_a_category() -> None:
    """Measured, and it was not hypothetical.

    Ranked purely on the index's evidence, all eight published Rebalancing
    agents came from one address — a batch of rarity-tiered `BORT` cards sharing
    a description template, an identical score and zero feedbacks. Correct
    ranking, useless page.

    The cap is a rendering rule and not a judgement about quality, which is the
    distinction this module otherwise refuses to cross. What it suppresses is
    counted, so a category thinned by the rule cannot be mistaken for one that
    is genuinely thin.
    """
    assert scan8004.CATEGORY_MAX_PER_OWNER < scan8004.CATEGORY_LIMIT


# ── the orderings, two of which this API accepts and does not perform ────────


def _row(token_id: str, score: float = 0.0) -> dict[str, Any]:
    return {"token_id": token_id, "total_score": score}


def test_a_sort_that_returned_the_unsorted_head_is_not_published() -> None:
    """`sort_by=star_count` and `sort_by=health_score` both do exactly this.

    They are accepted, and answered with the newest-first page unchanged — a
    ranking that looks like a ranking, in an artifact labelled "top by star
    count". Monotonicity alone would pass it: every value is zero, and zero is
    non-increasing.
    """
    head = ["9", "8", "7"]
    proof = scan8004._prove_sorted("star_count", [_row(t) for t in head], head)

    assert proof["sorted"] is False
    assert proof["monotone"] is True
    assert "rows" not in proof
    assert "IGNORED_SORTS" in proof["reason"]


def test_a_sort_whose_values_rise_is_not_believed() -> None:
    """Descending means descending. A rising run is some other ordering."""
    proof = scan8004._prove_sorted(
        "total_score", [_row("1", 12.0), _row("2", 49.1)], unsorted_head=["9"]
    )

    assert proof["sorted"] is False
    assert "rising" in proof["reason"]


def test_a_sort_that_moved_the_head_and_descends_is_published() -> None:
    """Both checks, because either alone is insufficient.

    Measured heads: `sort_by=total_score` gives OpenOdds.Ai at 49.06 where the
    unsorted page gives the newest mint, and the values fall from there.
    """
    proof = scan8004._prove_sorted(
        "total_score",
        [_row("11", 49.06), _row("12", 30.55), _row("13", 30.5)],
        unsorted_head=["307388", "307387", "307386"],
    )

    assert proof["sorted"] is True
    assert proof["differs_from_unsorted_head"] is True
    assert proof["rows"]


def test_the_owner_lookup_takes_the_address_rather_than_holding_one() -> None:
    """The whole point of `ours_as_indexed` being independent.

    The record on disk is `vetting/identity/97.json`. If the address queried
    were a literal in this module, the function would compare a constant against
    a file that is free to disagree with it — and would report agreement
    whenever the two constants matched, which is not corroboration of anything.
    """
    import inspect

    signature = inspect.signature(scan8004.ours_as_indexed)
    assert "owner_address" in signature.parameters
    assert signature.parameters["owner_address"].default is inspect.Parameter.empty

    source = inspect.getsource(scan8004.ours_as_indexed)
    assert "0x0c50" not in source.lower(), "the operator address is hardcoded in the lookup"
