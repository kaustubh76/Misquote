"""Sentinel, and the dead gate it found.

Two things are being checked here. The first is the agent: it leaves when the
pool looks unsafe and comes back when it has looked safe for long enough. The
second matters more — that spec section 3.4's imbalance arm is **wired to
something**. It was not, for nineteen steps, and the tests for it passed the
whole time because they handed the policy a z-score directly and never asked
whether anything produced one.
"""

from __future__ import annotations

import dataclasses

import pytest
from _helpers import META, make_events

from misquote.agents.sentinel.policy import (
    SentinelParams,
    decide_sentinel,
    sentinel_policy,
    unsafe,
)
from misquote.core.types import Action, Observation, Params, PositionState
from misquote.replay.driver import ReplayDriver
from misquote.replay.tape import MemoryTape

OUT_OF_MARKET = PositionState(
    lower=None,
    upper=None,
    liquidity=0,
    token_id=None,
    minted_ts=0,
    last_rebalance_ts=0,
    rebalances_today=0,
)


def position(lower=-64700, upper=-63700, *, minted=0, last_move=0) -> PositionState:
    return PositionState(
        lower=lower,
        upper=upper,
        liquidity=10**22,
        token_id=1,
        minted_ts=minted,
        last_rebalance_ts=last_move,
        rebalances_today=0,
    )


def observation(**overrides) -> Observation:
    from misquote.core.policy import LN_TICK_BASE
    from misquote.core.tickmath import get_sqrt_ratio_at_tick

    tick = overrides.pop("tick", -64200)
    fields = {
        "t": 100_000,
        "tick": tick,
        "y": tick * LN_TICK_BASE,
        "sqrt_price_x96": get_sqrt_ratio_at_tick(tick),
        "pool_liquidity": 10**24,
        "q": 0.0,
        "sigma": 0.02,
        "kappa": 500.0,
        "kappa_r2": 0.9,
        "kappa_is_fallback": False,
        "sigma_confidence": 0.95,
        "T_t": 24.0,
        "gas_cost_quote": 0.5,
        "slippage_quote": 0.2,
        "fee_rate_per_liquidity_target": 1e-20,
        "fee_rate_per_liquidity_current": 0.0,
        "target_liquidity": 10**22,
        "position_value_quote": 1000.0,
        "rebalance_notional_quote": 200.0,
        "cex_gap": None,
        "swap_imbalance_z": 0.0,
        "swap_imbalance_threshold": 2.5,
        "lvr_rate": 0.0,
        "fee_rate": 1.0,
        "toxic_streak": 0,
        "clear_streak": 99,
        "position": position(minted=0),
    }
    fields.update(overrides)
    return Observation(**fields)


# --- the health rule --------------------------------------------------------


def test_a_quiet_pool_is_safe() -> None:
    is_unsafe, rule, _ = unsafe(observation(), Params(), META)
    assert (is_unsafe, rule) == (False, "")


def test_one_way_flow_past_z_pull_is_unsafe_and_says_which_rule() -> None:
    """Naming the rule is not decoration: the two arms have completely different
    lead times, and a card saying "withdrew" without saying "after the fact" is
    overstating what the agent knew."""
    is_unsafe, rule, _ = unsafe(observation(swap_imbalance_z=3.0), Params(), META)
    assert (is_unsafe, rule) == (True, "imbalance")


def test_the_imbalance_rule_is_two_sided() -> None:
    """Matrix D-8. Section 3.4 writes `imb_t > z_pull`, which defends against
    being bought and leaves being sold wide open. Adverse selection does not care
    which token the informed trader is taking."""
    assert unsafe(observation(swap_imbalance_z=-3.0), Params(), META)[0]
    assert unsafe(observation(swap_imbalance_z=3.0), Params(), META)[0]
    assert not unsafe(observation(swap_imbalance_z=-2.0), Params(), META)[0]


