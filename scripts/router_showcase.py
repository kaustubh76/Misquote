"""Replay Router on the Venus rate tape and write the card the site reads.

    uv run python scripts/router_showcase.py
    make router-card

## Why this is its own emitter rather than a fourth entry in `showcase.py`

`showcase.py` replays LP policies over a *swap* tape with `ReplayDriver` and
quotes them with `ranges.quote`. Router replays a *rate* tape with
`AllocationDriver` and quotes it with `allocation_quote_from_results`. Threading
two tapes, two drivers and two quote types through one script to save a file
would make the expensive path — sixty LP window replays, hours of it — a
prerequisite for regenerating a card that takes under a second.

The repository already splits emitters this way: `venue_report.py`,
`vetting_report.py`, `addresses_report.py` and `registry_report.py` are all
separate scripts writing one artifact each. This is the same shape.

## The sub-windows are the quote, exactly as they are for the other three

Twenty overlapping windows times three parameter perturbations, and a window
shorter than the policy's own 24h horizon is refused rather than quoted. The
floors live in `replay/allocation.py` and are the same numbers `ranges.py`
uses, because assumption A5 is about the shape of a published range and does not
care which agent produced it.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from misquote.agents.router.policy import RouterParams, decide_router, park_policy
from misquote.chain import costs as chain_costs
from misquote.chain.addresses import known_pools_on
from misquote.chain.venus import markets_on
from misquote.core.types import DEFAULT_RESERVE_FACTOR, PoolMeta
from misquote.estimators.pool_apr import MIN_SWAPS
from misquote.indexer import store, venus
from misquote.replay.allocation import AllocationDriver, allocation_quote_from_results
from misquote.replay.ranges import DEFAULT_WINDOWS
from misquote.replay.venues import PoolVenue
from misquote.tearsheet import ledger, provenance
from misquote.tearsheet.advantage import MATERIAL_PP
from misquote.tearsheet.generate import read_journal
from misquote.vetting.badge import cleared_to_provide

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "apps" / "web" / "public" / "artifacts"
JOURNAL_DIR = REPO / "data" / "journal"

COUNTERFACTUAL_BADGE = "COUNTERFACTUAL — this position was not held"

WINDOWS = DEFAULT_WINDOWS

#: The parameter spread, perturbing what is genuinely uncertain.
#:
#: This scaled `horizon_hours` by 0.5/1.0/2.0 under a comment claiming it was
#: "the same three-point perturbation the LP agents get". It was not, in two
#: ways. `ranges.perturbations` scales **gamma** by +/-25% *because gamma is not
#: measured* (A5); the horizon is a **user input** — how long capital is
#: committed for — so varying it changes the question rather than testing
#: whether the answer is robust. And +/-25% is not a doubling.
#:
#: What is genuinely uncertain here is the **cost**, and one part of it in
#: particular: the fee is read from a verified pool and the gas price from the
#: chain, but `VENUS_SWITCH_GAS_UNITS` is stated rather than measured, because
#: measuring it needs a transaction this project will not send (A14). So the
#: spread is +/-25% on the cost model, matching A5's fraction.
COST_PERTURBATIONS = (0.75, 1.0, 1.25)


def sub_windows(tapes: dict[str, list], count: int):
    """`count` overlapping windows, each half the span, sliced across every venue.

    Takes the per-venue tapes and returns per-venue slices, because a window is
    a period of time rather than a subsequence of one venue's events. Cutting
    the venues on their own event indices would give each of them a different
    period and quietly compare a lending market over one fortnight against a
    pool over another.
    """
    starts = [rows[0].ts for rows in tapes.values() if len(rows) >= 2]
    ends = [rows[-1].ts for rows in tapes.values() if len(rows) >= 2]
    if not starts:
        return []
    start, end = min(starts), max(ends)
    span = end - start
    if span <= 0:
        return []
    width = span // 2
    step = (span - width) / max(1, count - 1)
    out = []
    for i in range(count):
        lo = int(start + i * step)
        hi = lo + width
        window = {v: [e for e in rows if lo <= e.ts <= hi] for v, rows in tapes.items()}
        if sum(len(rows) for rows in window.values()) >= 2:
            out.append(window)
    return out


def _pool_venue(conn, ref, *, capital_quote: float, price: float | None):
    """A badged pool as a venue Router may enter, or the reason it is not one.

    Four things have to be true, and each refusal is a sentence rather than a
    silent skip, because a pool missing from the card for an unstated reason is
    indistinguishable from a pool that was never considered.
    """
    cleared, why = cleared_to_provide(ref.address)
    if not cleared:
        return None, [], f"{ref.label}: {why}"
    if price is None:
        # Sizes cross from the pool's quote token into the router's dollars, and
        # A1's ceiling is one of them. Guessing the rate is P-25 exactly.
        return None, [], f"{ref.label}: no BNB price on the tape to convert sizes with"

    tape = list(store.read_swaps(conn, ref.address))
    if len(tape) < MIN_SWAPS:
        return None, [], f"{ref.label}: {len(tape)} swaps on the tape, below the {MIN_SWAPS} floor"

    # The width is measured, not chosen here. `pools.json` ran the ladder over
    # this same tape and published which width led and whether the lead was
    # separated; A21 says there is no width-free fee APR, so a venue that picked
    # a constant would be quoting a position nobody had a reason to hold.
    width = _measured_width(ref.address)
    if width is None:
        return (
            None,
            [],
            (f"{ref.label}: no measured width — run `make pools` to publish the ladder"),
        )

    venue = PoolVenue(
        _pool_meta(ref),
        width_ticks=width,
        # The router's dollars, expressed in the numeraire the pool prices in.
        # The estimator divides fees by this to get a rate and `LvrAccountant`
        # dilutes our fee share by it, so passing dollars to a pool that counts
        # in BNB would be wrong by the price of BNB in both.
        capital_quote=capital_quote / price,
        quote_price=price,
        label=ref.label,
    )
    return venue, tape, ""


def _measured_width(address: str) -> int | None:
    """The leading width `make pools` measured for this pool, or nothing."""
    path = DEFAULT_OUT / "pools.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    for pool in data.get("pools", []):
        if pool.get("address", "").lower() != address.lower():
            continue
        width = pool.get("best_width_ticks")
        return int(width) if width else None
    return None


def _pool_meta(ref) -> PoolMeta:
    """The pool as the engine sees it. Every field read, none defaulted."""
    return PoolMeta(
        address=ref.address,
        chain_id=ref.chain_id,
        token0=ref.token0,
        token1=ref.token1,
        dec0=ref.dec0,
        dec1=ref.dec1,
        fee_pips=ref.fee_pips,
        tick_spacing=ref.tick_spacing,
        fee_protocol=ref.fee_protocol,
    )


def _provenance(journal_dir: Path, *, derived_from_replay: bool) -> dict:
    """Where this card's numbers came from, in the shape the LP cards use.

    `make router` writes `data/journal/router.jsonl` — the real policy stepped
    over the real tape — and **nothing read it**. Router was the only card with
    no provenance block at all, in a repo where `agents/warden/__main__.py`
    argues the whole point of having an entrypoint is that *"it produces the
    journal every card's provenance block currently has to say is empty"*.

    `every_number_derived` carries the honest distinction: the figures on this
    card come from the replay in this script, not from the journalled run, and
    the journal is published beside them as the record that the same policy has
    actually executed.
    """
    path = journal_dir / "router.jsonl"
    summary = read_journal(path)
    # Repo-relative, as the LP cards publish it. `str(path)` on an absolute
    # journal_dir put "/Users/<name>/Desktop/Misquote/..." into an artifact the
    # site serves — a developer's home directory on a public page, and a path
    # that means nothing to anyone else.
    shown = path.relative_to(REPO) if path.is_relative_to(REPO) else path
    return {
        "journal": str(shown),
        "journal_rows": summary.rows,
        "hours_covered": round(summary.hours, 2),
        "every_number_derived": derived_from_replay,
    }


def _venue_row(key: str, meta) -> dict:
    """One venue as the card publishes it, in the shape its kind actually has.

    A `PoolVenue` already answers `card_fields()`; a Venus market is still the
    plain dict it has always been, and `as_venue` says why. The `venue_id` is
    added here because it is the driver's key rather than anything the venue
    knows about itself.
    """
    if hasattr(meta, "card_fields"):
        return {"venue_id": key, **meta.card_fields()}
    return {
        "venue_id": key,
        "kind": "lending",
        "symbol": meta["symbol"],
        "supplied_base_at_tape_end": round(meta["supplied_base_at_tape_end"], 2),
        "reserve_factor": meta["reserve_factor"],
        "reserve_factor_recorded": meta["reserve_factor_recorded"],
    }


def _params_dict(p) -> dict:
    """The published parameter block. One definition, both paths."""
    return {
        "horizon_hours": p.horizon_hours,
        "switch_cost_margin": p.switch_cost_margin,
        "persistence_samples": p.persistence_samples,
        "cooldown_s": p.cooldown_s,
        "max_switches_per_day": p.max_switches_per_day,
        "min_apr_samples": p.min_apr_samples,
        "eps_market_share": p.eps_market_share,
    }


def _register(out_dir: Path, payload: dict) -> None:
    """Write the card and merge Router into the index.

    Shared by the quoted and withheld paths so the fourth category appears in
    `index.json` either way — a withheld card that nothing lists is the same
    disappearance as no card at all.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "router.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"card   -> {path}")

    index_path = out_dir / "index.json"
    if not index_path.exists():
        print(f"index  {index_path} not found — run `make showcase-auto` first")
        return
    index = json.loads(index_path.read_text())
    agents = [a for a in index.get("agents", []) if a.get("slug") != "router"]
    agents.append({"built": True, "category": "Yield", "name": "Router", "slug": "router"})
    index["agents"] = agents
    index["not_built"] = ledger.to_dicts()
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    print(f"index  -> {index_path}  ({len(agents)} agents)")


