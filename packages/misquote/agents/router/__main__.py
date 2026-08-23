"""Run Router against the recorded rate tape, without the ability to spend.

    uv run python -m misquote.agents.router --hours 168
    make router

Same posture as `agents/warden/__main__.py`, and for the same reason: the policy
is real, the tape is real, the decisions are journalled, and nothing here can
sign. There is no `--live` flag. `chain/venus.py` reads markets and
`indexer/venus_backfill.py` reads accruals; neither imports a signer and this
does not either.

What it produces is the journal every Router card's provenance block would
otherwise have to report as empty — the difference between "the policy is
tested" and "the policy has run".

## It reads the tape rather than the chain, and that is deliberate

The Warden's entrypoint polls chain state because a range policy needs the
current tick. A rate policy needs a *trailing* rate, which is a property of
history rather than of the present, and the history is already on disk with its
coverage recorded. Polling live would add a second, weaker source of the same
number — and one that cannot say whether the window it summarises had holes in
it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from misquote.agents.router.policy import RouterParams, decide_router
from misquote.chain import costs as chain_costs
from misquote.chain.venus import markets_on
from misquote.core.allocation import AllocationAction
from misquote.core.types import DEFAULT_RESERVE_FACTOR
from misquote.indexer import store, venus
from misquote.replay.allocation import (
    DEFAULT_APR_WINDOW_S,
    DEFAULT_SAMPLE_INTERVAL_S,
    AllocationDriver,
)

DEFAULT_JOURNAL = Path("data/journal/router.jsonl")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chain", type=int, default=56, choices=(56,))
    ap.add_argument("--db", default="data/misquote.db")
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--journal", default=str(DEFAULT_JOURNAL))
    ap.add_argument("--sample-interval", type=int, default=DEFAULT_SAMPLE_INTERVAL_S)
    ap.add_argument("--apr-window", type=int, default=DEFAULT_APR_WINDOW_S)
    args = ap.parse_args()

    refs = markets_on(args.chain)
    if not refs:
        print(f"no verified Venus markets for chain {args.chain}.")
        print("scripts/verify_venus.py is the gate; this refuses to run without it.")
        return 1

    conn = store.connect(args.db)
    events = []
    markets: dict[str, dict] = {}
    for ref in refs:
        rows = venus.load_accruals(conn, ref.key)
        if not rows:
            print(f"  {ref.symbol}: no accruals on the tape — run `make venus` first")
            continue
        events.extend(rows)
        last = rows[-1]
        recorded = venus.reserve_factor_at(conn, ref.key, last.block)
        markets[ref.key] = {
            # None means unrecorded, and 0.1 is what every Venus core market
            # reads today. Carried explicitly rather than defaulted silently, so
            # a tape with no NewReserveFactor rows says which value it used.
            "reserve_factor": recorded if recorded is not None else DEFAULT_RESERVE_FACTOR,
            "supplied_base_at_tape_end": (last.cash_prior + last.total_borrows_prior)
            / 10**ref.underlying_decimals,
            "reserve_factor_recorded": recorded is not None,
            # Size is NOT recorded here. `AllocationDriver` derives it per
            # sample from the accrual it has seen, because taking it from
            # `rows[-1]` sized every earlier window with a market measured at
            # the end of the tape. Only decimals travel, so the driver can
            # scale what it reads.
            "underlying_decimals": ref.underlying_decimals,
            "symbol": ref.symbol,
        }

    if len(markets) < 2:
        print(f"only {len(markets)} market(s) have a tape. A router needs two to choose between.")
        return 1

    events.sort(key=lambda e: (e.ts, e.block, e.log_index))
    span_h = (events[-1].ts - events[0].ts) / 3600.0
    print(f"tape    {len(events):,} accruals across {len(markets)} markets, {span_h:.1f}h")
    for meta in markets.values():
        note = (
            "" if meta["reserve_factor_recorded"] else "  (reserve factor not on tape, using 0.1)"
        )
        print(
            f"        {meta['symbol']:8s} supplied {meta['supplied_base_at_tape_end']:,.0f} at tape end{note}"
        )

    driver = AllocationDriver(
        markets,
        policy=decide_router,
        params=RouterParams(),
        capital_quote=args.capital,
        costs=chain_costs.switch_cost(conn),
        sample_interval_s=args.sample_interval,
        apr_window_s=args.apr_window,
    )
    began = time.time()
    result = driver.run(events)
    took = time.time() - began

    journal = Path(args.journal)
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("w") as fh:
        for ts, decision in zip(result.timestamps, result.decisions, strict=True):
            fh.write(
                json.dumps(
                    {
                        "ts": ts,
                        "action": str(decision.action),
                        "target_venue": decision.target_venue,
                        "held_venue": decision.held_venue,
                        "edge_apr": decision.edge_apr,
                        "hurdle_apr": decision.hurdle_apr,
                        "reasons": dict(decision.reasons),
                    }
                )
                + "\n"
            )

    print(f"\nran     {result.samples:,} decisions in {took:.1f}s")
    print(
        f"moves   {result.entries} enter, {result.switches} switch, {result.exits} exit"
        f"   invested {100 * result.invested_fraction:.1f}% of samples"
    )
    print(f"        best venue held on {100 * result.best_venue_fraction:.1f}% of samples")
    print(
        f"edge    max {100 * result.max_edge_apr:.3f}pp against a median hurdle of "
        f"{100 * result.hurdle_apr_p50:.3f}pp"
    )
    if result.breakeven_horizon_hours:
        print(
            f"        best rate seen {100 * result.best_apr_seen:.3f}% — repays one round "
            f"trip after {result.breakeven_horizon_hours / 24:.1f} days of commitment"
        )
    if result.switches == 0:
        # A finding, printed as one. See the policy module's docstring: the
        # answer to a gate that never fires is to find out why, not to move it.
        print(
            "        zero switches — the edge never cleared the hurdle. That is the "
            "result, not a threshold to lower."
        )
    print(f"        yield {result.gross_yield_quote:,.4f}, costs {result.total_costs:,.4f}")
    print(f"journal {journal}  ({result.samples:,} rows)")
    print("\nRECORDED, not broadcast. This entrypoint cannot sign and has no --live flag.")

    held = sum(1 for d in result.decisions if d.action is AllocationAction.HOLD)
    print(f"        {held:,} of {result.samples:,} decisions were hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
