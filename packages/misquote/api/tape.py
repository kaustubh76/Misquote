"""What the indexed tape actually holds, which no static file can answer.

The artifacts record what a replay *found*. They cannot say what the database
looks like right now — whether the indexer is mid-backfill, whether the run it
quoted from is still the newest one, or whether the span it claims is contiguous.
That is a live question and this is the live answer.

## Coverage, not span

`max(ts) - min(ts)` is the number everyone reaches for and it is wrong: a tape
with one day at each end of a twenty-six day gap reports twenty-six days of
history and holds two. `indexer/store.py` distinguishes the two — `coverage()`
returns the ranges actually *read*, `covered_span()` the longest contiguous run
— and this endpoint reports both plus the holes between them.

An empty coverage list means "we do not know", not "nothing". A database written
before coverage was recorded holds real events and no record of what was fetched
to find them, and `store.coverage` says so in its own docstring. This reports
that as `known: false` rather than as zero blocks, because zero is a measurement
and this is the absence of one.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import Query

from misquote.api.errors import refuse
from misquote.api.locations import db_path
from misquote.chain.addresses import known_pools_on, pool_by_address
from misquote.indexer.store import (
    connect_readonly,
    coverage,
    covered_span,
    cursor_for,
    tape_summary,
)

#: The chain every recorded pool sits on. A parameter rather than a constant at
#: the call sites, so a second chain is a value and not a code change.
DEFAULT_CHAIN_ID = 56


def _holes(runs: list[tuple[int, int]]) -> list[dict[str, int]]:
    """The unread ranges *between* recorded runs.

    Not `store.gaps`, which answers "what is missing from this interval you
    named". The interval a reader cares about here is the one the tape itself
    claims, so it is derived from the runs rather than supplied — and on a tape
    with no coverage recorded the answer is an empty list of holes in an unknown
    range, which is why `known` is reported separately.
    """
    return [
        {"from_block": runs[i][1] + 1, "to_block": runs[i + 1][0] - 1}
        for i in range(len(runs) - 1)
        if runs[i + 1][0] > runs[i][1] + 1
    ]


def _read_one(conn: sqlite3.Connection, address: str) -> dict[str, Any]:
    runs = coverage(conn, address)
    span = covered_span(conn, address)
    return {
        "pool": address,
        "summary": tape_summary(conn, address),
        "cursor_block": cursor_for(conn, address),
        "coverage": {
            # Reported before the runs themselves: a reader who stops at the
            # first field must not come away with "no coverage" when the truth
            # is "this database never recorded any".
            "known": bool(runs),
            "runs": [{"from_block": lo, "to_block": hi} for lo, hi in runs],
            "longest_contiguous": (
                {"from_block": span[0], "to_block": span[1], "blocks": span[1] - span[0]}
                if span
                else None
            ),
            "holes": _holes(runs),
        },
    }


def tape(chain_id: int = Query(DEFAULT_CHAIN_ID)) -> dict[str, Any]:
    """Every verified pool on one chain, and what the tape holds for each."""
    pools = known_pools_on(chain_id)
    if not pools:
        raise refuse(
            404,
            error=f"no verified pool on chain {chain_id}",
            remedy="see `packages/misquote/chain/addresses.py::KNOWN_POOLS`",
            available=[str(DEFAULT_CHAIN_ID)],
            note=(
                "A pool this repository has not read is not indexed, deliberately: "
                "its fee_protocol decides what its swaps mean."
            ),
        )

    path = db_path()
    if not path.exists():
        raise refuse(
            503,
            error=f"no tape at {path}",
            remedy="make indexer POOL=0x...",
            note="Nothing has indexed anything yet. This is an absence, not a fault.",
        )

    conn = connect_readonly(path)
    try:
        return {
            "chain_id": chain_id,
            "database": str(path),
            "pools": [_read_one(conn, ref.address.lower()) for ref in pools],
        }
    finally:
        conn.close()


def tape_for_pool(address: str) -> dict[str, Any]:
    """One pool, refusing any address this repository has not verified."""
    try:
        ref = pool_by_address(address)
    except ValueError as error:
        raise refuse(
            404,
            error=str(error),
            remedy="index a verified pool, or record this one in chain/addresses.py",
            available=[p.address for p in known_pools_on(DEFAULT_CHAIN_ID)],
            note=(
                "Refusing is the point. A pool's fee_protocol, tick spacing and decimals "
                "decide what its swaps mean, and an unchecked address produces a complete, "
                "plausible, wrongly-denominated tape."
            ),
        ) from error

    path = db_path()
    if not path.exists():
        raise refuse(
            503,
            error=f"no tape at {path}",
            remedy=f"make indexer POOL={ref.address}",
            note="Nothing has indexed anything yet. This is an absence, not a fault.",
        )

    conn = connect_readonly(path)
    try:
        return {
            "chain_id": ref.chain_id,
            "database": str(path),
            **_read_one(conn, ref.address.lower()),
        }
    finally:
        conn.close()
