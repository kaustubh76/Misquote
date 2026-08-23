"""Router's switching boundary, and every gate that can stop it.

Mirrors `test_grid.py` in shape. The properties that matter most are the ones
that would let the agent look configured while doing nothing, or move for a
reason that is not the one on the card.
"""

from __future__ import annotations

import pytest

from misquote.agents.router.policy import (
    RouterParams,
    capped_notional,
    decide_router,
    hurdle_apr,
    quotable,
)
from misquote.core.allocation import (
    AllocationAction,
    AllocationObservation,
    VenueQuote,
)

A = "0xfd5840cd36d94d7229439859c0112a4185bc0255"  # vUSDT
B = "0xeca88125a5adbe82614ffc12d0db554e2e2867c8"  # vUSDC


def venue(vid: str, apr: float, *, stale: bool = False, samples: int = 200, base: float = 1e8):
    return VenueQuote(
        venue_id=vid,
        apr=apr,
        apr_samples=samples,
        apr_is_stale=stale,
        cash_quote=base * 0.4,
        supplied_base_quote=base,
    )


def obs(
    *,
    venues,
    held,
    notional=10_000.0,
    gas=0.30,
    slippage_bps=5.0,
    since_switch=10**6,
    switches_today=0,
    edge_streak=10,
    t=1_000_000,
):
    return AllocationObservation(
        t=t,
        venues=venues,
        held=held,
        notional_quote=notional,
        gas_quote=gas,
        switch_slippage_bps=slippage_bps,
        seconds_since_switch=since_switch,
        switches_today=switches_today,
        edge_streak=edge_streak,
    )


# --- the boundary itself ----------------------------------------------------


def test_an_edge_just_above_the_hurdle_switches_and_just_below_holds() -> None:
    p = RouterParams()
    base = obs(venues=(venue(A, 0.02), venue(B, 0.02)), held=A)
    h = hurdle_apr(base, p)

    over = obs(venues=(venue(A, 0.02), venue(B, 0.02 + h * 1.01)), held=A)
    under = obs(venues=(venue(A, 0.02), venue(B, 0.02 + h * 0.99)), held=A)

    assert decide_router(over, p).action is AllocationAction.SWITCH
    assert decide_router(under, p).action is AllocationAction.HOLD


def test_doubling_gas_strictly_raises_the_hurdle() -> None:
    """Catches the `CostModel.gas_quote = 0` class of defect (P-13)."""
    p = RouterParams()
    cheap = obs(venues=(venue(A, 0.02), venue(B, 0.05)), held=A, gas=0.30)
    dear = obs(venues=(venue(A, 0.02), venue(B, 0.05)), held=A, gas=0.60)
    assert hurdle_apr(dear, p) > hurdle_apr(cheap, p)


def test_the_hurdle_is_charged_for_two_transactions_not_one() -> None:
    """A switch is a redeem and a supply. Pricing one is pricing half a move."""
    p = RouterParams(switch_cost_margin=0.0)
    o = obs(venues=(venue(A, 0.02), venue(B, 0.05)), held=A, gas=1.0, slippage_bps=0.0)
    horizon_years = p.horizon_hours * 3600 / 31_536_000
    expected = 2.0 * 1.0 / o.notional_quote / horizon_years
    assert hurdle_apr(o, p) == pytest.approx(expected, rel=1e-12)


def test_slippage_enters_the_hurdle_in_basis_points_of_notional() -> None:
    p = RouterParams(switch_cost_margin=0.0)
    o = obs(venues=(venue(A, 0.02), venue(B, 0.05)), held=A, gas=0.0, slippage_bps=10.0)
    horizon_years = p.horizon_hours * 3600 / 31_536_000
    expected = (o.notional_quote * 10.0 / 10_000) / o.notional_quote / horizon_years
    assert hurdle_apr(o, p) == pytest.approx(expected, rel=1e-12)


# --- every gate can stop a move, and says so --------------------------------


def test_persistence_blocks_a_move_until_the_streak_is_met() -> None:
    p = RouterParams(persistence_samples=3)
    big = (venue(A, 0.02), venue(B, 0.40))
    # edge_streak counts *prior* samples; +1 counts this one.
    assert decide_router(obs(venues=big, held=A, edge_streak=1), p).action is AllocationAction.HOLD
    assert (
        decide_router(obs(venues=big, held=A, edge_streak=2), p).action is AllocationAction.SWITCH
    )


def test_cooldown_blocks_a_move_and_names_itself() -> None:
    p = RouterParams(cooldown_s=3600)
    d = decide_router(obs(venues=(venue(A, 0.02), venue(B, 0.40)), held=A, since_switch=60), p)
    assert d.action is AllocationAction.HOLD
    assert d.reason("cooldown_met") == 0.0


