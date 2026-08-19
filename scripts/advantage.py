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
import os
import random
import sys
import time
from pathlib import Path

from misquote.agents.sentinel.policy import SentinelParams, sentinel_policy
from misquote.chain.addresses import TARGET_POOL, TARGET_POOL_WIDE
from misquote.core.liquidity import capital_for_liquidity_cap
from misquote.core.policy import passive_policy
from misquote.core.tickmath import Q96, get_sqrt_ratio_at_tick
from misquote.core.types import (
    DEFAULT_CAPITAL_QUOTE,
    SYNTHETIC_SWAP_SIZE_TOKEN0,
    Event,
    Params,
    PoolMeta,
)
from misquote.estimators.imbalance import ImbalanceEstimator
from misquote.ops.parallel import fork_map
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
    swap_size: int = SYNTHETIC_SWAP_SIZE_TOKEN0,
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

    **And so is the amount.** V-13 fixed the direction and left the magnitude:
    `amount1` was set equal to `amount0`, which asserts a price of 1.0 on a pool
    whose own tick says 0.001632 — 612.6x too much token1 on every swap, on the
    leg the fee accrues to. `scripts/showcase.py` carries the same note at
    length. Both amounts now come from the price, so the tape is a possible
    history by construction.

    `liquidity` stays a parameter because task 3 needs two venues of different
    depth; the 4x contrast at its call site is relative and survives this.
    """
    rng = random.Random(seed)
    events: list[Event] = []
    tick, ts = -64180, 1_700_000_000
    moves = (-9, -4, 0, 4, 9)
    for i in range(count):
        move = rng.choice(moves)
        if drift and rng.random() < drift:
            move = abs(move) or 4  # push it one way
        tick += move
        ts += rng.randint(5, 45)

        sqrt_price = get_sqrt_ratio_at_tick(tick)
        price = (sqrt_price / Q96) ** 2  # token1 per token0, raw units
        quote_amount = int(swap_size * price)

        # On the token1 leg, which is where `fee_protocol` is skimmed and what
        # the LVR accountant reads.
        fee = quote_amount * META.fee_pips // 10**6
        cut = fee * META.fee_protocol // 10_000

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
                liquidity=liquidity,
                tick=tick,
                protocol_fee0=0 if up else cut,
                protocol_fee1=cut if up else 0,
            )
        )
    return events


# Task 3's second venue. Same pair, one fee tier up, and — the field that makes
# a shared meta wrong — a different protocol fee: 3200 here against 3400 on the
# flagship. Running both tapes through `META` would credit this pool's liquidity
# providers with 66% of a fee they actually keep 68% of.
META_WIDE = PoolMeta(
    address=TARGET_POOL_WIDE.address,
    chain_id=TARGET_POOL_WIDE.chain_id,
    token0=TARGET_POOL_WIDE.token0,
    token1=TARGET_POOL_WIDE.token1,
    dec0=TARGET_POOL_WIDE.dec0,
    dec1=TARGET_POOL_WIDE.dec1,
    fee_pips=TARGET_POOL_WIDE.fee_pips,
    tick_spacing=TARGET_POOL_WIDE.tick_spacing,
    fee_protocol=TARGET_POOL_WIDE.fee_protocol,
)


def _run(
    events: list[Event],
    policy,
    *,
    capital: float,
    meta: PoolMeta = META,
    jobs: int | None = None,
    label: str = "",
):
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

    # Six of these per report, each 60 replays over half the tape. On the 30-day
    # chain tape that is 6.9 hours serial, measured — so it says where it is.
    # Timed from the first completed window rather than from entry, so the full
    # replay above and a pool that dispatches eight at once are not read as slow
    # replays. The first version reported "~67 min left" while doing better.
    began = [0.0]

    def progress(done: int, total: int) -> None:
        if done == 1:
            began[0] = time.monotonic()
        if label and (done == total or done % 10 == 0):
            elapsed = time.monotonic() - began[0]
            rate = elapsed / max(1, done - 1) if done > 1 else elapsed
            print(
                f"  {label}: {done}/{total} replays  ~{rate * (total - done) / 60:.0f} min left",
                flush=True,
            )

    quote = compute_quote(
        meta,
        factory,
        capital_quote=capital,
        windows=20,
        policy=policy,
        map_fn=fork_map(jobs) if jobs else None,
        on_progress=progress,
    )
    return result, quote


def task_earn(
    events: list[Event],
    *,
    capital: float,
    venue: str,
    jobs: int | None = None,
    source: str = "synthetic",
) -> Comparison:
    """Can an agent earn more than a position you mint once and forget?"""
    base_result, base_quote = _run(
        events, passive_policy, capital=capital, jobs=jobs, label="earn/baseline"
    )
    agent_result, agent_quote = _run(
        events, None, capital=capital, jobs=jobs, label="earn/warden"
    )  # None = Warden
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
        source=source,
    )


def task_protect(
    events: list[Event],
    *,
    capital: float,
    venue: str,
    jobs: int | None = None,
    source: str = "synthetic",
) -> Comparison:
    """Does leaving when flow turns one-way pay for itself?

    An ablation: the same agent, the same band, the same reanchoring, with only
    the withdrawal decision switched off in the baseline.
    """
    base_result, base_quote = _run(
        events,
        sentinel_policy(NEVER_WITHDRAW),
        capital=capital,
        jobs=jobs,
        label="protect/baseline",
    )
    agent_result, agent_quote = _run(
        events,
        sentinel_policy(SentinelParams()),
        capital=capital,
        jobs=jobs,
        label="protect/sentinel",
    )
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
        source=source,
    )


def venue_depth(events: list[Event]) -> int:
    """Median active liquidity across the tape — "how deep is this pool", read.

    Median rather than mean: v3 liquidity jumps when a large position is minted
    or burned, and one whale's week should not decide which venue gets called
    the deeper one for the whole month.

    This exists so that "pick the deepest pool" is a decision made from the tape
    rather than a label assigned by whoever wrote the task down. When both
    venues are real, which one is deeper is a fact — and it is a fact that can
    change between backfills.
    """
    depths = sorted(e.liquidity for e in events if e.liquidity > 0)
    if not depths:
        return 0
    return depths[len(depths) // 2]


def venue_toxicity(events: list[Event], meta: PoolMeta) -> float:
    """How often this venue's flow is one-way, by spec section 3.4's own arm.

    The fraction of samples whose trailing swap-imbalance z-score exceeds
    `z_pull`. Not a new metric invented for this task: it is the statistic
    Sentinel already withdraws on, computed by the same `ImbalanceEstimator`, so
    "the pool the agent's screen prefers" means the screen the agent actually
    runs and not a proxy for it.

    This closes the last place task 3 was deciding its own answer. Which venue is
    deeper is measured by `venue_depth`; the baseline picks that one. The agent's
    column was then simply *the other venue*, which quietly assumes the screen
    would disagree with depth — and if it would not, the task compares a pool to
    itself while reporting a difference. Now both columns are chosen by the rule
    that names them, and the two are allowed to land on the same pool.
    """
    params = Params()
    estimator = ImbalanceEstimator(dec1=meta.dec1, window_swaps=params.imbalance_window)
    fired = samples = 0
    for event in events:
        # Time first, then the event. `ingest` refuses anything dated after the
        # decision time — T3's guard, unconditional and with no flag to disable
        # it — so a scan like this one has to advance the clock to the event it
        # is about to absorb rather than reading the tape as a block.
        estimator.set_decision_time(event.ts)
        estimator.ingest(event)
        if not estimator.ready:
            continue
        samples += 1
        if abs(estimator.value()) > params.z_pull:
            fired += 1
    return fired / samples if samples else 0.0


def a1_ceiling(events: list[Event], meta: PoolMeta, *, half_width_ticks: int = 400) -> float:
    """The largest capital A1 permits on this venue, across the whole tape.

    A1's ceiling is `eps x pool_liquidity` — a property of the **pool**. The
    flagship carries roughly 191x the median liquidity of the 0.25% tier, so a
    capital that sits well inside A1 on one breaches it on the other, and A1 is
    explicit that such a quote is *refused rather than rendered*. Measured on the
    partial tape: at the report's default of 1.0 the wide venue refused on 564
    mints, and at 0.1 it still refused.

    Taken as the **minimum over the tape**, not the median. The ceiling has to
    hold at the tape's thinnest moment, because that is the mint that refuses —
    and one refusal withholds the whole quote.

    `half_width_ticks` is a representative range rather than the policy's own,
    which is not knowable before the run and depends on the capital this
    function is choosing. Wider ranges hold less liquidity per unit of capital,
    so a wide reference is the conservative direction.
    """
    params = Params()
    ceilings = []
    for event in events:
        if event.liquidity <= 0 or event.sqrt_price_x96 <= 0:
            continue
        lower = (event.tick - half_width_ticks) // meta.tick_spacing * meta.tick_spacing
        upper = (event.tick + half_width_ticks) // meta.tick_spacing * meta.tick_spacing
        ceilings.append(
            capital_for_liquidity_cap(
                event.sqrt_price_x96,
                get_sqrt_ratio_at_tick(lower),
                get_sqrt_ratio_at_tick(upper),
                dec1=meta.dec1,
                pool_liquidity=event.liquidity,
                eps=params.eps_liquidity_share,
            )
        )
    return min(ceilings) if ceilings else 0.0


def shared_capital(
    venues: list[tuple[list[Event], PoolMeta, str]], *, requested: float, margin: float = 0.5
) -> tuple[float, str]:
    """One capital both venues can honestly carry, and the sentence explaining it.

    Both columns of task 3 must run at the **same** capital or the comparison is
    between two position sizes as much as between two pools. The binding
    constraint is the shallower venue's A1 ceiling, so the shared figure is the
    smaller ceiling — never the requested capital when that would breach.

    The margin is not decoration. A capital computed to land exactly on the
    ceiling breaches it on the first swap that removes liquidity, and A1 refuses
    the whole quote when it does.
    """
    ceilings = [(label, a1_ceiling(events, meta)) for events, meta, label in venues]
    binding_label, binding = min(ceilings, key=lambda pair: pair[1])
    admissible = binding * margin

    if requested <= admissible:
        return requested, ""

    detail = " · ".join(f"{label}: {ceiling:.4g}" for label, ceiling in ceilings)
    return admissible, (
        f"Capital for this task is {admissible:.4g}, not the report's {requested:g}. "
        f"A1's ceiling is eps x pool liquidity and therefore a property of the pool, "
        f"and the shallower venue binds it — {detail} (at {margin:g}x margin). "
        f"Both columns run at the same figure, because a comparison between two "
        f"venues at two capitals is partly a comparison between two position sizes."
    )


def task_choose(
    venue_a: tuple[list[Event], PoolMeta, str],
    venue_b: tuple[list[Event], PoolMeta, str],
    *,
    capital: float,
    jobs: int | None = None,
    source: str = "synthetic",
) -> Comparison:
    """Does screening a pool before entering it beat picking the deepest one?

    Both columns run the *same* agent. The only difference is which venue it was
    pointed at: depth chose one, the flow screen chose the other. That isolates
    the due-diligence decision from the strategy entirely.

    **Which venue is "deepest" is read from the tapes, not assigned.** The two
    venues used to be `synthetic_events(drift=0.55, liquidity=4x)` and
    `synthetic_events(drift=0.0)`, where the deep-and-toxic one was deep and
    toxic by construction — the task could not have come out any other way, and
    a task whose answer is in its own setup is not evidence. With two real pools
    the ordering is a measurement, and it is allowed to disagree with what we
    expected.

    Each venue carries its own `PoolMeta`, because they differ in exactly the
    fields that decide what a swap is worth: fee tier, tick spacing, and
    `fee_protocol` — 3400 on the flagship, 3200 on the wide tier. Running both
    through one meta would price one of them wrongly and the difference would
    still render as a confident number of percentage points.
    """
    (events_a, meta_a, label_a), (events_b, meta_b, label_b) = venue_a, venue_b

    # A1 first, because it decides whether there is a task at all. Both columns
    # must run at one capital, and the shallower venue's ceiling binds it.
    capital, capital_note = shared_capital([venue_a, venue_b], requested=capital)
    if capital_note:
        print(f"  choose: {capital_note}")

    # Both columns are chosen by the rule that names them, and neither rule is
    # allowed to be "the pool the other one did not take".
    depth_a, depth_b = venue_depth(events_a), venue_depth(events_b)
    deep = venue_a if depth_a >= depth_b else venue_b
    deep_depth, screened_depth = max(depth_a, depth_b), min(depth_a, depth_b)
    ratio = deep_depth / screened_depth if screened_depth else float("inf")

    tox_a = venue_toxicity(events_a, meta_a)
    tox_b = venue_toxicity(events_b, meta_b)
    screened = venue_a if tox_a <= tox_b else venue_b

    print(
        f"  choose: deepest is {deep[2]} at {ratio:.1f}x the median liquidity "
        f"of the other — read from the tapes"
    )
    print(
        f"  choose: §3.4 imbalance fires on {tox_a:.1%} of samples on {label_a} "
        f"and {tox_b:.1%} on {label_b}; the screen takes {screened[2]}"
    )

    # The two rules may agree, and if they do the honest report is that they
    # agreed — not a difference manufactured by handing the agent whichever pool
    # depth did not pick. The synthetic setup could never produce this case,
    # because it built one venue deep-and-toxic on purpose.
    rules_agree = deep[2] == screened[2]
    if rules_agree:
        print("  choose: the screen agrees with the depth heuristic — nothing to report")

    base_result, base_quote = _run(
        deep[0], None, capital=capital, meta=deep[1], jobs=jobs, label="choose/deepest"
    )
    agent_result, agent_quote = _run(
        screened[0], None, capital=capital, meta=screened[1], jobs=jobs, label="choose/screened"
    )
    return compare(
        task="Choose — which pool to provide liquidity to",
        category="security",
        venue=(
            f"two venues: {label_a} vs {label_b}"
            + (" — depth and the flow screen chose the same one" if rules_agree else "")
        ),
        metric=(
            "net return on capital of the same agent on the chosen venue, P25–P75"
            + (f". {capital_note}" if capital_note else "")
        ),
        without_agent=(
            f"pick the deepest pool — {deep[2]}, {ratio:.1f}x the median liquidity "
            "(the obvious heuristic: more TVL is safer)"
        ),
        with_agent=(
            f"pick the pool whose flow is not one-way — {screened[2]}, where §3.4's "
            f"imbalance arm fires on {min(tox_a, tox_b):.1%} of samples against "
            f"{max(tox_a, tox_b):.1%} on the other"
            + (" — which is the pool depth chose too" if rules_agree else "")
        ),
        baseline_quote=base_quote,
        agent_quote=agent_quote,
        baseline_result=base_result,
        agent_result=agent_result,
        source=source,
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
        # The report-level flag stays, but it is now derived from the tasks
        # rather than asserted over them: a run where any task fell back to a
        # constructed tape is "mixed", not "chain".
        "source": (source if all(c.source == source for c in comparisons) else "mixed"),
        "capital_quote": capital,
        # token1, which is WBNB here and not the USDT the pair label
        # reads as. See the note on `PoolRef.quote_symbol`.
        "quote_symbol": TARGET_POOL.quote_symbol,
        "summary": summarise(comparisons),
        "overall": {"called": overall(comparisons).called, "label": str(overall(comparisons))},
        "tasks": [
            {
                "task": c.task,
                "category": c.category,
                "venue": c.venue,
                # Per task, because the report-level flag cannot see a synthetic
                # venue inside an otherwise chain-sourced run. `go_no_go` gates
                # on every task carrying "chain", not on this report's header.
                "source": c.source,
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


def build(
    events: list[Event],
    *,
    capital: float,
    venue: str,
    jobs: int | None = None,
    source: str = "synthetic",
    second_venue: tuple[list[Event], PoolMeta, str] | None = None,
) -> list[Comparison]:
    """The three tasks. Kept separate from I/O so a test can call it directly."""
    earn = task_earn(events, capital=capital, venue=venue, jobs=jobs, source=source)
    protect = task_protect(events, capital=capital, venue=venue, jobs=jobs, source=source)

    # Task 3's second venue is built here rather than at the top of this
    # function, which is where it used to be. Its tapes are each `len(events)`
    # long — on the 30-day chain tape that is a further ~500MB beside the real
    # one — and tasks 1 and 2 never touch them. Holding them through those tasks
    # costs memory for a third of the run, while eight forked workers compete
    # for it.
    #
    # That is not a tidiness point. The parallel replay was measured to be bound
    # by memory bandwidth rather than by cores: eight workers sit at 82% CPU and
    # deliver 3x, not 8x. Memory held for no reason is the one resource actually
    # in contention.
    if second_venue is not None:
        choose_source = source
        venue_a = (events, META, TARGET_POOL.label)
        venue_b = second_venue
    else:
        # No second real tape, so the task falls back to two constructed venues
        # — and says so, per task, rather than inheriting the report's flag.
        # `make advantage-demo` lives here; `make advantage` should not.
        #
        # Same seeds, same lengths, same order of results as before.
        choose_source = "synthetic"
        deep_toxic = synthetic_events(
            len(events), seed=11, drift=0.55, liquidity=4 * 1_275_390_104_039_763_402_054_142
        )
        shallow_healthy = synthetic_events(len(events), seed=11, drift=0.0)
        # Named neutrally: which of the two is deeper is now measured from the
        # tape by `venue_depth`, so a label asserting it would be a second,
        # unchecked source of truth for the same fact.
        venue_a = (deep_toxic, META, "a one-way venue (synthetic)")
        venue_b = (shallow_healthy, META, "a balanced venue (synthetic)")

    choose = task_choose(venue_a, venue_b, capital=capital, jobs=jobs, source=choose_source)

    return [earn, protect, choose]


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
    parser.add_argument("--out", default=str(REPO / "docs" / "AGENT_ADVANTAGE.md"))
    parser.add_argument(
        "--artifact", default=str(REPO / "apps" / "web" / "public" / "artifacts" / "advantage.json")
    )
    args = parser.parse_args()

    second_venue = None
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
            print("  uv run python -m misquote.indexer.backfill --days 30")
            print("  Free endpoints are enough — measured, 1,151 chunks with zero refused.")
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

        # Task 3's second venue, if it has been indexed. Read from the same
        # database, over the same blocks — a second pool covering a different
        # month would make the comparison a statement about two time periods
        # rather than about two pools, and it would still produce a number.
        conn = store.connect(db)
        try:
            wide = list(store.read_swaps(conn, META_WIDE.address))
        finally:
            conn.close()
        if wide:
            lo, hi = max(events[0].block, wide[0].block), min(events[-1].block, wide[-1].block)
            events = [e for e in events if lo <= e.block <= hi]
            wide = [e for e in wide if lo <= e.block <= hi]
            second_venue = (wide, META_WIDE, TARGET_POOL_WIDE.label)
            print(
                f"      + {len(wide):,} real swaps on {TARGET_POOL_WIDE.label} "
                f"(task 3's second venue)"
            )
            print(f"      both tapes clipped to blocks {lo:,}-{hi:,}, the range they share")
        else:
            print(
                f"      no tape for {TARGET_POOL_WIDE.label} — task 3 falls back to\n"
                f"      two synthetic venues and will be labelled as such.\n"
                f"      uv run python -m misquote.indexer.backfill "
                f"--pool {TARGET_POOL_WIDE.address} \\\n"
                f"        --from-block {events[0].block} --to-block {events[-1].block}"
            )

    jobs = args.jobs if args.jobs and args.jobs > 0 else None
    if jobs:
        print(f"replays: {jobs} processes (identical results — tests/replay/test_ranges.py)")
    comparisons = build(
        events,
        capital=args.capital,
        venue=venue,
        jobs=jobs,
        source=source,
        second_venue=second_venue,
    )

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
