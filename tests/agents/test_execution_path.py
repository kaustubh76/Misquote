"""One execution path, and a position that never gets ahead of the chain.

Matrix **P-9**. The live loop used to act on every decision twice — `step()`
executed it, then the loop queued it for a second executor — and only stayed
harmless because one of the two was always inert. Worse, a failure on the queue
path was journalled and the engine was *not* rolled back, because `step()` had
already committed the position.

These tests pin the three properties that fix rests on:

1. a failed action leaves the engine's position exactly where it was;
2. a recentre that closes but cannot reopen leaves the engine **flat**, matching
   a chain where the old range no longer exists;
3. one decision produces one action, not two.

The third is the one that would silently come back. Nothing about a double
execution looks wrong in a journal — it looks like an agent that traded twice.
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest
from _helpers import META, make_events

from misquote.agents.warden.live import SimulatedExecutor, WardenLive
from misquote.agents.warden.loop import Journal, WardenLoop
from misquote.chain.source import TapeChainSource
from misquote.core.errors import PositionClosedNotReopened
from misquote.core.types import Action, PositionState
from misquote.replay.tape import MemoryTape


class Boom(RuntimeError):
    """An ordinary transaction failure: reverted, dropped, or a bad nonce."""


class FailingExecutor:
    """Acts on nothing and raises, so the caller's bookkeeping is what is tested."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error or Boom("reverted")
        self.calls = 0

    def mint(self, lower, upper, liquidity, ts):
        self.calls += 1
        raise self.error

    def rebalance(self, current, lower, upper, liquidity, ts):
        self.calls += 1
        raise self.error

    def pull(self, current, ts):
        self.calls += 1
        raise self.error


def _warden(events, executor):
    source = TapeChainSource(MemoryTape(events))
    source.advance(events[0].ts)
    return WardenLive(META, source, executor, capital_quote=1000.0)


