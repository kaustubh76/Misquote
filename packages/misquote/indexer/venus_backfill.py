"""Backfill the Venus rate tape.

    uv run python -m misquote.indexer.venus_backfill --days 30
    make venus

Reuses `BscReader` wholesale — the endpoint rotation, the pacing, the
`RangeTooLarge` handling and the block-timestamp cache all apply unchanged,
because a rate log is fetched exactly the way a swap log is. What differs is one
line of the filter and one table at the end.

## Every market in one request

`eth_getLogs` takes an address array, so the whole whitelist is one round trip
per chunk rather than one per market. Measured on a 5,000-block chunk: 483 logs
across three markets, 472 of them vUSDT's. A thirty-day whitelist tape therefore
costs the same ~1,152 requests the pool backfill pays, and free endpoints serve
them — the same measurement the Makefile records for `make indexer`.

## Both topics in one filter

`AccrueInterest` is the rate; `NewReserveFactor` is a governance parameter that
changes what a rate *means*. Fetching them together means the tape cannot hold a
window of accruals whose reserve factor was never captured, which is the rate
tape's version of P-1 — a protocol cut read as a constant, overstating LP
earnings by 1.515x.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time

from web3 import Web3

from ..chain.venus import markets_on
from . import store, venus
from .backfill import measure_block_seconds
from .reader import BscReader, RangeTooLarge, connect_all

DEFAULT_CHUNK = 5000
MIN_CHUNK = 50


def raw_rate_logs(
    reader: BscReader, markets: list[str], from_block: int, to_block: int
) -> list[dict]:
    """Both rate topics, every market, one request."""
    if to_block < from_block:
        return []
    params = {
        "address": [Web3.to_checksum_address(m) for m in markets],
        "fromBlock": from_block,
        "toBlock": to_block,
        "topics": [[venus.ACCRUE_TOPIC, venus.RESERVE_FACTOR_TOPIC]],
    }
    return list(reader._call(lambda w3: w3.eth.get_logs(params)))


def _timestamp_of(reader: BscReader, log: dict) -> int:
    """The log's own timestamp when the endpoint sends one, else the block's.

    Same fallback `reader.events` makes, and it matters for the same reason: at
    BSC's 0.45s block time, re-fetching every distinct block turns a chunk into
    hundreds of round trips to recover something the log already carried.
    """
    raw = log.get("blockTimestamp")
    if raw is not None:
        return int(raw, 16) if isinstance(raw, str) else int(raw)
    return reader.block_timestamp(int(log["blockNumber"]))


def backfill(
    conn: sqlite3.Connection,
    reader: BscReader,
    markets: list[str],
    from_block: int,
    to_block: int,
    *,
    chunk: int = DEFAULT_CHUNK,
    progress: bool = True,
) -> dict[str, int]:
    """Walk the range in chunks, writing accruals and coverage as it goes."""
    inserted = seen = chunks = 0
    start = from_block
    size = chunk

    while start <= to_block:
        end = min(start + size - 1, to_block)
        try:
            logs = raw_rate_logs(reader, markets, start, end)
        except RangeTooLarge:
            if size <= MIN_CHUNK:
                raise
            size = max(MIN_CHUNK, size // 2)
            if progress:
                print(f"  range refused, narrowing chunk to {size} blocks")
            continue

        accruals: list = []
        txs: list[str] = []
        factors: list[tuple[str, int, int, int]] = []
        for log in logs:
            ts = _timestamp_of(reader, log)
            topic = log["topics"][0]
            topic = topic.hex() if hasattr(topic, "hex") else str(topic)
            if not topic.startswith("0x"):
                topic = "0x" + topic
            tx = log["transactionHash"]
            tx = tx.hex() if hasattr(tx, "hex") else str(tx)
            if topic == venus.ACCRUE_TOPIC:
                accruals.append(venus.decode_accrual(log, ts))
                txs.append(tx if tx.startswith("0x") else "0x" + tx)
            elif topic == venus.RESERVE_FACTOR_TOPIC:
                factors.append(venus.decode_reserve_factor(log, ts))

        # Rows and coverage in one transaction, so a crash cannot leave coverage
        # claiming more than the tape holds.
        inserted += venus.write_accruals(
            conn,
            accruals,
            txs,
            markets=markets,
            covered=(start, end),
            reserve_factors=factors,
        )
        seen += len(accruals)
        chunks += 1

        if progress and chunks % 25 == 0:
            done = end - from_block + 1
            span = to_block - from_block + 1
            print(f"  {100 * done / span:5.1f}%  block {end:,}  {seen:,} accruals")

        start = end + 1
        if size < chunk:
            size = min(chunk, size * 2)

    return {"inserted": inserted, "seen": seen, "chunks": chunks}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chain", type=int, default=56, choices=(56,))
    ap.add_argument("--db", default="data/misquote.db")
    ap.add_argument("--days", type=float, default=30.0)
    ap.add_argument("--from-block", type=int, default=0)
    ap.add_argument("--to-block", type=int, default=0)
    ap.add_argument("--chunk", type=int, default=DEFAULT_CHUNK)
    ap.add_argument("--pace", type=float, default=0.2)
    args = ap.parse_args()

    refs = markets_on(args.chain)
    if not refs:
        print(f"no verified Venus markets for chain {args.chain}.")
        print("Run scripts/verify_venus.py first — this refuses to index what it has not checked.")
        return 1

    endpoints = connect_all(args.chain, on_reject=lambda url, why: print(f"  skip  {url} — {why}"))
    reader = BscReader(endpoints, pace_seconds=args.pace)

    conn = store.connect(args.db)
    with conn:
        venus.register_markets(conn, refs)

    head = reader.head_block()
    safe = reader.safe_head()
    # BSC's block time, measured rather than assumed — the same quantity whose
    # documented value is what makes Venus's own quoted APR wrong by 6.67x
    # (P-22).
    #
    # This comment sat above a hardcoded `0.45` for a whole round. It claimed a
    # measurement that never happened, in the module whose entire finding is
    # that a documented block time was wrong by more than sixfold. The function
    # it should have called was already imported from the sibling backfill, and
    # `BSC_BLOCK_SECONDS_FALLBACK` is where the literal honestly lives.
    block_seconds = measure_block_seconds(reader, head)
    target = min(safe, args.to_block) if args.to_block else safe
    window = int(args.days * 86_400 / block_seconds)
    start = args.from_block or max(0, target - window)

    addresses = [m.key for m in refs]
    print(f"chain  {args.chain}   head {head:,}   settled {safe:,}")
    print(f"markets {', '.join(m.symbol for m in refs)}  ({len(addresses)} in one request)")
    print(f"range  {start:,} -> {target:,}  ({target - start + 1:,} blocks, ~{args.days} days)")

    began = time.time()
    result = backfill(conn, reader, addresses, start, target, chunk=args.chunk)
    took = time.time() - began

    print(
        f"\ndone   {result['seen']:,} accruals seen, {result['inserted']:,} rows written, "
        f"{result['chunks']:,} chunks in {took / 60:.1f} min"
    )
    for market in refs:
        span = venus.covered_span(conn, market.key)
        rows = len(venus.load_accruals(conn, market.key))
        if span:
            print(f"  {market.symbol:8s} {rows:>7,} accruals   longest run {span[0]:,}-{span[1]:,}")
        else:
            print(f"  {market.symbol:8s} {rows:>7,} accruals   no coverage recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
