"""What a PancakeSwap v3 position would have earned — every cell, recorded.

    python scripts/simulate_report.py

Reads the indexed tape and the badges on disk. Writes no chain, the same split
`make vet` / `make vetting` and `make indexer` / `make pools` already follow.

## Why this exists when `pools.json` already does

`pools.json` answers *which width*, as three percentiles per rung. That is the
right shape for a ranking and the wrong shape for the question an LP arrives
with, which is **what would have happened to my capital**. The two differ in
every respect a person cares about: a percentile is not a window they can point
at, an APR is not an amount, and a rung is not a position drawn against the
prices it actually sat through.

Every one of those was already computed. `PoolAprEstimator.fit()` returns the
fee APR, the realized convexity cost, both in the quote token as well as
annualised, the depth the position sat in, the swap count, the hours, and now
the tick range it accounted over. `band_for_width` built twenty of those per
width and kept `net_apr` from each. This publishes the rest.

## One traversal, two surfaces

`window_fits` is the traversal, and both surfaces read it. The band `/venue`
draws is `percentile([f.net_apr for f in fits])`; the cells `/simulate` draws
are those same fits. So the ladder and the simulator cannot disagree — not
"agree today", cannot disagree, because there is one loop.

`tests/tearsheet/test_simulation.py` asserts that in the direction that would
actually break: the percentiles of the emitted cells against the band published
beside them.

## Money is per unit of capital, and the browser multiplies

Every `*_quote` field is emitted at `capital_quote = 1.0`. The page multiplies
by whatever capital a reader types, which is not interpolation: the estimator
takes `capital_quote` as a constructor argument and divides by it, so APR is
already per unit of capital and the money is already linear in it.

**Nothing between cells is interpolated.** A width that was not swept and a
window that did not clear the floor are absent, and the page refuses rather than
inventing the cell that would have sat there.

## Badged pools only

Same rule as `pools_report.py`, and A22's reason: the due-diligence layer
governs which pools an agent may enter, so it has to govern which pools a reader
is invited to imagine having capital in. Otherwise the layer is decoration.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from misquote.chain.addresses import BSC_MAINNET, PoolRef, known_pools_on
from misquote.core.tickmath import tick_to_price
from misquote.core.types import Event, Params, PoolMeta
from misquote.indexer import store
from misquote.tearsheet import provenance
from misquote.tearsheet.pools import (
    WIDTH_LADDER,
    WindowFit,
    band_for_width,
    best_width,
    window_fits,
)
from misquote.vetting.badge import cleared_to_provide

REPO = Path(__file__).resolve().parents[1]

#: How many points of the price path to publish per pool.
#:
#: The reader needs the shape of the price and where their range sat relative to
#: it. They do not need 252,923 ticks, which is 8MB of JSON to draw a line four
#: hundred pixels wide — more samples than the chart has pixels is a download
#: nobody can see the benefit of.
#:
#: Sampled evenly by *index* rather than by time, so a quiet stretch of tape
#: contributes as many points as a busy one and the line does not go straight
#: across the hours when nothing traded. Both ends are always kept.
PATH_POINTS = 240

#: The position sizes swept, in each pool's quote token.
#:
#: **Swept, not scaled.** The obvious design was one sweep at a capital of 1 and
#: a number box in the browser, on the reasoning that APR is per unit of capital
#: and money is therefore linear in it. Measured, it is not:
#:
#:     capital 1.0   ->  fees 0.008261755  apr 2.172275
#:     capital 10.0  ->  fees 0.082524533  apr 2.169830
#:
#: Ten times the capital earns 9.988 times the fees and a *lower* rate. That is
#: not error, it is the thing being measured — `LvrAccountant` prorates each
#: swap's fee by liquidity share, `L / (L_pool + L)`, so a larger position sits
#: in a larger denominator and dilutes itself. An LP putting in ten times as
#: much genuinely does earn slightly less than ten times as much.
#:
#: A browser multiplying by capital would have erased exactly that, in the
#: direction that flatters the bigger position, on the page whose whole purpose
#: is to be the quote that does not flatter. So every size a reader can pick is
#: a size the engine actually replayed.
#:
#: The ladder is small because A1 is small — see `A1_SHARE`. On the 0.25% pool a
#: +/-80 range can absorb 0.026 WBNB, so the bottom rung has to be far below one
#: BNB for that venue to have any answer at all.
CAPITAL_LADDER: tuple[float, ...] = (0.01, 0.1, 0.5, 2.0)

#: A1's ceiling, as a fraction of the venue a position may occupy.
#:
#: `Params.eps_liquidity_share`, imported rather than retyped. A replayed
#: position above this is refused rather than clamped — P-14's rule — because a
#: position that would have moved the price it is being paid at is not a
#: position that history can answer for.
A1_SHARE = Params().eps_liquidity_share


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


def price_path(
    swaps: list[Event], pool: PoolRef, points: int = PATH_POINTS
) -> list[dict[str, Any]]:
    """The pool's tick over the tape, thinned to something a chart can hold.

    `tick_to_price` is the display conversion the rest of the codebase uses, and
    it is decimal-adjusted — on these pools token0 is the stablecoin, so the
    price is BNB-per-dollar and below one. Both are published: the tick is what
    the range is expressed in and the price is what a reader recognises.
    """
    if not swaps:
        return []
    if len(swaps) <= points:
        chosen = swaps
    else:
        step = (len(swaps) - 1) / (points - 1)
        # Both ends kept: `round(step * (points - 1))` is the last index exactly.
        chosen = [swaps[round(step * i)] for i in range(points)]
    return [
        {
            "ts": e.ts,
            "tick": e.tick,
            "price": tick_to_price(e.tick, pool.dec0, pool.dec1),
        }
        for e in chosen
    ]


def cell(width_ticks: int, found: WindowFit) -> dict[str, Any]:
    """One window at one width, as the artifact carries it.

    Every field is the fit's own. Nothing is recomputed here — in particular not
    `net_apr`, which is a property on `PoolAprFit` precisely so it cannot drift
    from the two numbers it subtracts, and not the range, which the estimator
    now publishes for the same reason.
    """
    fit = found.fit
    return {
        "width_ticks": width_ticks,
        "window": found.window,
        # The size this cell was replayed at. Every money field below is that
        # size's own result, not a scaling of another size's.
        "capital_quote": fit.capital_quote,
        # A1's ceiling for this cell, computed where the depth was measured.
        # The page marks a size above it as refused, and a browser deriving the
        # product itself would be a second copy of the rule that decides whether
        # a quote may be published at all.
        "a1_ceiling_quote": fit.depth_quote * A1_SHARE,
        "start_ts": found.start_ts,
        "end_ts": found.end_ts,
        "hours": fit.hours,
        "swaps": fit.swaps,
        "fee_apr": fit.apr,
        "convexity_cost_apr": fit.convexity_cost_apr,
        "net_apr": fit.net_apr,
        "fees_quote": fit.fees_quote,
        "convexity_cost_quote": fit.convexity_cost_quote,
        "depth_quote": fit.depth_quote,
        "tick_lower": fit.tick_lower,
        "tick_upper": fit.tick_upper,
    }


def row_for(conn: Any, pool: PoolRef, *, capital: float) -> dict[str, Any]:
    """One pool: its tape, its price path, and every cell that cleared the floor."""
    meta = meta_for(pool)
    cleared, why = cleared_to_provide(pool.address)
    events = list(store.read_swaps(conn, pool.address))
    swaps = [e for e in events if e.kind == "swap"]

    row: dict[str, Any] = {
        "address": pool.address,
        "label": pool.label,
        "fee_pips": pool.fee_pips,
        "tick_spacing": pool.tick_spacing,
        "lp_fee_share": pool.lp_fee_share,
        "quote_symbol": pool.quote_symbol,
        "badged": cleared,
        "tape": {
            "swaps": len(swaps),
            "first_ts": swaps[0].ts if swaps else 0,
            "last_ts": swaps[-1].ts if swaps else 0,
        },
    }
    if not cleared:
        # No path either. A pool the vetting layer refused is one this page must
        # not draw at all, and half of it drawn is an invitation with the
        # refusal in small type.
        row["price_path"] = []
        row["cells"] = []
        row["bands"] = []
        row["best_width_ticks"] = None
        row["verdict"] = f"not published: {why}"
        return row

    row["price_path"] = price_path(swaps, pool)

    cells: list[dict[str, Any]] = []
    bands = []
    for width in WIDTH_LADDER:
        # The band is published at the reference capital, which is what makes it
        # the same band `/venue` draws. The other rungs of the ladder are cells
        # only — a band per size would be four answers to "which width", and the
        # question a band answers does not depend on how much you brought.
        found = window_fits(events, meta, width, capital_quote=capital)
        # Handed the same fits rather than sweeping again — see `band_for_width`.
        got = band_for_width(events, meta, width, capital_quote=capital, fits=found)
        bands.append(got)
        # **Cells only where the band cleared.**
        #
        # A fit is `is_ready` at MIN_SWAPS swaps inside its own window; a band is
        # `sufficient` at MIN_SAMPLES such windows. Those are different floors
        # and the gap between them is exactly TSLAx/USDT: 85 swaps across the
        # whole tape produce thirteen ready windows per width, which is thirteen
        # simulable positions on a pool `/venue` refuses to rank at all.
        #
        # Publishing them would let a reader set capital, press a rung and read
        # a number off a pool this site says it has no verdict on — the "we have
        # no idea" and "it pays nothing" collapse that every refusal here exists
        # to keep apart, arrived at by the back door. The band's floor is the
        # floor, and a width that did not clear it offers nothing to choose.
        if got.sufficient:
            cells.extend(cell(width, f) for f in found)
            for size in CAPITAL_LADDER:
                if size == capital:
                    continue
                cells.extend(
                    cell(width, f) for f in window_fits(events, meta, width, capital_quote=size)
                )

    leader, sentence = best_width(bands)
    row["cells"] = cells
    row["bands"] = [b.to_dict() for b in bands]
    row["best_width_ticks"] = leader.width_ticks if leader else None
    row["verdict"] = sentence
    return row


def build_payload(db: Path, *, capital: float) -> dict[str, Any]:
    conn = store.connect(db)
    try:
        rows = [row_for(conn, p, capital=capital) for p in known_pools_on(BSC_MAINNET)]
    finally:
        conn.close()

    simulable = [r for r in rows if r["cells"]]
    return {
        "chain_id": BSC_MAINNET,
        # The unit every money field below is in. Stated rather than assumed,
        # because the page multiplies by it and a reader has to be able to check
        # that the multiplication is a scaling of a measurement rather than a
        # measurement of its own.
        "capital_quote": capital,
        "width_ladder": list(WIDTH_LADDER),
        # Sizes, not a range. The page offers these and nothing between them.
        "capital_ladder": sorted({*CAPITAL_LADDER, capital}),
        "a1_share": A1_SHARE,
        "path_points": PATH_POINTS,
        "pools": rows,
        "summary": {
            "pools": len(rows),
            "badged": sum(1 for r in rows if r["badged"]),
            "simulable": len(simulable),
            "refused": len(rows) - len(simulable),
            "cells": sum(len(r["cells"]) for r in rows),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(REPO / "data" / "misquote.db"))
    parser.add_argument("--capital", type=float, default=1.0)
    parser.add_argument(
        "--out", default=str(REPO / "apps" / "web" / "public" / "artifacts" / "simulation.json")
    )
    args = parser.parse_args(argv)

    db = Path(args.db)
    if not db.exists():
        print(f"no tape at {db} — run `make indexer POOL=0x...`")
        return 1

    payload = build_payload(db, capital=args.capital)
    payload["build"] = provenance.build_stamp("python scripts/simulate_report.py", source="chain")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    s = payload["summary"]
    print(f"  pools      {s['pools']} ({s['badged']} badged)")
    print(f"  simulable  {s['simulable']}, refused {s['refused']}")
    print(f"  cells      {s['cells']}")
    for row in payload["pools"]:
        print(f"    {row['label']}: {len(row['cells'])} cells — {row['verdict']}")
    print(f"  -> {out}  ({out.stat().st_size / 1024:.0f}KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