def test_the_daily_switch_budget_blocks_a_move_and_names_itself() -> None:
    p = RouterParams(max_switches_per_day=2)
    d = decide_router(obs(venues=(venue(A, 0.02), venue(B, 0.40)), held=A, switches_today=2), p)
    assert d.action is AllocationAction.HOLD
    assert d.reason("switch_budget_left") == 0.0


def test_every_gate_appears_in_reasons_even_when_it_did_not_fire() -> None:
    """No gate wired to nothing: the histogram must have no empty column."""
    d = decide_router(obs(venues=(venue(A, 0.02), venue(B, 0.40)), held=A), RouterParams())
    for gate in (
        "edge_clears_hurdle",
        "persistence_met",
        "cooldown_met",
        "switch_budget_left",
        "best_is_held",
        "hurdle_apr",
        "edge_apr",
    ):
        assert d.reason(gate) is not None, f"{gate} was consulted but never journalled"


# --- staleness is disqualifying, not merely unattractive --------------------


def test_a_stale_venue_is_never_chosen_even_with_the_highest_recorded_apr() -> None:
    p = RouterParams()
    d = decide_router(obs(venues=(venue(A, 0.02), venue(B, 0.99, stale=True)), held=A), p)
    assert d.action is AllocationAction.HOLD
    assert d.target_venue is None


def test_a_venue_below_the_sample_floor_is_not_quotable() -> None:
    p = RouterParams(min_apr_samples=30)
    assert not quotable(venue(B, 0.5, samples=29), p)
    assert quotable(venue(B, 0.5, samples=30), p)


def test_a_held_venue_that_goes_stale_is_exited_not_held() -> None:
    """An unmeasurable position cannot be compared, so staying is not a choice."""
    p = RouterParams()
    d = decide_router(obs(venues=(venue(A, 0.02, stale=True), venue(B, 0.05)), held=A), p)
    assert d.action is AllocationAction.EXIT
    assert d.reason("held_stale") == 1.0


def test_no_quotable_venue_holds_rather_than_guessing() -> None:
    p = RouterParams()
    d = decide_router(
        obs(venues=(venue(A, 0.02, stale=True), venue(B, 0.05, stale=True)), held=None), p
    )
    assert d.action is AllocationAction.HOLD
    assert d.reason("reason_no_quotable_venue") == 1.0


# --- entering is priced like any other move ---------------------------------


def test_entering_from_flat_is_charged_the_same_hurdle() -> None:
    p = RouterParams()
    poor = obs(venues=(venue(A, 0.001),), held=None)
    rich = obs(venues=(venue(A, 0.90),), held=None)
    assert decide_router(poor, p).action is AllocationAction.HOLD
    assert decide_router(rich, p).action is AllocationAction.ENTER


# --- A1's analogue ----------------------------------------------------------


def test_the_notional_cap_is_a_share_of_the_market_not_a_constant() -> None:
    p = RouterParams(eps_market_share=0.01)
    assert capped_notional(venue(A, 0.02, base=1e8), p) == pytest.approx(1e6)
    assert capped_notional(venue(A, 0.02, base=1e6), p) == pytest.approx(1e4)


# --- refusals ---------------------------------------------------------------


def test_an_observation_with_no_venues_is_refused() -> None:
    with pytest.raises(ValueError, match="nothing to choose between"):
        obs(venues=(), held=None)


def test_a_held_venue_absent_from_the_observation_is_refused() -> None:
    with pytest.raises(ValueError, match="not among the observed venues"):
        obs(venues=(venue(A, 0.02),), held=B)


def test_a_rate_below_minus_one_hundred_percent_is_refused() -> None:
    with pytest.raises(ValueError, match="below -100%"):
        venue(A, -1.5)


def test_a_zero_notional_is_refused() -> None:
    with pytest.raises(ValueError, match="no yield to optimise"):
        obs(venues=(venue(A, 0.02),), held=None, notional=0.0)


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"horizon_hours": 0}, "horizon"),
        ({"switch_cost_margin": -0.1}, "negative margin"),
        ({"persistence_samples": 0}, "at least one sample"),
        ({"max_switches_per_day": 0}, "can never route"),
        ({"min_apr_samples": 1}, "two accruals"),
        ({"eps_market_share": 0}, "fraction of a market"),
        ({"eps_market_share": 1.5}, "fraction of a market"),
    ],
)
def test_params_refuse_configurations_that_could_not_work(kwargs, match) -> None:
    with pytest.raises(ValueError, match=match):
        RouterParams(**kwargs)


def test_the_refusals_are_not_vacuous() -> None:
    """A default RouterParams must construct, or every test above proves nothing."""
    assert RouterParams().persistence_samples >= 1