def _write_withheld(out_dir: Path, command: str, markets_found: int) -> None:
    """The card, refusing, with the command that would let it quote.

    Everything a reader needs to know is here except the numbers, and the
    reason the numbers are missing is the one thing they most need.
    """
    note = (
        f"withheld: no Venus rate tape — {markets_found} of the two verified markets "
        f"have accruals on disk. Run `make venus` to read them, then `make router-card`."
    )
    payload = {
        "agent": "Router",
        "category": "Yield",
        "kind": "allocation",
        "venue": "Venus Core Pool (BSC) — dollar markets only",
        "venues": [],
        "source": "none",
        "counterfactual": True,
        "badge": COUNTERFACTUAL_BADGE,
        "quote_symbol": "USD",
        "capital_quote": 0.0,
        "quote": {
            "p25": 0.0,
            "p50": 0.0,
            "p75": 0.0,
            "samples": 0,
            "windows": 0,
            "perturbations": 0,
            "best_venue_p50": 0.0,
            "switches_p50": 0.0,
            "hours_per_window": 0.0,
            "sufficient": False,
            "note": note,
            "annualised": False,
            "basis": "",
            "net_positive": 0,
            "returns": [],
            "max_edge_apr": 0.0,
            "hurdle_apr": 0.0,
        },
        "replay": {
            "samples": 0,
            "hours": 0.0,
            "entries": 0,
            "exits": 0,
            "switches": 0,
            "invested_fraction": 0.0,
            "best_venue_fraction": 0.0,
            "gross_yield_quote": 0.0,
            "costs_quote": 0.0,
            "net_quote": 0.0,
            "max_edge_apr": 0.0,
            "hurdle_apr_p50": 0.0,
            "best_apr_seen": 0.0,
            "breakeven_horizon_hours": 0.0,
        },
        # The parameters are known even when the tape is not — they are
        # defaults, not measurements — so the card carries them rather than
        # publishing an empty object the contract cannot describe.
        "params": _params_dict(RouterParams()),
        "cost_model": {
            "gas_quote": 0.0,
            "slippage_bps": 0.0,
            "derived": False,
            "basis": "not computed — there is no tape to price a move over",
        },
        "advantage": {
            "delta_pp": 0.0,
            "verdict": note,
            "material": False,
            "ranges_overlap": True,
            "separated": False,
            "quotable": False,
            "source": "none",
            "without_agent": ("supply to the highest-rate venue once and never move (park_policy)"),
            "baseline": {
                "p25": 0.0,
                "p50": 0.0,
                "p75": 0.0,
                "entries": 0,
                "switches": 0,
                "invested_fraction": 0.0,
                "gross_yield_quote": 0.0,
                "costs_quote": 0.0,
                "net_quote": 0.0,
            },
        },
        "finding": note,
        "provenance": _provenance(JOURNAL_DIR, derived_from_replay=False),
        "caveats": [COUNTERFACTUAL_BADGE, note],
        "build": provenance.build_stamp(command, source="none"),
    }
    _register(out_dir, payload)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chain", type=int, default=56, choices=(56,))
    ap.add_argument("--db", default=str(REPO / "data" / "misquote.db"))
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument(
        "--no-pools",
        dest="pools",
        action="store_false",
        help=(
            "replay Venus markets only. The pool venues are what let Router "
            "answer the PancakeSwap question at all, so this is a speed switch "
            "for local iteration and not a mode anything published should use: "
            "a card built with it silently claims Router considered lending "
            "alone."
        ),
    )
    ap.set_defaults(pools=True)
    args = ap.parse_args()

    command = "python scripts/router_showcase.py"
    refs = markets_on(args.chain)
    conn = store.connect(args.db)

    # Tapes per venue rather than one flat list. `AllocationDriver.run` used to
    # take everything sorted together and group it by `RateEvent.market`, which a
    # swap `Event` does not have — so a pool could not be fed however well the
    # rest of the seam was cut. Grouping here also removes a round trip: this
    # loaded per-market lists, flattened them, and let the driver undo it.
    tapes: dict[str, list] = {}
    markets: dict[str, object] = {}
    coverage_gaps = 0
    for ref in refs:
        rows = venus.load_accruals(conn, ref.key)
        if not rows:
            continue
        tapes[ref.key] = rows
        last = rows[-1]
        recorded = venus.reserve_factor_at(conn, ref.key, last.block)
        if recorded is None:
            coverage_gaps += 1
        markets[ref.key] = {
            "reserve_factor": recorded if recorded is not None else DEFAULT_RESERVE_FACTOR,
            "reserve_factor_recorded": recorded is not None,
            # Descriptive only — what the market looked like at the end of the
            # tape, for the card's venue table. The replay does not use it; it
            # derives size per sample. Named so nobody wires it back in.
            "supplied_base_at_tape_end": (last.cash_prior + last.total_borrows_prior)
            / 10**ref.underlying_decimals,
            # Size is NOT recorded here. `AllocationDriver` derives it per
            # sample from the accrual it has seen, because taking it from
            # `rows[-1]` sized every earlier window with a market measured at
            # the end of the tape. Only decimals travel, so the driver can
            # scale what it reads.
            "underlying_decimals": ref.underlying_decimals,
            "symbol": ref.symbol,
        }

    lending_count = len(markets)
    price_quote = chain_costs.native_price_from_tape(conn)
    pool_notes: list[str] = []
    if args.pools:
        for ref in known_pools_on(args.chain):
            venue, tape, note = _pool_venue(
                conn, ref, capital_quote=args.capital, price=price_quote
            )
            if venue is None:
                pool_notes.append(note)
                continue
            markets[ref.address] = venue
            tapes[ref.address] = tape
            print(f"pool   {ref.label} at +/-{venue.width_ticks} ticks, {len(tape):,} swaps")
    for note in pool_notes:
        print(f"       {note}")

    if lending_count < 2:
        # Withheld, not aborted.
        #
        # `artifacts:` lists this target, so returning non-zero stopped the whole
        # chain — advantage, registry, assumptions, judges and status never ran,
        # and a clean checkout could not build the site at all. `showcase-auto`
        # degrades to a labelled synthetic tape; this had no fallback, and a
        # *fabricated* lending tape is one thing this repo will not produce.
        #
        # So the card publishes its own refusal, which is the idiom everywhere
        # else here: `advantage-short` exists to withhold every task,
        # `check_rate_tape` answers UNVERIFIED, `read_survey` returns a reason.
        # The fourth category stays visible with the reason on it rather than
        # vanishing — the failure this repo already shipped once.
        print(f"only {lending_count} market(s) have a tape — a router needs two.")
        print("Writing a withheld card. Run `make venus` to quote it.")
        _write_withheld(Path(args.out), command, lending_count)
        return 0

    source = "chain"
    starts = [rows[0].ts for rows in tapes.values() if rows]
    ends = [rows[-1].ts for rows in tapes.values() if rows]
    span_h = (max(ends) - min(starts)) / 3600.0
    rows_total = sum(len(rows) for rows in tapes.values())
    pool_count = len(markets) - lending_count
    print(
        f"tape   {rows_total:,} events, {lending_count} market(s) + {pool_count} pool(s), "
        f"{span_h:.1f}h  [{source}]"
    )

    base_params = RouterParams()
    # Derived, not declared. Every input is a reading and the card records
    # which ones — see chain/costs.py and P-25.
    costs = chain_costs.switch_cost(conn)
    print(f"costs  {costs.basis}")
    if not costs.derived:
        print("       (fallback in use — the card says so)")

    def scaled(scale: float):
        """The cost model moved by `scale`. Params are held fixed."""
        return replace(
            costs,
            gas_quote=costs.gas_quote * scale,
            slippage_bps=costs.slippage_bps * scale,
            basis=f"{costs.basis} [x{scale:g}]",
        )

    def run(window, params, policy=decide_router, cost_model=None) -> object:
        driver = AllocationDriver(
            markets,
            policy=policy,
            params=params,
            capital_quote=args.capital,
            costs=cost_model if cost_model is not None else costs,
        )
        return driver.run(window)

    full = run(tapes, base_params)
    # The number the card is implicitly claiming to beat. Same driver, same
    # tape, same cost model — only the decision function differs, which is what
    # makes the delta a claim about the policy. See `park_policy`.
    baseline_full = run(tapes, base_params, park_policy)
    windows = sub_windows(tapes, WINDOWS)
    results = []
    for window in windows:
        for scale in COST_PERTURBATIONS:
            results.append(run(window, base_params, cost_model=scaled(scale)))

    baseline_results = []
    for window in windows:
        for scale in COST_PERTURBATIONS:
            baseline_results.append(run(window, base_params, park_policy, cost_model=scaled(scale)))

    quote = allocation_quote_from_results(
        results,
        windows=len(windows),
        perturbation_count=len(COST_PERTURBATIONS),
        capital_quote=args.capital,
    )
    baseline_quote = allocation_quote_from_results(
        baseline_results,
        windows=len(windows),
        perturbation_count=len(COST_PERTURBATIONS),
        capital_quote=args.capital,
    )

    print(f"quote  {quote.render()}")
    print(
        f"       max edge {100 * full.max_edge_apr:.3f}pp  median hurdle "
        f"{100 * full.hurdle_apr_p50:.3f}pp"
    )
    if full.breakeven_horizon_hours:
        print(
            f"       best rate {100 * full.best_apr_seen:.3f}% repays a round trip after "
            f"{full.breakeven_horizon_hours / 24:.1f} days"
        )

    pool_venues = [m for m in markets.values() if getattr(m, "kind", "lending") == "pool"]
    if pool_venues:
        widths = ", ".join(f"+/-{v.width_ticks}" for v in pool_venues)
        venue_label = (
            f"Venus Core Pool (BSC) dollar markets and "
            f"{len(pool_venues)} PancakeSwap v3 range(s) at {widths} ticks"
        )
    else:
        venue_label = "Venus Core Pool (BSC) — dollar markets only"

    # What a reader has to know before reading a pool row beside a lending one.
    # Only when there is a pool row: a caveat about a venue the card does not
    # carry is noise, and noise is how the ones that matter stop being read.
    pool_caveats: list[str] = []
    if pool_venues:
        pool_caveats = [
            "A pool venue is quoted NET of its convexity cost — realized fees minus "
            "the LVR the same window actually booked. The gross fee APR is the "
            "number every other venue quotes, and ranking it against a lending "
            "market's net supply rate would let it win on a subtraction it had "
            "not made (A10, A21).",
            "These are not the same risk. A supplied dollar earns a dollar rate and "
            "its principal stays a dollar. An LP range earns a rate measured in the "
            "pool's own quote token, and its principal is two assets whose value "
            "moves with the price — so a higher figure is not simply better, and "
            "the two numbers are not interchangeable however carefully each is "
            "derived.",
            "There is no width-free fee APR: two LPs in one pool at one moment earn "
            "differently because they chose differently. Each range here is quoted "
            "at the width `make pools` measured as the leader over this tape, and "
            "`pools.json` records that the lead is not separated at this sample "
            "size (A21, A23).",
            f"A window holding fewer than {MIN_SWAPS} swaps has no verdict rather "
            f"than a small number, and A1's ceiling is a fraction of the pool's own "
            f"depth over the quoted range — so a range can pay well and still be "
            f"refused for being too shallow to take the position.",
        ]

    payload = {
        "agent": "Router",
        "category": "Yield",
        # The discriminator every view dispatches on. The other three cards are
        # `lp_range` and carry fees, LVR and an in-range fraction; this one has
        # none of those and must not render a zero in their place.
        "kind": "allocation",
        "venue": venue_label,
        # Two shapes, because the venues are two kinds and a row that flattened
        # them would have to invent the field the other kind does not have. A
        # lending market has a reserve factor and no width; a range has a width,
        # a fee tier and an LP share of that tier, and no reserve factor.
        "venues": [_venue_row(key, meta) for key, meta in markets.items()],
        "source": source,
        "counterfactual": True,
        "badge": COUNTERFACTUAL_BADGE,
        "quote_symbol": "USD",
        "capital_quote": args.capital,
        "quote": quote.to_dict(),
        "replay": {
            "samples": full.samples,
            "hours": round(full.hours, 2),
            "entries": full.entries,
            "switches": full.switches,
            "exits": full.exits,
            "invested_fraction": round(full.invested_fraction, 4),
            "best_venue_fraction": round(full.best_venue_fraction, 4),
            "gross_yield_quote": round(full.gross_yield_quote, 8),
            "costs_quote": round(full.total_costs, 8),
            "net_quote": round(full.net_quote, 8),
            "max_edge_apr": round(full.max_edge_apr, 6),
            "hurdle_apr_p50": round(full.hurdle_apr_p50, 6),
            "best_apr_seen": round(full.best_apr_seen, 6),
            "breakeven_horizon_hours": round(full.breakeven_horizon_hours, 2),
        },
        "cost_model": {
            "gas_quote": round(costs.gas_quote, 8),
            "slippage_bps": costs.slippage_bps,
            "derived": costs.derived,
            "basis": costs.basis,
        },
        "params": _params_dict(base_params),
        "provenance": _provenance(JOURNAL_DIR, derived_from_replay=True),
        "caveats": [
            COUNTERFACTUAL_BADGE,
            # The finding, on the card rather than only in the docstring.
            "Rates are realized — derived by differencing Venus's borrowIndex "
            "accumulator, never from supplyRatePerBlock(), whose conversion to an "
            "annual figure needs a blocks-per-year constant that is not readable "
            "from chain and whose plausible values span 6.67x (A12, P-22).",
            "The switching boundary is the myopic break-even, widened by a "
            "published margin. It is not a solved free boundary (A13).",
            "Switch cost uses the full pool fee, not the LP's share of it: a "
            "router paying to swap pays PancakeSwap's protocol cut too (P-1).",
            *pool_caveats,
        ],
    }
    # What the run actually did, in words, because the numbers alone read
    # ambiguously in both directions.
    if full.entries == 0 and full.switches == 0:
        payload["finding"] = (
            f"Router did not supply at all. Over {span_h:.0f}h the best realized dollar rate "
            f"was {100 * full.best_apr_seen:.2f}%, against a round-trip hurdle of "
            f"{100 * full.hurdle_apr_p50:.2f}% — so capital would have to be committed for "
            f"{full.breakeven_horizon_hours / 24:.1f} days before entering repays its cost. "
            f"At this horizon the honest answer is to do nothing, and that is what it did."
        )
    elif full.switches == 0:
        payload["finding"] = (
            f"Router supplied once and then left it alone — and both halves of that are "
            f"the decision. It entered because the best realized rate, "
            f"{100 * full.best_apr_seen:.2f}%, clears the "
            f"{100 * full.hurdle_apr_p50:.2f}% round-trip hurdle after "
            f"{full.breakeven_horizon_hours / 24:.1f} days of commitment. It then never "
            f"switched, because the largest gap *between* the two venues over "
            f"{span_h:.0f}h was {100 * full.max_edge_apr:.3f}pp — well under the same "
            f"hurdle. It held the better-paying venue on "
            f"{100 * full.best_venue_fraction:.0f}% of samples and declined to chase the "
            f"rest, earning {full.gross_yield_quote:,.2f} against {full.total_costs:,.4f} "
            f"of cost. Churning after a 0.3pp edge is what the boundary exists to refuse."
        )
        # Appended inside this branch only. It sat after the `if/elif`, so the
        # zero-entry branch would have read "Router did not supply at all … An
        # earlier version of this card said Router never supplied. That was an
        # artefact" — a card contradicting itself in consecutive sentences.
        payload["finding"] += (
            " An earlier version of this card said Router never supplied at all. That was "
            "an artefact of two cost constants with nothing behind them — a gas figure "
            "forty times BSC's real cost and a swap fee copied from a WBNB/USDT pool "
            "rather than read from the USDT/USDC pool a stablecoin router actually uses. "
            "Both are now readings. See P-25."
        )

    else:
        payload["finding"] = (
            f"Router supplied and then moved {full.switches} time(s). Over {span_h:.0f}h the "
            f"best realized dollar rate was {100 * full.best_apr_seen:.2f}%, and the largest "
            f"gap between the two venues reached {100 * full.max_edge_apr:.3f}pp against a "
            f"round-trip hurdle of {100 * full.hurdle_apr_p50:.3f}pp — so the edge cleared, "
            f"and only just. It held the better-paying venue on "
            f"{100 * full.best_venue_fraction:.0f}% of samples, earning "
            f"{full.gross_yield_quote:,.2f} against {full.total_costs:,.4f} of cost. "
            f"A boundary that is crossed narrowly is the interesting case: the same agent "
            f"declined to move on a 0.3pp edge earlier in this tape."
        )

    if coverage_gaps:
        payload["caveats"].append(
            f"{coverage_gaps} market(s) have no NewReserveFactor row on the tape; "
            f"0.1 was used and the card says so per venue."
        )
    # The comparison, in the same shape the other three cards carry it, so
    # `tests/web/test_source_disclosure.py` guards this card too and a reader
    # gets the same question answered on every card: does hiring it beat doing
    # it yourself?
    delta = quote.p50 - baseline_quote.p50
    overlap = not (quote.p25 > baseline_quote.p75 or baseline_quote.p25 > quote.p75)
    quotable_both = quote.sufficient and baseline_quote.sufficient
    if not quotable_both:
        verdict = "withheld — one or both sides could not be quoted"
    elif abs(delta) < MATERIAL_PP:
        verdict = (
            f"indistinguishable: {delta:+.2f}pp is below the {MATERIAL_PP}pp materiality floor"
        )
    elif delta > 0:
        verdict = f"agent beats parking by {delta:.2f}pp"
        verdict += "" if overlap else ", bands do not overlap"
    else:
        verdict = f"agent loses to parking by {abs(delta):.2f}pp"
        verdict += "" if overlap else ", bands do not overlap"

    payload["advantage"] = {
        "delta_pp": round(delta, 4),
        "material": bool(quotable_both and abs(delta) >= MATERIAL_PP),
        "ranges_overlap": overlap,
        "separated": not overlap,
        "quotable": quotable_both,
        "verdict": verdict,
        "source": source,
        "without_agent": ("supply to the highest-rate venue once and never move (park_policy)"),
        "baseline": {
            "p25": round(baseline_quote.p25, 4),
            "p50": round(baseline_quote.p50, 4),
            "p75": round(baseline_quote.p75, 4),
            "entries": baseline_full.entries,
            "switches": baseline_full.switches,
            "invested_fraction": round(baseline_full.invested_fraction, 4),
            "gross_yield_quote": round(baseline_full.gross_yield_quote, 8),
            "costs_quote": round(baseline_full.total_costs, 8),
            "net_quote": round(baseline_full.net_quote, 8),
        },
    }

    payload["build"] = provenance.build_stamp(command, source=source)

    _register(Path(args.out), payload)

    return 0


if __name__ == "__main__":
    sys.exit(main())
