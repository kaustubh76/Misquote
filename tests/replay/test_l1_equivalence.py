"""L1: the live agent and the replay engine are the same policy, provably.

The frozen spec claims Showcase Mode runs "the same code path, different input
wallet". That is the sort of claim every project makes and few can demonstrate,
because the usual architecture has a replay harness that resembles the live loop
and drifts from it quietly.

So this asserts it. The live driver — its own loop, its own position
bookkeeping, its own sampling — is pointed at a `TapeChainSource` serving
recorded history, and its decision sequence is compared **byte for byte** with
the replay driver's over the same tape.

This is an implementation invariant rather than a spec test. It is not in the
frozen spec's T1–T4, and it is arguably the most valuable test here: T1 proves
the replay could not cheat, and L1 proves the thing that cheated is the thing
that will trade.
"""

from __future__ import annotations

import pytest
from _helpers import META, fingerprint, make_events

from misquote.agents.warden.live import SimulatedExecutor, WardenLive
from misquote.chain.source import TapeChainSource
from misquote.core.errors import LookAheadError
from misquote.core.types import Action, Params
from misquote.replay.driver import ReplayDriver
from misquote.replay.tape import MemoryTape


def _replay(events, *, capital: float = 1000.0, params: Params | None = None):
    driver = ReplayDriver(META, params=params, capital_quote=capital)
    return driver.run(MemoryTape(events))


def _live(events, *, capital: float = 1000.0, params: Params | None = None):
    source = TapeChainSource(MemoryTape(events))
    warden = WardenLive(META, source, SimulatedExecutor(), params=params, capital_quote=capital)
    warden.run_until(events[-1].ts, start_ts=events[0].ts)
    return warden


# --- L1 proper -------------------------------------------------------------


def test_l1_the_live_loop_and_the_replay_agree_bit_for_bit() -> None:
    """The claim, discharged.

    Two independent loops — different files, different position bookkeeping,
    different executors — over the same history, compared with every float
    packed to its exact bits. A tolerance here would let a real divergence
    through, and a divergence is the whole thing being tested for.
    """
    events = make_events(1200, swap_size=10**23)

    replayed = _replay(events)
    live = _live(events)

    assert len(live.decisions) == len(replayed.decisions) > 50
    assert live.timestamps == replayed.timestamps
    assert fingerprint(live.decisions) == fingerprint(replayed.decisions)


def test_l1_holds_across_risk_profiles() -> None:
    """The three published gamma settings, since a user picks one of them."""
    events = make_events(600, swap_size=10**23)
    for gamma in (0.4, 0.8, 1.5):
        params = Params(gamma=gamma)
        assert fingerprint(_live(events, params=params).decisions) == fingerprint(
            _replay(events, params=params).decisions
        )


def test_l1_holds_when_the_agent_actually_moves() -> None:
    """An equality that only holds while both sides do nothing proves nothing.

    The horizon is set to match the fixture. Range width is now floored by the
    volatility of a `window_hours` move (P-17), so a policy sized for 24 hours
    against a tape that runs for eight opens a range wider than the whole tape's
    excursion and correctly never needs to recentre — which would leave this test
    asserting the equality over mints and pulls alone. One hour is commensurate
    with the fixture and puts recentres back in the comparison, where they are
    the actions most likely to expose a divergence between the two drivers.
    """
    events = make_events(1200, swap_size=10**23)
    params = Params(window_hours=1.0)
    live = _live(events, params=params)
    replayed = _replay(events, params=params)

    moves = [d for d in replayed.decisions if d.action is not Action.HOLD]
    assert len(moves) > 1, "the comparison needs the agent to have done something"
    assert replayed.rebalances > 0
    assert fingerprint(live.decisions) == fingerprint(replayed.decisions)


def test_the_live_loop_reaches_the_same_position_not_just_the_same_decisions() -> None:
    """Decisions could match while the position diverged, if one side applied
    them differently. Then the next decision would differ, so this is really a
    check that the equality above is not a coincidence of a short run."""
    events = make_events(1200, swap_size=10**23)
    live = _live(events)
    replayed_driver = ReplayDriver(META, capital_quote=1000.0)
    replayed_driver.run(MemoryTape(events))

    assert live.engine.position.lower == replayed_driver.engine.position.lower
    assert live.engine.position.upper == replayed_driver.engine.position.upper
    assert live.engine.position.liquidity == replayed_driver.engine.position.liquidity


# --- the live path inherits the same guarantees ---------------------------


def test_the_live_source_cannot_run_its_clock_backwards() -> None:
    events = make_events(200)
    source = TapeChainSource(MemoryTape(events))
    source.advance(events[100].ts)
    with pytest.raises(LookAheadError, match="backwards"):
        source.advance(events[10].ts)


def test_the_live_source_cannot_serve_events_from_the_future() -> None:
    """The frontier discipline is the tape's, and the live path does not get to
    opt out of it — otherwise L1 would compare a guarded run against an
    unguarded one and the live agent would be the weaker of the two."""
    events = make_events(200)
    source = TapeChainSource(MemoryTape(events))

    early = source.events_since(0, events[50].ts)
    assert all(e.ts <= events[50].ts for e in early)

    with pytest.raises(LookAheadError):
        source.events_since(0, events[10].ts)


def test_the_live_loop_signs_nothing_by_construction() -> None:
    """The executor is the only thing that can act, and the simulated one holds
    no key. That is what makes it safe to run the whole loop over history."""
    executor = SimulatedExecutor()
    for forbidden in ("sign", "send_transaction", "private_key", "account"):
        assert not hasattr(executor, forbidden)

    # 800, not 400. The property under test — that the live loop holds no key and
    # cannot sign — is asserted above and is unaffected by tape length. What needs
    # the longer tape is the precondition beneath it: A20 holds the first mint
    # until sigma is mostly measurement rather than its prior, which takes three
    # hours, and 400 events span 2.83. Without a move, "signs nothing" would pass
    # vacuously on a loop that never did anything.
    events = make_events(800, swap_size=10**23)
    source = TapeChainSource(MemoryTape(events))
    warden = WardenLive(META, source, executor, capital_quote=1000.0)
    warden.run_until(events[-1].ts, start_ts=events[0].ts)
    assert executor.moves, "the loop did run and did decide to act"
