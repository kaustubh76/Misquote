"""What a personal quote would cost to produce, and whether it is possible.

The quote itself is not here yet, and the reason is recorded rather than
implied: `replay/ranges.py::quote()` measures 4.6 hours for four agents on the
30-day tape and is process-global non-reentrant, so it belongs behind a job
queue and a worker process, not behind a request. What *is* here is everything
that can be answered immediately — which pools a wallet holds, whether each
pool's tape could support a quote at all, and what the run would consist of.

That is not a placeholder. The pre-flight is the half a reader most needs: a
refusal that arrives in a hundred milliseconds and names the missing tape beats
a spinner that resolves into the same refusal twenty minutes later.
"""

from __future__ import annotations

from typing import Any

from misquote.api import rpc
from misquote.api.errors import refuse
from misquote.api.locations import db_path
from misquote.api.preflight import assess
from misquote.api.wallet import _valid
from misquote.chain.addresses import known_pools_on, pool_by_address
from misquote.chain.positions import PositionReader
from misquote.indexer.store import connect

DEFAULT_CHAIN_ID = 56


def _conn() -> Any:
    path = db_path()
    if not path.exists():
        raise refuse(
            503,
            error=f"no tape at {path}",
            remedy="make indexer POOL=0x...",
            note="Nothing has indexed anything yet, so no quote is possible for any pool.",
        )
    return connect(path)


def quote_preflight(chain_id: int = DEFAULT_CHAIN_ID) -> dict[str, Any]:
    """Per verified pool: could the tape support a quote, and if not, why not."""
    pools = known_pools_on(chain_id)
    conn = _conn()
    try:
        assessed = [assess(conn, ref) for ref in pools]
    finally:
        conn.close()

    return {
        "chain_id": chain_id,
        "pools": assessed,
        "quotable": [a["pool"] for a in assessed if a["quotable"]],
        "note": (
            "Quotable means the tape could support a replay, not that one has run. "
            "A quote is a 4.6-hour job on the 30-day tape and is not served from a "
            "request; this is the check that runs before one is queued."
        ),
    }


def quote_eligibility(address: str, chain_id: int = DEFAULT_CHAIN_ID) -> dict[str, Any]:
    """One wallet: what it holds, and which of it could be quoted.

    Three states per position, and they are deliberately not collapsed into two.
    A position in a pool we never verified is unquotable for a reason no amount
    of indexing time fixes; a position in a verified pool whose tape is too thin
    is unquotable *today*. Reporting both as "no" would tell a reader to wait
    for something that is never coming.
    """
    if not _valid(address):
        raise refuse(
            400,
            error=f"{address!r} is not a 20-byte hex address",
            remedy="pass a 0x-prefixed 40-hex-digit address",
            note=(
                "Refused before the chain read: an unreachable address and an empty "
                "wallet return the same thing from an RPC, and a typo must not come "
                "back as 'you hold nothing'."
            ),
        )

    pools = known_pools_on(chain_id)
    w3 = rpc.connect(chain_id)
    found = PositionReader(w3, chain_id).read(address, pools)

    conn = _conn()
    try:
        by_pool = {ref.address.lower(): assess(conn, ref) for ref in pools}
    finally:
        conn.close()

    holdings = []
    for pool, positions in found.in_known_pools.items():
        check = by_pool.get(pool, {})
        try:
            label = pool_by_address(pool).label
        except ValueError:  # pragma: no cover — it came from known_pools_on
            label = ""
        holdings.append(
            {
                "pool": pool,
                "label": label,
                "positions": len(positions),
                "open_positions": sum(1 for p in positions if p.is_open),
                "quotable": check.get("quotable", False),
                "why_not": check.get("why_not", []),
                "plan": check.get("plan"),
            }
        )

    return {
        "owner": found.owner,
        "chain_id": chain_id,
        "read_at_block": found.read_at_block,
        "held": len(found.held),
        # Named separately from "not quotable". Indexing will never make these
        # quotable; a thin tape will.
        "in_unverified_pools": found.unknown_pool_count,
        "holdings": holdings,
        "note": (
            "A position in a pool this repository has not verified cannot be replayed "
            "at all — its fee tier and protocol cut decide what its swaps mean. A "
            "position in a verified pool with too little tape cannot be replayed yet. "
            "Those are different absences and are reported separately."
        ),
    }
