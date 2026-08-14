"""Showcase Mode: replay a policy on real history and write what a card shows.

    uv run python scripts/showcase.py                    # from the indexed tape
    uv run python scripts/showcase.py --synthetic 4000   # without a tape yet

This is the pipeline the whole product turns on. It walks a recorded tape through
the replay engine, prices what the strategy would have earned net of adverse
selection and every cost, and emits a JSON artifact the web app reads without
importing Python.

**Every position it prices is counterfactual.** Matrix item D-2: the wallet this
project is built by has a real BSC trading record, but it contains no liquidity
positions at all — so a "here is what I earned" card would be a fabrication. What
this produces instead is "here is what this policy would have done over this
history, and here is every assumption that went into saying so", badged as such
on the artifact and on the card. Assumption A6.

The badge is not a disclaimer bolted on at the end. It is a field on the
artifact, asserted by a test, and the web app renders it as prominently as the
number it qualifies.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from misquote.agents.grid.policy import GridParams, decide_grid
from misquote.chain.addresses import TARGET_POOL
from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import Event, PoolMeta
from misquote.replay.driver import CostModel, ReplayDriver
from misquote.replay.ranges import quote as compute_quote
from misquote.replay.tape import MemoryTape
from misquote.tearsheet.generate import build

REPO = Path(__file__).resolve().parents[1]

COUNTERFACTUAL_BADGE = "COUNTERFACTUAL — this position was not held"
COUNTERFACTUAL_NOTE = (
    "This is a replay, not a record. The policy was run over this pool's real "
    "trade history; no capital was deployed and no position existed. Published "
    "as assumption A6."
)

META = PoolMeta(
    address=TARGET_POOL.address,
    chain_id=TARGET_POOL.chain_id,
    token0=TARGET_POOL.token0,
    token1=TARGET_POOL.token1,
    dec0=TARGET_POOL.dec0,
    dec1=TARGET_POOL.dec1,
    fee_pips=TARGET_POOL.fee_pips,
    tick_spacing=TARGET_POOL.tick_spacing,
    fee_protocol=TARGET_POOL.fee_protocol,
)


def synthetic_events(count: int, *, seed: int = 7, swap_size: int = 10**23) -> list[Event]:
    """A stand-in tape, clearly labelled as one.

    Used only when no real tape exists yet. Every artifact built from it carries
    `source: "synthetic"`, so a card produced this way can never be mistaken for
    one produced from chain data — which is the failure this whole project is
    named after.
    """
    rng = random.Random(seed)
    events: list[Event] = []
    tick, ts = -64180, 1_700_000_000
    fee = swap_size * META.fee_pips // 10**6
    for i in range(count):
        tick += rng.choice((-9, -4, 0, 4, 9))
        ts += rng.randint(5, 45)
        events.append(
            Event(
                block=1_000_000 + i,
                log_index=0,
                ts=ts,
                kind="swap",
                tx=f"0x{i:064x}",
                amount0=swap_size,
                amount1=-swap_size,
                sqrt_price_x96=get_sqrt_ratio_at_tick(tick),
                liquidity=1_275_390_104_039_763_402_054_142,
                tick=tick,
                protocol_fee0=fee * META.fee_protocol // 10_000,
                protocol_fee1=0,
            )
        )
    return events


def load_tape_events(db_path: Path) -> list[Event]:
    from misquote.indexer import store

    conn = store.connect(db_path)
    try:
        return list(store.read_swaps(conn, META.address))
    finally:
        conn.close()


def run_agent(name: str, events: list[Event], *, policy=None, capital: float) -> dict:
    """Replay one agent and price it. Returns the card's raw material."""
    import misquote.replay.engine as engine_module

    original = engine_module.decide
    if policy is not None:
        engine_module.decide = policy
    try:
        driver = ReplayDriver(META, costs=CostModel(), capital_quote=capital)
        result = driver.run(MemoryTape(events))

        def factory(start, end):
            if start is None:
                return MemoryTape(events)
            return MemoryTape([e for e in events if start <= e.ts <= end])

        quote = compute_quote(META, factory, capital_quote=capital, windows=20)
    finally:
        engine_module.decide = original

    return {"name": name, "result": result, "quote": quote}


