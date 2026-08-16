"""The running agent: does it stop when told, and does it refuse stale work.

These are the properties an operator depends on at three in the morning, so they
are tested rather than reasoned about. The loop runs against a tape-backed
source with a fake executor, so a full run takes milliseconds and signs nothing.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from _helpers import META, make_events

from misquote.agents.warden.live import WardenLive
from misquote.agents.warden.loop import ActionQueue, Journal, WardenLoop
from misquote.chain.signer import KillSwitchEngaged
from misquote.chain.source import TapeChainSource
from misquote.core.types import Action, Decision
from misquote.replay.tape import MemoryTape


def decision(action: Action = Action.MINT, centre: int = -64180) -> Decision:
    return Decision(
        action=action,
        target_lower=centre - 40,
        target_upper=centre + 40,
        center_tick=centre,
        half_width_ticks=40,
        r=-6.4,
        delta_star=0.004,
        reasons=(("R1", 1.0), ("R2", 1.0)),
    )


class SpyExecutor:
    """An `Executor` that reports every action and can be made to misbehave.

    The loop no longer takes an `executor_call` of its own — there is one
    execution path and it goes through `WardenLive.perform`, which calls *this*.
    So a test that wants to watch, block or break execution does it here, at the
    seam production actually uses (matrix P-9).
    """

    def __init__(self, on_act=None) -> None:
        self.on_act = on_act or (lambda _kind, _ts: None)
        self.moves: list[tuple[str, int]] = []

    def mint(self, lower, upper, liquidity, ts):
        self.moves.append(("mint", ts))
        self.on_act("mint", ts)
        return None

    def rebalance(self, current, lower, upper, liquidity, ts):
        self.moves.append(("rebalance", ts))
        self.on_act("rebalance", ts)
        return current.token_id

    def pull(self, current, ts):
        self.moves.append(("pull", ts))
        self.on_act("pull", ts)


def build_loop(tmp_path, *, events=None, executor=None, **kwargs) -> WardenLoop:
    events = events if events is not None else make_events(400, swap_size=10**23)
    source = TapeChainSource(MemoryTape(events))
    source.advance(events[0].ts)
    warden = WardenLive(META, source, executor or SpyExecutor(), capital_quote=1000.0)
    # Prime the market `perform` sizes against. Tests below seed `_queue`
    # directly, bypassing the policy, and `perform` refuses to act without a
    # market rather than inventing one.
    warden.decide(events[0].ts)
    return WardenLoop(
        warden=warden,
        kill_file=tmp_path / "KILL",
        journal=Journal(tmp_path / "journal"),
        sample_interval_s=kwargs.pop("sample_interval_s", 1),
        kill_poll_s=kwargs.pop("kill_poll_s", 0.01),
        **kwargs,
    )


# --- the one-slot queue ----------------------------------------------------


@pytest.mark.asyncio
async def test_a_newer_decision_replaces_a_pending_one() -> None:
    """A rebalance computed ninety seconds ago at a price that has since moved
    is worse than no rebalance. The queue is a replacement buffer, not a
    backlog."""
    queue = ActionQueue()
    queue.offer(decision(centre=-64180), 100)
    queue.offer(decision(centre=-64100), 105)
    queue.offer(decision(centre=-64000), 110)

    assert queue.replaced == 2
    taken, at_ts = await queue.take()
    assert taken.center_tick == -64000, "the newest decision must win"
    assert at_ts == 110
    assert not queue.pending


@pytest.mark.asyncio
async def test_offering_never_blocks_the_policy() -> None:
    """`asyncio.Queue(maxsize=1)` blocks the producer when full, which makes the
    *next* decision late rather than dropping the stale one. That is backwards:
    the policy is the thing that must keep running."""
    queue = ActionQueue()
    for i in range(1000):
        queue.offer(decision(), i)  # synchronous, no await, cannot block
    assert queue.replaced == 999
    assert queue.pending


# --- stopping --------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_kill_file_stops_the_loop(tmp_path) -> None:
    loop = build_loop(tmp_path)
    loop.kill_file.write_text("stop")

    stats = await asyncio.wait_for(loop.run(max_seconds=5), timeout=10)
    assert "kill file" in stats.stopped_reason
    assert stats.actions_executed == 0


@pytest.mark.asyncio
async def test_a_kill_file_appearing_mid_run_stops_it(tmp_path) -> None:
    """The switch is for the running agent, not just the starting one."""
    loop = build_loop(tmp_path)

    async def arm() -> None:
        await asyncio.sleep(0.05)
        loop.kill_file.write_text("stop")

    stats, _ = await asyncio.gather(asyncio.wait_for(loop.run(max_seconds=5), timeout=10), arm())
    assert "kill file" in stats.stopped_reason


@pytest.mark.asyncio
async def test_the_kill_check_keeps_running_while_the_executor_blocks(tmp_path) -> None:
    """The reason signing runs in a thread.

    The receipt poller blocks for up to three minutes. If that were awaited on
    the event loop, the kill-file check would be dead for the same three minutes
    — exactly the window in which an operator is reaching for it.
    """
    import time as _time

    entered = asyncio.Event()

    def slow_executor(_kind, _ts) -> None:
        entered.set()
        _time.sleep(1.0)  # blocking, like a real receipt poll

    loop = build_loop(tmp_path, executor=SpyExecutor(slow_executor))
    loop._queue.offer(decision(), 10**12)  # not stale, so it actually executes

    async def arm() -> None:
        await asyncio.wait_for(entered.wait(), timeout=5)
        loop.kill_file.write_text("stop")

    started = _time.monotonic()
    stats, _ = await asyncio.gather(asyncio.wait_for(loop.run(max_seconds=10), timeout=15), arm())
    elapsed = _time.monotonic() - started

    assert "kill file" in stats.stopped_reason
    assert elapsed < 3.0, "the kill check was blocked by the executor"


# --- staleness and caps ----------------------------------------------------


@pytest.mark.asyncio
async def test_a_stale_action_is_dropped_rather_than_executed(tmp_path) -> None:
    """Gas spent reaching a range the market has already left is gas wasted."""
    executed = []
    loop = build_loop(
        tmp_path,
        executor=SpyExecutor(lambda kind, ts: executed.append((kind, ts))),
        sample_interval_s=1,
    )
    loop._queue.offer(decision(), 0)  # timestamp far behind the tape's head

    stats = await asyncio.wait_for(loop.run(max_seconds=1.0), timeout=10)
    assert stats.stale_dropped >= 1
    assert not executed


@pytest.mark.asyncio
async def test_the_daily_action_cap_is_enforced(tmp_path) -> None:
    """Spec section 8's gas discipline: eight moves a day, not eight per hour."""
    loop = build_loop(tmp_path, max_actions_per_day=2)
    loop.stats.actions_executed = 2
    loop._queue.offer(decision(), 0)

    stats = await asyncio.wait_for(loop.run(max_seconds=0.6), timeout=10)
    assert stats.actions_executed == 2


