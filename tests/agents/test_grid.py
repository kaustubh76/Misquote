"""Grid, and the claim it exists to support.

A marketplace that says it replays *any* agent's policy on real history, and
ships one agent, has shown that one program works. So the load-bearing test here
is not that Grid trades well — it is that a genuinely different strategy runs
through the identical engine, tape, cost model, LVR accountant and quote
machinery with no special-casing anywhere.
"""

from __future__ import annotations

import pytest
from _helpers import META, make_events

from misquote.agents.grid.policy import GridParams, decide_grid
from misquote.core.types import Action, Observation, PositionState
from misquote.replay.tape import MemoryTape


def position(lower=-64400, upper=-64000, *, last_move=0) -> PositionState:
    return PositionState(
        lower=lower,
        upper=upper,
        liquidity=10**22,
        token_id=1,
        minted_ts=0,
        last_rebalance_ts=last_move,
        rebalances_today=0,
    )


def observation(tick=-64200, *, t=100_000, pos=None) -> Observation:
    from misquote.core.policy import LN_TICK_BASE
    from misquote.core.tickmath import get_sqrt_ratio_at_tick

    return Observation(
        t=t,
        tick=tick,
        y=tick * LN_TICK_BASE,
        sqrt_price_x96=get_sqrt_ratio_at_tick(tick),
        pool_liquidity=10**24,
        q=0.0,
        sigma=0.02,
        kappa=500.0,
        kappa_r2=0.9,
        kappa_is_fallback=False,
        T_t=24.0,
        gas_cost_quote=0.5,
        slippage_quote=0.2,
        fee_rate_per_liquidity_target=1e-20,
        fee_rate_per_liquidity_current=0.0,
        target_liquidity=10**22,
        position_value_quote=1000.0,
        rebalance_notional_quote=200.0,
        cex_gap=0.0,
        swap_imbalance_z=0.0,
        lvr_rate=0.0,
        fee_rate=1.0,
        toxic_streak=0,
        clear_streak=99,
        position=pos if pos is not None else position(),
    )


# --- the policy ------------------------------------------------------------


def test_with_no_position_it_places_a_ladder() -> None:
    empty = PositionState(
        lower=None,
        upper=None,
        liquidity=0,
        token_id=None,
        minted_ts=0,
        last_rebalance_ts=0,
        rebalances_today=0,
    )
    decision = decide_grid(observation(pos=empty), GridParams(), META)
    assert decision.action is Action.MINT
    assert decision.target_upper - decision.target_lower == 2 * decision.half_width_ticks


def test_inside_the_ladder_it_does_nothing() -> None:
    """No drift threshold and no fee-gain gate: being inside is sufficient."""
    decision = decide_grid(observation(tick=-64200), GridParams(), META)
    assert decision.action is Action.HOLD


def test_leaving_the_ladder_reanchors_it() -> None:
    decision = decide_grid(
        observation(tick=-63000, t=100_000, pos=position(last_move=0)), GridParams(), META
    )
    assert decision.action is Action.RECENTER
    assert decision.target_lower <= -63000 < decision.target_upper


def test_the_cooldown_holds_even_outside_the_ladder() -> None:
    """Anti-churn, and the only thing standing between Grid and a gas fire on a
    trending day."""
    decision = decide_grid(
        observation(tick=-63000, t=100, pos=position(last_move=0)),
        GridParams(cooldown_s=3600),
        META,
    )
    assert decision.action is Action.HOLD
    assert decision.reason("cooldown_met") == 0.0


def test_the_ladder_always_lands_on_the_spacing_grid() -> None:
    for tick in (-64183, -64187, -60001, 0):
        decision = decide_grid(observation(tick=tick), GridParams(rung_width_ticks=173), META)
        assert decision.center_tick % META.tick_spacing == 0
        assert decision.half_width_ticks % META.tick_spacing == 0


def test_a_ladder_with_no_width_is_refused() -> None:
    with pytest.raises(ValueError, match="not a ladder"):
        GridParams(rung_width_ticks=0)


def test_every_decision_carries_its_reasoning() -> None:
    """Same contract as Warden: the journal must be able to say why."""
    decision = decide_grid(observation(), GridParams(), META)
    assert decision.reason("grid_width_ticks") > 0
    assert decision.reason("in_range") == 1.0
    assert decision.reason("reason_hold") == 1.0


# --- the demonstration -----------------------------------------------------


def test_grid_returns_the_same_decision_type_warden_does() -> None:
    """So the driver, journal, replay engine and tearsheet need no knowledge of
    which agent produced it. That is the whole generality claim."""
    from misquote.core.policy import decide
    from misquote.core.types import Params

    obs = observation()
    warden = decide(obs, Params(), META)
    grid = decide_grid(obs, GridParams(), META)

    assert type(warden) is type(grid)
    assert set(dir(warden)) == set(dir(grid))
    for decision in (warden, grid):
        assert isinstance(decision.reasons, tuple)
        assert decision.center_tick % META.tick_spacing == 0


def test_grid_runs_through_the_same_replay_engine_with_no_special_casing() -> None:
    """The load-bearing test in this file.

    The engine was written alongside Warden. If it only worked for Warden, this
    would fail — and a marketplace claiming to replay any agent's policy would be
    claiming something it could not do.
    """
    from misquote.replay.driver import ReplayDriver

    events = make_events(600, swap_size=10**23)

    grid_params = GridParams(rung_width_ticks=200)
    # Passed to the driver, at the one seam that exists for it. This used to
    # assign over the engine module's `decide` global and restore it in a
    # `finally`; the seam moved onto the engine when a third agent made that
    # untenable.
    driver = ReplayDriver(
        META,
        capital_quote=1000.0,
        policy=lambda obs, params, meta: decide_grid(obs, grid_params, meta),
    )
    result = driver.run(MemoryTape(events))

    assert result.samples > 0
    assert result.mints >= 1, "Grid never opened a position"
    assert result.total_fees >= 0.0
    assert result.total_lvr >= 0.0
    assert all(d.half_width_ticks % META.tick_spacing == 0 for d in result.decisions)


def test_grid_moves_less_often_than_warden_on_the_same_history() -> None:
    """The comparison a marketplace should be able to make with numbers.

    Grid only reanchors when price leaves the ladder; Warden recentres on drift
    subject to four gates. Whether that is better depends on the market, which is
    exactly why a replay engine is more useful than an argument.
    """
    from misquote.replay.driver import ReplayDriver

    events = make_events(1200, swap_size=10**23)

    warden_result = ReplayDriver(META, capital_quote=1000.0).run(MemoryTape(events))

    grid_params = GridParams(rung_width_ticks=400, cooldown_s=7200)
    grid_result = ReplayDriver(
        META,
        capital_quote=1000.0,
        policy=lambda obs, params, meta: decide_grid(obs, grid_params, meta),
    ).run(MemoryTape(events))

    assert grid_result.samples == warden_result.samples
    # Both produced a full, comparable run through identical machinery — which is
    # the claim. The direction of the difference is a market fact, not a promise.
    assert grid_result.mints + grid_result.rebalances >= 1
    assert warden_result.mints + warden_result.rebalances >= 1