def _open_position(warden, events) -> PositionState:
    """Drive the agent until it holds something, using a working executor."""
    warden.run_until(events[len(events) // 3].ts, start_ts=events[0].ts)
    assert warden.engine.position.in_market, "the agent never opened a position"
    return warden.engine.position


# --- 1. a failure must not move the engine ---------------------------------


def test_a_failed_action_leaves_the_position_exactly_where_it_was() -> None:
    """The agent's idea of what it holds must never get ahead of the chain.

    `perform` executes and *then* applies. If the executor raises, the engine is
    never told — and that property comes from call order alone, so it is worth a
    test that would notice the two lines being swapped.
    """
    events = make_events(900, swap_size=10**23)
    warden = _warden(events, SimulatedExecutor())
    before = _open_position(warden, events)

    warden.executor = FailingExecutor()
    decision = warden.decide(events[-1].ts)
    assert decision is not None

    with pytest.raises(Boom):
        warden.perform(decision)

    after = warden.engine.position
    assert (after.lower, after.upper, after.liquidity, after.token_id) == (
        before.lower,
        before.upper,
        before.liquidity,
        before.token_id,
    ), "the engine moved on a transaction that never landed"


def test_a_failed_mint_from_flat_leaves_the_agent_flat() -> None:
    events = make_events(400, swap_size=10**23)
    warden = _warden(events, FailingExecutor())
    assert not warden.engine.position.in_market

    decision = warden.decide(events[0].ts)
    if decision is not None and decision.action is not Action.HOLD:
        with pytest.raises(Boom):
            warden.perform(decision)
    assert not warden.engine.position.in_market


# --- 2. the half-failed recentre -------------------------------------------


def test_a_recentre_that_closes_but_cannot_reopen_leaves_the_engine_flat() -> None:
    """The one failure a recentre has that is not "nothing happened".

    Closing comes first so a crash between the legs leaves the wallet solvent.
    But on chain the old range is *gone*, and an engine that still believes it
    holds it would spend every later decision reasoning about a position that
    does not exist — and would never re-mint, because it thinks it is already in.
    """
    events = make_events(900, swap_size=10**23)
    warden = _warden(events, SimulatedExecutor())
    held = _open_position(warden, events)
    assert held.token_id is None or held.token_id >= 0

    warden.executor = FailingExecutor(PositionClosedNotReopened(held.token_id, Boom("no room")))
    decision = warden.decide(events[-1].ts)
    assert decision is not None

    # Force the recentre branch. The engine is in market, so `_execute` routes a
    # non-HOLD, non-PULL action to `rebalance` — which is where the exception
    # comes from. `dataclasses.replace` because `Decision` is a frozen dataclass.
    moving = dataclasses.replace(
        decision,
        action=Action.RECENTER,
        target_lower=held.lower - 100,
        target_upper=held.upper - 100,
    )
    with pytest.raises(PositionClosedNotReopened):
        warden.perform(moving)

    assert not warden.engine.position.in_market, (
        "the position is gone on chain but the engine still holds it — every "
        "later decision would be about a range that does not exist"
    )


def test_the_exception_carries_the_dead_token_id() -> None:
    """So the journal records which NFT was burned, not merely that one was."""
    error = PositionClosedNotReopened(4242, Boom("mint reverted"))
    assert error.token_id == 4242
    assert "4242" in str(error)
    assert "mint reverted" in str(error)


# --- 3. one decision, one action -------------------------------------------


@pytest.mark.asyncio
async def test_one_queued_decision_produces_exactly_one_action(tmp_path) -> None:
    """The defect itself, asserted deterministically.

    Before P-9 was fixed there were two executors: `step()` acted through
    `warden.executor` and the loop acted again through its own `executor_call`.
    Nothing about that looks wrong in a journal — it looks like an agent that
    traded twice.

    Seeding the queue rather than waiting for the policy to reach a mint is
    deliberate. A timing-dependent version of this test passed as `0 == 0` when
    the agent happened to hold for the whole run, which proves nothing at all.
    """
    events = make_events(600, swap_size=10**23)
    executor = SimulatedExecutor()
    source = TapeChainSource(MemoryTape(events))
    source.advance(events[0].ts)
    warden = WardenLive(META, source, executor, capital_quote=1000.0)

    # Prime the market `perform` sizes against, and take a real decision to
    # reshape into an actionable one — so every field is one the policy produced.
    base = warden.decide(events[0].ts)
    assert base is not None
    action = dataclasses.replace(
        base,
        action=Action.MINT,
        target_lower=base.center_tick - 200,
        target_upper=base.center_tick + 200,
    )

    loop = WardenLoop(
        warden=warden,
        kill_file=tmp_path / "KILL",
        journal=Journal(tmp_path / "journal"),
        sample_interval_s=1,
        kill_poll_s=0.01,
    )
    # `at_ts` at the tape head, so the staleness check does not drop it.
    loop._queue.offer(action, warden.source.head().ts)

    stats = await asyncio.wait_for(loop.run(max_seconds=1.5), timeout=15)

    assert stats.actions_executed == 1, f"expected one execution, got {stats.actions_executed}"
    assert stats.stale_dropped == 0
    assert len(executor.moves) == 1, (
        f"{len(executor.moves)} executor calls for one queued decision — the "
        "decision path is acting as well as the executor path"
    )
    assert executor.moves[0][0] == "mint"
    assert warden.engine.position.in_market, "the action was executed but never applied"


@pytest.mark.asyncio
async def test_deciding_does_not_act(tmp_path) -> None:
    """`decide` is observation only. If it acted, the loop's staleness check,
    its replace-on-full queue and the daily cap would all govern a copy of the
    decision that had already happened."""
    events = make_events(600, swap_size=10**23)
    executor = SimulatedExecutor()
    source = TapeChainSource(MemoryTape(events))
    source.advance(events[0].ts)
    warden = WardenLive(META, source, executor, capital_quote=1000.0)

    for i in range(40):
        warden.decide(events[0].ts + i)

    assert warden.decisions, "nothing was decided"
    assert executor.moves == [], "decide() acted on something"
    assert not warden.engine.position.in_market, "decide() changed the position"


def test_perform_without_a_decision_refuses_rather_than_guessing() -> None:
    """There is no market to size against, and inventing one would size a real
    transaction against a price nobody read."""
    from misquote.core.errors import AssumptionViolated

    events = make_events(200)
    decided = _warden(events, SimulatedExecutor())
    decision = decided.decide(events[0].ts)
    assert decision is not None

    # A different agent, which has never observed anything.
    fresh = _warden(events, SimulatedExecutor())
    with pytest.raises(AssumptionViolated, match="no market"):
        fresh.perform(decision)