@pytest.mark.asyncio
async def test_a_failing_executor_does_not_kill_the_loop(tmp_path) -> None:
    """One reverted transaction is a bad minute, not a reason to stop trading.

    A kill switch is different, and is handled separately below.
    """

    def explode(_kind, _ts):
        raise RuntimeError("rpc had a bad day")

    loop = build_loop(tmp_path, executor=SpyExecutor(explode))
    loop._queue.offer(decision(), 10**12)  # not stale

    stats = await asyncio.wait_for(loop.run(max_seconds=0.8), timeout=10)
    assert stats.actions_failed >= 1
    assert "kill" not in stats.stopped_reason


@pytest.mark.asyncio
async def test_a_kill_switch_raised_by_the_signer_stops_everything(tmp_path) -> None:
    """The signer checks the file too, immediately before broadcast. If it fires
    there, the loop must stop rather than retry into a closed door."""

    def refuse(_kind, _ts):
        raise KillSwitchEngaged("ops/KILL exists")

    loop = build_loop(tmp_path, executor=SpyExecutor(refuse))
    loop._queue.offer(decision(), 10**12)

    stats = await asyncio.wait_for(loop.run(max_seconds=3), timeout=10)
    assert "kill switch" in stats.stopped_reason


# --- the journal -----------------------------------------------------------


@pytest.mark.asyncio
async def test_every_decision_is_journalled_including_the_holds(tmp_path) -> None:
    """A tearsheet that can only say "it did not rebalance" is much less useful
    than one that can say which gate held it back and by how much."""
    loop = build_loop(tmp_path, sample_interval_s=1)
    await asyncio.wait_for(loop.run(max_seconds=1.5), timeout=10)

    rows = [json.loads(line) for line in loop.journal.path.read_text().splitlines()]
    assert rows, "the journal is the tearsheet's only input"

    decisions = [r for r in rows if "action" in r]
    assert decisions
    assert all("reasons" in r and r["reasons"] for r in decisions)
    assert any(r["action"] == "hold" for r in decisions), "holds must be recorded too"


@pytest.mark.asyncio
async def test_the_journal_is_append_only_across_runs(tmp_path) -> None:
    """It is submission evidence. A run that truncated it would erase the record
    the tearsheet is built from."""
    first = build_loop(tmp_path, sample_interval_s=1)
    await asyncio.wait_for(first.run(max_seconds=1.0), timeout=10)
    after_first = len(first.journal.path.read_text().splitlines())

    second = build_loop(tmp_path, sample_interval_s=1)
    await asyncio.wait_for(second.run(max_seconds=1.0), timeout=10)
    after_second = len(second.journal.path.read_text().splitlines())

    assert after_second > after_first


@pytest.mark.asyncio
async def test_a_read_failure_is_logged_and_survived(tmp_path, monkeypatch) -> None:
    """Public endpoints fail. An agent that dies on the first 429 is not an
    agent that runs for twenty-four hours unattended."""
    loop = build_loop(tmp_path, sample_interval_s=1)

    # `WardenLive` uses __slots__, so the method is patched on the class rather
    # than the instance — which is also closer to how a real RPC failure arrives:
    # from underneath, not from a field someone reassigned.
    calls = {"n": 0}
    original = WardenLive.decide

    def flaky(self, t):
        calls["n"] += 1
        if calls["n"] == 1:  # fail once, then recover within the run window
            raise RuntimeError("429 Too Many Requests")
        return original(self, t)

    monkeypatch.setattr(WardenLive, "decide", flaky)
    stats = await asyncio.wait_for(loop.run(max_seconds=3.0), timeout=15)

    rows = [json.loads(line) for line in loop.journal.path.read_text().splitlines()]
    assert any(r.get("event") == "decide_error" for r in rows)
    assert stats.decisions > 0, "it recovered and kept deciding"
