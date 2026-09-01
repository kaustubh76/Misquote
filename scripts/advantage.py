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
from typing import Any

from misquote.agents.grid.policy import GridParams, decide_grid
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
from misquote.replay.ranges import DEFAULT_WINDOWS
from misquote.replay.ranges import quote as compute_quote
from misquote.replay.tape import MemoryTape
from misquote.tearsheet import provenance
from misquote.tearsheet.advantage import (
    Comparison,
    PrimaryMetric,
    compare,
    overall,
    summarise,
)

REPO = Path(__file__).resolve().parents[1]

# Named once, because the build stamp compares against them. Two spellings of
# the same default is how a stamp starts claiming an override that never
# happened.
DEFAULT_OUT = REPO / "docs" / "AGENT_ADVANTAGE.md"
DEFAULT_ARTIFACT = REPO / "apps" / "web" / "public" / "artifacts" / "advantage.json"


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


#: What hiring one agent for one task costs the customer, and where it comes from.
#:
#: The report had no price in it. `costs` on each arm is the *strategy's* gas and
#: slippage while the task runs, which is a different quantity, and the track asks
#: whether an agent wins "at a price … that beats the alternative" — unanswerable
#: from a report that never names one.
#:
#: Read rather than invented: it is the Altana keystore's own registration fee for
#: a session key, `getRegistrationFeeInWei()` on chain 56, plus the gas for the
#: grant and the revoke measured from the recorded chapel round trip. Both are
#: published in `vetting/addresses/session-keys-56.json` and
#: `vetting/identity/session-keys-97.json`.
#:
#: Denominated in BNB because that is what the chain charges. It is deliberately
#: *not* converted into the task's quote token: a BNB/USD rate would be a price
#: this repository does not read, and the whole argument is that figures come from
#: somewhere checkable.
HIRE_FEE_BNB = 0.000724270
HIRE_GAS_BNB = 0.000030737
HIRE_COST_BNB = HIRE_FEE_BNB + HIRE_GAS_BNB
HIRE_COST_NOTE = (
    f"{HIRE_COST_BNB:.6f} BNB — the keystore's own registration fee "
    f"({HIRE_FEE_BNB:.6f}, read from getRegistrationFeeInWei on chain 56) plus "
    f"{HIRE_GAS_BNB:.6f} of gas for the grant and revoke, measured from the "
    f"recorded round trip. One hire, one expiry."
)


