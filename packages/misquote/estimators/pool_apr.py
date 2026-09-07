"""What a PancakeSwap v3 position actually earned, per unit of capital, per year.

The primitive the PancakeSwap challenge needs and this repository did not have.
`estimators/apr.py` answers the same question for a *lending* market by
differencing an interest accumulator; a concentrated-liquidity pool has no
accumulator to difference, and its yield is not a property of the pool at all.

## Fee APR is not a number a pool has

A lending market pays every supplier the same rate. A v3 pool does not: two LPs
in the same pool at the same moment earn different returns because they chose
different widths. Narrow earns dense fees and leaves the range; wide earns thin
fees and stays. So "the APR of pool X" is not a well-formed quantity, and any
surface that prints one is quoting something that does not exist.

This estimator therefore **carries the width it was asked about** and cannot be
constructed without one. `reference_width_ticks` is on the result, on every
render, and in the assumption sheet. A caller who wants "the pool's APR" has to
say which position they mean.

## What it reuses, and why it reuses rather than restates

`LvrAccountant` already prorates a swap's fee to a position by liquidity share
and by how much of the price move happened inside the range (assumption A11), and
already takes the protocol's cut from the event's own `protocolFeesToken*` fields
rather than modelling 34% — which matters because P-1 and P-8 established that no
constant is right for both of our pools (3400 on the flagship, 3200 on the 0.25%
tier). Reimplementing that here would be a second copy of the one piece of
arithmetic this project has already got wrong twice.

So this wraps an accountant rather than doing fee maths. The estimator's own job
is narrow: hold the trailing window, know when it has too little to speak, and
divide by the right capital.

## Fees alone are a misquote

`value()` returns the fee APR because that is what the interface promises, but
`fit()` returns fees **and** the realized convexity cost from the same window,
and every caller in this repository is expected to render the pair. A fee APR
published without its adverse-selection cost is exactly the overstatement A10
exists to prevent: it is the gross number, and the gross number is the one every
other venue quotes.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from misquote.core.liquidity import get_amounts_for_liquidity, get_liquidity_for_amounts
from misquote.core.tickmath import Q96, get_sqrt_ratio_at_tick
from misquote.core.types import Event, PoolMeta
from misquote.estimators.base import TrailingEstimator
from misquote.lvr.accountant import LvrAccountant

HOURS_PER_YEAR = 8760.0

#: Below this many swaps inside the window the estimator is not `ready`.
#:
#: The same discipline `kappa` applies before it will publish a fit and the
#: tearsheet applies before it will call a verdict. A fee APR from four swaps is
#: a number, not evidence — and on a pool like TSLAx/USDT, which has 85 swaps
#: across the whole 30-day tape, publishing one would turn "we have no idea" into
#: a figure someone could sort a table by.
MIN_SWAPS = 30


@dataclass(frozen=True, slots=True)
class PoolAprFit:
    """A fee APR with everything needed to refuse to believe it."""

    apr: float
    #: The width this answer is about. There is no width-free answer.
    reference_width_ticks: int
    #: Realized convexity cost over the same window, as an APR on the same
    #: capital. An upper bound on adverse selection (A10), never netted silently.
    convexity_cost_apr: float
    fees_quote: float
    convexity_cost_quote: float
    capital_quote: float
    swaps: int
    hours: float
    is_ready: bool
    #: What the pool's own depth over the reference range is worth, in the
    #: pool's quote token. The size a position is measured *against*, never the
    #: size of the position itself.
    #:
    #: A1 bounds a replayed position at a fraction of the venue it sits in, so
    #: it needs the venue's size. `capital_quote` is what we deployed, which is
    #: the one quantity that cannot bound itself: a ceiling computed from the
    #: thing it is meant to constrain is not a ceiling.
    #:
    #: Defaulted so the eight-field constructor in existing tests still builds,
    #: and defaulted to zero rather than to something permissive: an unmeasured
    #: depth must absorb nothing, on the same argument the driver already makes
    #: about a market it has not observed.
    depth_quote: float = 0.0

    #: The range this fit is about, in ticks, as the accountant received it.
    #:
    #: `_compute` snaps the window's opening tick to the spacing and takes
    #: `centre +/- width`, and until now that range existed only inside the
    #: method. Anything wanting to *draw* the position — `/simulate` does — had
    #: to redo the snap from the same events, which is a second implementation
    #: of the one thing that decides which swaps paid this position at all. A
    #: drawn range one tick from the accounted range is a picture of a different
    #: position than the figures beside it.
    #:
    #: Both zero when the fit is not ready, and the pair is meaningless then:
    #: a refused fit accounted over nothing.
    tick_lower: int = 0
    tick_upper: int = 0

    @property
    def net_apr(self) -> float:
        """Fee APR minus the convexity-cost upper bound.

        Stated as a property rather than a stored field so it cannot drift from
        its two parts, and so a reader can see it is a subtraction rather than a
        third measurement.
        """
        return self.apr - self.convexity_cost_apr

    @property
    def label(self) -> str:
        """The estimator's own sentence about itself, for the card to render."""
        if not self.is_ready:
            return f"no verdict ({self.swaps} swaps, need {MIN_SWAPS})"
        return (
            f"{self.apr:.2%} fees, {self.convexity_cost_apr:.2%} convexity cost, "
            f"at +/-{self.reference_width_ticks} ticks"
        )


