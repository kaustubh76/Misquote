"""Fetch a pool's history into the tape, resumably.

    uv run python -m misquote.indexer.backfill --days 30
    uv run python -m misquote.indexer.backfill --days 30 --chain 97

Resumable and idempotent by construction: the cursor records the last settled
block, a re-run starts from there, and re-fetching an already-ingested range
inserts nothing. There is no "repair" mode because there is nothing to repair —
if a run dies, run it again.
"""

from __future__ import annotations

import argparse
import sys
import time

from misquote.chain.addresses import pool_for
from misquote.core.types import PoolMeta
from misquote.indexer import store
from misquote.indexer.reader import BscReader, RangeTooLarge, connect_all

# Measured at runtime rather than assumed. BSC has sped up repeatedly — it was
# 3s, then 0.75s, and as of Aug 2026 it is 0.45s, which changes a 30-day window
# from 864,000 blocks to 5.76 million. A stale constant here silently backfills
# the wrong span.
BSC_BLOCK_SECONDS_FALLBACK = 0.45
DEFAULT_CHUNK = 2000
MIN_CHUNK = 50


def measure_block_seconds(reader: BscReader, head: int, sample: int = 100_000) -> float:
    """Seconds per block, measured over a real span."""
    try:
        span = min(sample, head)
        return (reader.block_timestamp(head) - reader.block_timestamp(head - span)) / span
    except Exception:  # noqa: BLE001 — a fallback is better than refusing to run
        return BSC_BLOCK_SECONDS_FALLBACK


def blocks_for_days(days: float, block_seconds: float) -> int:
    return int(days * 24 * 3600 / block_seconds)


def backfill(
    conn,
    reader: BscReader,
    pool: str,
    from_block: int,
    to_block: int,
    *,
    chunk: int = DEFAULT_CHUNK,
    progress: bool = True,
) -> dict[str, int]:
    """Walk `[from_block, to_block]` in chunks, writing as it goes.

    The chunk size adapts. Public endpoints disagree about how many blocks or
    logs they will return, and they say so in prose rather than in a status code,
    so a refusal halves the chunk and retries rather than aborting the run.
    """
    inserted = total_events = chunks = 0
    start = from_block
    size = chunk

    while start <= to_block:
        end = min(start + size - 1, to_block)
        try:
            events = reader.events(pool, start, end)
        except RangeTooLarge:
            if size <= MIN_CHUNK:
                raise
            size = max(MIN_CHUNK, size // 2)
            if progress:
                print(f"  range refused, narrowing chunk to {size} blocks")
            continue

        # The cursor advances with the rows, in one transaction. A crash between
        # them would otherwise leave a gap nothing downstream could detect.
        inserted += store.write_events(
            conn, pool, events, advance_cursor_to=end, now_ts=int(time.time())
        )
        total_events += len(events)
        chunks += 1

        if progress and chunks % 25 == 0:
            done = end - from_block + 1
            span = to_block - from_block + 1
            print(f"  {100 * done / span:5.1f}%  block {end:,}  {total_events:,} events")

        start = end + 1
        if size < chunk:  # recover after a narrowing
            size = min(chunk, size * 2)

    return {"inserted": inserted, "seen": total_events, "chunks": chunks}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chain", type=int, default=56, choices=(56, 97))
    ap.add_argument("--days", type=float, default=30.0)
    ap.add_argument("--pool", default=None, help="defaults to the verified target pool")
    ap.add_argument("--db", default="data/misquote.db")
    ap.add_argument("--chunk", type=int, default=DEFAULT_CHUNK)
    ap.add_argument("--from-block", type=int, default=None)
    ap.add_argument(
        "--pace",
        type=float,
        default=0.15,
        help="minimum seconds between RPC calls; free endpoints 403 without it",
    )
    args = ap.parse_args()

    ref = pool_for(args.chain)
    pool = (args.pool or ref.address).lower()

    endpoints = connect_all(args.chain)
    reader = BscReader(endpoints, pace_seconds=args.pace)
    head = reader.head_block()
    safe = reader.safe_head()

    conn = store.connect(args.db)
    store.register_pool(
        conn,
        PoolMeta(
            address=ref.address,
            chain_id=ref.chain_id,
            token0=ref.token0,
            token1=ref.token1,
            dec0=ref.dec0,
            dec1=ref.dec1,
            fee_pips=ref.fee_pips,
            tick_spacing=ref.tick_spacing,
            fee_protocol=ref.fee_protocol,
        ),
    )

    # Reorg hygiene: discard anything past the settled head before extending.
    # Cheap on BSC, and much simpler than working out which events changed.
    dropped = store.rewind(conn, pool, safe)
    if dropped:
        print(f"dropped {dropped} rows above the settled head (reorg protection)")

    resume = store.cursor_for(conn, pool)
    block_seconds = measure_block_seconds(reader, safe)
    start = args.from_block or (
        resume + 1 if resume is not None else safe - blocks_for_days(args.days, block_seconds)
    )
    start = max(0, start)

    print(f"pool   {ref.label}")
    print(f"       {pool}")
    print(f"chain  {args.chain}   head {head:,}   settled {safe:,} (head - {reader.confirmations})")
    print(f"       {len(endpoints)} endpoint(s), pacing {args.pace:.2f}s")
    print(f"       {block_seconds:.3f} s/block, measured")
    print(f"range  {start:,} -> {safe:,}  ({safe - start + 1:,} blocks, ~{args.days:g}d)")
    if resume is not None:
        print(f"resume from cursor at {resume:,}")
    print()

    began = time.monotonic()
    try:
        result = backfill(conn, reader, pool, start, safe, chunk=args.chunk)
    except Exception as error:  # noqa: BLE001 — the message matters more than the trace
        done = store.cursor_for(conn, pool)
        print(f"\nstopped at block {done:,} after {time.monotonic() - began:.0f}s")
        print(f"  {type(error).__name__}: {str(error)[:120]}")
        print()
        print("  Free BSC endpoints will not sustain a multi-day backfill: they cap")
        print("  eth_getLogs ranges, refuse sustained request rates with 403 and")
        print("  -32005, and all of them do it. Rotation and pacing extend the run;")
        print("  they do not make it finish.")
        print()
        print("  Progress is durable — the cursor advanced with the rows — so re-running")
        print("  resumes from where this stopped. To finish in one pass, set BSC_RPC_URL")
        print("  to a keyed endpoint (NodeReal, QuickNode, Ankr) and run again.")
        return 1
    elapsed = time.monotonic() - began

    summary = store.tape_summary(conn, pool)
    print(
        f"\ndone in {elapsed:.0f}s — {result['chunks']:,} chunks, {result['inserted']:,} new rows"
    )
    print(
        f"tape: {summary['swaps']:,} swaps, {summary['mints']:,} mints, {summary['burns']:,} burns"
    )
    if summary["first_ts"]:
        span_days = (summary["last_ts"] - summary["first_ts"]) / 86400
        print(
            f"      blocks {summary['first_block']:,}..{summary['last_block']:,}  ({span_days:.1f}d)"
        )
    print(f"      cursor at {summary['cursor']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
