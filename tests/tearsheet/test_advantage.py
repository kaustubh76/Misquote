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
    NEVER_WITHDRAW,
    build,
    synthetic_events,
    task_earn,
    task_protect,
    to_payload,
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
    assert protect.baseline_costs == pytest.approx(expected_open * protect.baseline_moves)

    # The symmetry is the actual claim, and it holds without knowing the formula:
    # whatever a move costs, both columns pay the same for it.
    assert protect.agent_costs == pytest.approx(expected_open * protect.agent_moves)


# --- the artifact -----------------------------------------------------------


def test_the_artifact_round_trips_and_carries_the_badge(comparisons) -> None:
    import json

    payload = to_payload(comparisons, source="synthetic", capital=1000.0)
    assert payload["source"] == "synthetic"
    assert payload["counterfactual"] is True
    assert "COUNTERFACTUAL" in payload["badge"]
    assert len(payload["tasks"]) >= 3
    for task in payload["tasks"]:
        assert {"baseline", "agent", "delta_pp", "verdict"} <= set(task)
    assert json.loads(json.dumps(payload)) == payload