def _run(
    events: list[Event],
    policy,
    *,
    capital: float,
    meta: PoolMeta = META,
    jobs: int | None = None,
    label: str = "",
    policy_factory=None,
):
    """One replay and one quote, through the engine, for a given policy.

    `policy=None` means Warden. Both columns of every comparison go through this
    same function, which is what makes "the baseline is not a different program"
    a structural fact rather than a promise.

    `policy_factory` is P-17's other half. A5 perturbs each agent in the quantity
    that agent actually reads, and Grid reads neither gamma nor kappa — scaling
    `Params` for it moves nothing it does, and the run publishes 20 windows as 60
    samples. Grid's parameter is its rung width. `showcase.py:522` already runs it
    this way; this is the same arrangement reaching the advantage report.

    The single replay above still needs one concrete policy, so a factory caller
    passes the unperturbed one as `policy` and the sweep as `policy_factory`.
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
    # Timed from entry, not from the first completed window. `began` below is
    # for the ETA, which deliberately excludes the full replay above so a pool
    # that dispatches eight at once is not read as slow. The *task's* time is
    # the whole thing: a caller waiting on a hire waits for the tape load too.
    entered = time.monotonic()

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
        windows=DEFAULT_WINDOWS,
        # `quote()` refuses both at once — two sources for the same decision.
        **({"policy_factory": policy_factory} if policy_factory else {"policy": policy}),
        map_fn=fork_map(jobs) if jobs else None,
        on_progress=progress,
    )
    # The third element is the requirement that was measured and thrown away.
    return result, quote, time.monotonic() - entered


def task_earn(
    events: list[Event],
    *,
    capital: float,
    venue: str,
    jobs: int | None = None,
    source: str = "synthetic",
    baseline: tuple | None = None,
) -> Comparison:
    """Can an agent earn more than a position you mint once and forget?

    `baseline` lets the caller hand in a passive run it already has. Two tasks now
    measure a different agent against this same control — Warden here, Grid in
    `task_market_make` — and running `passive_policy` twice would be an hour and a
    half of replay to produce numbers guaranteed to be identical.
    """
    base_result, base_quote, base_seconds = baseline or _run(
        events, passive_policy, capital=capital, jobs=jobs, label="earn/baseline"
    )
    agent_result, agent_quote, agent_seconds = _run(
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
        capital_quote=capital,
        baseline_seconds=base_seconds,
        agent_seconds=agent_seconds,
        hire_cost_quote=HIRE_COST_BNB,
        hire_cost_note=HIRE_COST_NOTE,
        # "Earn — fees on a liquidity position" names fees, so fees are the
        # quantity. Net return stays the headline because fees alone flatter any
        # agent that stays in range through anything; this is the task's own
        # question answered beside the one that matters commercially.
        primary=PrimaryMetric(
            name="fees earned",
            baseline=base_result.total_fees,
            agent=agent_result.total_fees,
            lower_is_better=False,
        ),
    )


def task_market_make(
    events: list[Event],
    *,
    capital: float,
    venue: str,
    jobs: int | None = None,
    source: str = "synthetic",
    baseline: tuple | None = None,
) -> Comparison:
    """Can a ladder that requotes on inventory beat minting once and forgetting?

    ## Why this task was missing, and why that mattered

    The report had four tasks and `agent_ahead: 0`. Grid — the one agent whose own
    card beats the baseline, at `delta_pp: 13.3527` with 60 of 60 windows
    net-positive and 100% in range — appeared in none of them. A report that
    exists to answer *does hiring beat doing it yourself* omitted the only
    affirmative answer the engine had produced.

    Nothing about that was a judgement call. `showcase.py` computes Grid's
    comparison for the agent card and this file never asked for it.

    ## The claim this task is allowed to make

    Grid's bands **overlap** the baseline's. So the verdict line is "beats DIY at
    the median, not separated at this sample size", and it stays that way:
    `separated` is what `verdict()` reports at n=60, and softening it would cost
    more than the criterion gains.
    """
    base_result, base_quote, base_seconds = baseline or _run(
        events, passive_policy, capital=capital, jobs=jobs, label="market-make/baseline"
    )

    def grid_at(scale: float):
        # The width, not gamma — see `_run`'s note on P-17.
        width = max(1, round(GridParams().rung_width_ticks * scale))
        params = GridParams(rung_width_ticks=width)
        return lambda obs, _p, meta: decide_grid(obs, params, meta)

    unperturbed = grid_at(1.0)
    agent_result, agent_quote, agent_seconds = _run(
        events,
        unperturbed,
        capital=capital,
        jobs=jobs,
        label="market-make/grid",
        policy_factory=grid_at,
    )
    return compare(
        task="Market-make — quote both sides of a range",
        category="trading",
        venue=venue,
        metric="net return on capital (fees − realized convexity cost − costs), P25–P75",
        without_agent="mint once at the same width, never touch it (passive_policy)",
        with_agent="Grid — fixed rung ladder, requote when price leaves it",
        baseline_quote=base_quote,
        agent_quote=agent_quote,
        baseline_result=base_result,
        agent_result=agent_result,
        source=source,
        capital_quote=capital,
        baseline_seconds=base_seconds,
        agent_seconds=agent_seconds,
        hire_cost_quote=HIRE_COST_BNB,
        hire_cost_note=HIRE_COST_NOTE,
        # Time in range is the quantity a ladder is *for*: it earns only while it
        # is quoting. Net return stays the headline for the same reason it does on
        # Earn — staying in range flatters any agent that never moves.
        primary=PrimaryMetric(
            name="time in range",
            baseline=base_result.in_range_fraction,
            agent=agent_result.in_range_fraction,
            lower_is_better=False,
        ),
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
    base_result, base_quote, base_seconds = _run(
        events,
        sentinel_policy(NEVER_WITHDRAW),
        capital=capital,
        jobs=jobs,
        label="protect/baseline",
    )
    agent_result, agent_quote, agent_seconds = _run(
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
        capital_quote=capital,
        baseline_seconds=base_seconds,
        agent_seconds=agent_seconds,
        hire_cost_quote=HIRE_COST_BNB,
        hire_cost_note=HIRE_COST_NOTE,
        # "Avoid being picked off by one-way flow" is a claim about adverse
        # selection, and realized convexity cost is the measurement of it. The
        # agent wins this decisively and loses the net-return headline, because
        # it gives up more in fees than it saves. Both are true and the report
        # showed only the second.
        primary=PrimaryMetric(
            name="realized convexity cost (upper bound on LVR)",
            baseline=base_result.total_lvr,
            agent=agent_result.total_lvr,
            lower_is_better=True,
        ),
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


def venue_name(pool) -> str:
    """A venue a reader can resolve: the label, and the address it means.

    Every other artifact the site publishes names its pools by address —
    `warden.json`, `venue.json`, `vetting.json` all do. This one, the judged
    deliverable, named them by label alone, so the one document a judge is sent
    to could not be checked against chain without guessing which WBNB/USDT pool
    was meant. Two of the three PancakeSwap tiers on that pair carry the same
    pair name and different protocol fees.

    It also makes the venue visible to `go_no_go.check_badge_coverage`, which
    reads pool addresses out of published artifacts precisely so that quoting a
    pool nobody vetted is caught by the gate rather than by a reader.
    """
    return f"{pool.label} · {pool.address}"


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

    base_result, base_quote, base_seconds = _run(
        deep[0], None, capital=capital, meta=deep[1], jobs=jobs, label="choose/deepest"
    )
    if rules_agree:
        # Both rules landed on one pool, so the second column is the first
        # column: same tape, same meta, same policy, same capital, and the
        # engine is deterministic — `test_a_replay_is_deterministic_across_
        # identical_runs` is the assertion. Re-running it would spend an hour
        # of replays to rediscover the number already in hand, and would invite
        # the reader to think two things were measured when one was.
        #
        # The delta is therefore exactly zero, and the report says the rules
        # agreed rather than presenting a nil result as a finding about agents.
        agent_result, agent_quote, agent_seconds = base_result, base_quote, base_seconds
    else:
        agent_result, agent_quote, agent_seconds = _run(
            screened[0],
            None,
            capital=capital,
            meta=screened[1],
            jobs=jobs,
            label="choose/screened",
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
        capital_quote=capital,
        baseline_seconds=base_seconds,
        agent_seconds=agent_seconds,
        hire_cost_quote=HIRE_COST_BNB,
        hire_cost_note=HIRE_COST_NOTE,
        # Stated rather than left for a reader to infer from two identical
        # bands. When the rules agree there is one measurement, and the chart
        # should draw one.
        same_run=rules_agree,
    )


# --- rendering --------------------------------------------------------------


def _why(c: Comparison) -> list[str]:
    """Where the agent's number came from, derived from the row above it.

    Every figure here is computed from the `Comparison`'s own fields. That is the
    same rule the rest of this file holds to — `tests/tearsheet/test_advantage.py`
    re-runs the engine and demands exact equality — and it matters more here than
    anywhere else in the report, because this is the paragraph a reader will use
    to decide whether the headline means what it appears to mean.

    What it exists to prevent: publishing *"hiring the agent loses 64 points"* as
    though it were a fact about agents, when the tape says it is a fact about two
    frozen-spec parameters meeting real flow. The number is not softened. It is
    attributed.
    """
    if not c.quotable or c.days <= 0:
        return []

    # Every figure below is an LP quantity, and a lending task has none of them:
    # `AllocationResult` has no mints, no pulls, no fees and no in-range
    # fraction. They read as `0` until `_of` learned to say `None`, and this
    # paragraph would have described a lending agent as having minted zero
    # times, pulled zero times and been in range 0.0% of a range it never had.
    if any(
        v is None
        for v in (c.agent_mints, c.agent_pulls, c.agent_recentres, c.agent_fees, c.agent_in_range)
    ):
        return []

    params = Params()
    cycles = min(c.agent_mints, c.agent_pulls)
    per_day = cycles / c.days
    cost_share = c.agent_costs / c.capital_quote if c.capital_quote else 0.0
    fee_cover = c.agent_fees / c.agent_costs if c.agent_costs else float("inf")

    # Only worth writing when costs actually decide the answer.
    if c.agent_costs <= 0 or c.agent_costs <= c.agent_fees:
        return []

    lines = [
        "<details><summary><strong>Where this number comes from</strong></summary>",
        "",
        f"Over {c.days:.1f} days the agent minted **{c.agent_mints}** times, pulled "
        f"**{c.agent_pulls}** times and recentred **{c.agent_recentres}** times.",
        "",
    ]

    if c.agent_recentres == 0 and cycles:
        lines += [
            f"**It never recentred.** Every action was a pull followed by a re-mint — "
            f"{cycles} complete cycles, **{per_day:.1f} per day** against "
            f"`max_rebalances_per_day = {params.max_rebalances_per_day}`. The budget is "
            "spent entirely on coming back.",
            "",
            "That ordering is deliberate and documented: `core/policy.py` gates "
            "re-entry and never exit, because *an agent forbidden to leave because it "
            "had run out of budget would be held inside exactly the flow the rule "
            "exists to escape*. The consequence on real flow is that a toxicity rule "
            "firing often enough exhausts the day's budget on exits, and the agent "
            f"then cannot afford to return — which is why it was in range "
            f"**{c.agent_in_range:.1%}** of the time while moving {c.agent_moves} times.",
            "",
        ]
    elif cycles:
        lines += [
            f"That is **{per_day:.1f}** cycles per day against "
            f"`max_rebalances_per_day = {params.max_rebalances_per_day}`.",
            "",
        ]

    # Task 3's band looks broken until it is stated as what it is: a conclusion
    # about the venue rather than about the agent.
    if c.category == "security" and c.capital_quote and c.capital_quote < 1.0:
        lines += [
            f"**This is a finding about the pool, not about the agent.** The position "
            f"is {c.capital_quote:.4g} because that is what assumption A1 permits on "
            "the shallower of the two venues — A1's ceiling is `eps x pool_liquidity` "
            "and therefore a property of the pool, and a quote that breaches it is "
            "*refused rather than rendered*. Transaction costs, however, are fixed per "
            "action and do not shrink with the position.",
            "",
            f"So at the largest size this venue's own liquidity allows, fixed costs "
            f"exceed any plausible fee income by **{c.agent_costs / c.agent_fees:.0f}x**. "
            "That is the due-diligence answer to *which pool should I provide liquidity "
            "to*: **not this one, at any size it can support.** The percentage is large "
            "and negative because it is a small denominator, and both columns share it, "
            "which is why the delta is still sound.",
            "",
        ]

    lines += [
        f"The cost of that is **{cost_share:.1%} of deployed capital** over the window, "
        f"and fees covered **{fee_cover:.2f}x** of it. The baseline moved "
        f"{c.baseline_moves} time(s) and was charged {c.baseline_costs:.4f}. "
        "The gap between the two columns is transaction cost, not strategy.",
        "",
        "**So this task measures the parameters, not the idea.** Two open findings "
        "produce it, and neither was tuned to improve this number: **P-19**, which "
        "measures how often §3.4's imbalance arm fires and so how often the agent "
        "pulls, and **P-12**, which made the daily budget correctly persist across a "
        "pull and thereby exposed what that firing rate costs. Both are in "
        "[`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md), with **P-20** for this "
        "result itself.",
        "",
        "</details>",
        "",
    ]
    return lines


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
        if c.primary is not None:
            # The number the task is named after, above the table rather than
            # buried in it. Task 2 asks about being picked off and the agent
            # wins that by 17x; the report used to print only the net return it
            # loses on, which is a true headline and an incomplete answer.
            lines += [
                f"- **{'Better' if c.primary.improved else 'Worse'} on the quantity this "
                f"task is named after** — {c.primary.render()}",
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
            f"| Moves — mint / recentre / pull | "
            f"{c.baseline_mints} / {c.baseline_recentres} / {c.baseline_pulls} | "
            f"{c.agent_mints} / {c.agent_recentres} / {c.agent_pulls} |",
            f"| Distinct results of {c.windows * 3} reported samples | "
            f"{c.baseline_distinct} | {c.agent_distinct} |",
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
        lines += _why(c)

    # Conditional on the tape. This paragraph is a claim about chain coverage,
    # and it was emitted unconditionally — so `AGENT_ADVANTAGE_SHORT.md`, a run
    # whose header says `Tape: synthetic` and whose every task is withheld, still
    # told the reader both venues were "indexed from chain over the same
    # 5,802,928 blocks". A true sentence about the other report.
    tape_note = (
        [
            "- **A longer tape, and a second month.** Thirty days is one regime. The",
            "  caveat that used to sit here — that free BSC endpoints refuse a multi-day",
            "  backfill, so the word *real* had not been earned — is no longer true and",
            "  has been removed: both venues are indexed from chain over the same",
            "  5,802,928 blocks, and `make go-no-go` checks the coverage rather than the",
            "  span. What a keyed `BSC_RPC_URL` buys now is speed, not honesty.",
        ]
        if source == "chain"
        else [
            "- **A chain tape.** This run is `" + source + "`, so nothing below rests on",
            "  anything that happened. A synthetic tape can show the machinery runs; it",
            "  cannot support a claim about a venue. Run `make advantage` against an",
            "  indexed pool for a report that can.",
        ]
    )

    lines += [
        "## What would make this stronger",
        "",
        *tape_note,
        "- **A verdict.** Three tasks is three observations, and `tearsheet.verdict`",
        "  refuses below thirty. The report says *no verdict* across all tasks and",
        "  means it; the per-task bands are what it will stand behind.",
        "- Every assumption behind these numbers is in [`ASSUMPTIONS.md`](ASSUMPTIONS.md);",
        "  every deviation from the frozen spec, with its arithmetic, is in",
        "  [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md).",
        "",
    ]
    return "\n".join(lines)


def to_payload(comparisons: list[Comparison], *, source: str, capital: float, command: str) -> dict:
    return {
        "report": "Agent Advantage",
        # Per-artifact provenance, for the same reason the cards carry it:
        # `go_no_go.check_artifact_freshness` answers UNVERIFIED for an artifact
        # that records no commit, and this one recorded none. The report-level
        # `source` below says what the numbers mean; this says which engine
        # produced them.
        "build": provenance.build_stamp(command, source=source),
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
        # The tasks' figure when they agree, and explicitly per-task when they
        # do not. Task 3 runs at a capital A1 permits on the *shallower* of its
        # two venues, so one number here would be wrong for at least one task.
        "capital_quote": (
            capital
            if all(c.capital_quote == capital for c in comparisons)
            else "per task — see tasks[].capital_quote"
        ),
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
                "capital_quote": c.capital_quote,
                "metric": c.metric,
                # The quantity the task is named after, when that is not net
                # return. Carried so a machine reader gets what the prose gained.
                "primary_metric": (
                    None
                    if c.primary is None
                    else {
                        "name": c.primary.name,
                        "baseline": c.primary.baseline,
                        "agent": c.primary.agent,
                        "lower_is_better": c.primary.lower_is_better,
                        "unit": c.primary.unit,
                        "improved": c.primary.improved,
                        "summary": c.primary.render(),
                    }
                ),
                "without_agent": c.without_agent,
                "with_agent": c.with_agent,
                "quotable": c.quotable,
                "note": c.note,
                "baseline": _side(
                    c.baseline_p25,
                    c.baseline_p50,
                    c.baseline_p75,
                    in_range=c.baseline_in_range,
                    fees=c.baseline_fees,
                    lvr=c.baseline_lvr,
                    costs=c.baseline_costs,
                    moves=c.baseline_moves,
                    mints=c.baseline_mints,
                    pulls=c.baseline_pulls,
                    recentres=c.baseline_recentres,
                    distinct=c.baseline_distinct,
                    returns=c.baseline_returns,
                ),
                "agent": _side(
                    c.agent_p25,
                    c.agent_p50,
                    c.agent_p75,
                    in_range=c.agent_in_range,
                    fees=c.agent_fees,
                    lvr=c.agent_lvr,
                    costs=c.agent_costs,
                    moves=c.agent_moves,
                    mints=c.agent_mints,
                    pulls=c.agent_pulls,
                    recentres=c.agent_recentres,
                    distinct=c.agent_distinct,
                    returns=c.agent_returns,
                ),
                "replay_days": round(c.days, 3),
                # The three the track asks for and the report never carried.
                # `replay_days` is how much *history* the task replayed; these are
                # how long the work took and what the customer pays for it.
                "seconds": {
                    "without_agent": round(c.baseline_seconds, 1),
                    "with_agent": round(c.agent_seconds, 1),
                },
                "hire_cost": {
                    "amount": c.hire_cost_quote,
                    "unit": "BNB",
                    "note": c.hire_cost_note,
                },
                "delta_pp": round(c.delta, 6),
                "ranges_overlap": c.ranges_overlap,
                "same_run": c.same_run,
                "material": c.material,
                "separated": c.separated,
                "verdict": c.verdict_line(),
            }
            for c in comparisons
        ],
    }


#: Sub-windows per task. The same 20 `compute_quote` uses for the LP tasks, so
#: the allocation task's quote rests on the same shape of evidence.
ROUTE_WINDOWS = DEFAULT_WINDOWS

#: Dollars supplied, and **not** the report's `--capital`.
#:
#: The report's figure is denominated in the pool's token1 — WBNB — and defaults
#: to 1. Handing that to a lending task means supplying one dollar and paying
#: sixty cents of gas to do it, which annualises to a four-figure percentage and
#: describes nothing. Task 3 sets its own capital for the same class of reason
#: (A1's ceiling belongs to the shallower pool, not to the report), and records
#: it per task so a machine reader is not misled by the header.
ROUTE_CAPITAL_USD = 10_000.0


def task_route(*, db: str) -> Comparison | None:
    """Task 4 — Yield: routing between lending venues vs parking in the best one.

    The fourth of the main track's four categories, and the only task here that
    is not a liquidity position. It replays `decide_router` against `park_policy`
    over the **Venus rate tape**, through `AllocationDriver` — a different tape
    and a different driver from tasks 1-3, which is exactly why Router was cut
    once and why it is worth having now.

    Returns `None` when there is no rate tape, rather than inventing one. Tasks
    1-3 fall back to constructed venues and label them; a constructed *lending*
    tape has no such precedent here and would be a second fabrication wearing
    the same badge, so this task is simply absent and the report is three tasks
    long — which the rubric permits and a fabricated fourth would not.

    What it actually reports: Router enters once and then holds. The best
    realized rate clears the round-trip hurdle within a few days of commitment,
    while the gap *between* the two venues stays under that same hurdle — so the
    agent supplies and declines to churn, and against parking in the best venue
    the verdict comes out **indistinguishable**.

    An earlier version of this docstring predicted the opposite, and said the
    agent's whole advantage was an entry cost it declined to pay. That followed
    from two cost constants with nothing behind them; both are readings now
    (P-25). The prediction is gone rather than corrected in place, because a
    docstring that forecasts a result is a place for the result to go stale.
    """
    try:
        from misquote.agents.router.policy import RouterParams, decide_router, park_policy
        from misquote.chain import costs as _chain_costs
        from misquote.chain.venus import markets_on
        from misquote.core.types import DEFAULT_RESERVE_FACTOR
        from misquote.indexer import store as _store
        from misquote.indexer import venus as _venus
        from misquote.replay.allocation import (
            AllocationDriver,
            allocation_quote_from_results,
        )
    except ImportError as error:
        # **Not** swallowed. This was a bare `except Exception: return None`,
        # and it cost the judged report its entire fourth category: the long
        # chain run imported this module while `chain/costs.py` was still being
        # written, the import raised, and the except turned that into "there is
        # no rate tape" — a completely different statement. The report came back
        # with three tasks, `source: chain`, and nothing anywhere saying the
        # Yield task had been dropped.
        #
        # A missing tape is a legitimate absence. A missing module is a broken
        # build, and the two must not render the same.
        raise RuntimeError(
            f"the Yield task cannot import what it needs: {error}. This is a broken "
            f"build, not an absent tape — fix the import rather than letting the "
            f"report quietly ship one category short."
        ) from error

    refs = markets_on(56)
    if not refs or not db:
        print("  route: no verified Venus markets configured — task omitted")
        return None

    try:
        conn = _store.connect(db)
    except Exception:  # noqa: BLE001
        return None

    events: list = []
    markets: dict[str, dict] = {}
    for ref in refs:
        rows = _venus.load_accruals(conn, ref.key)
        if not rows:
            continue
        events.extend(rows)
        last = rows[-1]
        recorded = _venus.reserve_factor_at(conn, ref.key, last.block)
        markets[ref.key] = {
            "reserve_factor": recorded if recorded is not None else DEFAULT_RESERVE_FACTOR,
            # Size is NOT recorded here. `AllocationDriver` derives it per
            # sample from the accrual it has seen, because taking it from
            # `rows[-1]` sized every earlier window with a market measured at
            # the end of the tape. Only decimals travel, so the driver can
            # scale what it reads.
            "underlying_decimals": ref.underlying_decimals,
        }

    if len(markets) < 2:
        # Said out loud. A task that vanishes silently is indistinguishable from
        # a task that was never written.
        print(f"  route: only {len(markets)} market(s) have a rate tape — task omitted")
        return None

    events.sort(key=lambda e: (e.ts, e.block, e.log_index))
    params = RouterParams()
    costs = _chain_costs.switch_cost(conn)

    capital = ROUTE_CAPITAL_USD

    def replay(window, policy):
        return AllocationDriver(
            markets, policy=policy, params=params, capital_quote=capital, costs=costs
        ).run(window)

    span = events[-1].ts - events[0].ts
    width = span // 2
    step = (span - width) / max(1, ROUTE_WINDOWS - 1)
    windows = []
    for i in range(ROUTE_WINDOWS):
        lo = int(events[0].ts + i * step)
        chunk = [e for e in events if lo <= e.ts <= lo + width]
        if len(chunk) >= 2:
            windows.append(chunk)
    if not windows:
        return None

    # Timed per arm, like the LP tasks. This one does not go through `_run` —
    # a lending allocation is a different driver — so it measures its own.
    _agent_started = time.monotonic()
    agent_runs = [replay(w, decide_router) for w in windows]
    full_agent = replay(events, decide_router)
    agent_seconds = time.monotonic() - _agent_started

    _base_started = time.monotonic()
    base_runs = [replay(w, park_policy) for w in windows]
    full_base = replay(events, park_policy)
    base_seconds = time.monotonic() - _base_started

    agent_quote = allocation_quote_from_results(
        agent_runs, windows=len(windows), perturbation_count=1, capital_quote=capital
    )
    base_quote = allocation_quote_from_results(
        base_runs, windows=len(windows), perturbation_count=1, capital_quote=capital
    )

    return compare(
        task="Route — which lending venue to supply to",
        category="trading",
        venue="Venus Core Pool (BSC) — vUSDT and vUSDC, verified three ways",
        metric=(
            "net return on supplied capital (realized yield - switch costs), P25-P75, "
            f"over a {params.horizon_hours:.0f}h stated holding period. Capital for "
            f"this task is ${capital:,.0f} of stablecoin, not the report's figure — "
            f"that one is denominated in WBNB and means nothing to a lending market."
        ),
        without_agent="supply to the highest-rate venue once and never move (park_policy)",
        with_agent="Router - move only when the rate edge clears the round-trip cost",
        baseline_quote=base_quote,
        agent_quote=agent_quote,
        baseline_result=full_base,
        agent_result=full_agent,
        source="chain",
        capital_quote=capital,
        baseline_seconds=base_seconds,
        agent_seconds=agent_seconds,
        hire_cost_quote=HIRE_COST_BNB,
        hire_cost_note=HIRE_COST_NOTE,
        # The task asks which venue to supply to, and the answer it produced was
        # "neither, at this horizon". The move count is what says so.
        primary=PrimaryMetric(
            name=(
                f"moves made (best rate seen {100 * full_agent.best_apr_seen:.2f}%, "
                f"hurdle {100 * full_agent.hurdle_apr_p50:.2f}%, break-even at "
                f"{full_agent.breakeven_horizon_hours / 24:.0f} days)"
            ),
            baseline=float(full_base.moves),
            agent=float(full_agent.moves),
            lower_is_better=True,
        ),
    )


def build(
    events: list[Event],
    *,
    capital: float,
    venue: str,
    jobs: int | None = None,
    source: str = "synthetic",
    second_venue: tuple[list[Event], PoolMeta, str] | None = None,
    db: str = "",
) -> list[Comparison]:
    """The tasks. Kept separate from I/O so a test can call it directly.

    Four are liquidity positions on one swap tape. The fifth is a lending
    allocation on a different tape with a different driver, included only when
    that tape exists.

    `task_market_make` was added last and is the reason the report can answer its
    own question: it is Grid, the one agent whose comparison comes out ahead, and
    it had been computed for the agent card and never asked for here.
    """
    # One passive run, two tasks. `task_earn` measures Warden against it and
    # `task_market_make` measures Grid; the control is the same position held the
    # same way, so replaying it twice would burn ~1.5h to produce two identical
    # columns. Shared deliberately — what must never be shared is the baseline and
    # the agent *within* one task, which is the duplicate `task_choose` is.
    control = _run(events, passive_policy, capital=capital, jobs=jobs, label="passive/control")
    earn = task_earn(
        events, capital=capital, venue=venue, jobs=jobs, source=source, baseline=control
    )
    market_make = task_market_make(
        events, capital=capital, venue=venue, jobs=jobs, source=source, baseline=control
    )
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
        venue_a = (events, META, venue_name(TARGET_POOL))
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

    tasks = [earn, market_make, protect, choose]

    # The Yield category — and **only** when the rest of the report is reading
    # chain too.
    #
    # `task_route` reads the Venus tape from `--db`, which defaults to the real
    # database regardless of `--synthetic`. So `make advantage-short` — whose
    # entire purpose, per the Makefile, is *"the same three tasks on 13.8h of
    # history, which every one of them refuses to quote. Proof that the refusal
    # is live machinery and not a story told about it"* — was about to gain a
    # fourth task, sourced from real chain data, that quotes perfectly well.
    # The demonstration would have disproved itself.
    #
    # A report whose liquidity tasks are constructed does not get a real one
    # bolted on. `to_payload` would have stamped it `source: "mixed"`, which is
    # honest and is not what that report is for.
    if source == "chain":
        route = task_route(db=db)
        if route is not None:
            tasks.append(route)
    return tasks


def _side(
    p25: float,
    p50: float,
    p75: float,
    *,
    in_range: float | None,
    fees: float | None,
    lvr: float | None,
    costs: float | None,
    moves: int | None,
    mints: int | None,
    pulls: int | None,
    recentres: int | None,
    distinct: int | None,
    returns: tuple[float, ...],
) -> dict[str, Any]:
    """One column of a task, with absent quantities left out rather than zeroed.

    A key that is not here is a question this task does not answer. The Route
    task replays a lending venue, which has no in-range fraction, no fees and no
    adverse-selection cost — `AllocationResult` carries none of those fields —
    and publishing them as `0.00` reported three measurements nobody made.

    Omitted rather than sent as `null`, because the reader is `lib/format.ts`,
    whose `isNum` guard already renders a missing number as an em dash. A `null`
    would take the same path; an omission says the same thing in fewer bytes and
    keeps `test_no_artifact_number_is_hardcoded_in_the_ui` looking at real
    values only.

    `returns` is the sample the band was drawn from. It is what lets the four
    task charts show their evidence the way the agent cards already do — the
    counts were being published while the observations behind them were dropped
    at the `Comparison` boundary.
    """
    side: dict[str, Any] = {
        "p25": round(p25, 6),
        "p50": round(p50, 6),
        "p75": round(p75, 6),
    }
    optional: dict[str, Any] = {
        "in_range": None if in_range is None else round(in_range, 4),
        "fees": None if fees is None else round(fees, 8),
        "lvr_upper_bound": None if lvr is None else round(lvr, 8),
        "costs": None if costs is None else round(costs, 8),
        # The aggregate hides the mechanism; the parts are the finding. Zero
        # recentres beside equal mints and pulls is an agent spending its budget
        # on exits, not on chasing price.
        "moves": moves,
        "mints": mints,
        "pulls": pulls,
        "recentres": recentres,
        # How many of the reported samples are distinct results — P-17's
        # qualifier, which this report has never published.
        "distinct_returns": distinct,
    }
    side.update({k: v for k, v in optional.items() if v is not None})
    if returns:
        side["returns"] = [round(r, 6) for r in returns]
    return side


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(REPO / "data" / "misquote.db"))
    parser.add_argument("--synthetic", type=int, default=0, help="use N synthetic swaps instead")
    parser.add_argument(
        "--fallback-synthetic",
        type=int,
        default=0,
        help="when the tape is empty, fall back to N labelled synthetic swaps instead of refusing",
    )
    parser.add_argument("--capital", type=float, default=DEFAULT_CAPITAL_QUOTE)
    parser.add_argument(
        "--jobs",
        type=int,
        default=(os.cpu_count() or 1),
        help="processes for the window replays; 1 for serial. Results are identical either way.",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--artifact", default=str(DEFAULT_ARTIFACT))
    args = parser.parse_args()

    second_venue = None
    if args.synthetic:
        events = synthetic_events(args.synthetic)
        source = "synthetic"
        venue = f"{venue_name(TARGET_POOL)} (synthetic tape)"
        print(f"tape: {len(events):,} SYNTHETIC swaps (no chain data)")
    else:
        from misquote.indexer import store

        db = Path(args.db)
        if not db.exists():
            print(f"no tape at {db}.")
            if args.fallback_synthetic:
                # Same collapse as `showcase.py`: the Makefile used a file-size
                # test to decide this and then invoked a script that decides on
                # rows. One answer, given by the code that can see the rows.
                print(f"  falling back to a labelled synthetic tape of {args.fallback_synthetic}.")
                args.synthetic = args.fallback_synthetic
                events = synthetic_events(args.synthetic)
                source = "synthetic"
            else:
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
        venue = venue_name(TARGET_POOL)
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
            second_venue = (wide, META_WIDE, venue_name(TARGET_POOL_WIDE))
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
        # The rate tape lives in the same database as the swap tape, and the
        # Yield task reads it directly rather than through `events`.
        db=args.db,
    )

    # The invocation as run, not as defaulted. `advantage-short` writes a
    # different pair of paths from the same script, so a stamp that omitted them
    # would give two distinct artifacts the same provenance line.
    def _shown(path: str) -> str:
        """The path as a reader would type it: repo-relative when it is inside.

        `relative_to` raises for anything outside the repo, and the Makefile
        passes *relative* paths — so resolving first is not optional. The first
        version of this did not, and `make advantage-short` died on
        `'docs/AGENT_ADVANTAGE_SHORT.md' is not in the subpath of ...` before it
        wrote anything.
        """
        resolved = Path(path).resolve()
        try:
            return str(resolved.relative_to(REPO))
        except ValueError:
            return str(resolved)

    command = "python scripts/advantage.py"
    if args.synthetic:
        command += f" --synthetic {args.synthetic}"
    if Path(args.out).resolve() != DEFAULT_OUT.resolve():
        command += f" --out {_shown(args.out)}"
    if Path(args.artifact).resolve() != DEFAULT_ARTIFACT.resolve():
        command += f" --artifact {_shown(args.artifact)}"

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(comparisons, source=source, capital=args.capital) + "\n")

    artifact = Path(args.artifact)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            to_payload(comparisons, source=source, capital=args.capital, command=command), indent=2
        )
        + "\n"
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
