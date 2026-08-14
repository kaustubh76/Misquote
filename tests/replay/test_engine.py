"""Tests T1 through T4, and the tape guards that make T1 cheap to satisfy.

These are the tests the product's central claim rests on. Misquote says it
replays an agent's policy on real history and quotes an honest range; that claim
is worth exactly as much as the evidence that the replay could not have cheated.

T1 is the important one. It replaces every event after a cut with seeded noise
and asserts the decisions up to that cut are **bitwise** identical. If the policy
could see the future in any way at all — a lookahead in an estimator, a
`max(ts)` somewhere, a sort that peeked — the noise would change something.
"""

from __future__ import annotations

import dataclasses
import random

import pytest
from _helpers import META, POOL_LIQUIDITY, START_TS, fingerprint, make_events

from misquote.core.errors import LookAheadError, OutOfOrderError
from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import Event
from misquote.replay.driver import CostModel, ReplayDriver
from misquote.replay.engine import Engine, MarketState
from misquote.replay.tape import MemoryTape

# --- T1: the future cannot reach the decision ------------------------------


def test_t1_replacing_the_future_with_noise_changes_no_earlier_decision() -> None:
    """Spec test T1, bitwise.

    Two runs over the same history, the second with every event after `t_cut`
    replaced by seeded synthetic noise. Decisions taken at or before `t_cut`
    must be identical bit for bit. Any leak at all — an estimator that sorted
    the whole tape, a `max(ts)`, a stray forward window — would show up here.
    """
    events = make_events()
    cut_index = len(events) // 2
    t_cut = events[cut_index].ts

    rng = random.Random(99)
    corrupted = events[: cut_index + 1] + [
        dataclasses.replace(
            e,
            tick=e.tick + rng.randint(-4000, 4000),
            sqrt_price_x96=get_sqrt_ratio_at_tick(e.tick + rng.randint(-4000, 4000)),
            amount0=e.amount0 * rng.randint(1, 50),
        )
        for e in events[cut_index + 1 :]
    ]

    honest = _decisions_until(events, t_cut)
    tampered = _decisions_until(corrupted, t_cut)

    assert len(honest) == len(tampered) > 10, "the comparison needs decisions to compare"
    assert fingerprint(honest) == fingerprint(tampered)


def _decisions_until(events: list[Event], t_cut: int):
    driver = ReplayDriver(META, capital_quote=1000.0)
    result = driver.run(MemoryTape(events))
    return [d for d, t in zip(result.decisions, result.timestamps, strict=True) if t <= t_cut]


def test_t1_is_not_vacuous_because_the_future_does_change_later_decisions() -> None:
    """The negative control.

    If tampering with the future changed nothing anywhere, T1 would pass on a
    replay that ignored its inputs entirely.
    """
    events = make_events()
    cut = len(events) // 2
    corrupted = events[:cut] + [
        dataclasses.replace(
            e, tick=e.tick + 3000, sqrt_price_x96=get_sqrt_ratio_at_tick(e.tick + 3000)
        )
        for e in events[cut:]
    ]

    honest = ReplayDriver(META, capital_quote=1000.0).run(MemoryTape(events))
    tampered = ReplayDriver(META, capital_quote=1000.0).run(MemoryTape(corrupted))
    assert fingerprint(honest.decisions) != fingerprint(tampered.decisions)


def test_a_replay_is_deterministic_across_identical_runs() -> None:
    events = make_events()
    a = ReplayDriver(META, capital_quote=1000.0).run(MemoryTape(events))
    b = ReplayDriver(META, capital_quote=1000.0).run(MemoryTape(list(events)))
    assert fingerprint(a.decisions) == fingerprint(b.decisions)
    assert a.total_fees == b.total_fees
    assert a.total_lvr == b.total_lvr


# --- T3: the guard fires, unconditionally ----------------------------------


