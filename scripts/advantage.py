"""The Agent Advantage Report: three tasks, each done with and without an agent.

    uv run python scripts/advantage.py --synthetic 9000
    uv run python scripts/advantage.py                    # from the indexed tape

This is the TermiX track's deliverable and the one question it judges: *does
hiring an agent on your marketplace beat doing the job yourself, and can you
prove it?*

**Every number here comes out of the replay engine.** There are no literals in
this file that reach the report — `tests/tearsheet/test_advantage.py` asserts it
by running the engine itself and comparing. If a figure changed, the evidence
changed.

## The three tasks, and why the baselines differ

The weakness to avoid is three tasks that are secretly one task relabelled. Each
baseline below is a genuinely different "what you would have done":

**1 · Earn** — *baseline: mint once at the same width and never touch it.*
Isolates the recentring decision. `passive_policy` already exists for exactly
this: it is spec §4.1's comparator and test T4's instrument.

**2 · Protect** — *baseline: the same agent with its withdrawal disabled.*
Sentinel against Sentinel-that-never-pulls: identical band, identical
reanchoring, and the **only** difference is whether it leaves when flow turns
one-way. An ablation rather than a different program, so the comparison is about
the withdrawal decision and nothing else. Using `passive_policy` here again would
have made task 2 task 1 with a different label — and would have confounded the
withdrawal decision with a change of band width.

**3 · Choose** — *baseline: pick the deepest pool.* Two venues, and the agent's
screen prefers the one whose flow is not one-way while depth prefers the other.
This is the task where doing it yourself is not "do nothing" but "use the obvious
heuristic", which is what an LP actually does. Deeper is not safer, and that is
the finding the task exists to test.

## Sign

`delta` is agent minus baseline. It is allowed to be negative and is not clamped,
reordered, or hidden. On a driftless random walk with a tight range, active
recentring pays gas for nothing — we have already published that result once and
this report will publish it again if it holds.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from misquote.agents.sentinel.policy import SentinelParams, sentinel_policy
from misquote.chain.addresses import TARGET_POOL
from misquote.core.policy import passive_policy
from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import Event, PoolMeta
from misquote.replay.driver import CostModel, ReplayDriver
from misquote.replay.ranges import quote as compute_quote
from misquote.replay.tape import MemoryTape
from misquote.tearsheet.advantage import Comparison, compare, overall, summarise

REPO = Path(__file__).resolve().parents[1]

COUNTERFACTUAL_BADGE = "COUNTERFACTUAL — neither position was held"

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

# Sentinel with withdrawal switched off: `held_for >= min_hold_s` can never hold,
# so the pull branch is unreachable while every other behaviour is identical.
# This is task 2's baseline and the reason it is an ablation rather than a
# different program.
NEVER_WITHDRAW = SentinelParams(min_hold_s=10**9)


def synthetic_events(
    count: int,
    *,
    seed: int = 7,
    swap_size: int = 10**23,
    drift: float = 0.0,
    liquidity: int = 1_275_390_104_039_763_402_054_142,
) -> list[Event]:
    """A stand-in tape, clearly labelled as one wherever it is used.

    `drift` biases the direction of flow in [0, 1): 0.0 is the balanced random
    walk the showcase uses, and higher values push a growing share of swaps the
    same way — which is what one-way, informed-looking flow looks like from
    inside the pool. It is how task 3 gets a venue whose flow is toxic without
    pretending to have found one on chain.

    Direction is derived from the price move rather than asserted beside it. See
    matrix V-13: the previous generator emitted swaps no AMM could produce, and
    nothing noticed until the imbalance z-score was wired up.
    """
    rng = random.Random(seed)
    events: list[Event] = []
    tick, ts = -64180, 1_700_000_000
    fee = swap_size * META.fee_pips // 10**6
    cut = fee * META.fee_protocol // 10_000
    moves = (-9, -4, 0, 4, 9)
    for i in range(count):
        move = rng.choice(moves)
        if drift and rng.random() < drift:
            move = abs(move) or 4  # push it one way
        tick += move
        ts += rng.randint(5, 45)
        up = move > 0 if move != 0 else i % 2 == 0
        events.append(
            Event(
                block=1_000_000 + i,
                log_index=0,
                ts=ts,
                kind="swap",
                tx=f"0x{i:064x}",
                amount0=-swap_size if up else swap_size,
                amount1=swap_size if up else -swap_size,
                sqrt_price_x96=get_sqrt_ratio_at_tick(tick),
                liquidity=liquidity,
                tick=tick,
                protocol_fee0=0 if up else cut,
                protocol_fee1=cut if up else 0,
            )
        )
    return events


def _run(events: list[Event], policy, *, capital: float, meta: PoolMeta = META):
    """One replay and one quote, through the engine, for a given policy.

    `policy=None` means Warden. Both columns of every comparison go through this
    same function, which is what makes "the baseline is not a different program"
    a structural fact rather than a promise.
    """
    driver = ReplayDriver(meta, costs=CostModel(), capital_quote=capital, policy=policy)
    result = driver.run(MemoryTape(events))

    def factory(start, end):
        if start is None:
            return MemoryTape(events)
        return MemoryTape([e for e in events if start <= e.ts <= end])

    quote = compute_quote(meta, factory, capital_quote=capital, windows=20, policy=policy)
    return result, quote


def task_earn(events: list[Event], *, capital: float, venue: str) -> Comparison:
    """Can an agent earn more than a position you mint once and forget?"""
    base_result, base_quote = _run(events, passive_policy, capital=capital)
    agent_result, agent_quote = _run(events, None, capital=capital)  # None = Warden
    return compare(
        task="Earn — fees on a liquidity position",
        category="trading",
        venue=venue,
        metric="net return on capital (fees − realized convexity cost − costs), P25–P75",
        without_agent="mint once at the same width, never touch it (passive_policy)",
        with_agent="Warden — Avellaneda–Stoikov recentring",
        baseline_quote=base_quote,
        agent_quote=agent_quote,
        baseline_result=base_result,
        agent_result=agent_result,
    )


def task_protect(events: list[Event], *, capital: float, venue: str) -> Comparison:
    """Does leaving when flow turns one-way pay for itself?

    An ablation: the same agent, the same band, the same reanchoring, with only
    the withdrawal decision switched off in the baseline.
    """
    base_result, base_quote = _run(events, sentinel_policy(NEVER_WITHDRAW), capital=capital)
    agent_result, agent_quote = _run(events, sentinel_policy(SentinelParams()), capital=capital)
    return compare(
        task="Protect — avoid being picked off by one-way flow",
        category="security",
        venue=venue,
        metric="net return on capital, P25–P75 (the cost of the withdrawals is charged in full)",
        without_agent="the same wide band, held through everything (withdrawal disabled)",
        with_agent="Sentinel — withdraw on §3.4 toxicity, re-enter after m_clear",
        baseline_quote=base_quote,
        agent_quote=agent_quote,
        baseline_result=base_result,
        agent_result=agent_result,
    )


def task_choose(
    deep_toxic: list[Event], shallow_healthy: list[Event], *, capital: float
) -> Comparison:
    """Does screening a pool before entering it beat picking the deepest one?

    Both columns run the *same* agent. The only difference is which venue it was
    pointed at: depth chose one, the flow screen chose the other. That isolates
    the due-diligence decision from the strategy entirely.
    """
    base_result, base_quote = _run(deep_toxic, None, capital=capital)
    agent_result, agent_quote = _run(shallow_healthy, None, capital=capital)
    return compare(
        task="Choose — which pool to provide liquidity to",
        category="security",
        venue="two venues: deeper-but-one-way vs shallower-but-balanced",
        metric="net return on capital of the same agent on the chosen venue, P25–P75",
        without_agent="pick the deepest pool (the obvious heuristic: more TVL is safer)",
        with_agent="pick the pool whose flow is not one-way (§3.4 imbalance screen)",
        baseline_quote=base_quote,
        agent_quote=agent_quote,
        baseline_result=base_result,
        agent_result=agent_result,
    )


# --- rendering --------------------------------------------------------------


def render_markdown(comparisons: list[Comparison], *, source: str, capital: float) -> str:
    summary = summarise(comparisons)
    call = overall(comparisons)

    lines = [
        "# Agent Advantage Report",
        "",
        "**Does hiring an agent beat doing the job yourself, and can we prove it?**",
        "",
        f"> **{COUNTERFACTUAL_BADGE}.** Every position priced here is a replay, not a",
        "> record. No capital was deployed. Published as assumption A6.",
        "",
        f"- **Tape:** `{source}`",
        f"- **Capital per task:** {capital:,.0f} (quote token)",
        f"- **Tasks:** {summary['tasks']} · quotable {summary['quotable']} ·"
        f" withheld {summary['withheld']}",
        f"- **Categories:** {', '.join(summary['categories'])}",
        "",
        "## The claim this report is allowed to make",
        "",
        "The baseline is **not a different program**. Every column runs through the",
        "same `ReplayDriver`, the same tape, the same cost model, the same LVR",
        "accountant and the same quote machinery. The only thing that differs is the",
        "function that returns a `Decision`. Swap `policy=` and everything else is",
        "held fixed by construction — which is why the usual way of flattering an",
        "agent, by charging its baseline differently, is not available here.",
        "",
        "## Results",
        "",
        "| Task | Category | DIY (P25–P75) | Agent (P25–P75) | Δ median | Verdict |",
        "|---|---|---|---|---|---|",
    ]

    for c in comparisons:
        if c.quotable:
            diy = f"{c.baseline_p25:.2f} – {c.baseline_p75:.2f}%"
            agent = f"{c.agent_p25:.2f} – {c.agent_p75:.2f}%"
            delta = f"**{c.delta:+.2f}pp**"
        else:
            diy = agent = delta = "withheld"
        lines.append(
            f"| {c.task} | {c.category} | {diy} | {agent} | {delta} | {c.verdict_line()} |"
        )

    lines += [
        "",
        f"**Across all tasks:** {call}",
        "",
        "That refusal is deliberate and it is the honest headline. `verdict()` will",
        "not call a rate on fewer than 30 observations, and three tasks are three",
        "observations. What carries the argument is each task's own quote, where the",
        "sample is 20 sub-windows × 3 parameter perturbations rather than one run.",
        "",
        "## Task detail",
        "",
    ]

    for c in comparisons:
        lines += [
            f"### {c.task}",
            "",
            f"- **Category:** {c.category} · **Venue:** {c.venue}",
            f"- **Without an agent:** {c.without_agent}",
            f"- **With an agent:** {c.with_agent}",
            f"- **Metric:** {c.metric}",
            "",
        ]
        if not c.quotable:
            lines += [f"**No verdict.** {c.note}", ""]
            continue
        lines += [
            "| | DIY | Agent |",
            "|---|---|---|",
            f"| Net return P25–P75 | {c.baseline_p25:.2f} – {c.baseline_p75:.2f}% "
            f"| {c.agent_p25:.2f} – {c.agent_p75:.2f}% |",
            f"| Median | {c.baseline_p50:.2f}% | {c.agent_p50:.2f}% |",
            f"| In range | {c.baseline_in_range:.1%} | {c.agent_in_range:.1%} |",
            f"| Fees | {c.baseline_fees:.4f} | {c.agent_fees:.4f} |",
            f"| Realized convexity cost (upper bound on LVR) | {c.baseline_lvr:.4f} "
            f"| {c.agent_lvr:.4f} |",
            f"| Costs charged | {c.baseline_costs:.2f} | {c.agent_costs:.2f} |",
            f"| Moves | {c.baseline_moves} | {c.agent_moves} |",
            "",
            f"**{c.verdict_line()}**",
            "",
            f"Bands overlap: **{'yes' if c.ranges_overlap else 'no'}**. "
            + (
                "Overlapping bands mean the two are not distinguishable at this sample "
                "size, however far apart the medians sit — which is precisely why this "
                "product publishes ranges rather than a single number."
                if c.ranges_overlap
                else "Non-overlapping bands are what lets the difference be stated at all."
            ),
            "",
        ]

    lines += [
        "## What would make this stronger",
        "",
        "- **A real tape.** These runs are labelled above. Free BSC endpoints refuse a",
        "  multi-day backfill — six hours of the target pool dies in 11 seconds with",
        "  `-32005 limit exceeded` — so the report needs a keyed `BSC_RPC_URL` before",
        "  the word *real* in the track's requirement is earned.",
        "- Every assumption behind these numbers is in [`ASSUMPTIONS.md`](ASSUMPTIONS.md);",
        "  every deviation from the frozen spec, with its arithmetic, is in",
        "  [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md).",
        "",
    ]
    return "\n".join(lines)


def to_payload(comparisons: list[Comparison], *, source: str, capital: float) -> dict:
    return {
        "report": "Agent Advantage",
        "question": (
            "Does hiring an agent on your marketplace beat doing the job yourself, "
            "and can you prove it?"
        ),
        "counterfactual": True,
        "badge": COUNTERFACTUAL_BADGE,
        "source": source,
        "capital_quote": capital,
        "summary": summarise(comparisons),
        "overall": {"called": overall(comparisons).called, "label": str(overall(comparisons))},
        "tasks": [
            {
                "task": c.task,
                "category": c.category,
                "venue": c.venue,
                "metric": c.metric,
                "without_agent": c.without_agent,
                "with_agent": c.with_agent,
                "quotable": c.quotable,
                "note": c.note,
                "baseline": {
                    "p25": round(c.baseline_p25, 6),
                    "p50": round(c.baseline_p50, 6),
                    "p75": round(c.baseline_p75, 6),
                    "in_range": round(c.baseline_in_range, 4),
                    "fees": round(c.baseline_fees, 8),
                    "lvr_upper_bound": round(c.baseline_lvr, 8),
                    "costs": round(c.baseline_costs, 8),
                    "moves": c.baseline_moves,
                },
                "agent": {
                    "p25": round(c.agent_p25, 6),
                    "p50": round(c.agent_p50, 6),
                    "p75": round(c.agent_p75, 6),
                    "in_range": round(c.agent_in_range, 4),
                    "fees": round(c.agent_fees, 8),
                    "lvr_upper_bound": round(c.agent_lvr, 8),
                    "costs": round(c.agent_costs, 8),
                    "moves": c.agent_moves,
                },
                "delta_pp": round(c.delta, 6),
                "ranges_overlap": c.ranges_overlap,
                "material": c.material,
                "separated": c.separated,
                "verdict": c.verdict_line(),
            }
            for c in comparisons
        ],
    }


def build(events: list[Event], *, capital: float, venue: str) -> list[Comparison]:
    """The three tasks. Kept separate from I/O so a test can call it directly."""
    deep_toxic = synthetic_events(
        len(events), seed=11, drift=0.55, liquidity=4 * 1_275_390_104_039_763_402_054_142
    )
    shallow_healthy = synthetic_events(len(events), seed=11, drift=0.0)
    return [
        task_earn(events, capital=capital, venue=venue),
        task_protect(events, capital=capital, venue=venue),
        task_choose(deep_toxic, shallow_healthy, capital=capital),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(REPO / "data" / "misquote.db"))
    parser.add_argument("--synthetic", type=int, default=0, help="use N synthetic swaps instead")
    parser.add_argument("--capital", type=float, default=1000.0)
    parser.add_argument("--out", default=str(REPO / "docs" / "AGENT_ADVANTAGE.md"))
    parser.add_argument(
        "--artifact", default=str(REPO / "apps" / "web" / "public" / "artifacts" / "advantage.json")
    )
    args = parser.parse_args()

    if args.synthetic:
        events = synthetic_events(args.synthetic)
        source = "synthetic"
        venue = f"{TARGET_POOL.label} (synthetic tape)"
        print(f"tape: {len(events):,} SYNTHETIC swaps (no chain data)")
    else:
        from misquote.indexer import store

        db = Path(args.db)
        if not db.exists():
            print(f"no tape at {db}.")
            print("  Run the backfill first, or pass --synthetic 9000.")
            print("  The backfill needs a keyed BSC_RPC_URL: six hours of the target pool")
            print("  dies in 11 seconds with -32005 on free endpoints.")
            return 1
        conn = store.connect(db)
        try:
            events = list(store.read_swaps(conn, META.address))
        finally:
            conn.close()
        if not events:
            print(f"tape at {db} is empty. Run the backfill.")
            return 1
        source = "chain"
        venue = TARGET_POOL.label
        span = (events[-1].ts - events[0].ts) / 86400
        print(f"tape: {len(events):,} real swaps spanning {span:.1f} days")

    comparisons = build(events, capital=args.capital, venue=venue)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(comparisons, source=source, capital=args.capital) + "\n")

    artifact = Path(args.artifact)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(to_payload(comparisons, source=source, capital=args.capital), indent=2) + "\n"
    )

    print(f"\n  {COUNTERFACTUAL_BADGE}\n")
    for c in comparisons:
        print(f"  {c.task}")
        print(f"    without   {c.without_agent}")
        print(f"    with      {c.with_agent}")
        if c.quotable:
            print(f"    DIY       {c.baseline_p25:.2f}% to {c.baseline_p75:.2f}%")
            print(f"    agent     {c.agent_p25:.2f}% to {c.agent_p75:.2f}%")
            print(f"    delta     {c.delta:+.2f}pp")
        print(f"    -> {c.verdict_line()}")
        print()
    print(f"  across all tasks: {overall(comparisons)}")
    print(f"  report   -> {out}")
    print(f"  artifact -> {artifact}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