def test_bleeding_more_to_arbitrage_than_it_earns_is_unsafe() -> None:
    """And only after it has persisted for `m` samples, because Sentinel reuses
    section 3.4 rather than restating it — so the persistence rule comes along."""
    params = Params(m_toxic=3)
    bleeding = observation(lvr_rate=5.0, fee_rate=1.0, toxic_streak=2)
    is_unsafe, rule, _ = unsafe(bleeding, params, META)
    assert (is_unsafe, rule) == (True, "realized_lvr")

    first_sample = observation(lvr_rate=5.0, fee_rate=1.0, toxic_streak=0)
    assert not unsafe(first_sample, params, META)[0], "one sample is not a trend"


def test_a_position_with_no_verdict_yet_is_not_called_unsafe() -> None:
    """The engine reports both rates as zero until it has seen enough swaps
    (assumption A12), and `0.0 > 0.0` must not read as trouble."""
    quiet = observation(lvr_rate=0.0, fee_rate=0.0, toxic_streak=99)
    assert not unsafe(quiet, Params(), META)[0]


# --- the policy -------------------------------------------------------------


def test_it_opens_a_position_when_the_pool_is_quiet() -> None:
    decision = decide_sentinel(observation(position=OUT_OF_MARKET), Params(), META)
    assert decision.action is Action.MINT
    assert decision.target_lower is not None
    assert decision.half_width_ticks % META.tick_spacing == 0


def test_it_withdraws_when_flow_turns_one_way() -> None:
    obs = observation(swap_imbalance_z=4.0, position=position(minted=0), t=100_000)
    decision = decide_sentinel(obs, Params(), META)
    assert decision.action is Action.PULL
    assert decision.reason("unsafe") == 1.0
    assert decision.reason("unsafe_rule_imbalance") == 1.0


def test_it_will_not_pull_before_it_has_held_the_position() -> None:
    """Without a minimum hold, a position minted into an already-imbalanced
    window pulls on its first sample — paying to open and earning nothing."""
    obs = observation(
        swap_imbalance_z=4.0,
        swap_imbalance_threshold=2.5,
        position=position(minted=99_900),
        t=100_000,
    )
    config = SentinelParams(min_hold_s=600)
    assert decide_sentinel(obs, Params(), META, config).action is Action.HOLD


def test_after_a_pull_it_waits_for_the_clear_streak() -> None:
    pulled = dataclasses.replace(OUT_OF_MARKET, last_rebalance_ts=99_000)
    params = Params(m_clear=10)

    waiting = decide_sentinel(observation(position=pulled, clear_streak=4), params, META)
    assert waiting.action is Action.HOLD
    assert waiting.reason("reason_wait_clear_streak") == 1.0

    ready = decide_sentinel(observation(position=pulled, clear_streak=10), params, META)
    assert ready.action is Action.REENTER, "coming back after a pull is a re-entry, not a mint"


def test_it_does_not_re_enter_into_a_pool_that_is_still_unsafe() -> None:
    pulled = dataclasses.replace(OUT_OF_MARKET, last_rebalance_ts=99_000)
    decision = decide_sentinel(
        observation(position=pulled, clear_streak=99, swap_imbalance_z=4.0), Params(), META
    )
    assert decision.action is Action.HOLD
    assert decision.reason("reason_wait_unsafe") == 1.0


def test_it_never_recentres_for_profit() -> None:
    """Sentinel has no view on where the range should be. Price well inside the
    band, a large fee opportunity — it holds anyway. That is the whole difference
    between it and Warden."""
    obs = observation(
        tick=-64200,
        position=position(lower=-64700, upper=-63700, minted=0),
        fee_rate_per_liquidity_target=1e-6,
    )
    assert decide_sentinel(obs, Params(), META).action is Action.HOLD


def test_it_reanchors_only_when_price_leaves_the_band() -> None:
    obs = observation(tick=-60000, position=position(lower=-64700, upper=-63700, minted=0))
    assert decide_sentinel(obs, Params(), META).action is Action.RECENTER