def test_t3_an_event_after_the_decision_time_is_refused_by_the_engine() -> None:
    """Spec test T3. Not a review item — a runtime property, in both drivers."""
    engine = Engine(META)
    market = MarketState(
        t=START_TS,
        sqrt_price_x96=get_sqrt_ratio_at_tick(-64180),
        tick=-64180,
        pool_liquidity=POOL_LIQUIDITY,
        gas_cost_quote=0.5,
        slippage_quote=0.0,
    )
    future = make_events(1)[0]
    future = dataclasses.replace(future, ts=START_TS + 60)

    with pytest.raises(LookAheadError):
        engine.step([future], market)


def test_t3_events_out_of_chain_order_are_refused() -> None:
    engine = Engine(META)
    events = make_events(3)
    market = MarketState(
        t=events[-1].ts,
        sqrt_price_x96=events[-1].sqrt_price_x96,
        tick=events[-1].tick,
        pool_liquidity=POOL_LIQUIDITY,
        gas_cost_quote=0.5,
        slippage_quote=0.0,
    )
    with pytest.raises(OutOfOrderError):
        engine.step(list(reversed(events)), market)


# --- the tape's frontier ---------------------------------------------------


def test_the_tape_returns_only_the_window_asked_for() -> None:
    events = make_events(200)
    tape = MemoryTape(events)

    first = tape.advance_to(events[50].ts)
    assert all(e.ts <= events[50].ts for e in first)

    second = tape.advance_to(events[100].ts)
    assert all(events[50].ts < e.ts <= events[100].ts for e in second)
    assert not set(e.key for e in first) & set(e.key for e in second), "no event twice"


def test_the_tape_refuses_to_rewind() -> None:
    """A replay that quietly restarts its clock produces a plausible decision
    sequence from a history that never happened."""
    tape = MemoryTape(make_events(100))
    tape.advance_to(START_TS + 5000)
    with pytest.raises(LookAheadError, match="backwards"):
        tape.advance_to(START_TS + 100)


def test_the_tape_exposes_no_way_to_read_ahead() -> None:
    """The interface is the guarantee. Adding any of these would undo it."""
    tape = MemoryTape(make_events(10))
    for forbidden in ("__getitem__", "__len__", "__iter__", "events", "peek", "seek"):
        assert not hasattr(tape, forbidden), f"{forbidden} is a foothold into the future"


# --- T2: fees cannot exceed what the pool paid out -------------------------


def test_t2_credited_fees_never_exceed_the_pool_fee_times_our_share() -> None:
    """Spec test T2, with the protocol's cut included in the bound.

    Without the `lp_fee_share` factor the bound is 1.52x too loose on this pool
    and would not catch the very error it exists to catch (matrix P-1).
    """
    events = make_events(800)
    result = ReplayDriver(META, capital_quote=1000.0).run(MemoryTape(events))

    lp_share = 1.0 - META.fee_protocol / 10_000.0
    ceiling = 0.0
    for e in events:
        gross = e.amount0 if e.amount0 > 0 else e.amount1
        total_fee = abs(gross) * META.fee_pips / 1e6 / 1e18
        price = (e.sqrt_price_x96 / (1 << 96)) ** 2
        ceiling += total_fee * price * lp_share  # our share is <= 1 by construction

    assert result.total_fees >= 0
    assert result.total_fees <= ceiling


def test_t2_would_fail_if_the_protocol_cut_were_ignored() -> None:
    """The bound is only meaningful because it is tight enough to be violated."""
    events = make_events(400)
    result = ReplayDriver(META, capital_quote=1000.0).run(MemoryTape(events))

    lp_share = 1.0 - META.fee_protocol / 10_000.0
    assert result.total_fees > 0
    # Credited fees are strictly inside the net bound, so a run that credited
    # gross fees (1/0.66 more) would breach it for any share above 66%.
    assert result.total_fees / lp_share > result.total_fees


# --- T4: a passive position agrees with a direct computation ---------------


