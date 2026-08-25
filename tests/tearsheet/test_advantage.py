"""The Agent Advantage Report, and the claim that its numbers are not literals.

The TermiX track judges one question — does hiring an agent beat doing the job
yourself, and can you prove it? The proof is worth nothing if the report's
figures could have been typed in, so the load-bearing test here re-runs the
engine independently and demands exact equality.

The second thing under test is subtler: that the three tasks have three genuinely
different baselines. Three tasks sharing one baseline is one task relabelled, and
it would satisfy the letter of "at least three tasks" while proving nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from advantage import (  # noqa: E402
    META,
    META_WIDE,
    NEVER_WITHDRAW,
    a1_ceiling,
    build,
    shared_capital,
    synthetic_events,
    task_earn,
    task_protect,
    to_payload,
    venue_depth,
    venue_toxicity,
)
from misquote.agents.sentinel.policy import SentinelParams, sentinel_policy  # noqa: E402
from misquote.core.policy import passive_policy  # noqa: E402
from misquote.replay.driver import CostModel, ReplayDriver  # noqa: E402
from misquote.replay.ranges import Quote  # noqa: E402
from misquote.replay.tape import MemoryTape  # noqa: E402
from misquote.tearsheet.advantage import MATERIAL_PP, compare, overall, summarise  # noqa: E402

SMALL = 200


@pytest.fixture(scope="module")
def comparisons():
    """`build()` runs the whole report — six columns, each 61 replays.

    Module-scoped because it is deterministic and the alternative is paying for
    it once per test, which took 46s and roughly doubled the suite.
    """
    return build(synthetic_events(SMALL), capital=1000.0, venue="test")


def quote(p25: float, p50: float, p75: float, *, sufficient: bool = True, note: str = "") -> Quote:
    return Quote(
        p25=p25,
        p50=p50,
        p75=p75,
        samples=60,
        windows=20,
        perturbations=3,
        in_range_p50=0.5,
        rebalances_p50=1.0,
        hours_per_window=48.0,
        sufficient=sufficient,
        note=note,
        annualised=False,
        basis="over 48h",
    )


def comparison(baseline, agent, **kw):
    return compare(
        task="t",
        category="trading",
        venue="v",
        metric="m",
        without_agent="diy",
        with_agent="agent",
        baseline_quote=baseline,
        agent_quote=agent,
        **kw,
    )


# --- the arithmetic ---------------------------------------------------------


def test_delta_is_agent_minus_baseline_in_percentage_points() -> None:
    c = comparison(quote(1.0, 2.0, 3.0), quote(4.0, 5.5, 7.0))
    assert c.delta == pytest.approx(3.5)


def test_a_negative_delta_is_reported_not_hidden() -> None:
    """We have already published one tape where the agent lost. Nothing here
    clamps, reorders or suppresses on sign — that is the whole project."""
    c = comparison(quote(4.0, 5.0, 6.0), quote(1.0, 2.0, 3.0))
    assert c.delta == pytest.approx(-3.0)
    assert c.material
    assert "loses to" in c.verdict_line()


def test_overlapping_bands_are_called_out_however_far_apart_the_medians_are() -> None:
    """A median difference across overlapping ranges is a difference the sample
    cannot support, which is precisely why this product quotes ranges."""
    c = comparison(quote(0.0, 1.0, 10.0), quote(5.0, 9.0, 14.0))
    assert c.delta == pytest.approx(8.0)
    assert c.ranges_overlap
    assert not c.separated
    assert "bands overlap" in c.verdict_line()


def test_disjoint_bands_are_separated() -> None:
    c = comparison(quote(0.0, 1.0, 2.0), quote(5.0, 6.0, 7.0))
    assert not c.ranges_overlap
    assert c.separated
    assert "do not overlap" in c.verdict_line()


def test_a_difference_below_the_materiality_floor_is_not_an_edge() -> None:
    c = comparison(quote(1.0, 2.0, 3.0), quote(1.0, 2.0 + MATERIAL_PP / 2, 3.0))
    assert not c.material
    assert not c.separated
    assert "indistinguishable" in c.verdict_line()


def test_an_insufficient_quote_is_withheld_rather_than_treated_as_zero() -> None:
    """Subtracting two zeros and reporting a confident nil is exactly the failure
    the sample-size floors exist to prevent."""
    thin = quote(0.0, 0.0, 0.0, sufficient=False, note="4 usable replays, need 20")
    c = comparison(thin, quote(1.0, 2.0, 3.0))
    assert not c.quotable
    assert not c.separated
    assert "no verdict" in c.verdict_line()
    assert "4 usable replays" in c.note


def test_the_overall_call_refuses_on_three_observations() -> None:
    """Three tasks are three observations. `verdict(min_n=30)` will not call a
    rate on that, and the refusal is the honest headline."""
    three = [comparison(quote(0.0, 1.0, 2.0), quote(5.0, 6.0, 7.0)) for _ in range(3)]
    call = overall(three)
    assert not call.called
    assert "need 30" in str(call)


def test_the_summary_counts_agree_with_the_comparisons() -> None:
    wins = comparison(quote(0.0, 1.0, 2.0), quote(5.0, 6.0, 7.0))
    loses = comparison(quote(5.0, 6.0, 7.0), quote(0.0, 1.0, 2.0))
    withheld = comparison(quote(0.0, 0.0, 0.0, sufficient=False, note="thin"), quote(1, 2, 3))
    s = summarise([wins, loses, withheld])
    assert s["tasks"] == 3
    assert s["quotable"] == 2
    assert s["withheld"] == 1
    assert s["agent_ahead"] == 1
    assert s["diy_ahead"] == 1


# --- the baselines are genuinely different ----------------------------------


def test_task_twos_baseline_never_withdraws() -> None:
    """Task 2 is an ablation: same band, same reanchoring, withdrawal off. If the
    baseline still pulled, the comparison would not isolate the decision it
    claims to isolate."""
    events = synthetic_events(1200, drift=0.6)
    result = ReplayDriver(META, capital_quote=1000.0, policy=sentinel_policy(NEVER_WITHDRAW)).run(
        MemoryTape(events)
    )
    assert result.pulls == 0, "the task-2 baseline withdrew — it is not an ablation"

    # ...and the agent it is compared against does withdraw on the same tape,
    # or the comparison would be measuring nothing.
    live = ReplayDriver(META, capital_quote=1000.0, policy=sentinel_policy(SentinelParams())).run(
        MemoryTape(events)
    )
    assert live.pulls > 0, "Sentinel never withdrew, so task 2 compares two identical runs"


def test_the_three_tasks_do_not_share_one_baseline(comparisons) -> None:
    """Three tasks with the same DIY column is one task relabelled."""
    assert len(comparisons) >= 3
    baselines = [c.without_agent for c in comparisons]
    assert len(set(baselines)) == len(baselines), f"duplicated baseline: {baselines}"


def test_the_report_covers_both_weighted_categories(comparisons) -> None:
    summary = summarise(comparisons)
    assert "trading" in summary["categories"]
    assert "security" in summary["categories"]


# --- the load-bearing one: no literals reach the report ---------------------


def test_every_figure_comes_from_the_engine() -> None:
    """Re-run the engine independently and demand exact equality.

    Not approximate. The report's supporting numbers are the replay's own
    attributes, so any difference at all would mean something between the engine
    and the page is inventing figures — which is the one failure this whole
    project exists to argue against.
    """
    events = synthetic_events(SMALL)
    earn = task_earn(events, capital=1000.0, venue="test")

    expected_baseline = ReplayDriver(
        META, costs=CostModel(), capital_quote=1000.0, policy=passive_policy
    ).run(MemoryTape(events))
    expected_agent = ReplayDriver(META, costs=CostModel(), capital_quote=1000.0).run(
        MemoryTape(events)
    )

    assert earn.baseline_fees == expected_baseline.total_fees
    assert earn.baseline_lvr == expected_baseline.total_lvr
    assert earn.baseline_costs == expected_baseline.total_costs
    assert earn.baseline_in_range == expected_baseline.in_range_fraction

    assert earn.agent_fees == expected_agent.total_fees
    assert earn.agent_lvr == expected_agent.total_lvr
    assert earn.agent_costs == expected_agent.total_costs
    assert earn.agent_in_range == expected_agent.in_range_fraction

    assert earn.baseline_moves == (
        expected_baseline.mints + expected_baseline.rebalances + expected_baseline.pulls
    )


def test_the_passive_baseline_mints_once_and_then_holds() -> None:
    """The DIY column has to actually be do-nothing, or the comparison flatters
    the agent by giving its baseline something to do."""
    events = synthetic_events(SMALL)
    result = ReplayDriver(META, capital_quote=1000.0, policy=passive_policy).run(MemoryTape(events))
    assert result.mints == 1
    assert result.rebalances == 0
    assert result.pulls == 0
    assert result.total_costs > 0, "even doing nothing pays to open the position once"


def test_the_baseline_is_charged_the_same_cost_model_as_the_agent() -> None:
    """The usual way to flatter an agent is to charge its baseline differently.
    Both columns go through one `_run`, so this asserts the consequence."""
    events = synthetic_events(SMALL)
    protect = task_protect(events, capital=1000.0, venue="test")

    # One mint each at the same CostModel means the same per-move charge.
    #
    # The base is **half the capital**, not all of it: opening a position swaps
    # one asset into the other to reach the target composition, and A4 charges
    # its bps on what is swapped. This assertion used to multiply by the full
    # 1,000 — which is what the driver did, against A4's own wording and against
    # the notional the engine hands the policy. See P-13.
    per_move = CostModel()
    entry_notional = 1000.0 / 2.0
    expected_open = (
        per_move.gas_quote
        + entry_notional * (per_move.slippage_bps + per_move.mev_haircut_bps) / 10_000.0
    )
    # The baseline mints once and never touches it, so its whole cost is one
    # opening and the formula is checkable exactly.
    assert protect.baseline_moves == 1
    assert protect.baseline_costs == pytest.approx(expected_open)

    # The agent's cost is *not* `expected_open * moves`, and an earlier version of
    # this test asserted exactly that. Opening, recentring and returning after a
    # pull swap different amounts, so they cost different amounts (P-13, P-18).
    # What must hold is that the agent pays the same opening as the baseline and
    # its returns cost less — burning a v3 position pays out both tokens, so
    # coming back swaps only the mismatch against the new range, not half the
    # capital again.
    assert protect.agent_moves > protect.baseline_moves
    assert protect.agent_costs > expected_open, "the agent skipped the opening charge"
    assert protect.agent_costs < expected_open * protect.agent_moves, (
        "every agent move was charged as a fresh entry from a single asset"
    )

    # The symmetry is the actual claim: both columns run through one `_run` with
    # one `CostModel`, so they can only be charged differently if their *moves*
    # differ. With per-move-type pricing that can no longer be asserted as one
    # multiplication, so it is asserted as the two things that must hold.
    opening = ReplayDriver(
        META, costs=per_move, capital_quote=1000.0, policy=sentinel_policy(SentinelParams())
    ).run(MemoryTape(events))
    assert opening.pulls > 0, "this assertion is only interesting while the agent withdraws"

    # Every withdrawal is charged gas and nothing else — a burn swaps nothing.
    # This branch used to charge *nothing at all*, an undercharge that fell on
    # the agent and never on the never-withdraw baseline. Immaterial while a
    # return cost half the capital; now that a return is priced as the swap it
    # is, gas is most of a cycle's cost.
    entries = opening.mints + opening.rebalances
    floor = expected_open + per_move.gas_quote * opening.pulls
    assert protect.agent_costs > floor, "withdrawals are being charged nothing"
    assert protect.agent_costs < expected_open * entries, (
        "every entry was charged as a fresh one from a single asset"
    )


# --- the artifact -----------------------------------------------------------


def test_the_artifact_round_trips_and_carries_the_badge(comparisons) -> None:
    import json

    payload = to_payload(comparisons, source="synthetic", capital=1000.0, command="pytest")
    assert payload["source"] == "synthetic"
    # Per-artifact provenance, not by proxy through build.json. `go_no_go`'s
    # `check_artifact_freshness` answers UNVERIFIED for an artifact recording no
    # commit, so an unstamped report could never clear that gate — and the
    # gate's own stated remedy, regenerate it, could not clear it either.
    assert payload["build"]["command"] == "pytest"
    assert payload["build"]["source"] == "synthetic"
    assert payload["counterfactual"] is True
    assert "COUNTERFACTUAL" in payload["badge"]
    assert len(payload["tasks"]) >= 3
    for task in payload["tasks"]:
        assert {"baseline", "agent", "delta_pp", "verdict"} <= set(task)
    assert json.loads(json.dumps(payload)) == payload


# --- task 3's two venues ----------------------------------------------------
#
# The task used to run on two tapes from `synthetic_events()`, one deep and
# toxic *by construction* and one shallow and balanced *by construction*. Its
# answer was therefore written into its own setup. These pin the two decisions
# that replaced that: which venue is deeper is measured, and what capital both
# can honestly carry is derived.


def test_the_deeper_venue_is_measured_rather_than_labelled() -> None:
    """`venue_depth` must rank by what the tape says, not by argument order."""
    shallow = synthetic_events(400, seed=3, liquidity=10**22)
    deep = synthetic_events(400, seed=3, liquidity=50 * 10**22)

    assert venue_depth(deep) > venue_depth(shallow)
    assert venue_depth(deep) / venue_depth(shallow) == pytest.approx(50.0, rel=0.01)


def test_an_empty_tape_has_no_depth_rather_than_crashing() -> None:
    assert venue_depth([]) == 0


def test_a_shallow_venue_lowers_the_capital_for_both_columns() -> None:
    """A1's ceiling belongs to the pool, so the shallower venue binds the pair.

    The failure this prevents is concrete and was measured: at the report's
    default capital the 0.25% tier refused on 564 mints, and A1 says a quote
    that breaches is *refused rather than rendered* — so task 3 would have
    published nothing at all.
    """
    deep = synthetic_events(300, seed=5, liquidity=200 * 10**22)
    shallow = synthetic_events(300, seed=5, liquidity=10**22)

    assert a1_ceiling(deep, META) > a1_ceiling(shallow, META_WIDE)

    capital, note = shared_capital(
        [(deep, META, "deep"), (shallow, META_WIDE, "shallow")], requested=1.0
    )
    assert capital < 1.0, "the requested capital breaches A1 on the shallow venue"
    assert capital <= a1_ceiling(shallow, META_WIDE), "above the binding ceiling"
    assert "shallow" in note and "A1" in note, "the reduction must be explained, not silent"


def test_a_capital_both_venues_can_carry_is_left_alone() -> None:
    """The clamp must not fire when it is not needed, or every task 3 would
    quietly run at half the ceiling of whichever venue happened to be thinnest."""
    deep = synthetic_events(300, seed=5, liquidity=200 * 10**22)
    other = synthetic_events(300, seed=5, liquidity=180 * 10**22)

    capital, note = shared_capital([(deep, META, "deep"), (other, META, "other")], requested=1e-6)
    assert capital == 1e-6
    assert note == "", "nothing was changed, so nothing should be explained"


def test_both_columns_get_the_same_capital() -> None:
    """The point of the exercise. Two venues at two capitals is partly a
    comparison between two position sizes, whatever the label says."""
    deep = synthetic_events(300, seed=5, liquidity=200 * 10**22)
    shallow = synthetic_events(300, seed=5, liquidity=10**22)
    venues = [(deep, META, "deep"), (shallow, META_WIDE, "shallow")]

    first, _ = shared_capital(venues, requested=1.0)
    second, _ = shared_capital(list(reversed(venues)), requested=1.0)
    assert first == second, "the shared capital must not depend on venue order"


def test_the_screen_picks_the_agents_venue_rather_than_the_leftover() -> None:
    """§3.4's imbalance arm chooses, using the estimator Sentinel withdraws on.

    The subtler rigging this replaces: with two venues, the baseline took the
    deeper one and the agent was simply handed *the other*. That silently
    assumes the screen disagrees with depth — and if it does not, the task
    reports a difference it never measured.
    """
    one_way = synthetic_events(600, seed=11, drift=0.55)
    balanced = synthetic_events(600, seed=11, drift=0.0)

    assert venue_toxicity(one_way, META) > 0.9, "a one-way tape must read as toxic"
    assert venue_toxicity(balanced, META) < 0.1, "a balanced one must not"


def test_a_quiet_venue_is_not_called_toxic_by_a_short_window() -> None:
    """Below a full window there is no verdict, so the fraction is zero rather
    than an emergency computed from four swaps."""
    assert venue_toxicity(synthetic_events(5, seed=2), META) == 0.0
    assert venue_toxicity([], META) == 0.0


def test_each_task_records_the_capital_it_actually_ran_at() -> None:
    """A report-level capital would describe task 3 wrongly, and authoritatively.

    Tasks 1 and 2 run at the report's figure. Task 3 cannot: A1's ceiling is a
    property of the pool, and on the 0.25% tier the default breached it on 564
    mints — A1 refuses such a quote rather than clamping it. The prose said so
    already; a machine reading `capital_quote` off the artifact could not.
    """
    quote = Quote(
        p25=1.0,
        p50=2.0,
        p75=3.0,
        samples=40,
        windows=20,
        perturbations=3,
        in_range_p50=0.8,
        rebalances_p50=1.0,
        hours_per_window=48.0,
        sufficient=True,
        note="",
    )
    tasks = [
        compare(
            task=f"t{i}",
            category="trading",
            venue="v",
            metric="m",
            without_agent=f"diy {i}",
            with_agent="agent",
            baseline_quote=quote,
            agent_quote=quote,
            source="chain",
            capital_quote=cap,
        )
        for i, cap in enumerate((1.0, 1.0, 0.0318))
    ]

    payload = to_payload(tasks, source="chain", capital=1.0, command="pytest")
    assert [t["capital_quote"] for t in payload["tasks"]] == [1.0, 1.0, 0.0318]
    assert payload["capital_quote"] != 1.0, (
        "one figure cannot describe a report whose tasks ran at two"
    )
    assert "per task" in str(payload["capital_quote"])


def test_the_report_level_capital_survives_when_every_task_agrees() -> None:
    """The disclosure must not fire when there is nothing to disclose."""
    quote = Quote(
        p25=1.0,
        p50=2.0,
        p75=3.0,
        samples=40,
        windows=20,
        perturbations=3,
        in_range_p50=0.8,
        rebalances_p50=1.0,
        hours_per_window=48.0,
        sufficient=True,
        note="",
    )
    tasks = [
        compare(
            task=f"t{i}",
            category="trading",
            venue="v",
            metric="m",
            without_agent=f"diy {i}",
            with_agent="agent",
            baseline_quote=quote,
            agent_quote=quote,
            source="chain",
            capital_quote=1.0,
        )
        for i in range(3)
    ]
    assert to_payload(tasks, source="chain", capital=1.0, command="pytest")["capital_quote"] == 1.0


def test_when_both_rules_pick_one_pool_the_delta_is_zero_not_a_finding() -> None:
    """Measured on the real 30-day tapes: §3.4's imbalance arm fires on 41.9% of
    samples on the flagship and 42.8% on the 0.25% tier — it does not separate
    them, so the screen picks the pool depth already picked.

    The honest report is that the two rules agreed. This pins the arithmetic of
    that case: identical venue, identical capital, deterministic engine, so the
    delta is exactly zero and lands below the materiality floor rather than
    being dressed up as an agent result.
    """
    quote = Quote(
        p25=1.0,
        p50=2.0,
        p75=3.0,
        samples=40,
        windows=20,
        perturbations=3,
        in_range_p50=0.8,
        rebalances_p50=1.0,
        hours_per_window=48.0,
        sufficient=True,
        note="",
    )
    same = compare(
        task="Choose",
        category="security",
        venue="two venues — depth and the flow screen chose the same one",
        metric="m",
        without_agent="pick the deepest pool",
        with_agent="pick by the flow screen — which is the pool depth chose too",
        baseline_quote=quote,
        agent_quote=quote,
        source="chain",
        capital_quote=0.0318,
    )

    assert same.delta == 0.0
    assert not same.material, "zero cannot clear the materiality floor"
    assert not same.separated
    assert "indistinguishable" in same.verdict_line()


# --- the evidence behind `moves` --------------------------------------------


def test_the_move_parts_add_up_to_the_aggregate() -> None:
    """`moves` is mints + recentres + pulls, and the parts are published.

    The aggregate hides the mechanism. 498 moves reads as a busy agent; 249
    mints beside 249 pulls and **zero recentres** reads as an agent that spent
    its whole daily budget leaving and coming back. Only the second is what the
    real tape showed, and only the second is a finding.
    """
    events = synthetic_events(600, seed=4, drift=0.4)
    result = ReplayDriver(META, costs=CostModel(), capital_quote=1.0).run(MemoryTape(events))

    c = task_earn(events, capital=1.0, venue="v", source="chain")
    assert c.agent_mints + c.agent_recentres + c.agent_pulls == c.agent_moves
    assert c.baseline_mints + c.baseline_recentres + c.baseline_pulls == c.baseline_moves
    assert result.mints >= 0  # the driver is the source of those counters


def test_distinct_returns_travels_with_the_quote() -> None:
    """P-17 built this field so a reader can see the spread is hollow.

    A5 counts each window three times under a +/-25% perturbation of (gamma,
    kappa). When the anti-dust floor discards both, those three replays are one
    replay — P-17 measured Warden at 23 distinct of 60. A band drawn from 20
    results counted three times is narrower than the evidence supports, and this
    report published nothing that would let anyone notice.

    Tested against a constructed `Quote` rather than through the engine: the
    contract added here is that `compare()` carries the field into the
    comparison and the payload, and a 600-swap tape is legitimately withheld —
    which would test the refusal path instead of this one.
    """
    quote = Quote(
        p25=1.0,
        p50=2.0,
        p75=3.0,
        samples=60,
        windows=20,
        perturbations=3,
        in_range_p50=0.8,
        rebalances_p50=1.0,
        hours_per_window=48.0,
        sufficient=True,
        note="",
        distinct_returns=23,
    )
    c = compare(
        task="t",
        category="trading",
        venue="v",
        metric="m",
        without_agent="diy",
        with_agent="agent",
        baseline_quote=quote,
        agent_quote=quote,
        source="chain",
    )

    assert c.agent_distinct == 23
    assert c.agent_distinct <= c.windows * 3, "cannot exceed the reported sample count"

    payload = to_payload([c], source="chain", capital=1.0, command="pytest")
    assert payload["tasks"][0]["agent"]["distinct_returns"] == 23
    assert payload["tasks"][0]["baseline"]["distinct_returns"] == 23


def test_a_withheld_quote_reports_no_distinct_results_rather_than_guessing() -> None:
    """Nothing was measured, so the honest count is zero, not the sample count."""
    withheld = Quote(
        p25=0.0,
        p50=0.0,
        p75=0.0,
        samples=0,
        windows=20,
        perturbations=3,
        in_range_p50=0.0,
        rebalances_p50=0.0,
        hours_per_window=0.0,
        sufficient=False,
        note="0 usable replays",
    )
    c = compare(
        task="t",
        category="trading",
        venue="v",
        metric="m",
        without_agent="diy",
        with_agent="agent",
        baseline_quote=withheld,
        agent_quote=withheld,
        source="chain",
    )
    assert not c.quotable
    assert c.agent_distinct == 0


def test_the_rate_divides_by_calendar_days_not_elapsed_span() -> None:
    """ "Per day" has to mean what the budget means by it, or the report lies.

    `core.position.rebalances_today` resets on the **UTC calendar day** of the
    last move and says calendar days are what "per day" means to the operator
    reading the parameter. Dividing by elapsed span instead put 32 cycles over a
    2.6-day span at 12.3/day — against a cap of 8, which reads as the agent
    breaching its own limit. Against the 4 calendar days it touched it is 8.0,
    which is the cap being hit exactly.
    """
    events = synthetic_events(600, seed=4)
    c = task_earn(events, capital=1.0, venue="v", source="chain")

    first, last = events[0].ts, events[-1].ts
    calendar = last // 86400 - first // 86400 + 1
    elapsed = (last - first) / 86400.0

    assert c.days == calendar
    assert c.days >= elapsed, "calendar days can never be fewer than the span they cover"


def test_every_venue_names_the_pool_by_address() -> None:
    """The judged artifact was the one place a pool could not be resolved.

    `warden.json`, `venue.json` and `vetting.json` all name their pools by
    address; `advantage.json` named them by label alone. Two of the three
    PancakeSwap tiers on WBNB/USDT carry the same pair name and different
    protocol fees, so "PancakeSwap v3 WBNB/USDT 0.05%" is not something a reader
    can check against chain without guessing.

    It also makes the venue visible to `go_no_go.check_badge_coverage`, which
    reads pool addresses out of published artifacts so that quoting a pool
    nobody vetted fails the gate rather than a reader's attention.
    """
    import re

    from advantage import venue_name
    from misquote.chain.addresses import TARGET_POOL

    named = venue_name(TARGET_POOL)
    assert TARGET_POOL.address in named
    assert TARGET_POOL.label in named
    assert re.search(r"0x[0-9a-fA-F]{40}", named), "a venue must resolve to an address"


# --------------------------------------------------------------------------
# P-19: an absent quantity is not a measured zero.


class _LpResult:
    """What a liquidity replay returns: every field the report knows about."""

    in_range_fraction = 0.9
    total_fees = 1.5
    total_lvr = 0.25
    total_costs = 0.75
    mints = 3
    pulls = 2
    rebalances = 1


class _LendingResult:
    """What an allocation replay returns.

    Faithful to `AllocationResult`, which is the point: it carries `total_costs`
    and a `moves` property summing entries/switches/exits, and **none** of
    `in_range_fraction`, `total_fees`, `total_lvr`, `mints`, `pulls` or
    `rebalances`. `replay/allocation.py` says as much about `rebalances_p50`:
    "neither of which exists for an allocation agent".
    """

    total_costs = 1.03
    moves = 2


class _Quote:
    def __init__(self, p25=1.0, p50=2.0, p75=3.0, **extra):
        self.p25, self.p50, self.p75 = p25, p50, p75
        self.sufficient = True
        self.note = ""
        self.basis = "annualised"
        self.windows = 20
        for key, value in extra.items():
            setattr(self, key, value)


def _compare(baseline_result, agent_result, **quote_kw):
    from misquote.tearsheet.advantage import compare

    return compare(
        task="t",
        category="trading",
        venue="v",
        metric="m",
        without_agent="b",
        with_agent="a",
        baseline_quote=_Quote(**quote_kw),
        agent_quote=_Quote(**quote_kw),
        baseline_result=baseline_result,
        agent_result=agent_result,
    )


def test_a_lending_result_reports_no_fees_rather_than_zero_fees() -> None:
    """The Route task published `fees 0.00 WBNB` for a venue that has no fees."""
    c = _compare(_LendingResult(), _LendingResult())

    assert c.agent_fees is None
    assert c.agent_lvr is None
    assert c.agent_in_range is None
    assert c.agent_mints is None
    # Costs and moves are real on a lending venue and must survive the change.
    assert c.agent_costs == pytest.approx(1.03)
    assert c.agent_moves == 2


def test_a_measured_zero_is_still_a_zero() -> None:
    """The other half. An agent that genuinely earned nothing earned nothing."""

    class _Idle(_LpResult):
        total_fees = 0.0
        mints = 0

    c = _compare(_Idle(), _Idle())
    assert c.agent_fees == 0.0
    assert c.agent_mints == 0


def test_a_liquidity_result_is_unaffected() -> None:
    c = _compare(_LpResult(), _LpResult())
    assert c.agent_fees == pytest.approx(1.5)
    assert c.agent_in_range == pytest.approx(0.9)
    assert c.agent_recentres == 1


def test_distinct_returns_is_absent_when_the_quote_kind_does_not_report_it() -> None:
    """An allocation `Quote` has no `distinct_returns`, and 0 was invented.

    The one field whose entire purpose is telling a reader how much of the
    sample is real is the worst possible place to publish a confident zero.
    """
    c = _compare(_LendingResult(), _LendingResult())
    assert c.agent_distinct is None

    withdistinct = _compare(_LpResult(), _LpResult(), distinct_returns=23)
    assert withdistinct.agent_distinct == 23


def test_the_observations_behind_the_band_are_carried_not_just_counted() -> None:
    """`compare` held the `Quote` and kept only the count of distinct results."""
    c = _compare(_LpResult(), _LpResult(), returns=[0.1, 0.2, 0.2, 0.3])
    assert c.agent_returns == (0.1, 0.2, 0.2, 0.3)
    assert c.baseline_returns == (0.1, 0.2, 0.2, 0.3)


def test_a_quote_without_returns_yields_an_empty_tuple_not_none() -> None:
    """The band is optional; the field is not. A `None` here would need a guard
    at every call site, and an empty rug is correctly drawn as no rug."""
    c = _compare(_LpResult(), _LpResult())
    assert c.agent_returns == ()


def _emitted(**kw):
    """One column as it reaches the artifact, through the emitter's own helper."""
    from advantage import _side

    defaults = dict(
        in_range=0.9,
        fees=1.5,
        lvr=0.25,
        costs=0.75,
        moves=6,
        mints=3,
        pulls=2,
        recentres=1,
        distinct=20,
        returns=(),
    )
    return _side(1.0, 2.0, 3.0, **{**defaults, **kw})


