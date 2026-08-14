"""The SQLite-backed tape: the frontier guard, enforced by SQL.

Lives here rather than in `replay/` because it holds a database connection, and
the layering test forbids the pure layers from touching one. That rule caught
this file being in the wrong place, which is what it is for.

The guarantee it provides is the second of the four layers that make look-ahead
structural. There is no list of events in memory — there is a connection and a
frontier, and the only accessor returns events in `(frontier, t]`:

    SELECT ... WHERE ts > :frontier AND ts <= :t ORDER BY block, log_index

**The guard is a SQL bind parameter.** Not an `if`, not a slice, not a filter
applied after the fact — a bound value the query cannot return rows past. There
is no `__getitem__`, no `__len__`, no `.events`, and no cursor to seek. Reading
ahead requires writing new SQL, which is a conspicuous act rather than an easy
mistake.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from misquote.core.errors import LookAheadError
from misquote.core.types import Event


class SqliteTape:
    """Events in time order, readable only up to a frontier that never rewinds."""

    __slots__ = ("_conn", "_pool", "_frontier", "_first_ts", "_last_ts", "_owns_conn")

    def __init__(self, db_path: str | Path | sqlite3.Connection, pool: str) -> None:
        if isinstance(db_path, sqlite3.Connection):
            self._conn = db_path
            self._owns_conn = False
        else:
            self._conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
            self._owns_conn = True
        self._conn.row_factory = sqlite3.Row
        self._pool = pool.lower()
        self._frontier = -1

        row = self._conn.execute(
            "SELECT min(ts) AS first_ts, max(ts) AS last_ts FROM swap WHERE pool = ?",
            (self._pool,),
        ).fetchone()
        self._first_ts = row["first_ts"]
        self._last_ts = row["last_ts"]

    # --- what a driver is allowed to know --------------------------------

    @property
    def first_ts(self) -> int | None:
        """When the tape starts. Bounds a replay window; reveals no event."""
        return self._first_ts

    @property
    def last_ts(self) -> int | None:
        return self._last_ts

    @property
    def frontier(self) -> int:
        return self._frontier

    # --- the only way to read ---------------------------------------------

    def advance_to(self, t: int) -> Sequence[Event]:
        """Events in `(frontier, t]`, in chain order, then move the frontier.

        This is the whole interface. There is deliberately no way to ask for
        "the next N events", "events near t", or "the last event before t" —
        each of those is a foothold for reading past the decision time.
        """
        if t < self._frontier:
            raise LookAheadError(
                f"tape frontier moved backwards: {self._frontier} -> {t}. "
                "A replay that restarts its clock produces a plausible decision "
                "sequence from a history that never happened."
            )

        rows = self._conn.execute(
            """SELECT * FROM swap
               WHERE pool = :pool AND ts > :frontier AND ts <= :t
               ORDER BY block, log_index""",
            {"pool": self._pool, "frontier": self._frontier, "t": t},
        ).fetchall()

        self._frontier = t
        return [_event(row) for row in rows]

    def close(self) -> None:
        if self._owns_conn:
            self._conn.close()

    def __enter__(self) -> SqliteTape:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _event(row: sqlite3.Row) -> Event:
    return Event(
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
