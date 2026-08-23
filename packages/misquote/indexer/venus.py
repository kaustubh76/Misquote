"""Decode and store Venus accruals: the rate tape.

The pool tape answers "what did price do". This answers "what did the lending
rate do", and it is a different shape of question in one respect that decides
the whole design.

## Event-derived, not block-sampled, and that was measured rather than chosen

The obvious way to build a rate tape is to poll `borrowIndex()` at a grid of
past blocks. Probed against the three free BSC endpoints that serve logs at all,
thirty days back:

| probe at block 111,419,176 | blxrbdn | 48.club | publicnode |
|---|---|---|---|
| `eth_getLogs`, 5,000 blocks | **served, 472 logs** | `header not found` | archive token required |
| `eth_call` at that block | **`-32000 not supported`** | — | archive token required |

Archive *logs* are served by exactly one of them; archive *state* by none. So
the design that reads naturally is the one no free endpoint will answer, and the
one that works is reading the accruals themselves — which is also the better
answer, because `AccrueInterest` carries every input the rate formula needs
inside its own data. See `estimators/apr.py`.

## One request covers every market

`eth_getLogs` accepts an address array. Measured: 483 logs across three markets
in a single 5,000-block request, 472 of them vUSDT's. So a thirty-day,
whole-whitelist rate tape costs the same 1,152 requests the pool backfill
already pays, not one budget per market.

## Coverage, and why it matters more here than for swaps

`venus_covered` records the ranges actually read, and the reason is the same one
`covered` exists for with one extra turn of the screw: for swaps, a quiet window
and an unfetched window are indistinguishable in the rows. For rates, they are
indistinguishable *and the quiet one is common* — vUSDC accrues roughly twice
per 5,000 blocks, so "no rows" is the normal state of a healthy market. Nothing
but coverage can separate that from a request nobody made.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from typing import Any

from ..chain.venus import (
    ACCRUE_INTEREST_SIGNATURE,
    NEW_RESERVE_FACTOR_SIGNATURE,
    MarketRef,
    market_by_address,
)
from ..estimators.apr import RateEvent


def topic0(signature: str) -> str:
    """keccak of an event signature, as an 0x-prefixed topic."""
    from eth_utils import keccak

    return "0x" + keccak(text=signature).hex()


ACCRUE_TOPIC = topic0(ACCRUE_INTEREST_SIGNATURE)
RESERVE_FACTOR_TOPIC = topic0(NEW_RESERVE_FACTOR_SIGNATURE)


def decode_accrual(log: dict[str, Any], ts: int) -> RateEvent:
    """One `AccrueInterest` log into a `RateEvent`.

    All four values are unindexed, so they are in `data` in declaration order:
    `cashPrior, interestAccumulated, borrowIndex, totalBorrows`.

    Refuses short data rather than padding it. A truncated log decoded leniently
    produces a plausible borrow index, and a borrow index that is wrong by a
    factor is a rate that is wrong by a factor with nothing downstream to notice.
    """
    data = log["data"]
    if isinstance(data, str):
        data = bytes.fromhex(data.removeprefix("0x"))
    if len(data) != 128:
        raise ValueError(
            f"AccrueInterest data is {len(data)} bytes, expected 128 (four uint256). "
            f"A short read decoded leniently becomes a wrong rate that looks right."
        )
    # The address must be one this repository has verified on chain. A market's
    # `underlying_decimals` and `v_decimals` differ by ten and decide what its
    # accumulator readings *mean*, so indexing an unverified address produces a
    # complete, plausible, wrongly-scaled rate — the same argument
    # `pool_by_address` makes about a pool's fee tier, and the same refusal.
    market = market_by_address(str(log["address"]))

    words = [int.from_bytes(data[i : i + 32], "big") for i in range(0, 128, 32)]
    return RateEvent(
        market=market.key,
        block=int(log["blockNumber"]),
        log_index=int(log["logIndex"]),
        ts=ts,
        cash_prior=words[0],
        interest_accumulated=words[1],
        borrow_index=words[2],
        total_borrows=words[3],
    )


def decode_reserve_factor(log: dict[str, Any], ts: int) -> tuple[str, int, int, int]:
    """`NewReserveFactor(oldMantissa, newMantissa)` -> the new value.

    Returns `(market, block, ts, new_mantissa)`. The old value is discarded: the
    series is what is stored, and the previous row already holds the old one.
    """
    data = log["data"]
    if isinstance(data, str):
        data = bytes.fromhex(data.removeprefix("0x"))
    if len(data) != 64:
        raise ValueError(f"NewReserveFactor data is {len(data)} bytes, expected 64")
    new = int.from_bytes(data[32:64], "big")
    return (str(log["address"]).lower(), int(log["blockNumber"]), ts, new)


def register_markets(conn: sqlite3.Connection, markets: Iterable[MarketRef]) -> None:
    """Record the verified markets, so the tape says which venue it describes."""
    conn.executemany(
        "INSERT OR REPLACE INTO venus_market "
        "(address, chain_id, symbol, underlying, underlying_decimals, v_decimals, comptroller) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                m.key,
                m.chain_id,
                m.symbol,
                m.underlying.lower(),
                m.underlying_decimals,
                m.v_decimals,
                m.comptroller.lower(),
            )
            for m in markets
        ],
    )


def write_accruals(
    conn: sqlite3.Connection,
    events: Sequence[RateEvent],
    txs: Sequence[str],
    *,
    markets: Sequence[str],
    covered: tuple[int, int] | None = None,
    reserve_factors: Sequence[tuple[str, int, int, int]] = (),
) -> int:
    """Insert accruals idempotently and record what was read, in one transaction.

    `covered` is the range the caller actually *read*, which is not the range
    the events span. Written in the same transaction as the rows, so a crash
    cannot leave coverage claiming more than the tape holds — the property
    `store.write_events` establishes and the reason this does not just append.
    """
    if len(events) != len(txs):
        raise ValueError("every accrual needs its transaction hash")

    # `store.connect` opens with `isolation_level=None`, so Python's implicit
    # transaction handling is off and `with conn:` commits nothing and rolls
    # back nothing. This function used to use `with conn:` and claimed
    # atomicity in its docstring while having none — a crash between the rows
    # and the coverage write would have left coverage claiming more than the
    # tape held, which is the one thing coverage exists to prevent.
    #
    # Explicit, exactly as `store.write_events` does it.
    conn.execute("BEGIN IMMEDIATE")
    try:
        before = _row_count(conn)

        conn.executemany(
            "INSERT OR IGNORE INTO accrue "
            "(market, block, log_index, tx, ts, cash_prior, interest_accumulated, "
            " borrow_index, total_borrows) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    e.market,
                    e.block,
                    e.log_index,
                    tx,
                    e.ts,
                    str(e.cash_prior),
                    str(e.interest_accumulated),
                    str(e.borrow_index),
                    str(e.total_borrows),
                )
                for e, tx in zip(events, txs, strict=True)
            ],
        )
        if reserve_factors:
            conn.executemany(
                "INSERT OR IGNORE INTO reserve_factor (market, block, ts, mantissa) "
                "VALUES (?, ?, ?, ?)",
                [(m, b, t, str(v)) for m, b, t, v in reserve_factors],
            )

        # Counted before coverage is touched. `_record_covered` merges by
        # DELETE-then-INSERT, so its bookkeeping shows up in a `total_changes`
        # delta — and the backfill printed that sum as "rows written". That is
        # how a run reported **161,030 rows written** against **159,956
        # accruals seen**: 1,074 of the difference was coverage churn, not data.
        # A row count that exceeds the rows the caller handed in is not a count.
        inserted = _row_count(conn) - before

        if covered is not None:
            for market in markets:
                _record_covered(conn, market, covered[0], covered[1])

        conn.execute("COMMIT")
        return inserted
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _row_count(conn: sqlite3.Connection) -> int:
    """Rows of *data* on the rate tape. Coverage is bookkeeping, not data."""
    accruals = conn.execute("SELECT COUNT(*) FROM accrue").fetchone()[0]
    factors = conn.execute("SELECT COUNT(*) FROM reserve_factor").fetchone()[0]
    return int(accruals) + int(factors)


def _record_covered(conn: sqlite3.Connection, market: str, lo: int, hi: int) -> None:
    """Merge [lo, hi] into a market's coverage. Caller holds the transaction.

    Adjacent counts as overlapping, exactly as in `store._record_covered` —
    otherwise every chunk boundary reads as a one-block hole and the gaps report
    becomes noise nobody can act on.
    """
    market = market.lower()
    touching = (market, lo - 1, hi + 1)
    for row in conn.execute(
        "SELECT from_block, to_block FROM venus_covered "
        "WHERE market = ? AND to_block >= ? AND from_block <= ?",
        touching,
    ).fetchall():
        lo = min(lo, int(row[0]))
        hi = max(hi, int(row[1]))
    conn.execute(
        "DELETE FROM venus_covered WHERE market = ? AND to_block >= ? AND from_block <= ?",
        touching,
    )
    conn.execute(
        "INSERT INTO venus_covered (market, from_block, to_block) VALUES (?, ?, ?)",
        (market, lo, hi),
    )


def coverage(conn: sqlite3.Connection, market: str) -> list[tuple[int, int]]:
    """Block ranges actually read for a market, merged and ordered.

    Empty means "we do not know", never "nothing was there". Same rule as the
    pool tape's, and the caller must not read it as an absence of history.
    """
    return [
        (int(a), int(b))
        for a, b in conn.execute(
            "SELECT from_block, to_block FROM venus_covered WHERE market = ? ORDER BY from_block",
            (market.lower(),),
        )
    ]


def covered_span(conn: sqlite3.Connection, market: str) -> tuple[int, int] | None:
    """The longest contiguous run of blocks actually read, or None."""
    runs = coverage(conn, market)
    if not runs:
        return None
    return max(runs, key=lambda r: r[1] - r[0])


def load_accruals(
    conn: sqlite3.Connection, market: str, *, limit: int | None = None
) -> list[RateEvent]:
    """The rate tape for one market, in chain order."""
    sql = (
        "SELECT market, block, log_index, ts, cash_prior, interest_accumulated, "
        "borrow_index, total_borrows FROM accrue WHERE market = ? "
        "ORDER BY block, log_index"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return [
        RateEvent(
            market=str(r[0]),
            block=int(r[1]),
            log_index=int(r[2]),
            ts=int(r[3]),
            cash_prior=int(r[4]),
            interest_accumulated=int(r[5]),
            borrow_index=int(r[6]),
            total_borrows=int(r[7]),
        )
        for r in conn.execute(sql, (market.lower(),))
    ]


def reserve_factor_at(conn: sqlite3.Connection, market: str, block: int) -> float | None:
    """The reserve factor in force at a block, or None if nothing was recorded.

    None rather than a default. Applying today's governance parameter to last
    month's history is the same class of error as reading a pool's protocol fee
    as a constant, which cost this repository a 1.515x overstatement (P-1).
    """
    row = conn.execute(
        "SELECT mantissa FROM reserve_factor WHERE market = ? AND block <= ? "
        "ORDER BY block DESC LIMIT 1",
        (market.lower(), block),
    ).fetchone()
    return int(row[0]) / 1e18 if row else None