class PoolAprEstimator(TrailingEstimator):
    """Realized fee APR for a position of a stated width, over a trailing window.

    Subclasses `TrailingEstimator` so the no-look-ahead guards apply
    unconditionally: an event newer than the decision time raises, and so does
    one out of chain order. That is not decoration here — a fee APR is exactly
    the kind of number it would be easy to compute over a window that includes
    the future and never notice.
    """

    __slots__ = ("_meta", "_width", "_window_s", "_events", "_capital", "_centre", "_cached")

    def __init__(
        self,
        meta: PoolMeta,
        *,
        reference_width_ticks: int,
        capital_quote: float,
        window_seconds: int = 24 * 3600,
    ) -> None:
        super().__init__()
        if reference_width_ticks <= 0:
            raise ValueError(
                "a fee APR needs a width: a v3 pool has no width-free yield, and a "
                "caller that does not name one is asking a question with no answer"
            )
        if capital_quote <= 0:
            raise ValueError("capital must be positive: it is the denominator")
        self._meta = meta
        self._width = reference_width_ticks
        self._capital = capital_quote
        self._window_s = window_seconds
        # A deque, and the reason is measured rather than stylistic. Eviction is
        # from the front only — events arrive in chain order — so a deque pops in
        # O(1). The list this replaced was rebuilt by a comprehension on *every*
        # event, which is O(n) per event and therefore O(n^2) per window: on a
        # window holding 126,000 swaps that is ~16 billion operations, and it
        # turned a width ladder over the real tape into a 100-minute job.
        self._events: deque[Event] = deque()
        self._centre: int | None = None
        # The last fit, held until the window changes.
        #
        # `fit()` replays an `LvrAccountant` over the entire window on every
        # call, and the allocation driver asks for one two to three times per
        # sample — to accrue, to quote, and again to rebase on entry. Recomputing
        # an identical answer is the same class of waste as the eviction bug
        # above, and the same size: on the real tape a 24h window holds ~8,400
        # swaps and a 30-day replay takes ~725 hourly samples, so the repeats
        # alone were ~6 billion accountant steps.
        #
        # The invariant that makes this safe is narrow and checkable: a fit is a
        # pure function of `_events` and `_centre`, and both change in exactly
        # two places — `_absorb` and `_on_time_advanced`. Neither the decision
        # time nor anything else `TrailingEstimator` holds enters the result.
        self._cached: PoolAprFit | None = None

    def _absorb(self, event: Event) -> None:
        if event.kind != "swap":
            return
        if self._centre is None:
            self._centre = event.tick
        self._events.append(event)
        self._cached = None

    def _on_time_advanced(self) -> None:
        """Retire what has aged out, so `ready` can answer honestly.

        Eviction belongs here rather than in `value()` for the reason
        `TrailingEstimator` gives: an estimator whose window has emptied is not
        ready, and finding that out only when someone asks for the number is how
        a stale estimate gets published as a fresh one.
        """
        cutoff = self.decision_time - self._window_s
        popped = False
        while self._events and self._events[0].ts < cutoff:
            self._events.popleft()
            popped = True
        # The centre is the oldest surviving tick — the range an LP would have
        # opened when the window began. Only re-read when something actually
        # aged out, so the common case costs one comparison.
        if popped:
            self._cached = None
            if self._events:
                self._centre = self._events[0].tick

    @property
    def ready(self) -> bool:
        return len(self._events) >= MIN_SWAPS

    def value(self) -> float:
        """The trailing fee APR. Zero — no verdict — before the floor."""
        return self.fit().apr

    def fit(self) -> PoolAprFit:
        """The estimate with everything needed to disbelieve it attached."""
        if self._cached is not None:
            return self._cached
        self._cached = fit = self._compute()
        return fit

    def _compute(self) -> PoolAprFit:
        events = self._events
        if not events or self._centre is None:
            return PoolAprFit(0.0, self._width, 0.0, 0.0, 0.0, self._capital, 0, 0.0, False)

        spacing = self._meta.tick_spacing
        centre = (self._centre // spacing) * spacing
        lower, upper = centre - self._width, centre + self._width

        sqrt_price = events[0].sqrt_price_x96
        liquidity = self._liquidity_for_capital(sqrt_price, lower, upper)
        if liquidity <= 0:
            return PoolAprFit(0.0, self._width, 0.0, 0.0, 0.0, self._capital, 0, 0.0, False)

        # The accountant does the fee and LVR arithmetic. This class does not.
        book = LvrAccountant(lower, upper, liquidity, self._meta, l_pool_includes_self=False)
        for event in events:
            book.absorb(event)

        hours = max(1e-9, (events[-1].ts - events[0].ts) / 3600.0)
        scale = HOURS_PER_YEAR / hours / self._capital
        return PoolAprFit(
            apr=book.total_fees * scale,
            reference_width_ticks=self._width,
            convexity_cost_apr=book.total_lvr * scale,
            fees_quote=book.total_fees,
            convexity_cost_quote=book.total_lvr,
            capital_quote=self._capital,
            swaps=len(events),
            hours=hours,
            is_ready=len(events) >= MIN_SWAPS,
            depth_quote=self._depth_quote(sqrt_price, lower, upper),
            tick_lower=lower,
            tick_upper=upper,
        )

    def _depth_quote(self, sqrt_price: int, lower: int, upper: int) -> float:
        """What the pool's own liquidity over this range is worth, in quote.

        The median active liquidity across the window rather than the latest,
        for the reason every other figure here is a median: one swap's `liquidity`
        is whatever happened to be in range at that block, and sizing a ceiling
        off a single observation is how a quiet moment becomes a claim about the
        pool. `tearsheet/pools.py` measures depth the same way from the same
        field, and this is the trailing-window counterpart of it.
        """
        active = sorted(float(e.liquidity) for e in self._events if e.liquidity > 0)
        if not active:
            return 0.0
        median = active[len(active) // 2]
        return self._quote_value(sqrt_price, lower, upper, int(median))

    def _liquidity_for_capital(self, sqrt_price: int, lower: int, upper: int) -> int:
        """How much liquidity `capital_quote` buys at this price and width.

        Solved by scaling rather than inverted in closed form: ask what one unit
        of liquidity costs across the two legs, then buy as many as the capital
        affords. The alternative is a second implementation of the amounts maths,
        and `core/liquidity.py` is differential-tested against the real Solidity
        while a reimplementation here would not be.
        """
        sa, sb = get_sqrt_ratio_at_tick(lower), get_sqrt_ratio_at_tick(upper)
        probe = get_liquidity_for_amounts(sqrt_price, sa, sb, 10**18, 10**18)
        if probe <= 0:
            return 0
        cost = self._quote_value(sqrt_price, lower, upper, probe)
        if cost <= 0:
            return 0
        return int(probe * (self._capital / cost))

    def _quote_value(self, sqrt_price: int, lower: int, upper: int, liquidity: int) -> float:
        """Both legs of a position, valued in the quote token.

        Shared by the two callers rather than written twice. The second copy is
        the one that would drift, and what it computes — how much a quantity of
        liquidity is worth — is the denominator of a fee APR in one caller and
        the denominator of A1's ceiling in the other. Those disagreeing would be
        invisible and would make the ceiling meaningless in exactly the units it
        is expressed in.
        """
        if liquidity <= 0:
            return 0.0
        sa, sb = get_sqrt_ratio_at_tick(lower), get_sqrt_ratio_at_tick(upper)
        amount0, amount1 = get_amounts_for_liquidity(sqrt_price, sa, sb, liquidity)
        price = ((sqrt_price / Q96) ** 2) * 10.0 ** (self._meta.dec0 - self._meta.dec1)
        return amount1 / 10.0**self._meta.dec1 + (amount0 / 10.0**self._meta.dec0) * price
