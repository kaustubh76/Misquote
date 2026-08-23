"""Replay a venue-allocation policy over a rate tape.

`driver.py` replays a range policy over a swap tape. This replays an allocation
policy over an accrual tape, and it is a sibling rather than a generalisation
for the same reason `core/allocation.py`'s types are: the two agents earn money
in different ways and a driver pretending otherwise would have to report one of
them in the other's units.

## What it charges, and what it does not

A supplied position earns the venue's realized rate for as long as it is there,
and pays two transactions plus swap slippage every time it moves. There is no
LVR term — a lending position is not quoted against an arbitrageur and cannot be
picked off — and no in-range fraction, because there is no range. Reporting a
zero in those columns would read as "this agent lost nothing to adverse
selection", which is a stronger claim than "adverse selection does not apply".
`app/view.tsx` makes the same argument about drawing a 404'd card as a zero.

## Yield accrues on the accumulator, not on the estimate

Between two samples the position earns what the market actually paid over that
interval — recovered from `borrowIndex` — not the trailing estimate the policy
happened to be looking at. Those differ, and using the estimate would let a
policy that mis-estimates a rate be paid its own mistake, which is the
backtesting equivalent of marking your own homework.

## A1, applied to a lending market

Supplying moves utilisation and therefore the rate. So a notional above
`eps_market_share` of the market's supplied base is counted in `a1_capped`, and
`quote_from_results` refuses the quote rather than clamping and publishing it —
P-14, in the venue the same argument applies to.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from misquote.core.allocation import (
    AllocationAction,
    AllocationDecision,
    AllocationObservation,
    VenueId,
    VenueQuote,
)
from misquote.core.types import DEFAULT_RESERVE_FACTOR, SECONDS_PER_YEAR
from misquote.estimators.apr import RateEvent, TrailingAprEstimator

#: How often the policy is asked. Rates move slowly; sampling every accrual
#: would ask a weekly-horizon decision hundreds of times an hour and charge
#: cooldown logic for the privilege.
DEFAULT_SAMPLE_INTERVAL_S = 3600

#: The trailing window each venue's realized rate is measured over.
DEFAULT_APR_WINDOW_S = 86_400


@dataclass(slots=True)
class AllocationResult:
    """One allocation run's outcome, with enough detail to argue with."""

    decisions: list[AllocationDecision] = field(default_factory=list)
    timestamps: list[int] = field(default_factory=list)
    entries: int = 0
    switches: int = 0
    exits: int = 0
    samples: int = 0
    #: Samples spent holding the venue that had the best quotable rate.
    best_venue_samples: int = 0
    #: Samples spent holding anything at all. A router parked flat earns nothing
    #: and that has to be visible rather than folded into the return.
    invested_samples: int = 0
    gross_yield_quote: float = 0.0
    total_costs: float = 0.0
    a1_capped: int = 0
    first_ts: int | None = None
    last_ts: int | None = None
    #: The largest edge the tape ever offered, and the hurdle it was measured
    #: against. Published so "it never switched" can be read as "the edge was
    #: never there" rather than "the threshold was impossible".
    max_edge_apr: float = 0.0
    hurdle_apr_p50: float = 0.0
    #: The best rate any quotable venue offered over the run.
    best_apr_seen: float = 0.0
    #: How long capital would have to be committed before that best rate repays
    #: one round trip. The actionable form of "it never moved".
    breakeven_horizon_hours: float = 0.0

    @property
    def net_quote(self) -> float:
        return self.gross_yield_quote - self.total_costs

    @property
    def best_venue_fraction(self) -> float:
        return self.best_venue_samples / self.samples if self.samples else 0.0

    @property
    def invested_fraction(self) -> float:
        return self.invested_samples / self.samples if self.samples else 0.0

    @property
    def moves(self) -> int:
        return self.entries + self.switches + self.exits

    @property
    def hours(self) -> float:
        if self.first_ts is None or self.last_ts is None:
            return 0.0
        return max(0.0, (self.last_ts - self.first_ts) / 3600.0)


#: Used only when a gas price or a native price could not be read.
#:
#: 250,000 units at BSC's measured 0.05 gwei is 1.25e-5 BNB; at roughly $600
#: that is under a cent. Rounded up to two cents, which is conservative in the
#: direction that makes the agent trade *less* — the same bias `CostModel`'s
#: docstring argues for.
FALLBACK_GAS_QUOTE = 0.02


