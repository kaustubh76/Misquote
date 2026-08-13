"""The SQLite tape: writing events so a quote can be reproduced from a file.

Everything here exists to make one sentence true: **re-running a backfill is a
no-op.** That means a crash needs no reconciliation, a rate-limited run can be
resumed by repeating it, and a judge can rebuild the tape from scratch and get
the same file.

Two mechanisms carry that. Inserts are `INSERT OR IGNORE` against a primary key
of `(tx, log_index)`, which is the chain's own natural identity for a log. And
the cursor advances *inside the same transaction* as the rows it covers, so
there is no window in which the cursor claims progress the rows do not support.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path

from misquote.core.types import Event, PoolMeta

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open the tape, creating it if absent."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)  # explicit transactions
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


def register_pool(
    conn: sqlite3.Connection, meta: PoolMeta, created_block: int | None = None
) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO pool
           (address, chain_id, token0, token1, dec0, dec1, fee_pips, tick_spacing, created_block)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            meta.address.lower(),
            meta.chain_id,
            meta.token0.lower(),
            meta.token1.lower(),
            meta.dec0,
            meta.dec1,
            meta.fee_pips,
            meta.tick_spacing,
            created_block,
        ),
    )


def _swap_row(pool: str, e: Event) -> tuple:
    # Every uint256 goes in as TEXT. SQLite's INTEGER is signed 64-bit and would
    # truncate sqrtPriceX96 and liquidity without complaining.
    return (
        pool,
        e.block,
        e.log_index,
        e.tx,
        e.ts,
        None,
        None,
        str(e.amount0),
        str(e.amount1),
        str(e.sqrt_price_x96),
        str(e.liquidity),
        e.tick,
        str(e.protocol_fee0),
        str(e.protocol_fee1),
    )


def _position_row(pool: str, e: Event) -> tuple:
    return (
        pool,
        e.block,
        e.log_index,
        e.tx,
        e.ts,
        None,
        e.tick_lower,
        e.tick_upper,
        str(e.liquidity),
        str(e.amount0),
        str(e.amount1),
    )


def write_events(
    conn: sqlite3.Connection,
    pool: str,
    events: Sequence[Event],
    *,
    advance_cursor_to: int | None = None,
    now_ts: int = 0,
) -> int:
    """Insert a batch and optionally advance the cursor, atomically.

    Returns the number of rows actually inserted, which is zero on a re-run —
    the property the whole design turns on, and one the caller can assert.
    """
    pool = pool.lower()
    swaps = [_swap_row(pool, e) for e in events if e.kind == "swap"]
    mints = [_position_row(pool, e) for e in events if e.kind == "mint"]
    burns = [_position_row(pool, e) for e in events if e.kind == "burn"]
    blocks = {(e.block, e.ts) for e in events}

    conn.execute("BEGIN IMMEDIATE")
    try:
        before = _total_rows(conn, pool)

        if blocks:
            chain_id = conn.execute(
                "SELECT chain_id FROM pool WHERE address = ?", (pool,)
            ).fetchone()
            chain = chain_id["chain_id"] if chain_id else 0
            conn.executemany(
                "INSERT OR IGNORE INTO block (chain_id, number, ts) VALUES (?, ?, ?)",
                [(chain, number, ts) for number, ts in blocks],
            )

        if swaps:
            conn.executemany(
                """INSERT OR IGNORE INTO swap
                   (pool, block, log_index, tx, ts, sender, recipient,
                    amount0, amount1, sqrt_price_x96, liquidity, tick,
                    protocol_fee0, protocol_fee1)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                swaps,
            )
        for table, rows in (("mint", mints), ("burn", burns)):
            if rows:
                conn.executemany(
                    f"""INSERT OR IGNORE INTO {table}
                        (pool, block, log_index, tx, ts, owner,
                         tick_lower, tick_upper, amount, amount0, amount1)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    rows,
                )

        if advance_cursor_to is not None:
            # Inside the same transaction as the rows it covers. Advancing it
            # separately leaves a window where a crash produces a cursor that
            # claims progress the tape cannot support — a gap that nothing
            # downstream would ever detect.
            conn.execute(
                """INSERT INTO cursor (pool, last_block, updated_ts) VALUES (?, ?, ?)
                   ON CONFLICT(pool) DO UPDATE SET
                     last_block = max(cursor.last_block, excluded.last_block),
                     updated_ts = excluded.updated_ts""",
                (pool, advance_cursor_to, now_ts),
            )

        inserted = _total_rows(conn, pool) - before
        conn.execute("COMMIT")
        return inserted
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _total_rows(conn: sqlite3.Connection, pool: str) -> int:
    return sum(
        conn.execute(f"SELECT count(*) FROM {table} WHERE pool = ?", (pool,)).fetchone()[0]
        for table in ("swap", "mint", "burn")
    )


def cursor_for(conn: sqlite3.Connection, pool: str) -> int | None:
    row = conn.execute("SELECT last_block FROM cursor WHERE pool = ?", (pool.lower(),)).fetchone()
    return int(row["last_block"]) if row else None


def rewind(conn: sqlite3.Connection, pool: str, to_block: int) -> int:
    """Drop everything after `to_block`. Reorg recovery, and it is cheap.

    BSC reorgs are shallow, so on startup it costs almost nothing to discard the
    tail and re-fetch it. Trying to detect *which* events changed would be more
    code and more ways to be subtly wrong.
    """
    pool = pool.lower()
    conn.execute("BEGIN IMMEDIATE")
    try:
        removed = 0
        for table in ("swap", "mint", "burn"):
            removed += conn.execute(
                f"DELETE FROM {table} WHERE pool = ? AND block > ?", (pool, to_block)
            ).rowcount
        conn.execute(
            "UPDATE cursor SET last_block = min(last_block, ?) WHERE pool = ?", (to_block, pool)
        )
        conn.execute("COMMIT")
        return removed
    except Exception:
        conn.execute("ROLLBACK")
        raise


def read_swaps(
    conn: sqlite3.Connection, pool: str, *, since_ts: int = 0, until_ts: int | None = None
) -> Iterable[Event]:
    """Swaps in chain order. The tape's read path, used by κ and by replay."""
    clause = "SELECT * FROM swap WHERE pool = ? AND ts >= ?"
    params: list[object] = [pool.lower(), since_ts]
    if until_ts is not None:
        clause += " AND ts <= ?"
        params.append(until_ts)
    clause += " ORDER BY block, log_index"

    for row in conn.execute(clause, params):
        yield Event(
            block=row["block"],
            log_index=row["log_index"],
            ts=row["ts"],
            kind="swap",
            tx=row["tx"],
            amount0=int(row["amount0"]),
            amount1=int(row["amount1"]),
            sqrt_price_x96=int(row["sqrt_price_x96"]),
            liquidity=int(row["liquidity"]),
            tick=row["tick"],
            protocol_fee0=int(row["protocol_fee0"]),
            protocol_fee1=int(row["protocol_fee1"]),
        )


def tape_summary(conn: sqlite3.Connection, pool: str) -> dict[str, object]:
    """What the tape actually contains, for the run log and the tearsheet."""
    pool = pool.lower()
    row = conn.execute(
        """SELECT count(*) AS n, min(ts) AS first_ts, max(ts) AS last_ts,
                  min(block) AS first_block, max(block) AS last_block
           FROM swap WHERE pool = ?""",
        (pool,),
    ).fetchone()
    return {
        "swaps": row["n"],
        "mints": conn.execute("SELECT count(*) FROM mint WHERE pool = ?", (pool,)).fetchone()[0],
        "burns": conn.execute("SELECT count(*) FROM burn WHERE pool = ?", (pool,)).fetchone()[0],
        "first_ts": row["first_ts"],
        "last_ts": row["last_ts"],
        "first_block": row["first_block"],
        "last_block": row["last_block"],
        "cursor": cursor_for(conn, pool),
    }
