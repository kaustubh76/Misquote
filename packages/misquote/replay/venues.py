"""What differs between a lending market and a liquidity pool, and nothing else.

`AllocationDriver` was written when every venue was a Venus market, and
`agents/router/policy.py:190` argued against inventing a `VenueMeta` to hold the
difference — *"shape for its own sake"*. That was right: there was no difference
to hold. A second venue **type** is exactly the thing that changes it.

Three operations differ, and only three. The policy does not differ at all:
`decide_router` reads `apr`, `apr_samples`, `apr_is_stale` and `venue_id`, and
has never seen a `RateEvent`.

- **estimator** — how a trailing yield is measured. Both `TrailingAprEstimator`
  and `PoolAprEstimator` already subclass `TrailingEstimator`, so this seam
  existed before this module did; it was simply not being used.
- **quote** — what the policy is shown, including the size that bounds A1.
- **accrual** — what the held position actually earned since the last sample.

The third is the one that could not be parameterised. Venus pays an accumulator
ratio times utilisation times `(1 - reserve_factor)`; a pool has no accumulator
at all, and its honest analogue is realized fees minus realized convexity cost
over the interval. Those are different computations, so they are different
methods rather than one method with a flag.

## Why a pool's `apr` is the net figure

`decide_router` ranks venues by `VenueQuote.apr` (`policy.py:216`). A pool
supplying its **gross** fee APR there would be compared against a lending venue's
**net** supply rate and win on the difference alone — a misquote in the strict
sense, and the one `estimators/pool_apr.py` names in its own docstring. So
`PoolVenue.quote` publishes `PoolAprFit.net_apr`, fees minus the
convexity-cost upper bound, and the gross figure stays visible on the card beside
it rather than standing in for it.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from misquote.core.allocation import VenueId, VenueQuote
from misquote.core.types import PoolMeta
from misquote.estimators.apr import DEFAULT_RESERVE_FACTOR, TrailingAprEstimator
from misquote.estimators.base import TrailingEstimator
from misquote.estimators.pool_apr import PoolAprEstimator
from misquote.lvr.accountant import LvrAccountant


@runtime_checkable
class VenueSource(Protocol):
    """The three operations that differ by venue type."""

    #: Rendered on the card so a reader can see which kind of venue this is.
    kind: str

    #: Whether arriving here crosses underlyings, and so pays the swap fee.
    #:
    #: `_move_cost` charged the fee only on a SWITCH, on the argument that
    #: "entering vUSDT from a dollar position that is already USDT swaps
    #: nothing". True of every dollar market and false of a pool: entering a v3
    #: range from a single asset requires half of it to become the other token.
    #: `replay/driver.py` has carried that branch since P-18; this one had no
    #: way to express it until a second venue type existed.
    swaps_on_entry: bool

    def estimator(self, window_seconds: int) -> TrailingEstimator: ...

    def quote(self, venue_id: VenueId, last_event: Any, fit: Any) -> VenueQuote: ...

    def accrue(self, state: Any, events: Any, fit: Any) -> tuple[float, Any]:
        """The fraction of held capital earned since `state` was taken.

        Returns `(fraction, new_state)`. `state` is opaque to the driver — it was
        a `(block, borrow_index)` tuple when Venus was the only venue, and
        generalising it is the one change that reshapes driver state.

        `events` is every row consumed since the previous sample, not just the
        last one. A lending market only needs the last, because `borrowIndex` is
        an accumulator and one reading of it summarises everything before it. A
        pool has no such number on chain: what a range earned over an interval is
        a function of **each** swap in it, so the rows have to arrive.

        Passing only the last row is what made the first pool accrual wrong. See
        `PoolVenue.accrue`.
        """
        ...

    def card_fields(self) -> dict[str, Any]:
        """What the artifact should say about this venue, by type.

        `reserve_factor` has no pool analogue and `reference_width_ticks` has no
        lending one, so the shapes differ and the card renders what is there.
        """
        ...


class LendingVenue:
    """A Venus market. The behaviour the driver had before this module existed."""

    kind = "lending"
    swaps_on_entry = False

    __slots__ = ("meta",)

    def __init__(self, meta: dict[str, Any]) -> None:
        self.meta = meta

    def estimator(self, window_seconds: int) -> TrailingEstimator:
        return TrailingAprEstimator(
            window_seconds=window_seconds,
            reserve_factor=self.meta.get("reserve_factor", DEFAULT_RESERVE_FACTOR),
        )

    def quote(self, venue_id: VenueId, last_event: Any, fit: Any) -> VenueQuote:
        scale = 10 ** int(self.meta.get("underlying_decimals", 18))
        if last_event is None:
            cash = supplied = 0.0
        else:
            cash = last_event.cash_prior / scale
            supplied = (last_event.cash_prior + last_event.total_borrows_prior) / scale
        return VenueQuote(
            venue_id=venue_id,
            apr=fit.supply_apr,
            apr_samples=fit.accruals,
            apr_is_stale=fit.is_stale,
            cash_quote=cash,
            supplied_base_quote=supplied,
        )

    def accrue(self, state: Any, events: Any, fit: Any) -> tuple[float, Any]:
        """Pay the accumulator, not the estimate.

        The module's central claim, unchanged: `borrowIndex` is what the market
        actually did, and the trailing estimate is only what the policy was shown.

        Takes the last of `events` and ignores the rest, which is not laziness:
        an accumulator's whole purpose is that one reading of it stands for every
        accrual before it. That property is exactly what a pool does not have.
        """
        last_event = events[-1] if events else None
        if last_event is None:
            return 0.0, state
        now = (last_event.block, last_event.borrow_index)
        if state is None:
            return 0.0, now
        _prev_block, prev_index = state
        if last_event.borrow_index > prev_index and prev_index > 0:
            growth = last_event.borrow_index / prev_index - 1.0
            return growth * fit.utilisation * (1.0 - fit.reserve_factor), now
        return 0.0, now

    def card_fields(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "symbol": self.meta.get("symbol", ""),
            "reserve_factor": self.meta.get("reserve_factor", DEFAULT_RESERVE_FACTOR),
            "reserve_factor_recorded": self.meta.get("reserve_factor_recorded", False),
            "supplied_base_at_tape_end": self.meta.get("supplied_base_at_tape_end", 0.0),
        }


class PoolVenue:
    """A PancakeSwap v3 pool, at a stated width.

    The width is not optional and is not a default. A21: two LPs in the same pool
    at the same moment earn different returns because they chose differently, so a
    venue that did not name one would be quoting a quantity that does not exist.
    """

    kind = "pool"
    # Half the capital has to become the other token to open a range.
    swaps_on_entry = True

    __slots__ = (
        "pool",
        "width_ticks",
        "capital_quote",
        "quote_price",
        "label",
        "_fees",
        "_costs",
    )

    def __init__(
        self,
        pool: PoolMeta,
        *,
        width_ticks: int,
        capital_quote: float,
        quote_price: float,
        label: str = "",
    ) -> None:
        if width_ticks <= 0:
            raise ValueError("a pool venue needs a width: there is no width-free fee APR (A21)")
        if quote_price <= 0:
            raise ValueError(
                "a pool venue needs the price of its quote token in the router's "
                "units. Every badged pool is quoted in WBNB or TSLAx and the "
                "router keeps its books in dollars, so a size crossing that seam "
                "unconverted is wrong by the price of BNB. There is no default: a "
                "silent 1.0 here is P-25 with a nicer face."
            )
        self.pool = pool
        self.width_ticks = width_ticks
        self.capital_quote = capital_quote
        self.quote_price = quote_price
        self.label = label or pool.address
        # Realized totals at the last accrual, so the driver can be paid the
        # difference rather than a rate. The pool analogue of `borrowIndex`:
        # not an accumulator the chain maintains, but one we keep from the same
        # events the estimator sees.
        self._fees = 0.0
        self._costs = 0.0

    def estimator(self, window_seconds: int) -> TrailingEstimator:
        return PoolAprEstimator(
            self.pool,
            reference_width_ticks=self.width_ticks,
            capital_quote=self.capital_quote,
            window_seconds=window_seconds,
        )

    def quote(self, venue_id: VenueId, last_event: Any, fit: Any) -> VenueQuote:
        """`net_apr`, never `apr`. See this module's docstring."""
        del last_event  # a pool's size comes from the fit, not from one swap
        # A1's ceiling: the pool's own depth over the reference range, converted
        # into the units the router keeps its books in.
        #
        # This read `fit.capital_quote` — what we deployed — under a comment
        # saying it was what the pool could absorb. A ceiling derived from the
        # position it is meant to bound is not a ceiling, and against a $10,000
        # notional it made `capped_notional` (`policy.py:178`) meaningless in
        # both directions at once.
        depth = fit.depth_quote * self.quote_price if fit.is_ready else 0.0
        return VenueQuote(
            venue_id=venue_id,
            apr=fit.net_apr,
            apr_samples=fit.swaps,
            apr_is_stale=not fit.is_ready,
            # A pool has no "free liquidity to withdraw" in the lending sense.
            cash_quote=0.0,
            supplied_base_quote=max(depth, 0.0),
            # A10: the convexity cost is an upper bound, so fees minus it is a
            # lower bound. Declared rather than assumed, because the -100% floor
            # `VenueQuote` applies to a lending rate is wrong for an annualised
            # one and the type has to be told which it is holding.
            apr_is_lower_bound=True,
        )

    def accrue(self, state: Any, events: Any, fit: Any) -> tuple[float, Any]:
        """What the range actually earned over the interval, from its own book.

        ## The first version of this paid a ratchet

        It differenced `fit.fees_quote - fit.convexity_cost_quote` between
        samples — the totals of a **trailing window**. Those do not accumulate.
        As the window slides an hour it gains an hour of swaps and drops an hour
        of swaps, so the delta is (entering − leaving), which is mean-zero over
        a long hold rather than the interval's earnings. Flooring it at zero,
        which I justified as "the window moving, not a loss", then kept only the
        positive half of a mean-zero series. It drifted upward without bound, and
        the longer a position was held the worse it got:

            120h hold, flagship at +/-80
              this method       1.5034% of capital  ->  109.8% annualised
              the same fit      net                     23.40% annualised

        Nothing published carried it: at the notional Router is quoted on, A1
        refuses every range, so no pool was ever held and the pool contribution
        to `gross_yield_quote` was zero. It would have become wrong the moment a
        position was small enough to open.

        ## What pays instead

        A position, which is what an LP holds. The range is fixed at entry — the
        centre and width chosen then — and an `LvrAccountant` absorbs every swap
        since. Its `total_fees` and `total_lvr` only grow, so differencing them
        is the interval's earnings and nothing else.

        That restores the split `LendingVenue` already had and this did not: **a
        monotonic accumulator pays, a trailing window estimates.** Venus
        differences `borrowIndex` and quotes from a trailing fit; this
        differences an accountant and quotes from the same fit. `replay/driver.py`
        holds a real range exactly this way, and the reason is the same one —
        `l_pool_includes_self=False`, so the position is diluted by its own
        liquidity rather than earning as though it were not there.
        """
        if self.capital_quote <= 0:
            return 0.0, state
        swaps = [e for e in (events or ()) if e.kind == "swap"]

        if state is None:
            # Opening. The range is chosen once, here, from the price this swap
            # left behind — and never re-derived, because an LP who opened at
            # +/-80 around one tick still holds that range when the price moves.
            # Re-centring it every sample is what let the window's own drift
            # leak into the payment.
            if not swaps:
                return 0.0, None
            book = self._open_at(swaps[-1])
            if book is None:
                return 0.0, None
            return 0.0, (book, 0.0)

        book, paid = state
        for event in swaps:
            book.absorb(event)
        booked = book.total_fees - book.total_lvr
        # Charged in both directions. A range really can lose over an interval —
        # that is what the convexity cost is — and flooring it here is exactly
        # the mistake this method is written against.
        return (booked - paid) / self.capital_quote, (book, booked)

    def _open_at(self, event: Any) -> LvrAccountant | None:
        """The book for a range opened around this swap, or nothing.

        Mirrors `PoolAprEstimator.fit`'s sizing so the position paid for is the
        position quoted: the same spacing-aligned centre, the same width, and the
        same capital converted to liquidity by `core/liquidity.py`.
        """
        spacing = self.pool.tick_spacing
        centre = (event.tick // spacing) * spacing
        lower, upper = centre - self.width_ticks, centre + self.width_ticks
        liquidity = self._liquidity_for(event.sqrt_price_x96, lower, upper)
        if liquidity <= 0:
            return None
        return LvrAccountant(lower, upper, liquidity, self.pool, l_pool_includes_self=False)

    def _liquidity_for(self, sqrt_price: int, lower: int, upper: int) -> int:
        """How much liquidity this venue's capital buys at this price and width.

        Delegated to the estimator rather than reimplemented: a second copy of
        the sizing would be a second answer to "what position is this", and the
        payment and the quote have to be about the same one.
        """
        est = PoolAprEstimator(
            self.pool,
            reference_width_ticks=self.width_ticks,
            capital_quote=self.capital_quote,
        )
        return est._liquidity_for_capital(sqrt_price, lower, upper)  # noqa: SLF001

    def card_fields(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "symbol": self.label,
            "fee_pips": self.pool.fee_pips,
            "reference_width_ticks": self.width_ticks,
            "lp_fee_share": 1.0 - self.pool.fee_protocol / 10_000.0,
            # On the card because the comparison is not unit-clean and saying so
            # is the only honest way to publish it: this pool's fee rate is
            # measured in its own quote token while the lending rates beside it
            # are dollar rates, and this is the price that reconciled the sizes.
            "quote_price_quote": self.quote_price,
        }


def as_venue(value: Any) -> VenueSource:
    """Accept the plain dict the driver has always taken, or a venue source.

    Every existing caller and fixture passes `{"reserve_factor": ..., ...}`, and
    rewriting them all to construct a `LendingVenue` would be a large diff whose
    only effect is to say the same thing differently. A dict means Venus, which is
    what it has always meant.
    """
    if isinstance(value, dict):
        return LendingVenue(value)
    return value
