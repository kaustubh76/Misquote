"""Which PancakeSwap pool, at what width — the artifact the site reads.

    python scripts/pools_report.py

Reads the indexed tape and the badges on disk. Writes no chain: `make indexer`
does the reading, `make vet` does the badging, and this publishes what they left
behind — the same split as `make vet` / `make vetting`.

## What this answers that nothing else did

The challenge asks for a real benefit to PancakeSwap liquidity providers. The
question an LP has is not "is this agent good", it is *which pool, how wide, and
what would that have earned me*. Every existing surface here answers a question
about an **agent**: what Warden chose, what Grid chose, whether hiring beat doing
it yourself. None of them answers a question about a **pool**.

## Two rules this file inherits rather than invents

**Bands, never a leaderboard.** Every figure is a P25-P75 range over rolling
windows with its observation count, and two widths whose ranges overlap are
reported as not separated rather than ranked (A5). A sorted column of point
estimates is the exact shape of the thing this project is named against.

**Badged pools only.** A row is published only where `vetting/badges/<pool>.json`
says `safe_to_provide`. "They flag, we prove" already governs which pools an
agent may touch; it has to govern which pools we point a reader at, or the
due-diligence layer is decoration.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from misquote.chain.addresses import BSC_MAINNET, PoolRef, known_pools_on
from misquote.core.types import PoolMeta
from misquote.indexer import store
from misquote.tearsheet import provenance
from misquote.tearsheet.pools import (
    WIDTH_LADDER,
    best_width,
    demand_for_pool,
    ladder_for_pool,
    ladder_payload,
)
from misquote.vetting.badge import cleared_to_provide

REPO = Path(__file__).resolve().parents[1]


def meta_for(pool: PoolRef) -> PoolMeta:
    """The pool as the engine sees it. Every field read, none defaulted."""
    return PoolMeta(
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


def badge_clears(address: str) -> tuple[bool, str]:
    """Whether the vetting layer will let us point a reader at this pool.

    The rule itself lives in `vetting/badge.py` beside the badge it reads, since
    Router now gates on the same thing before it will enter a pool as a venue.
    Two copies of "an absent badge is a refusal" is one copy too many: the second
    is the one that drifts, and what it decides is which pools a reader's money
    is pointed at.
    """
    return cleared_to_provide(address)


def row_for(conn: Any, pool: PoolRef, *, capital: float) -> dict[str, Any]:
    """One pool: its demand, its width ladder, and what may be claimed."""
    meta = meta_for(pool)
    cleared, why = badge_clears(pool.address)
    events = list(store.read_swaps(conn, pool.address))

    row: dict[str, Any] = {
        "address": pool.address,
        "label": pool.label,
        "fee_pips": pool.fee_pips,
        "tick_spacing": pool.tick_spacing,
        "lp_fee_share": pool.lp_fee_share,
        "quote_symbol": pool.quote_symbol,
        "badged": cleared,
        "demand": demand_for_pool(events, meta).to_dict(),
    }
    if not cleared:
        row["ladder"] = []
        row["verdict"] = f"not published: {why}"
        return row

    bands = ladder_for_pool(events, meta, capital_quote=capital)
    leader, sentence = best_width(bands)
    # `ladder_payload` rather than `to_dict` per band: each row also carries the
    # widths it is not separated from, and that is a fact about a band's
    # siblings which no band can serialise on its own.
    row["ladder"] = ladder_payload(bands)
    row["best_width_ticks"] = leader.width_ticks if leader else None
    row["verdict"] = sentence
    return row


def build_payload(db: Path, *, capital: float) -> dict[str, Any]:
    conn = store.connect(db)
    try:
        rows = [row_for(conn, p, capital=capital) for p in known_pools_on(BSC_MAINNET)]
    finally:
        conn.close()

    published = [r for r in rows if r["badged"] and r["ladder"]]
    quotable = [r for r in published if any(b["sufficient"] for b in r["ladder"])]
    return {
        "chain_id": BSC_MAINNET,
        "capital_quote": capital,
        "width_ladder": list(WIDTH_LADDER),
        "pools": rows,
        "summary": {
            "pools": len(rows),
            "badged": sum(1 for r in rows if r["badged"]),
            "quotable": len(quotable),
            # Named rather than inferred from the difference: a reader should not
            # have to subtract two counts to discover that a pool was refused.
            "refused": len(rows) - len(quotable),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(REPO / "data" / "misquote.db"))
    parser.add_argument("--capital", type=float, default=1.0)
    parser.add_argument(
        "--out", default=str(REPO / "apps" / "web" / "public" / "artifacts" / "pools.json")
    )
    args = parser.parse_args(argv)

    db = Path(args.db)
    if not db.exists():
        print(f"no tape at {db} — run `make indexer POOL=0x...`")
        return 1

    payload = build_payload(db, capital=args.capital)
    payload["build"] = provenance.build_stamp("python scripts/pools_report.py", source="chain")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    s = payload["summary"]
    print(f"  pools      {s['pools']} ({s['badged']} badged)")
    print(f"  quotable   {s['quotable']}, refused {s['refused']}")
    for row in payload["pools"]:
        print(f"    {row['label']}: {row['verdict']}")
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