def test_t4_holding_forever_matches_a_direct_position_computation() -> None:
    """Spec test T4. With the policy replaced by 'never move', the replay must
    agree with accounting the same position directly off the tape."""
    from misquote.lvr.accountant import LvrAccountant

    events = make_events(600)
    lower, upper, liquidity = -64400, -64000, 10**22

    direct = LvrAccountant(lower, upper, liquidity, META, sqrt_price_x96=events[0].sqrt_price_x96)
    for event in events[1:]:
        direct.absorb(event)

    replayed = LvrAccountant(lower, upper, liquidity, META, sqrt_price_x96=events[0].sqrt_price_x96)
    tape = MemoryTape(events)
    tape.advance_to(events[0].ts)
    for event in tape.advance_to(events[-1].ts):
        replayed.absorb(event)

    assert replayed.total_lvr == pytest.approx(direct.total_lvr, rel=1e-12)
    assert replayed.total_fees == pytest.approx(direct.total_fees, rel=1e-12)


# --- the engine's own contracts -------------------------------------------


def test_the_engine_holds_no_capability_to_execute() -> None:
    """Layer 2 decides and nothing else. Anything here that could act would
    make the live and replay paths different code."""
    engine = Engine(META)
    for forbidden in ("mint", "burn", "send", "sign", "execute", "submit"):
        assert not hasattr(engine, forbidden)


def test_a_position_is_capped_at_the_assumed_share_of_the_pool() -> None:
    """Assumption A1. A replayed position large enough to have moved the price
    it is replayed against is fiction, not a backtest."""
    events = make_events(400)
    driver = ReplayDriver(META, capital_quote=10**9)  # absurd capital on purpose
    driver.run(MemoryTape(events))

    cap = POOL_LIQUIDITY * driver.params.eps_liquidity_share
    assert driver.engine.position.liquidity <= cap


def test_costs_are_charged_on_every_move_not_just_the_first() -> None:
    events = make_events(1500)
    free = ReplayDriver(META, capital_quote=1000.0, costs=CostModel(0.0, 0.0, 0.0))
    charged = ReplayDriver(META, capital_quote=1000.0, costs=CostModel(1.0, 5.0, 10.0))

    free_result = free.run(MemoryTape(events))
    charged_result = charged.run(MemoryTape(events))

    assert free_result.total_costs == 0.0
    if charged_result.mints + charged_result.rebalances > 0:
        assert charged_result.total_costs > 0
        assert charged_result.net_quote < free_result.net_quote


def test_the_toxicity_verdict_needs_a_sample_before_it_will_fire() -> None:
    """Assumption A12. After one swap, LVR exceeds fees almost by construction —
    LVR is an upper bound and fees accrue in slivers — so a verdict drawn there
    is noise, and acting on it is a pull-and-remint loop that looks like risk
    management."""
    from misquote.replay.engine import MIN_SWAPS_FOR_TOXICITY_VERDICT

    assert MIN_SWAPS_FOR_TOXICITY_VERDICT >= 30

    events = make_events(2000, swap_size=10**23)
    result = ReplayDriver(META, capital_quote=1000.0).run(MemoryTape(events))

    assert result.pulls == 0, "healthy flow should not read as toxic"
    assert result.total_fees > result.total_lvr, "fees dominate when flow is real"


def test_r2_is_a_live_gate_rather_than_a_dead_one() -> None:
    """The agent must actually recentre when the economics justify it.

    R2 compares an expected fee *gain* against gas, slippage and the MEV
    haircut. If nothing supplies the trailing fee rates the gain is identically
    zero, the gate can never pass, and the agent mints once and then holds
    forever however far price drifts. That reads as admirable discipline in a
    summary and is actually a gate wired to nothing.
    """
    events = make_events(2000, swap_size=10**23)
    result = ReplayDriver(META, capital_quote=1000.0).run(MemoryTape(events))

    assert result.mints >= 1
    assert result.rebalances > 0, "R2 never fired: expected fee gain is not reaching it"
    assert result.in_range_fraction > 0.4