@dataclass(frozen=True, slots=True)
class SwitchCost:
    """What moving costs, in the underlying's units.

    ## This class was P-13 happening again

    It shipped as two bare literals — `gas_quote = 0.30`, `slippage_bps = 5.0` —
    with no measurement behind either, on the path that decides every figure
    Router publishes. `replay/driver.py`'s `CostModel.gas_quote` carries the
    comment about the last time that happened: a field holding `0.5` where the
    chain-derived value was `3.0e-5`, "16,667x too large", and the conclusion
    *"the quote it produced was a statement about this constant rather than
    about the strategy."*

    `slippage_bps = 5.0` was that exactly. It was copied from an estimate for a
    **WBNB/USDT** recentre while claiming to be the full pool fee for a
    **stablecoin** swap. PancakeSwap runs USDT/USDC at 0.01% — **one** basis
    point. At five, the hurdle was 5.84% against a best observed rate of 2.50%
    and Router never supplied; at one it is far lower and the whole published
    finding turns over. See P-25.

    ## Constructed from readings, or explicitly labelled as not

    `from_venue()` derives both fields: the fee from the verified pool's own
    `fee_pips`, and the gas from a gas-unit count times a gas price. `derived`
    records which inputs were real, so a card can say whether it is quoting a
    measurement or a fallback — the distinction `measure_block_seconds` makes
    and this class did not.
    """

    gas_quote: float
    slippage_bps: float
    #: What produced these numbers, in one line, carried onto the card.
    basis: str
    #: False when any input fell back to a stated default rather than a reading.
    derived: bool = True

    def with_basis_note(self, note: str) -> SwitchCost:
        """Same numbers, with one input demoted from reading to fallback.

        Returned rather than mutated because the class is frozen, and `derived`
        drops to False: a cost that is three-quarters measured is not a measured
        cost, and the card should say which.
        """
        return SwitchCost(
            gas_quote=self.gas_quote,
            slippage_bps=self.slippage_bps,
            basis=f"{self.basis} ({note})",
            derived=False,
        )

    @classmethod
    def from_venue(
        cls,
        venue,
        *,
        gas_units: int,
        gas_price_wei: int | None,
        native_price_quote: float | None,
    ) -> SwitchCost:
        """Cost of one transaction and one swap, from what was actually read.

        `native_price_quote` is the gas token's price in the underlying's units
        — BNB in dollars here. Gas is quoted in BNB by the chain and the router
        keeps its books in dollars, and silently mixing those two is precisely
        how `gas_quote = 0.30` looked reasonable: it is about fifteen times the
        real cost when read as dollars and nine thousand times it when read as
        BNB, and nothing recorded which was meant.

        Any missing input falls back and says so rather than inventing one.
        """
        fee_bps = venue.taker_fee_bps
        if gas_price_wei is None or native_price_quote is None:
            return cls(
                gas_quote=FALLBACK_GAS_QUOTE,
                slippage_bps=fee_bps,
                basis=(
                    f"fee {fee_bps:g}bps from {venue.label}; gas is the stated "
                    f"fallback of {FALLBACK_GAS_QUOTE:g} — no gas price or native "
                    f"price was available"
                ),
                derived=False,
            )
        gas_native = gas_units * gas_price_wei / 1e18
        gas_quote = gas_native * native_price_quote
        return cls(
            gas_quote=gas_quote,
            slippage_bps=fee_bps,
            basis=(
                f"fee {fee_bps:g}bps from {venue.label}; gas {gas_units:,} units x "
                f"{gas_price_wei / 1e9:.3f} gwei x {native_price_quote:,.2f} per native "
                f"= {gas_quote:,.4f} per transaction"
            ),
            derived=True,
        )


