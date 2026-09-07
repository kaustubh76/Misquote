"""Which PancakeSwap pool, at what width — as bands, and as refusals.

The PancakeSwap challenge asks for a real benefit to liquidity providers, and the
question an LP actually has is not "is this agent good". It is *which pool should
I provide to, how wide, and what would that have earned me*. Nothing here
answered it: the replay reported what a policy happened to choose, and no surface
compared pools at all.

## Why this is bands and not a leaderboard

A leaderboard is the misquote. One number per pool, sorted, is precisely the
shape of the thing this project is named against — it hides the sample it rests
on and invites a reader to trust the ordering more than the evidence supports.

So every figure here is a **P25-P75 range over rolling windows** (assumption A5),
carrying the count of observations behind it, and two pools whose ranges overlap
are reported as *not separated at this sample size* rather than ranked. That
sentence already exists in `tearsheet/advantage.py`; it is reused rather than
reinvented, because a second phrasing of the same refusal is a second thing to
drift.

## Why it is the estimator and not the replay driver

`replay/ranges.py::quote()` is the full machinery — 20 windows times 3
perturbations, per policy. Across a width ladder and four pools that is hours,
and it would be measuring the wrong thing anyway: a *policy's* choices, when the
question is what a *width* earns. `PoolAprEstimator` answers exactly the asked
question and is cheap enough to run across the ladder, so the ladder is the unit
of work here.

The floors are `replay/ranges.py`'s own — `MIN_SAMPLES`, `MIN_WINDOW_HOURS` — so
a pool refused here is refused on the same evidence standard a quote is.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Any

from misquote.core.types import Event, PoolMeta
from misquote.estimators.pool_apr import MIN_SWAPS, PoolAprEstimator
from misquote.replay.ranges import (
    MIN_SAMPLES,
    MIN_WINDOW_HOURS,
    percentile,
    rolling_windows,
)

#: The widths an LP is actually choosing between, in ticks of half-width.
#:
#: Spans the two ends that matter: below the dust floor a position earns fees on
#: nothing, and past the top of this ladder a v3 position is a passive one paying
#: to be managed. The A18/A19 band sits inside it deliberately, so the derived
#: floor and ceiling can be checked against measurement rather than assumed.
WIDTH_LADDER: tuple[int, ...] = (40, 80, 130, 200, 244, 400, 800)


@dataclass(frozen=True, slots=True)
class WidthBand:
    """What one width earned, over rolling windows, with its sample size."""

    width_ticks: int
    p25: float
    p50: float
    p75: float
    observations: int
    sufficient: bool
    note: str

    def overlaps(self, other: WidthBand) -> bool:
        """Whether two bands are distinguishable at this sample size."""
        return not (self.p75 < other.p25 or other.p75 < self.p25)

    def to_dict(self) -> dict[str, Any]:
        return {
            "width_ticks": self.width_ticks,
            "p25": self.p25,
            "p50": self.p50,
            "p75": self.p75,
            "observations": self.observations,
            "sufficient": self.sufficient,
            "note": self.note,
        }


def band_for_width(
    events: list[Event],
    meta: PoolMeta,
    width_ticks: int,
    *,
    capital_quote: float = 1.0,
    windows: int = MIN_SAMPLES,
) -> WidthBand:
    """Net APR at one width, as a range over rolling windows.

    Net of the protocol's cut and net of the realized convexity cost — the two
    subtractions that separate what an LP keeps from what a pool pays out.
    """
    swaps = [e for e in events if e.kind == "swap"]
    if len(swaps) < MIN_SWAPS:
        return WidthBand(
            width_ticks,
            0.0,
            0.0,
            0.0,
            0,
            False,
            f"{len(swaps)} swaps on this pool, need {MIN_SWAPS}",
        )

    spans = rolling_windows(swaps[0].ts, swaps[-1].ts, windows)
    returns: list[float] = []
    # Windows are sorted and overlapping, so bisect the shared list rather than
    # filtering it once per window: `rolling_windows` makes each window half the
    # tape, and a linear scan per window is 140 passes over 250,000 events for a
    # seven-width ladder.
    stamps = [e.ts for e in swaps]
    for start, end in spans:
        if (end - start) / 3600.0 < MIN_WINDOW_HOURS:
            continue
        lo = bisect_left(stamps, start)
        hi = bisect_right(stamps, end)
        inside = swaps[lo:hi]
        if len(inside) < MIN_SWAPS:
            continue
        est = PoolAprEstimator(
            meta,
            reference_width_ticks=width_ticks,
            capital_quote=capital_quote,
            window_seconds=end - start + 1,
        )
        for event in inside:
            est.set_decision_time(event.ts)
            est.ingest(event)
        fit = est.fit()
        if fit.is_ready:
            returns.append(fit.net_apr)

    if len(returns) < MIN_SAMPLES:
        return WidthBand(
            width_ticks,
            0.0,
            0.0,
            0.0,
            len(returns),
            False,
            f"{len(returns)} usable windows, need {MIN_SAMPLES}",
        )

    return WidthBand(
        width_ticks,
        percentile(returns, 0.25),
        percentile(returns, 0.50),
        percentile(returns, 0.75),
        len(returns),
        True,
        "",
    )


def ladder_for_pool(
    events: list[Event], meta: PoolMeta, *, capital_quote: float = 1.0
) -> list[WidthBand]:
    """Every width on the ladder, for one pool."""
    return [band_for_width(events, meta, w, capital_quote=capital_quote) for w in WIDTH_LADDER]


def separation(bands: list[WidthBand]) -> dict[int, list[int]]:
    """For each width that cleared the floor, the widths it is *not* separated from.

    `best_width` answers this for exactly one pair — the leader and the runner-up
    — because that is the pair a verdict sentence is about. A reader choosing a
    width is asking it about a different pair every time they look at a different
    row, and the answer for those pairs existed nowhere: the artifact carried
    seven bands and one sentence about two of them.

    Emitted rather than derived in the browser, and that is the whole reason this
    function exists rather than four lines of TypeScript. `components/Band.tsx`
    states the rule it follows — recomputing `Comparison.ranges_overlap` one
    screen-inch from the verdict Python wrote means two implementations that
    agree today and cannot be *made* to disagree tomorrow. `WidthBand.overlaps`
    is the one implementation, and this is how it reaches a page.

    Insufficient bands are absent from the mapping entirely rather than mapped to
    an empty list. Their quartiles are the `0.0` placeholders `band_for_width`
    writes for "no evidence", and overlapping a placeholder means nothing — an
    empty list would read as "separated from everything", which is the exact
    inversion of what a refused band knows.
    """
    usable = [b for b in bands if b.sufficient]
    return {
        band.width_ticks: [
            other.width_ticks for other in usable if other is not band and band.overlaps(other)
        ]
        for band in usable
    }


def ladder_payload(bands: list[WidthBand]) -> list[dict[str, Any]]:
    """The ladder as the artifact carries it: every band, plus who it ties with.

    Joined here rather than in `scripts/pools_report.py` so the pairwise rule and
    the band that implements it stay in one file. `to_dict` cannot do it — a band
    does not know its siblings.
    """
    ties = separation(bands)
    return [
        {**band.to_dict(), "indistinguishable_from": ties[band.width_ticks]}
        if band.width_ticks in ties
        else band.to_dict()
        for band in bands
    ]


def best_width(bands: list[WidthBand]) -> tuple[WidthBand | None, str]:
    """The width that earned most — and whether that is a claim or a coincidence.

    Returns the leader and a sentence about it. The sentence is the product: a
    leader whose band overlaps the runner-up has not been shown to be better, and
    saying so is the difference between this and a leaderboard.
    """
    usable = [b for b in bands if b.sufficient]
    if not usable:
        return None, "no width has enough evidence on this pool"
    if len(usable) == 1:
        return usable[0], "only one width cleared the evidence floor"

    ordered = sorted(usable, key=lambda b: b.p50, reverse=True)
    leader, runner_up = ordered[0], ordered[1]
    if leader.overlaps(runner_up):
        return leader, (
            f"+/-{leader.width_ticks} ticks leads at the median, but its P25-P75 band "
            f"overlaps +/-{runner_up.width_ticks} — not separated at this sample size"
        )
    return leader, (
        f"+/-{leader.width_ticks} ticks earned more than every other width on the "
        f"ladder, and its band does not overlap the runner-up"
    )


@dataclass(frozen=True, slots=True)
class Demand:
    """What flow the pool actually saw, and how much depth served it.

    The criterion's third example asks about *"researching market movements to
    find demand where creating PancakeSwap pools could improve liquidity
    efficiency"*. This is that measurement, and the load-bearing field is the
    last one: volume alone says a pool is busy, and busy is not the same as
    underserved. Fee income per unit of liquidity is what an LP's return is
    actually proportional to, so it is what says whether the depth already there
    is being paid well or thinly.
    """

    swaps: int
    volume_quote: float
    tick_crossings: int
    median_liquidity: float
    fee_per_unit_liquidity: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "swaps": self.swaps,
            "volume_quote": self.volume_quote,
            "tick_crossings": self.tick_crossings,
            "median_liquidity": self.median_liquidity,
            "fee_per_unit_liquidity": self.fee_per_unit_liquidity,
        }


def demand_for_pool(events: list[Event], meta: PoolMeta) -> Demand:
    """Realized demand and the depth that served it, from the tape alone.

    Fees are taken net of the protocol's cut from each swap's own
    `protocolFeesToken*` fields — the same rule the accountant follows, and for
    the same reason: P-8 established that no modelled constant is right for both
    of our pools.
    """
    swaps = [e for e in events if e.kind == "swap"]
    if not swaps:
        return Demand(0, 0.0, 0, 0.0, 0.0)

    volume = 0.0
    lp_fees = 0.0
    crossings = 0
    previous_tick = swaps[0].tick
    liquidity: list[float] = []

    for event in swaps:
        # Quote-side magnitude, decimal-adjusted. `amount1` is the quote leg.
        quote = abs(event.amount1) / 10.0**meta.dec1
        volume += quote
        gross = quote * meta.fee_pips / 1_000_000.0
        cut_raw = event.protocol_fee1 if event.amount1 > 0 else event.protocol_fee0
        cut = cut_raw / 10.0**meta.dec1
        lp_fees += max(0.0, gross - cut)

        if event.tick // meta.tick_spacing != previous_tick // meta.tick_spacing:
            crossings += 1
        previous_tick = event.tick
        if event.liquidity > 0:
            liquidity.append(float(event.liquidity))

    median_liquidity = percentile(liquidity, 0.5) if liquidity else 0.0
    return Demand(
        swaps=len(swaps),
        volume_quote=volume,
        tick_crossings=crossings,
        median_liquidity=median_liquidity,
        fee_per_unit_liquidity=(lp_fees / median_liquidity) if median_liquidity > 0 else 0.0,
    )