def test_it_pulls_rather_than_reanchors_when_both_apply() -> None:
    """Leaving beats chasing. A band that price has left *and* one-way flow is
    the worst case, and moving into it would pay gas to stand in front of it."""
    obs = observation(
        tick=-60000,
        swap_imbalance_z=4.0,
        swap_imbalance_threshold=2.5,
        position=position(lower=-64700, upper=-63700, minted=0),
    )
    assert decide_sentinel(obs, Params(), META).action is Action.PULL


def test_its_band_lands_on_the_tick_spacing() -> None:
    for band in (137, 200, 501, 999):
        decision = decide_sentinel(
            observation(position=OUT_OF_MARKET), Params(), META, SentinelParams(band_ticks=band)
        )
        assert decision.half_width_ticks % META.tick_spacing == 0
        assert decision.target_lower % META.tick_spacing == 0
        assert decision.target_upper % META.tick_spacing == 0


def test_a_band_with_no_width_is_refused() -> None:
    with pytest.raises(ValueError, match="not a band"):
        SentinelParams(band_ticks=0)


# --- through the engine, unchanged ------------------------------------------


def test_sentinel_runs_through_the_shared_engine() -> None:
    """The load-bearing test. A third agent, no engine changes, same machinery.

    Grid already proved the engine was not a Warden harness. Sentinel proves
    something narrower and more useful: that the engine's *withdrawal* path works
    for an agent driven by it, rather than for one that reaches it once a month.
    """
    events = make_events(1200, swap_size=10**23)
    result = ReplayDriver(META, capital_quote=1000.0, policy=sentinel_policy(SentinelParams())).run(
        MemoryTape(events)
    )

    assert result.samples > 0
    assert result.mints >= 1, "Sentinel never opened a position"
    assert all(d.half_width_ticks % META.tick_spacing == 0 for d in result.decisions)
    assert result.total_fees >= 0.0


def test_the_policy_seam_needs_no_monkeypatching() -> None:
    """Two agents over one history, at the same time, in one process.

    Running a second agent used to mean assigning over the engine module's
    `decide` global and restoring it in a `finally`. That cannot express this
    test at all — the two drivers would fight over one global — which is the
    concrete reason the seam moved onto the engine.
    """
    events = make_events(600, swap_size=10**23)
    warden = ReplayDriver(META, capital_quote=1000.0)
    sentinel = ReplayDriver(META, capital_quote=1000.0, policy=sentinel_policy())

    a = warden.run(MemoryTape(events))
    b = sentinel.run(MemoryTape(events))

    assert a.samples == b.samples > 0
    assert a.decisions != b.decisions, "two different agents produced the same decisions"


def test_the_imbalance_arm_is_wired_to_something() -> None:
    """The regression test for the defect Sentinel found.

    `Engine._observe` passed a literal `0.0` for `swap_imbalance_z`, so section
    3.4's second arm could never fire, `z_pull` and `M` were parameters that
    traced to nothing, and the policy's imbalance branch was unreachable. Every
    existing test still passed, because they all supplied the z-score by hand.

    Asserting a non-zero value somewhere in a real run is what makes that
    impossible to reintroduce quietly.
    """
    from misquote.core.policy import decide

    events = make_events(1200, swap_size=10**23)
    seen: list[float] = []

    def recording_warden(obs, params, meta):
        seen.append(obs.swap_imbalance_z)
        return decide(obs, params, meta)

    ReplayDriver(META, capital_quote=1000.0, policy=recording_warden).run(MemoryTape(events))

    assert seen, "no decisions were taken"
    assert any(z != 0.0 for z in seen), (
        "swap_imbalance_z was zero on every sample — section 3.4's imbalance arm "
        "is wired to nothing again"
    )
    assert max(abs(z) for z in seen) > 1.0, "the z-score never reached a meaningful magnitude"


