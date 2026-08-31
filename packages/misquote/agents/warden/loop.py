"""The live agent as a running process: four tasks, one kill switch.

`WardenLive.step()` is the decision; this is the thing that keeps calling it and
survives the ways real operation goes wrong. Two structural choices carry most
of the weight.

**The action queue holds one item and replaces on full.** A rebalance computed
ninety seconds ago at a price that has since moved is worse than no rebalance —
it spends gas to reach a range the market has already left. So a newer decision
displaces a pending one rather than queueing behind it. The queue is a
replacement buffer, not a backlog.

**Signing runs in a worker thread.** The receipt poller blocks for up to three
minutes, and `await`ing that on the event loop would leave the kill-file check
dead for the same three minutes — precisely the window in which an operator is
most likely to be reaching for it.

The kill switch is checked from two places for that reason: once a second here,
and again inside the signer immediately before broadcast. Redundant on purpose;
the second one is the load-bearing one because no code path can route around it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from misquote.agents.warden.live import WardenLive
from misquote.chain.signer import KillSwitchEngaged
from misquote.core.types import Action, Decision
from misquote.ops import metrics
from misquote.ops.alerts import notify
from misquote.ops.heartbeat import Heartbeat

DEFAULT_KILL_FILE = "ops/KILL"


@dataclass(slots=True)
class LoopStats:
    decisions: int = 0
    actions_queued: int = 0
    actions_replaced: int = 0
    actions_executed: int = 0
    actions_failed: int = 0
    stale_dropped: int = 0
    started_at: float = 0.0
    stopped_reason: str = ""
    journal_rows: int = 0


class ActionQueue:
    """A one-slot replacement buffer.

    `asyncio.Queue(maxsize=1)` blocks the producer when full, which is the wrong
    behaviour: the producer is the policy, and blocking it means the next
    decision is made late rather than the stale one being dropped.
    """

    __slots__ = ("_item", "_event", "replaced")

    def __init__(self) -> None:
        self._item: tuple[Decision, int] | None = None
        self._event = asyncio.Event()
        self.replaced = 0

    def offer(self, decision: Decision, at_ts: int) -> None:
        if self._item is not None:
            self.replaced += 1
        self._item = (decision, at_ts)
        self._event.set()

    async def take(self) -> tuple[Decision, int]:
        await self._event.wait()
        assert self._item is not None
        item, self._item = self._item, None
        self._event.clear()
        return item

    @property
    def pending(self) -> bool:
        return self._item is not None


class Journal:
    """Append-only JSONL. The tearsheet's only input, and submission evidence.

    Every decision is written, including the ones that did nothing, because a
    tearsheet that can only say "it did not rebalance" is far less useful than
    one that can say which gate held it back and by how much. `Decision.reasons`
    carries all four R-gates and the toxicity terms on every row.
    """

    __slots__ = ("path", "rows")

    def __init__(self, directory: str | Path | None = None, agent: str = "warden") -> None:
        base = Path(directory or os.environ.get("MISQUOTE_JOURNAL_DIR", "data/journal"))
        base.mkdir(parents=True, exist_ok=True)
        # One file per agent. The name was hardcoded to `warden.jsonl`, which was
        # correct while Warden was the only agent with an entrypoint and would
        # have made Grid and Sentinel append their decisions into Warden's
        # journal the moment they had one — a file the tearsheet reads as one
        # agent's record.
        self.path = base / f"{agent}.jsonl"
        self.rows = 0

    def write(self, record: dict[str, Any]) -> None:
        with self.path.open("a") as handle:
            handle.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
        self.rows += 1

    def decision(self, decision: Decision, at_ts: int, note: str = "") -> None:
        self.write(
            {
                "ts": at_ts,
                "action": decision.action.value,
                "lower": decision.target_lower,
                "upper": decision.target_upper,
                "centre": decision.center_tick,
                "half_width": decision.half_width_ticks,
                "r": decision.r,
                "delta_star": decision.delta_star,
                "reasons": dict(decision.reasons),
                "note": note,
            }
        )


@dataclass(slots=True)
class WardenLoop:
    """The running agent.

    There is **one** execution path: this loop decides on one task and performs
    on another, and `WardenLive.perform` is the only thing that acts. It used to
    hold a second `executor_call` of its own while `warden.step()` also executed,
    so every decision was acted on twice unless one of the two executors was
    inert — and the staleness check, the replace-on-full queue and the daily cap
    all governed the inert one. Matrix P-9.

    `perform` runs in a worker thread because a receipt poller blocks for up to
    three minutes, and awaiting that on the event loop would leave the kill-file
    check dead for the same three minutes.
    """

    warden: WardenLive
    kill_file: Path = field(default_factory=lambda: Path(DEFAULT_KILL_FILE))
    sample_interval_s: int = 5
    kill_poll_s: float = 1.0
    max_actions_per_day: int = 8
    journal: Journal = field(default_factory=Journal)
    stats: LoopStats = field(default_factory=LoopStats)
    #: Agent liveness, distinct from the job queue's worker heartbeat.
    #:
    #: Spec §10's acceptance list has said "heartbeat green" since the start and
    #: nothing implemented it. Beaten on every completed decision cycle rather
    #: than on a timer, because a timer proves the timer is running.
    agent: str = "warden"
    heartbeat: Heartbeat | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _queue: ActionQueue = field(default_factory=ActionQueue)

    async def run(self, *, max_seconds: float | None = None) -> LoopStats:
        """Start every task and stop them all together when any one says stop."""
        self.stats.started_at = time.monotonic()
        if self.heartbeat is None:
            self.heartbeat = Heartbeat(agent=self.agent, journal=self.journal)
        tasks = [
            asyncio.create_task(self._watch_kill_file(), name="kill"),
            asyncio.create_task(self._decide_forever(), name="policy"),
            asyncio.create_task(self._execute_forever(), name="executor"),
        ]
        if max_seconds is not None:
            tasks.append(asyncio.create_task(self._deadline(max_seconds), name="deadline"))

        try:
            await self._stop.wait()
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        return self.stats

    def stop(self, reason: str) -> None:
        if not self.stats.stopped_reason:
            self.stats.stopped_reason = reason
        self._stop.set()

    # --- the tasks ---------------------------------------------------------

    async def _watch_kill_file(self) -> None:
        """Poll for the operator's stop signal.

        Once a second rather than once a cycle, because the decision cadence is
        the agent's convenience and the kill switch is the operator's.
        """
        while not self._stop.is_set():
            if self.kill_file.exists():
                self.stop(f"kill file present: {self.kill_file}")
                self.journal.write({"event": "kill_switch", "path": str(self.kill_file)})
                metrics.metric("kill_switch").labels(agent=self.agent).set(1)
                notify(f"{self.agent}: kill file present at {self.kill_file}; loop stopping.")
                return
            await asyncio.sleep(self.kill_poll_s)

    async def _deadline(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        self.stop(f"reached the {seconds:.0f}s deadline")

    async def _decide_forever(self) -> None:
        """Sample, decide, journal, and offer any action to the executor."""
        while not self._stop.is_set():
            try:
                head = self.warden.source.head()
                # `decide`, not `step`. `step` also *performs* the decision, and
                # this task already queues it for the executor task below — so
                # calling `step` here acted on every decision twice, and the
                # queue's staleness check, its replace-on-full behaviour and the
                # daily cap all governed the second, inert copy. Matrix P-9.
                decision = self.warden.decide(head.ts)
            except Exception as error:  # noqa: BLE001 — a read failure is not fatal
                self.journal.write({"event": "decide_error", "error": str(error)[:300]})
                await asyncio.sleep(self.sample_interval_s)
                continue

            if decision is None:
                await asyncio.sleep(self.sample_interval_s)
                continue

            self.stats.decisions += 1
            self.journal.decision(decision, head.ts)
            # After the decision is journalled, never before it is made. An
            # exporter on the decision path can delay one; this cannot.
            if self.heartbeat is not None:
                self.heartbeat.beat()
            metrics.metric("decisions").labels(agent=self.agent).inc()

            if decision.action is not Action.HOLD:
                if self.stats.actions_executed >= self.max_actions_per_day:
                    self.journal.decision(decision, head.ts, note="daily action cap reached")
                else:
                    self._queue.offer(decision, head.ts)
                    self.stats.actions_queued += 1

            await asyncio.sleep(self.sample_interval_s)

    async def _execute_forever(self) -> None:
        """Take the newest pending action and perform it off the event loop."""
        while not self._stop.is_set():
            decision, at_ts = await self._queue.take()
            self.stats.actions_replaced = self._queue.replaced

            # If a newer decision arrived while this one waited, it already
            # replaced this one in the queue — but the one we hold may still be
            # stale relative to the head, so check before spending gas.
            head = self.warden.source.head()
            if head.ts - at_ts > self.sample_interval_s * 4:
                self.stats.stale_dropped += 1
                self.journal.decision(decision, at_ts, note=f"stale by {head.ts - at_ts}s, dropped")
                continue

            try:
                # In a thread: the receipt poller blocks for up to three minutes,
                # and awaiting that here would leave the kill check dead for the
                # same three minutes.
                #
                # `warden.perform` is now the *only* thing that acts. It applies
                # the position after the executor returns, so a raise here leaves
                # the engine's idea of the position equal to the chain's.
                await asyncio.to_thread(self.warden.perform, decision)
                self.stats.actions_executed += 1
                self.journal.decision(decision, at_ts, note="executed")
                metrics.metric("actions").labels(
                    agent=self.agent, kind=str(getattr(decision.action, "name", decision.action))
                ).inc()
                # Announced after it is journalled, so a hung HTTP request
                # cannot sit between the action and its durable record.
                notify(f"{self.agent}: executed {decision.action} at ts {at_ts}.")
            except KillSwitchEngaged as error:
                self.stats.actions_failed += 1
                self.journal.write({"event": "kill_switch_blocked_action", "error": str(error)})
                self.stop("kill switch engaged during execution")
                return
            except Exception as error:  # noqa: BLE001 — one failure is not fatal
                self.stats.actions_failed += 1
                self.journal.decision(decision, at_ts, note=f"failed: {str(error)[:200]}")
                metrics.metric("action_failures").labels(agent=self.agent).inc()
                notify(f"{self.agent}: action failed — {str(error)[:300]}")
