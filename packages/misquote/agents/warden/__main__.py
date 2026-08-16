"""Run the Warden against a live chain, without the ability to spend.

    uv run python -m misquote.agents.warden --seconds 600
    uv run python -m misquote.agents.warden --chain 97 --seconds 86400
    make warden

This is the entrypoint `docs`' own not-built ledger names, and the reason it
matters is narrow and concrete: `agents/warden/loop.py` implements the loop, the
action queue, the journal and the kill file, and nothing wired it to a command.
So **every journal in this repo has zero rows**, every tearsheet reports its
provenance journal empty, and every verdict on every card is computed from a
replay because there has never been a run to compute one from.

## It does not sign, and that is a wiring choice rather than a missing capability

`chain/executor.py` defines `ChainExecutor`, which mints, adjusts and closes a
position through the NonfungiblePositionManager, and nine tests exercise it
against a forked BSC with real transactions. It exists and it works.

This entrypoint deliberately does not use it. It wires `RecordingExecutor`
(below) instead, so the actions the policy decides on are journalled rather than
broadcast.

There is still no `--live` flag, but the reason has changed: the gate is no
longer missing code, it is a funded wallet on a chain that matters and a
go/no-go that is green rather than NOT YET. A flag would invite someone to cross
that gate with a keystroke. What runs here is the real policy, on real chain
state, at the real cadence, writing a real journal.

That is worth having on its own. It is the difference between "the loop is tested"
and "the loop has run", and it produces the journal every card's provenance block
currently has to say is empty.

## What it is honest about

- **The sampling cadence is not the spec's.** Section 8 sets Δs = 5s. A source
  that asked the chain for logs every five seconds issues twelve `eth_getLogs` a
  minute and is refused within the first minute — measured, see
  `chain/live_source.py`. The chain is polled once a minute by default and the
  policy still ticks at Δs against the last observed state. Matrix item D-9.
- **A quiet run and a broken run look the same from the decisions alone**, so the
  source's poll counters and failure counts go into the journal at the end.
- **The kill file wins.** `ops/KILL` stops the loop within a second, checked on
  its own task rather than once per decision cycle.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from misquote.agents.warden.live import SimulatedExecutor, WardenLive
from misquote.agents.warden.loop import DEFAULT_KILL_FILE, Journal, WardenLoop
from misquote.chain.addresses import pool_for
from misquote.chain.live_source import DEFAULT_POLL_SECONDS, LiveChainSource
from misquote.core.types import Decision, Params, PoolMeta
from misquote.indexer.reader import BscReader, connect_all


class RecordingExecutor:
    """The loop's action path, in a build with nothing that can transact.

    `WardenLive` already keeps the position through its own `SimulatedExecutor`;
    this is the loop's separate chain-action hook, and here it only records. It
    exists as a named class rather than a lambda so that the day a real executor
    lands, the thing it replaces is obvious.
    """

    __slots__ = ("actions", "journal")

    def __init__(self, journal: Journal) -> None:
        self.actions: list[tuple[str, int]] = []
        self.journal = journal

    def __call__(self, decision: Decision, at_ts: int) -> None:
        self.actions.append((str(decision.action), at_ts))
        self.journal.write(
            {
                "event": "action_not_broadcast",
                "action": str(decision.action),
                "at_ts": at_ts,
                "target_lower": decision.target_lower,
                "target_upper": decision.target_upper,
                "why": (
                    "this entrypoint wires RecordingExecutor rather than "
                    "ChainExecutor, so the decision was journalled and not "
                    "performed"
                ),
            }
        )


def build_source(chain_id: int, poll_seconds: float) -> tuple[LiveChainSource, PoolMeta]:
    pool = pool_for(chain_id)
    meta = PoolMeta(
        address=pool.address,
        chain_id=pool.chain_id,
        token0=pool.token0,
        token1=pool.token1,
        dec0=pool.dec0,
        dec1=pool.dec1,
        fee_pips=pool.fee_pips,
        tick_spacing=pool.tick_spacing,
        fee_protocol=pool.fee_protocol,
    )
    endpoints = connect_all(chain_id)
    if not endpoints:
        raise SystemExit(f"no reachable RPC for chain {chain_id}")
    reader = BscReader(endpoints, pace_seconds=0.2)
    return LiveChainSource(meta, reader, poll_seconds=poll_seconds), meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", type=int, default=56, choices=(56, 97))
    parser.add_argument("--seconds", type=float, default=600.0, help="0 runs until killed")
    parser.add_argument("--interval", type=int, default=5, help="decision cadence, spec Δs")
    parser.add_argument(
        "--poll", type=float, default=DEFAULT_POLL_SECONDS, help="seconds between chain polls"
    )
    parser.add_argument("--capital", type=float, default=1000.0)
    parser.add_argument("--journal-dir", default=os.environ.get("MISQUOTE_JOURNAL_DIR"))
    args = parser.parse_args(argv)

    source, meta = build_source(args.chain, args.poll)
    journal = Journal(args.journal_dir)
    executor = RecordingExecutor(journal)

    warden = WardenLive(
        meta,
        source,
        SimulatedExecutor(),
        params=Params(sample_interval_s=args.interval),
        capital_quote=args.capital,
    )
    loop = WardenLoop(
        warden=warden,
        executor_call=executor,
        kill_file=Path(DEFAULT_KILL_FILE),
        sample_interval_s=args.interval,
        journal=journal,
    )

    print(f"  pool     {meta.address}  (chain {meta.chain_id})")
    print(f"  cadence  decide every {args.interval}s, poll the chain every {args.poll:.0f}s")
    print(f"  journal  {journal.path}")
    print("  signing  RECORDED, not broadcast — this entrypoint wires RecordingExecutor")
    print(f"  stop     touch {DEFAULT_KILL_FILE}, or wait for the deadline\n")

    try:
        source.prime()
    except Exception as error:  # noqa: BLE001 — report it rather than a traceback
        print(f"  could not read the pool: {type(error).__name__}: {str(error)[:160]}")
        return 1

    head = source.head()
    print(f"  primed at block {head.block:,}, tick {source.slot0()[1]}, ts {head.ts}")

    journal.write(
        {
            "event": "run_start",
            "pool": meta.address,
            "chain_id": meta.chain_id,
            "sample_interval_s": args.interval,
            "poll_seconds": args.poll,
            "can_sign": False,
            "head_block": head.block,
            "head_ts": head.ts,
        }
    )

    started = time.monotonic()
    deadline = args.seconds if args.seconds > 0 else None
    stats = asyncio.run(loop.run(max_seconds=deadline))
    elapsed = time.monotonic() - started

    summary = {
        "event": "run_end",
        "elapsed_s": round(elapsed, 1),
        "decisions": stats.decisions,
        "actions_queued": stats.actions_queued,
        "actions_recorded": len(executor.actions),
        "actions_failed": stats.actions_failed,
        "stale_dropped": stats.stale_dropped,
        "stopped_reason": stats.stopped_reason,
        **source.status(),
    }
    journal.write(summary)

    print(f"\n  ran {elapsed:.0f}s — {stats.stopped_reason or 'finished'}")
    print(f"  decisions        {stats.decisions:,}")
    print(f"  actions recorded {len(executor.actions)} (none broadcast)")
    print(
        f"  chain polls      {source.polls} ok, {source.poll_failures} refused, "
        f"{source.events_seen} events"
    )
    print(f"\n{json.dumps(summary, indent=2, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