class AllocationDriver:
    """Steps an allocation policy through a rate tape and keeps the books.

    Owns `edge_streak`, `switches_today` and `seconds_since_switch` for the same
    reason `ReplayDriver` owns `toxic_streak`: a policy that incremented its own
    counters would be holding state between calls and would stop being a pure
    function of its observation, which is what makes replay deterministic.
    """

    def __init__(
        self,
        markets: dict[VenueId, dict],
        *,
        policy,
        params,
        capital_quote: float,
        costs: SwitchCost | None = None,
        sample_interval_s: int = DEFAULT_SAMPLE_INTERVAL_S,
        apr_window_s: int = DEFAULT_APR_WINDOW_S,
    ) -> None:
        if not markets:
            raise ValueError("an allocation replay needs at least one venue")
        self.markets = markets
        self.policy = policy
        self.params = params
        self.capital_quote = capital_quote
        if costs is None:
            raise ValueError(
                "an allocation replay needs an explicit SwitchCost. There is no "
                "default: the two fields it used to default to were a literal "
                "gas figure and a fee copied from another venue, and together "
                "they decided every number Router published (P-25). Build one "
                "with `chain.costs.switch_cost()` or `SwitchCost.from_venue()`."
            )
        self.costs = costs
        self.sample_interval_s = sample_interval_s
        self.apr_window_s = apr_window_s

    def run(self, events: list[RateEvent]) -> AllocationResult:
        """Replay the tape. `events` must be every market's accruals, in ts order."""
        result = AllocationResult()
        if not events:
            return result

        estimators = {
            venue: TrailingAprEstimator(
                window_seconds=self.apr_window_s,
                reserve_factor=self.markets[venue].get("reserve_factor", DEFAULT_RESERVE_FACTOR),
            )
            for venue in self.markets
        }
        # The last accrual seen per venue, so yield can be accrued from the
        # accumulator rather than from the estimate.
        last_index: dict[VenueId, tuple[int, int]] = {}

        held: VenueId | None = None
        value = self.capital_quote
        edge_streak = 0
        switches_today = 0
        day_started = events[0].ts
        last_switch_ts = events[0].ts
        hurdles: list[float] = []

        by_venue: dict[VenueId, list[RateEvent]] = {v: [] for v in self.markets}
        for e in events:
            if e.market in by_venue:
                by_venue[e.market].append(e)

        cursor = {v: 0 for v in self.markets}

        for sample_ts in _sample_times(events, self.sample_interval_s):
            # Advance every estimator to this decision time and feed it only
            # what happened before it. The guards in `TrailingEstimator` make a
            # mistake here raise rather than silently leak the future.
            for venue, est in estimators.items():
                est.set_decision_time(sample_ts)
                rows = by_venue[venue]
                i = cursor[venue]
                while i < len(rows) and rows[i].ts <= sample_ts:
                    est.ingest(rows[i])
                    i += 1
                cursor[venue] = i

            # Accrue what the held position actually earned since the last
            # sample, from the accumulator.
            if held is not None:
                rows = by_venue[held]
                seen = cursor[held]
                if seen >= 1:
                    now = rows[seen - 1]
                    prev = last_index.get(held)
                    if prev is not None:
                        prev_block, prev_index = prev
                        if now.borrow_index > prev_index and prev_index > 0:
                            growth = now.borrow_index / prev_index - 1.0
                            fit = estimators[held].fit()
                            earned = growth * fit.utilisation * (1.0 - fit.reserve_factor)
                            result.gross_yield_quote += value * earned
                    last_index[held] = (now.block, now.borrow_index)

            quotes = []
            for venue, est in estimators.items():
                fit = est.fit()
                meta = self.markets[venue]
                # Market size as of **this** sample, from the last accrual the
                # estimator has been allowed to see.
                #
                # The emitters used to compute this once from `rows[-1]` — the
                # final accrual on the tape — and pass it in as a constant, so a
                # window replayed on day one was sized by a market measured on
                # day seven. That is look-ahead, in the project whose central
                # claim is that look-ahead is structurally impossible. It fed
                # every `VenueQuote` and A1's ceiling.
                #
                # `cash_prior` and `total_borrows_prior` are in every
                # `RateEvent`, so the correct figure needs no new data and no
                # extra read — only the discipline of taking it from the
                # trailing edge rather than the end.
                scale = 10 ** int(meta.get("underlying_decimals", 18))
                seen = cursor[venue]
                if seen >= 1:
                    at = by_venue[venue][seen - 1]
                    cash = at.cash_prior / scale
                    supplied = (at.cash_prior + at.total_borrows_prior) / scale
                else:
                    # Nothing observed yet: a market of unknown size, which A1
                    # must treat as unable to absorb anything rather than as
                    # infinite.
                    cash = supplied = 0.0
                quotes.append(
                    VenueQuote(
                        venue_id=venue,
                        apr=fit.supply_apr,
                        apr_samples=fit.accruals,
                        apr_is_stale=fit.is_stale,
                        cash_quote=cash,
                        supplied_base_quote=supplied,
                    )
                )

            if sample_ts - day_started >= 86_400:
                switches_today = 0
                day_started = sample_ts

            obs = AllocationObservation(
                t=sample_ts,
                venues=tuple(quotes),
                held=held,
                notional_quote=value,
                gas_quote=self.costs.gas_quote,
                switch_slippage_bps=self.costs.slippage_bps,
                seconds_since_switch=max(0, sample_ts - last_switch_ts),
                switches_today=switches_today,
                edge_streak=edge_streak,
            )

            # A1: refuse rather than clamp. Counted per sample the position
            # would have exceeded epsilon of the venue it is sitting in.
            for q in quotes:
                if (
                    held == q.venue_id
                    and value > self.params.eps_market_share * q.supplied_base_quote
                ):
                    result.a1_capped += 1

            decision = self.policy(obs, self.params, None)
            result.decisions.append(decision)
            result.timestamps.append(sample_ts)
            result.samples += 1
            hurdles.append(decision.hurdle_apr)
            # Only when a position was actually held. `decide_router` sets
            # `edge_apr` to the best venue's **absolute** rate while flat —
            # there is no held venue to difference against — so folding those
            # samples in makes `max_edge_apr` a rate, not an edge. On a run with
            # zero entries it made the two identical: `router.json` published
            # `max_edge_apr == best_apr_seen == 0.024973`, byte for byte, and
            # `RouterDetail.tsx` rendered the same number twice under "Best
            # realized rate seen" and "Largest edge between venues". One of
            # those was a claim the run did not support.
            if held is not None:
                result.max_edge_apr = max(result.max_edge_apr, decision.edge_apr)
            live_now = [q for q in quotes if not q.apr_is_stale]
            if live_now:
                result.best_apr_seen = max(result.best_apr_seen, max(q.apr for q in live_now))

            if held is not None:
                result.invested_samples += 1
                live = [q for q in quotes if not q.apr_is_stale]
                if live and held == max(live, key=lambda q: q.apr).venue_id:
                    result.best_venue_samples += 1

            # The streak counts consecutive samples where the edge cleared, and
            # is reset by anything else — including a sample where the best
            # venue *is* the held one, which is an edge of zero.
            # Same reason. While flat, `edge_apr` is a rate level rather than a
            # difference, so counting those samples lets `persistence_samples`
            # be pre-satisfied before the position exists — and ENTER does not
            # reset the streak (only SWITCH does), so the first switch after
            # entering could clear a gate that had never observed an edge. That
            # is a gate structurally unable to bind, which is the defect
            # `core/allocation.py`'s docstring says this repo has shipped twice.
            edge_streak = (
                edge_streak + 1
                if held is not None and decision.edge_apr > decision.hurdle_apr
                else 0
            )

            # One number, deducted from the position and recorded in the books.
            #
            # These were two calls: `_move_cost(value)` came off the position
            # while `_move_cost(self.capital_quote)` went into `total_costs`.
            # Slippage is a fraction of notional, so after the first move the
            # two disagree — and `net_quote` is `gross_yield - total_costs`,
            # which then describes a position other than the one that was held.
            # A cost is one event; it is charged once and written down once.
            if decision.moves:
                charged = _move_cost(
                    value, self.costs, swaps=decision.action is AllocationAction.SWITCH
                )
                value -= charged
                result.total_costs += charged
                last_switch_ts = sample_ts

            if decision.action is AllocationAction.ENTER:
                # A fresh position has no edge history. Whatever was counted
                # before it existed described a different question.
                edge_streak = 0
                held = decision.target_venue
                last_index.pop(held, None)
                rows = by_venue[held]
                if cursor[held] >= 1:
                    now = rows[cursor[held] - 1]
                    last_index[held] = (now.block, now.borrow_index)
                result.entries += 1
            elif decision.action is AllocationAction.SWITCH:
                held = decision.target_venue
                rows = by_venue[held]
                if cursor[held] >= 1:
                    now = rows[cursor[held] - 1]
                    last_index[held] = (now.block, now.borrow_index)
                result.switches += 1
                switches_today += 1
                edge_streak = 0
            elif decision.action is AllocationAction.EXIT:
                held = None
                result.exits += 1

            if result.first_ts is None:
                result.first_ts = sample_ts
            result.last_ts = sample_ts

        if hurdles:
            ordered = sorted(hurdles)
            result.hurdle_apr_p50 = ordered[len(ordered) // 2]
        if result.best_apr_seen > 0:
            result.breakeven_horizon_hours = (
                self.params.horizon_hours * result.hurdle_apr_p50 / result.best_apr_seen
            )
        return result


def _move_cost(notional: float, costs: SwitchCost, *, swaps: bool) -> float:
    """Gas on every move; the pool fee only when a swap actually happens.

    `swaps` is not a refinement, it is a correction. This charged the full fee
    on every move, including `park_policy`'s single ENTER — and entering vUSDT
    from a dollar position that is already USDT swaps **nothing**. On the seven
    day tape that phantom fee was 5.0 of the baseline's 5.6 total cost, so
    roughly nine tenths of Router's advertised advantage over parking was a
    charge the baseline would never have paid.

    `replay/driver.py`'s `_move_cost` has carried the equivalent branch since
    P-18 — "entering from a single asset: half of it has to become the other" —
    and this one had none.

    Entering and exiting hold the underlying they already have. Only moving
    *between* venues crosses underlyings.
    """
    fee = notional * costs.slippage_bps / 10_000.0 if swaps else 0.0
    return 2.0 * costs.gas_quote + fee


def _sample_times(events: list[RateEvent], interval: int) -> list[int]:
    """Decision times across the tape, at a fixed cadence."""
    start, end = events[0].ts, events[-1].ts
    if end <= start:
        return [start]
    return list(range(start, end + 1, interval))


# --- turning replays into a published range ---------------------------------

# The floors, **imported** rather than restated.
#
# These were three copies of numbers that already had a home, under a comment
# saying "same floors as `ranges.quote_from_results`" — and one of the three was
# simply missing, which is what a copy does that an import cannot.
# `MIN_HOURS_TO_ANNUALISE` was not carried across, so this module annualised
# **unconditionally** while `ranges.py` refuses below a week:
#
#     "Annualising is a multiplication, and multiplying an eight-hour result by
#      a thousand does not make it an annual one."
#
# Router's windows are 84 hours — half the floor — and its card published a
# 3.5-day result multiplied by 104 with `annualised: true` on it. That is the
# exact number this project exists to refuse, produced by the copy that looked
# faithful.
from .ranges import (  # noqa: E402 — the floors belong at the top of this file
    MIN_HOURS_TO_ANNUALISE,
    MIN_SAMPLES,
    MIN_WINDOW_HOURS,
)


@dataclass(frozen=True, slots=True)
class AllocationQuote:
    """What a Router card shows, and everything needed to disbelieve it.

    Deliberately not a `ranges.Quote`. That type carries `in_range_p50` and
    `rebalances_p50`, neither of which exists for an allocation agent, and
    filling them with zeros would render as "never out of range, never
    rebalanced" — two claims this agent is not entitled to make.
    """

    p25: float
    p50: float
    p75: float

    samples: int
    windows: int
    perturbations: int

    best_venue_p50: float
    switches_p50: float
    hours_per_window: float

    sufficient: bool
    note: str
    annualised: bool = False
    basis: str = ""
    net_positive: int = 0
    returns: tuple[float, ...] = ()
    #: The largest edge the tape offered and the hurdle it was tested against.
    #: Both published so a zero-switch result is readable as a finding.
    max_edge_apr: float = 0.0
    hurdle_apr: float = 0.0

    def render(self) -> str:
        if not self.sufficient:
            return f"withheld — {self.note}"
        return f"{self.p25:.2f}% – {self.p75:.2f}% (median {self.p50:.2f}%)"

    def to_dict(self) -> dict:
        """The card's own shape.

        `generate._quote_dict` prefers this when a quote defines it, so the
        three existing agents' artifacts stay byte-identical while Router emits
        the fields that are true of Router.
        """
        return {
            "p25": round(self.p25, 4),
            "p50": round(self.p50, 4),
            "p75": round(self.p75, 4),
            "samples": self.samples,
            "windows": self.windows,
            "perturbations": self.perturbations,
            "best_venue_p50": round(self.best_venue_p50, 4),
            "switches_p50": round(self.switches_p50, 4),
            "hours_per_window": round(self.hours_per_window, 2),
            "sufficient": self.sufficient,
            "note": self.note,
            "annualised": self.annualised,
            "basis": self.basis,
            "net_positive": self.net_positive,
            "returns": [round(r, 4) for r in self.returns],
            "max_edge_apr": round(self.max_edge_apr, 6),
            "hurdle_apr": round(self.hurdle_apr, 6),
        }


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def allocation_quote_from_results(
    results: list[AllocationResult],
    *,
    windows: int,
    perturbation_count: int,
    capital_quote: float,
    annualise: bool = True,
) -> AllocationQuote:
    """Turn a set of allocation replays into a published range.

    The metric is net return on supplied capital — realized yield, minus what it
    cost to move — annualised. No LVR term and no in-range term, because neither
    applies to a supplied position; see the module docstring.
    """
    breached = sum(r.a1_capped for r in results)
    if breached:
        return AllocationQuote(
            p25=0.0,
            p50=0.0,
            p75=0.0,
            samples=0,
            windows=windows,
            perturbations=perturbation_count,
            best_venue_p50=0.0,
            switches_p50=0.0,
            hours_per_window=0.0,
            sufficient=False,
            note=(
                f"refused: the position breached assumption A1's ceiling on "
                f"{breached} sample(s) — supplying that much moves the very rate it "
                f"was chosen for. A1 says such a quote is refused rather than "
                f"rendered. Quote for less capital."
            ),
        )

    usable = [r for r in results if r.samples > 0 and r.hours >= MIN_WINDOW_HOURS]
    if len(usable) < MIN_SAMPLES:
        short = [r for r in results if 0 < r.hours < MIN_WINDOW_HOURS]
        detail = f"{len(usable)} usable replays, assumption A5 requires {MIN_SAMPLES}"
        if short:
            detail += (
                f"; {len(short)} window(s) were shorter than the "
                f"{MIN_WINDOW_HOURS:.0f}h policy horizon"
            )
        return AllocationQuote(
            p25=0.0,
            p50=0.0,
            p75=0.0,
            samples=len(usable),
            windows=windows,
            perturbations=perturbation_count,
            best_venue_p50=0.0,
            switches_p50=0.0,
            hours_per_window=0.0,
            sufficient=False,
            note=f"withheld: {detail}",
        )

    # Annualise only when the windows are long enough to survive it, and say
    # which period the figure covers when they are not. `ranges.py` gates on
    # exactly this and states the period in `basis`; this module multiplied
    # regardless.
    median_hours = _percentile([r.hours for r in usable], 0.50)
    do_annualise = annualise and median_hours >= MIN_HOURS_TO_ANNUALISE

    returns: list[float] = []
    for r in usable:
        raw = r.net_quote / capital_quote
        if do_annualise and r.hours > 0:
            raw *= SECONDS_PER_YEAR / (r.hours * 3600.0)
        returns.append(100.0 * raw)

    return AllocationQuote(
        p25=_percentile(returns, 0.25),
        p50=_percentile(returns, 0.50),
        p75=_percentile(returns, 0.75),
        samples=len(usable),
        windows=windows,
        perturbations=perturbation_count,
        best_venue_p50=_percentile([r.best_venue_fraction for r in usable], 0.50),
        switches_p50=_percentile([float(r.switches) for r in usable], 0.50),
        hours_per_window=_percentile([r.hours for r in usable], 0.50),
        sufficient=True,
        note="",
        annualised=do_annualise,
        basis=(
            "net return on supplied capital (realized yield − switch costs)"
            if do_annualise
            else (
                f"net return on supplied capital (realized yield − switch costs), "
                f"over {median_hours:.0f}h — too short to annualise honestly"
            )
        ),
        net_positive=sum(1 for x in returns if x > 0),
        returns=tuple(returns),
        max_edge_apr=max((r.max_edge_apr for r in usable), default=0.0),
        hurdle_apr=_percentile([r.hurdle_apr_p50 for r in usable], 0.50),
    )