def emit(run: dict, journal_dir: Path, out_dir: Path, *, source: str) -> Path:
    """Build the tearsheet and write the artifact, with the badge attached."""
    result = run["result"]
    windows = max(1, result.samples // 100)

    sheet = build(
        agent=run["name"],
        pool=f"{TARGET_POOL.label} · {TARGET_POOL.address}",
        journal_path=journal_dir / "warden.jsonl",
        quote=run["quote"],
        in_range_samples=result.in_range_samples,
        in_range_total=result.samples,
        net_positive_windows=windows if result.net_quote > 0 else 0,
        total_windows=windows,
        extra_caveats=[COUNTERFACTUAL_NOTE],
    )

    payload = sheet.to_dict()
    payload["counterfactual"] = True
    payload["badge"] = COUNTERFACTUAL_BADGE
    payload["source"] = source
    payload["replay"] = {
        "samples": result.samples,
        "hours": round(result.hours, 2),
        "mints": result.mints,
        "rebalances": result.rebalances,
        "pulls": result.pulls,
        "in_range_fraction": round(result.in_range_fraction, 4),
        "fees_quote": round(result.total_fees, 8),
        "lvr_quote_upper_bound": round(result.total_lvr, 8),
        "costs_quote": round(result.total_costs, 8),
        "net_quote": round(result.net_quote, 8),
    }

    slug = run["name"].split()[0].lower()
    path = out_dir / f"{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(REPO / "data" / "misquote.db"))
    parser.add_argument("--synthetic", type=int, default=0, help="use N synthetic swaps instead")
    parser.add_argument("--capital", type=float, default=1000.0)
    parser.add_argument("--out", default=str(REPO / "apps" / "web" / "public" / "artifacts"))
    args = parser.parse_args()

    if args.synthetic:
        events = synthetic_events(args.synthetic)
        source = "synthetic"
        print(f"tape: {len(events):,} SYNTHETIC swaps (no chain data)")
    else:
        db = Path(args.db)
        events = load_tape_events(db) if db.exists() else []
        source = "chain"
        if not events:
            print(f"no tape at {db}.")
            print("  Run the backfill first, or pass --synthetic 4000 to see the pipeline work.")
            print("  The backfill needs a keyed BSC_RPC_URL: free endpoints cap eth_getLogs")
            print("  and refuse sustained request rates.")
            return 1
        span = (events[-1].ts - events[0].ts) / 86400
        print(f"tape: {len(events):,} real swaps spanning {span:.1f} days")

    journal_dir = Path("data/journal")
    out_dir = Path(args.out)

    runs = [
        run_agent("Warden", events, capital=args.capital),
        run_agent(
            "Grid",
            events,
            policy=lambda obs, params, meta: decide_grid(obs, GridParams(), meta),
            capital=args.capital,
        ),
    ]

    print(f"\n  {COUNTERFACTUAL_BADGE}\n")
    for run in runs:
        path = emit(run, journal_dir, out_dir, source=source)
        result, quote = run["result"], run["quote"]
        print(f"  {run['name']}")
        print(f"    quote        {quote.render()}")
        print(f"    in range     {100 * result.in_range_fraction:.1f}%")
        print(
            f"    moves        {result.mints} mint, "
            f"{result.rebalances} recentre, {result.pulls} pull"
        )
        print(
            f"    fees {result.total_fees:.6f}  "
            f"LVR(upper) {result.total_lvr:.6f}  costs {result.total_costs:.6f}"
        )
        print(f"    net          {result.net_quote:.6f}")
        print(f"    -> {path.relative_to(REPO) if path.is_relative_to(REPO) else path}")
        print()

    index = out_dir / "index.json"
    index.write_text(
        json.dumps(
            {
                "agents": [r["name"] for r in runs],
                "pool": TARGET_POOL.label,
                "counterfactual": True,
                "badge": COUNTERFACTUAL_BADGE,
                "source": source,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"  index -> {index}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