def test_an_absent_field_is_missing_from_the_artifact_not_zero_in_it() -> None:
    """A key that is not there is a question this task does not answer.

    `lib/format.ts::isNum` already renders a missing number as an em dash, so
    the front end needs no change to show the Route task's in-range fraction as
    absent — it needed the emitter to stop asserting one.
    """
    side = _emitted(in_range=None, fees=None, lvr=None, mints=None, distinct=None)

    for absent in ("in_range", "fees", "lvr_upper_bound", "mints", "distinct_returns"):
        assert absent not in side, f"{absent} was published for a task that has none"
    # Present-and-real must survive alongside the omissions.
    assert side["costs"] == 0.75
    assert side["moves"] == 6
    assert side["p50"] == 2.0


def test_a_measured_zero_is_published() -> None:
    """The inverse, and the reason omission is keyed on None rather than falsy."""
    side = _emitted(fees=0.0, mints=0, in_range=0.0)
    assert side["fees"] == 0.0
    assert side["mints"] == 0
    assert side["in_range"] == 0.0


def test_the_observations_reach_the_artifact() -> None:
    side = _emitted(returns=(0.11111111, 0.2, 0.2))
    assert side["returns"] == [0.111111, 0.2, 0.2]


def test_no_returns_key_when_there_are_none() -> None:
    """An empty list would draw an empty rug; an absent key draws no rug."""
    assert "returns" not in _emitted(returns=())
