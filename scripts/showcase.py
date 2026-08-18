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
import os
import random
import sys
import time
from pathlib import Path

from misquote.agents.grid.policy import GridParams, decide_grid
from misquote.agents.sentinel.policy import SentinelParams, sentinel_policy
from misquote.chain.addresses import TARGET_POOL
from misquote.core.policy import passive_policy
from misquote.core.tickmath import Q96, get_sqrt_ratio_at_tick
from misquote.core.types import (
    DEFAULT_CAPITAL_QUOTE,
    SYNTHETIC_SWAP_SIZE_TOKEN0,
    Event,
    PoolMeta,
)
from misquote.ops.parallel import fork_map
from misquote.replay.driver import CostModel, ReplayDriver
from misquote.replay.ranges import quote as compute_quote
from misquote.replay.tape import MemoryTape
from misquote.tearsheet import ledger, provenance
from misquote.tearsheet.advantage import compare
from misquote.tearsheet.generate import build as build_tearsheet

REPO = Path(__file__).resolve().parents[1]

COUNTERFACTUAL_BADGE = "COUNTERFACTUAL — this position was not held"

# The four categories the landing page routes between. Router is the fourth and
# is not built; it is carried in `tearsheet.ledger` rather than here, so that the
# only way for it to disappear from the UI is to actually build it.
CATEGORIES = {
    "Warden": "Rebalancing",
    "Grid": "Market making",
    "Sentinel": "Health",
}
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


