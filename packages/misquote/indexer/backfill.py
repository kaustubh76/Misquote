"""Fetch a pool's history into the tape, resumably.

    uv run python -m misquote.indexer.backfill --days 30
    uv run python -m misquote.indexer.backfill --days 30 --chain 97

Resumable and idempotent by construction: every chunk records the block range it
actually read, a re-run fetches only the ranges nobody has, and re-fetching an
already-ingested range inserts nothing. There is no "repair" mode because there
is nothing to repair — if a run dies, run it again.

Resuming from *coverage* rather than from the cursor is the whole point. The
cursor is a single high-water mark, so `--days 30` used to mean "carry on from
wherever anything last stopped" — and once the tail has run, that is the head.
A request for thirty days of history became a five-thousand-block poll, and the
flag was overridden rather than ignored loudly.
"""

from __future__ import annotations

import argparse
import sys
import time

from misquote.chain.addresses import pool_by_address, pool_for
from misquote.core.types import PoolMeta
from misquote.indexer import store
from misquote.indexer.reader import BscReader, RangeTooLarge, connect_all

# Measured at runtime rather than assumed. BSC has sped up repeatedly — it was
# 3s, then 0.75s, and as of Aug 2026 it is 0.45s, which changes a 30-day window
# from 864,000 blocks to 5.76 million. A stale constant here silently backfills
# the wrong span.
BSC_BLOCK_SECONDS_FALLBACK = 0.45

# The ceiling both log-serving endpoints declare, measured 16 Aug 2026: 5,000 is
# served, 10,000 is refused with "exceed maximum block range: 5000". 2,000 was
# never the measured limit — it was the number the previous endpoint set
# tolerated, and those endpoints turned out to serve no logs at all.
#
# The width is the scarce resource, not the wall clock. Requests are what the
# endpoints ration, so 5,000 crosses the same history for 40% of the requests.
# `RangeTooLarge` still halves this on refusal, and "exceed maximum block range"
# lands in that classifier rather than the transient one, so an endpoint with a
# tighter cap corrects itself instead of retrying into it.
DEFAULT_CHUNK = 5000
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
        #
        # `covered` records the range we actually read, which the events cannot
        # tell you: a chunk with no swaps in it and a chunk nobody fetched both
        # arrive here as an empty list. An interrupted backfill is precisely how
        # a tape acquires a hole, and this is what makes the hole nameable.
        inserted += store.write_events(
            conn,
            pool,
            events,
            advance_cursor_to=end,
            covered=(start, end),
            now_ts=int(time.time()),
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
    ap.add_argument("--to-block", type=int, default=None, help="stop here instead of at the head")
    ap.add_argument(
        "--pace",
        type=float,
        default=0.15,
        help="minimum seconds between RPC calls; free endpoints 403 without it",
    )
    args = ap.parse_args()

    # `--pool` used to change which address was *read* while the metadata written
    # to the database stayed the default pool's. The two verified pools differ in
    # fee tier, tick spacing and protocol fee, so that produced a complete tape
    # denominated wrongly — and the pool row it needed was never written at all,
    # so `write_events` fell back to chain_id 0. Resolving through the verified
    # table means an unknown address is refused rather than silently mis-labelled.
    try:
        ref = pool_by_address(args.pool) if args.pool else pool_for(args.chain)
    except ValueError as error:
        print(error)
        return 1
    pool = ref.address.lower()

    endpoints = connect_all(args.chain, on_reject=lambda url, why: print(f"  skip  {url} — {why}"))
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

    block_seconds = measure_block_seconds(reader, safe)
    target = min(safe, args.to_block) if args.to_block else safe
    window_start = max(0, args.from_block or (safe - blocks_for_days(args.days, block_seconds)))

    # Resume from what was actually **read**, not from the cursor.
    #
    # The cursor is one high-water mark maintained with max(), so `--days 30`
    # used to compute `start = cursor + 1` and silently become "carry on from
    # wherever anything last stopped". Once the tail has ever run, the cursor
    # sits at the head — and a request for thirty days of history quietly turned
    # into a five-thousand-block poll. The flag was not ignored loudly; it was
    # overridden.
    #
    # `gaps()` is the honest version of the same idea, and it cannot skip a range
    # nobody read. A database predating the coverage table reports no coverage,
    # so this re-fetches the window; that is idempotent by construction and
    # cheaper than trusting a claim we cannot substantiate.
    todo = store.gaps(conn, pool, window_start, target)

    print(f"pool   {ref.label}")
    print(f"       {pool}")
    print(f"chain  {args.chain}   head {head:,}   settled {safe:,} (head - {reader.confirmations})")
    print(f"       {len(endpoints)} endpoint(s), pacing {args.pace:.2f}s")
    print(f"       {block_seconds:.3f} s/block, measured")
    print(f"window {window_start:,} -> {target:,}  ({target - window_start + 1:,} blocks)")
    if not todo:
        print("       already read in full; nothing to do")
        return 0
    outstanding = sum(hi - lo + 1 for lo, hi in todo)
    print(f"unread {len(todo)} range(s), {outstanding:,} blocks")
    for lo, hi in todo[:6]:
        print(f"       {lo:,} -> {hi:,}  ({hi - lo + 1:,})")
    if len(todo) > 6:
        print(f"       ... and {len(todo) - 6} more")
    print()

    began = time.monotonic()
    result = {"inserted": 0, "seen": 0, "chunks": 0}
    try:
        for lo, hi in todo:
            part = backfill(conn, reader, pool, lo, hi, chunk=args.chunk)
            for key in result:
                result[key] += part[key]
    except Exception as error:  # noqa: BLE001 — the message matters more than the trace
        print(f"\nstopped after {time.monotonic() - began:.0f}s")
        print(f"  {type(error).__name__}: {str(error)[:120]}")
        print()
        for name, served, refused in reader.attribution():
            print(f"  {served:>4} served  {refused:>4} refused   {name}")
        print()
        print("  Progress is durable and recorded as coverage, so re-running resumes")
        print("  from the ranges that were never read rather than from a high-water")
        print("  mark. If every endpoint above refused everything, they may not serve")
        print("  eth_getLogs at all — see requirements-matrix P-11.")
        remaining = store.gaps(conn, pool, window_start, target)
        print(f"  {sum(hi - lo + 1 for lo, hi in remaining):,} blocks still unread")
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
            f"      blocks {summary['first_block']:,}..{summary['last_block']:,}  "
            f"({span_days:.1f}d between the two ends)"
        )
    # The span above is the distance between the first and last event and says
    # nothing about the middle. This is the number that means what it says.
    longest = summary["longest_covered"]
    if longest:
        read_days = (longest[1] - longest[0]) * block_seconds / 86400
        print(f"      longest unbroken run {longest[0]:,}..{longest[1]:,}  ({read_days:.1f}d read)")
    holes = store.gaps(conn, pool, window_start, target)
    if holes:
        print(
            f"      {len(holes)} gap(s) left in the window, {sum(h - l + 1 for l, h in holes):,} blocks"
        )
    print(f"      cursor at {summary['cursor']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