def test_an_unreachable_z_pull_is_refused_rather_than_accepted() -> None:
    """The other way to wire a gate to nothing: set a threshold above its ceiling.

    The z-score cannot exceed sqrt(M), so `z_pull >= sqrt(M)` is a rule that reads
    as configured, prints a sensible number on every card, and never fires. This
    project has shipped two dead gates already, both found by accident; making
    the unreachable case refuse to construct is cheaper than finding a third the
    same way.
    """
    with pytest.raises(ValueError, match="unreachable"):
        Params(z_pull=8.0, imbalance_window=50)  # sqrt(50) = 7.07

    Params(z_pull=8.0, imbalance_window=100)  # sqrt(100) = 10, reachable
    assert Params().z_pull < Params().imbalance_window ** 0.5, "the default must be reachable"


# --- the same bound, on both agents -----------------------------------------


def test_sentinel_will_not_re_enter_once_the_daily_budget_is_gone() -> None:
    """Sentinel's whole active behaviour is leaving and returning, so it is the
    agent this bound matters most to — and it is the one the first version of
    the fix missed.

    P-12 went into `core.policy.decide` and not into `decide_sentinel`. The run
    that proved it capped Warden at 249 round trips and left Sentinel at 1,761,
    on the same tape, in the same run, because the rule existed in two places and
    only one of them was edited. It is one function now.
    """
    params = Params()
    # Same UTC day as the observation's clock (t=100_000). `reentries_today`
    # zeroes a count whose last move was yesterday — correctly, it is a per-day
    # cap — so a fixture straddling midnight tests the rollover, not the budget.
    flat = dataclasses.replace(
        OUT_OF_MARKET,
        last_rebalance_ts=99_000,
        reentries_today=params.max_reentries_per_day,
    )
    obs = observation(position=flat, clear_streak=99, swap_imbalance_z=0.0)

    decision = decide_sentinel(obs, params, META)
    assert decision.action is Action.HOLD
    assert dict(decision.reasons)["reason_wait_budget"] == 1.0


def test_sentinel_re_enters_while_the_budget_lasts() -> None:
    """A gate that can never open is not a gate."""
    params = Params()
    flat = dataclasses.replace(OUT_OF_MARKET, last_rebalance_ts=99_000, rebalances_today=0)
    obs = observation(position=flat, clear_streak=99, swap_imbalance_z=0.0)

    assert decide_sentinel(obs, params, META).action is Action.REENTER


def test_sentinel_still_leaves_with_no_budget_left() -> None:
    """The asymmetry, checked on this agent too. Exit is never rationed: an agent
    held inside toxic flow because it had spent its budget is worse off than one
    that churns."""
    params = Params()
    held = dataclasses.replace(
        position(minted=0),
        last_rebalance_ts=99_000,
        rebalances_today=params.max_rebalances_per_day * 10,
    )
    obs = observation(position=held, swap_imbalance_z=params.z_pull + 1.0)

    assert decide_sentinel(obs, params, META).action is Action.PULL


def test_both_agents_read_the_same_budget_function() -> None:
    """Not a style point. V-12 was Warden and the engine applying two different
    imbalance rules, and P-12 was two policies applying two different re-entry
    rules. Both were invisible until an agent leaned on the half that was wrong.
    """
    import inspect

    from misquote.agents.sentinel import policy as sentinel_module
    from misquote.core import policy as core_module

    for module in (core_module, sentinel_module):
        source = inspect.getsource(module)
        assert "reentry_affordable(" in source, (
            f"{module.__name__} does not consult the shared re-entry budget"
        )

    # Deliberately not asserting that neither module mentions
    # `max_rebalances_per_day` anywhere else. `core.policy` reads it directly in
    # R3, which caps *recentring* — a different rule that happens to share a
    # parameter. An assertion that banned the name would have been a test of
    # spelling rather than of behaviour, and would have failed on correct code.
    assert "max_rebalances_per_day" not in inspect.getsource(sentinel_module), (
        "Sentinel restates the budget rule instead of calling it"
    )