def synthetic_events(
    count: int, *, seed: int = 7, swap_size: int = SYNTHETIC_SWAP_SIZE_TOKEN0
) -> list[Event]:
    """A stand-in tape, clearly labelled as one — and a *possible* one.

    Used only when no real tape exists yet. Every artifact built from it carries
    `source: "synthetic"`, so a card produced this way can never be mistaken for
    one produced from chain data — which is the failure this whole project is
    named after.

    ## The two amounts have to agree with the tick

    A v3 swap pays one token and receives the other at the pool's price. This
    generator emitted `amount0 = -swap_size` and `amount1 = +swap_size` — equal
    magnitudes — while the `tick` on the same event asserted a price of 0.001632
    token1 per token0. Every swap therefore claimed to pay 100,000 WBNB for
    100,000 USDT on a pool priced at 612 USDT per WBNB: **612.6x too much
    token1**, on the side the LVR accountant reads.

    This is V-13 a second time. That finding — recorded in
    `docs/REQUIREMENTS_MATRIX.md` — was that the tape "was not a possible
    history": every swap had the pool receiving token0 and paying token1 while
    the tick walked both ways. The fix corrected the *direction* of each swap and
    left the *magnitude* alone, and nothing was watching the magnitude. It went
    unnoticed until the demo's own quote was read against the chain tape's.

    `amount1` is derived from the price here rather than mirrored, so the tape is
    a possible history by construction and cannot drift back.
    `tests/replay/test_synthetic_tape.py` asserts it on every generator in the
    repository, so a fifth copy fails on arrival.
    """
    rng = random.Random(seed)
    events: list[Event] = []
    tick, ts = -64180, 1_700_000_000
    for i in range(count):
        move = rng.choice((-9, -4, 0, 4, 9))
        tick += move
        ts += rng.randint(5, 45)

        sqrt_price = get_sqrt_ratio_at_tick(tick)
        # token1 per token0, in raw units. Both tokens are 18 decimals on this
        # pool, so no decimal adjustment applies; `PoolRef.dec0`/`dec1` are equal
        # and `lvr/accountant.py` scales by their difference, which is zero.
        price = (sqrt_price / Q96) ** 2
        quote_amount = int(swap_size * price)

        # The fee is taken on the token1 leg, which is what the accountant reads
        # and what `fee_protocol` is skimmed from. It was computed from
        # `swap_size` — the token0 leg — so it inherited the same overstatement.
        fee = quote_amount * META.fee_pips // 10**6
        cut = fee * META.fee_protocol // 10_000

        # Direction is derived from the price move, not asserted beside it. See
        # the docstring: this half was already correct.
        up = move > 0 if move != 0 else i % 2 == 0
        events.append(
            Event(
                block=1_000_000 + i,
                log_index=0,
                ts=ts,
                kind="swap",
                tx=f"0x{i:064x}",
                amount0=-swap_size if up else swap_size,
                amount1=quote_amount if up else -quote_amount,
                sqrt_price_x96=sqrt_price,
                liquidity=1_275_390_104_039_763_402_054_142,
                tick=tick,
                protocol_fee0=0 if up else cut,
                protocol_fee1=cut if up else 0,
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


def tape_coverage_gaps(db_path: Path, first: int, last: int) -> list[tuple[int, int]] | None:
    """Ranges inside the tape that were never read. `None` when unrecorded.

    `None` and `[]` are different claims and must not be collapsed: `[]` says we
    checked and there are no holes, `None` says this database predates the
    coverage table and nobody can now say. Returning `[]` for both would let an
    unverifiable tape be published as a verified one.
    """
    from misquote.indexer import store

    conn = store.connect(db_path)
    try:
        if not store.coverage(conn, META.address):
            return None
        return store.gaps(conn, META.address, first, last)
    finally:
        conn.close()


def run_agent(
    name: str, events: list[Event], *, policy=None, capital: float, jobs: int | None = None
) -> dict:
    """Replay one agent and price it. Returns the card's raw material.

    `policy` is passed to the driver, not installed over the engine module's
    `decide` global. That global assignment was how a second agent used to run,
    and it could not survive a third: it cannot run two agents concurrently, does
    not nest, and leaves the wrong policy installed if anything between the swap
    and the restore raises. `None` means Warden.
    """
    started = time.monotonic()
    print(f"{name}: full replay over {len(events):,} events …", flush=True)
    driver = ReplayDriver(META, costs=CostModel(), capital_quote=capital, policy=policy)
    result = driver.run(MemoryTape(events))
    estimators = read_estimators(driver)

    def factory(start, end):
        if start is None:
            return MemoryTape(events)
        return MemoryTape([e for e in events if start <= e.ts <= end])

    # A 30-day tape is 60 replays of ~125,000 events per agent — 4.6 hours
    # serial, measured. The first attempt at this printed nothing for thirty
    # minutes and then died to a timeout, which is P-10's failure in different
    # clothes: a long job that cannot say it is alive.
    #
    # Timed from the window phase rather than from entry. The first version
    # divided *total* elapsed — which includes the serial full replay above, 137s
    # on a 30-day tape — by the number of *window* replays done, and reported
    # "72.8s each, ~67 min left" while the real throughput was better than that.
    # An estimate that is reliably wrong in one direction is a small lie.
    windows_began = [0.0]

    def progress(done: int, total: int) -> None:
        if done == 1:
            windows_began[0] = time.monotonic()
        if done == total or done % 5 == 0:
            # Rate over the replays *since the first completed one*, so a pool
            # that dispatches eight at once is not read as eight slow replays.
            elapsed = time.monotonic() - windows_began[0]
            rate = elapsed / max(1, done - 1) if done > 1 else elapsed
            print(
                f"  {name}: {done}/{total} replays  "
                f"{rate:.1f}s each  ~{rate * (total - done) / 60:.0f} min left",
                flush=True,
            )

    quote = compute_quote(
        META,
        factory,
        capital_quote=capital,
        windows=20,
        policy=policy,
        map_fn=fork_map(jobs) if jobs else None,
        on_progress=progress,
    )
    print(f"{name}: done in {(time.monotonic() - started) / 60:.1f} min", flush=True)
    return {"name": name, "result": result, "quote": quote, "estimators": estimators}


def read_estimators(driver: ReplayDriver) -> dict:
    """The state the estimators ended the replay in.

    `ASSUMPTIONS.md` A8 says, in as many words, that *every card that uses kappa
    shows its r-squared and whether the fallback was used*. Nothing in the repo
    kept that promise — the fit was computed on every decision and discarded, so
    a card could quote a range whose width came from a provisional default and
    look identical to one whose width came from a fit.

    Read after the run, off the same engine that made the decisions. `.label` is
    the estimator's own sentence about itself, so the card cannot describe the
    fit in terms the fit would not use.
    """
    engine = driver.engine
    fit = engine.kappa.fit()
    return {
        "sigma_per_sqrt_hour": engine.sigma.value(),
        "sigma_ready": engine.sigma.ready,
        "kappa_per_tick": fit.kappa_per_tick,
        "kappa_per_logprice": fit.kappa_per_logprice,
        "kappa_r_squared": fit.r_squared,
        "kappa_is_fallback": fit.is_fallback,
        "kappa_buckets_used": fit.buckets_used,
        "kappa_swaps_used": fit.swaps_used,
        "kappa_label": fit.label,
        "imbalance_z": engine.imbalance.value(),
        "imbalance_ready": engine.imbalance.ready,
    }


def emit(
    run: dict,
    journal_dir: Path,
    out_dir: Path,
    *,
    source: str,
    baseline: dict | None = None,
) -> Path:
    """Build the tearsheet and write the artifact, with the badge attached."""
    result = run["result"]
    quote = run["quote"]
    slug = run["name"].split()[0].lower()

    sheet = build_tearsheet(
        agent=run["name"],
        pool=f"{TARGET_POOL.label} · {TARGET_POOL.address}",
        # Per agent. This was hardcoded to `warden.jsonl`, so every card stamped
        # Warden's journal as its own provenance — a misattribution on the one
        # field a reader would check to audit the card.
        journal_path=journal_dir / f"{slug}.jsonl",
        quote=quote,
        in_range_samples=result.in_range_samples,
        in_range_total=result.samples,
        # The count of windows that finished in profit, and the count of windows.
        # Both come off the quote, which got them by replaying.
        #
        # These two arguments used to be `windows = max(1, result.samples // 100)`
        # — a single replay's 44,802 decisions divided by a hundred and then
        # asserted to be 448 unanimous observations. Every card rendered
        # "PASS (100% of 448)". There were never 448 observations; there was one
        # replay, and the arithmetic manufactured precisely the sample size that
        # `verdict(min_n=30)` exists to refuse. The real denominator is 60:
        # twenty sub-windows times three parameter perturbations.
        net_positive_windows=quote.net_positive,
        total_windows=quote.samples,
        extra_caveats=[COUNTERFACTUAL_NOTE],
        estimators=run.get("estimators"),
    )

    payload = sheet.to_dict()
    payload["counterfactual"] = True
    payload["badge"] = COUNTERFACTUAL_BADGE
    payload["source"] = source
    # The unit of every `*_quote` figure below, carried rather than assumed.
    # `net_quote` is token1, which on this pool is WBNB and not the USDT the
    # label's pair reads as — see the note on `PoolRef.quote_symbol`. The front
    # end renders no unit at all when this is absent, which is the right answer
    # for an artifact written before this field existed and the wrong one to
    # guess at.
    payload["quote_symbol"] = TARGET_POOL.quote_symbol
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

    # What the card was missing: the number it is implicitly claiming to beat.
    #
    # A quote of "37.74%" answers nothing on its own — the reader's alternative
    # is not zero, it is minting once at the same width and leaving it alone.
    # The baseline runs through the same ReplayDriver, the same tape, the same
    # CostModel and the same LVR accountant; only the function returning a
    # Decision differs. That is what makes the delta a claim about the policy
    # rather than about two differently-rigged programs.
    if baseline is not None:
        comparison = compare(
            task=f"{run['name']} — net return on a liquidity position",
            category="trading",
            venue=f"{TARGET_POOL.label} ({source} tape)",
            metric="net return on capital (fees − realized convexity cost − costs), P25–P75",
            without_agent="mint once at the same width, never touch it (passive_policy)",
            with_agent=run["name"],
            baseline_quote=baseline["quote"],
            agent_quote=quote,
            baseline_result=baseline["result"],
            agent_result=result,
        )
        payload["advantage"] = {
            "delta_pp": round(comparison.delta, 4),
            "material": comparison.material,
            "ranges_overlap": comparison.ranges_overlap,
            "separated": comparison.separated,
            "quotable": comparison.quotable,
            "verdict": comparison.verdict_line(),
            "without_agent": comparison.without_agent,
            "baseline": {
                "p25": round(comparison.baseline_p25, 4),
                "p50": round(comparison.baseline_p50, 4),
                "p75": round(comparison.baseline_p75, 4),
                "in_range_fraction": round(comparison.baseline_in_range, 4),
                "fees_quote": round(comparison.baseline_fees, 8),
                "lvr_quote_upper_bound": round(comparison.baseline_lvr, 8),
                "costs_quote": round(comparison.baseline_costs, 8),
                "moves": comparison.baseline_moves,
            },
        }

    path = out_dir / f"{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(REPO / "data" / "misquote.db"))
    parser.add_argument("--synthetic", type=int, default=0, help="use N synthetic swaps instead")
    parser.add_argument("--capital", type=float, default=DEFAULT_CAPITAL_QUOTE)
    parser.add_argument(
        "--jobs",
        type=int,
        default=(os.cpu_count() or 1),
        help="processes for the window replays; 1 for serial. Results are identical either way.",
    )
    parser.add_argument("--out", default=str(REPO / "apps" / "web" / "public" / "artifacts"))
    args = parser.parse_args()

    tape_gaps: list[tuple[int, int]] | None = None
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
            print("  uv run python -m misquote.indexer.backfill --days 30")
            print("  Free endpoints are enough: three of them serve eth_getLogs at 5,000")
            print("  blocks a request, and a 30-day tape is about an hour. See P-11.")
            return 1

        # The honest span is the blocks somebody *read*, not the distance between
        # the first event and the last. Those differ by exactly the size of any
        # hole, and a hole is invisible in the events themselves — a quiet window
        # and an unfetched one are both zero swaps. A card stamped `source: chain`
        # over a tape with a hole in it is the misquote this project exists to
        # argue against, so the gap count travels with the card.
        ends_span = (events[-1].ts - events[0].ts) / 86400
        tape_gaps = tape_coverage_gaps(db, events[0].block, events[-1].block)
        print(f"tape: {len(events):,} real swaps, {ends_span:.1f} days between the two ends")
        if tape_gaps is None:
            print("      coverage unrecorded — this tape predates the covered table,")
            print("      so completeness is unknown rather than confirmed")
        elif tape_gaps:
            missing = sum(hi - lo + 1 for lo, hi in tape_gaps)
            print(f"      *** {len(tape_gaps)} gap(s), {missing:,} blocks never read ***")
            print("      re-run the backfill to close them before publishing this")
        else:
            print("      no gaps: every block in that range was read")

    journal_dir = Path("data/journal")
    out_dir = Path(args.out)

    # Computed once, not once per agent. The passive baseline does not depend on
    # which agent it is being compared against, and each `run_agent` costs a full
    # replay plus twenty windows times three perturbations — so folding it into
    # the loop would have tripled the most expensive thing this script does to
    # produce three identical answers.
    jobs = args.jobs if args.jobs and args.jobs > 0 else None
    if jobs:
        print(f"replays: {jobs} processes (identical results — tests/replay/test_ranges.py)")

    print("baseline: passive_policy (mint once, never move) …")
    baseline = run_agent(
        "DIY (passive)", events, policy=passive_policy, capital=args.capital, jobs=jobs
    )

    runs = [
        run_agent("Warden", events, capital=args.capital, jobs=jobs),
        run_agent(
            "Grid",
            events,
            policy=lambda obs, params, meta: decide_grid(obs, GridParams(), meta),
            capital=args.capital,
            jobs=jobs,
        ),
        run_agent(
            "Sentinel",
            events,
            policy=sentinel_policy(SentinelParams()),
            capital=args.capital,
            jobs=jobs,
        ),
    ]

    print(f"\n  {COUNTERFACTUAL_BADGE}\n")
    for run in runs:
        path = emit(run, journal_dir, out_dir, source=source, baseline=baseline)
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
                "schema_version": 2,
                # Objects, not bare strings. The card page derived each agent's
                # filename by lowercasing its display name, so an agent called
                # "Foo Bar" would have silently 404'd. The slug is now emitted by
                # the same code that names the file.
                "agents": [
                    {
                        "name": r["name"],
                        "slug": r["name"].split()[0].lower(),
                        "category": CATEGORIES.get(r["name"], "Unclassified"),
                        "built": True,
                    }
                    for r in runs
                ],
                # The fourth category. Advertised in the README, absent from the
                # code, and previously absent from the UI too — which made the
                # omission invisible rather than disclosed.
                "not_built": ledger.to_dicts(),
                "pool": TARGET_POOL.label,
                "quote_symbol": TARGET_POOL.quote_symbol,
                "pool_address": TARGET_POOL.address,
                "counterfactual": True,
                "badge": COUNTERFACTUAL_BADGE,
                "source": source,
                "baseline": {
                    "name": baseline["name"],
                    "description": "mint once at the same width, never touch it (passive_policy)",
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"  index -> {index}")

    build = out_dir / "build.json"
    build.write_text(
        json.dumps(
            provenance.build_stamp(
                f"python scripts/showcase.py{f' --synthetic {args.synthetic}' if args.synthetic else ''}",
                source=source,
                events=len(events),
                capital_quote=args.capital,
                quote_symbol=TARGET_POOL.quote_symbol,
                span_hours=round((events[-1].ts - events[0].ts) / 3600, 2),
                # `span_hours` is the distance between the first event and the
                # last, so it counts any hole as though it were history. These
                # two say whether there is one. `null` means unrecorded, which is
                # neither "no gaps" nor "gaps" — see `tape_coverage_gaps`.
                tape_gaps=None if tape_gaps is None else len(tape_gaps),
                tape_blocks_unread=(
                    None if tape_gaps is None else sum(hi - lo + 1 for lo, hi in tape_gaps)
                ),
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"  build -> {build}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
