"""Realized adverse selection, per swap, from chain events (spec section 4).

Spec equation (3):

    LVR_k = -( dy_k + P_k * dx_k )  >= 0

where `(dx_k, dy_k)` is how *our* position's holdings moved along the bonding
curve during swap k, and `P_k` is the **post-swap** price. The story it tells:
the pool trades at stale prices, so the position sells into a rise below what
the market ends up paying and buys into a fall above it. The gap is the
arbitrageur's edge, and it is exactly what the LP gave up.

Three things here were found by verification rather than by writing the obvious
code, and each one changes the number by a lot.

**Clamp the price path to the position's range** (matrix P-3). A swap that
crosses the range entirely and is accounted end-to-end overstates LVR by 3x
typically and 53x in the measured worst case. Above the upper bound the position
holds no token0 — there is nothing left to pick off — and the rebalancing
benchmark has sold out too. Only the segment inside the range ever involved us.
Since this agent runs narrow ranges by design, that is the common case.

**Strip the fee before forming the deltas** (matrix P-2). Swap event amounts are
gross of the fee. Feeding them in directly computes `LVR_k - fee_k`, which both
loses equation (3)'s non-negativity guarantee and double-counts against `F` in
equation (4). The post-swap `sqrtPriceX96` is already fee-exclusive, which is why
deriving the deltas from the *price path* rather than from the event amounts is
the right move — the curve math never sees a gross amount at all.

**The protocol keeps 34%** (matrix P-1). Pancake's Swap event reports its cut
per swap, so what an LP earns is read from chain rather than modelled.

And one honest caveat, published as A10: equation (3) is non-negative for every
swap regardless of who traded, which is the tell that it is not really measuring
adverse selection. It assumes the post-swap *pool* price is fair, so a round trip
`P0 -> P1 -> P0` books a loss where the LP was flat and collected two fees. It is
an **upper bound** on LVR, and the tearsheet says so.
"""

from __future__ import annotations

from dataclasses import dataclass

from misquote.core.fees import fee_amount_from_gross
from misquote.core.liquidity import get_amount0_delta, get_amount1_delta
from misquote.core.tickmath import Q96, get_sqrt_ratio_at_tick
from misquote.core.types import Event, PoolMeta, Tick


@dataclass(frozen=True, slots=True)
class LvrIncrement:
    """One swap's contribution, with the chain reference that produced it.

    `tx` and `log_index` travel with the number so the UI can link every
    increment to BscScan. That is what makes "audit me" a literal instruction
    rather than a slogan.
    """

    block: int
    log_index: int
    tx: str
    ts: int

    lvr_quote: float  # token1 units, >= 0 by convexity
    fee_quote: float  # LP's share of this swap's fee, token1 units, net of protocol
    delta0: float  # our position's token0 change, token0 units
    delta1: float
    price_after: float  # token1 per token0, decimal-adjusted

    in_range: bool  # did any of this swap touch our range at all
    fully_crossed: bool  # did price traverse the whole range in one swap

    @property
    def net_quote(self) -> float:
        """Fees minus adverse selection — the quantity equation (4) is about."""
        return self.fee_quote - self.lvr_quote


class LvrAccountant:
    """Walks a swap tape and accrues LVR and fees for one position.

    Stateful only in the price cursor: it needs the pre-swap price, and a Swap
    event reports the post-swap one. The first event therefore establishes the
    cursor and produces nothing, which is correct rather than a special case —
    there is no prior price against which to have been adversely selected.
    """

    __slots__ = (
        "lower",
        "upper",
        "liquidity",
        "meta",
        "_sqrt_a",
        "_sqrt_b",
        "_sqrt_prev",
        "_scale",
        "l_pool_includes_self",
        "total_lvr",
        "total_fees",
        "swaps_seen",
        "negative_increments",
    )

    def __init__(
        self,
        lower: Tick,
        upper: Tick,
        liquidity: int,
        meta: PoolMeta,
        *,
        sqrt_price_x96: int | None = None,
        l_pool_includes_self: bool = False,
    ) -> None:
        if lower >= upper:
            raise ValueError(f"range is empty: [{lower}, {upper})")
        if liquidity <= 0:
            raise ValueError("a position with no liquidity cannot be adversely selected")

        self.lower = lower
        self.upper = upper
        self.liquidity = liquidity
        self.meta = meta

        self._sqrt_a = get_sqrt_ratio_at_tick(lower)
        self._sqrt_b = get_sqrt_ratio_at_tick(upper)
        self._sqrt_prev = sqrt_price_x96

        # Decimal adjustment, applied once. Price is token1 per token0, so a
        # decimals mismatch scales every LVR figure by a power of ten and is
        # invisible in a ratio — which is how it survives review.
        self._scale = 10.0 ** (meta.dec0 - meta.dec1)

        # Matrix D-1: a live Swap event's `liquidity` already includes a real
        # position's L, so dividing by it double-counts. A hypothetical position
        # in a replay is not in that number and must be added.
        self.l_pool_includes_self = l_pool_includes_self

        self.total_lvr = 0.0
        self.total_fees = 0.0
        self.swaps_seen = 0
        self.negative_increments = 0

    # --- the curve ---------------------------------------------------------

    def _clamp(self, sqrt_price: int) -> int:
        return min(max(sqrt_price, self._sqrt_a), self._sqrt_b)

    def _holdings(self, sqrt_price: int) -> tuple[int, int]:
        """What the position holds at a price, in raw token units.

        Below the range it is all token0, above it all token1, and in between it
        is the split the bonding curve dictates. Same integer math the tick layer
        was differential-tested against.
        """
        s = self._clamp(sqrt_price)
        amount0 = get_amount0_delta(s, self._sqrt_b, self.liquidity, False)
        amount1 = get_amount1_delta(self._sqrt_a, s, self.liquidity, False)
        return amount0, amount1

    def _price(self, sqrt_price_x96: int) -> float:
        return ((sqrt_price_x96 / Q96) ** 2) * self._scale

    # --- fees --------------------------------------------------------------

    def _fee_share(self, event: Event, previous: int) -> float:
        """This position's share of the swap fee, net of the protocol's cut.

        The protocol's cut comes from the event itself rather than from a
        modelled percentage, so it is correct even if governance changes the
        parameter mid-history.

        Fee accrual is prorated by the fraction of the price move that happened
        inside our range — assumption A11. v3 accrues fees to whichever ticks are
        active as price sweeps, so a swap that only clips the edge of our range
        should only pay us for the part it clipped.
        """
        active = event.liquidity
        denominator = active + self.liquidity if not self.l_pool_includes_self else active
        if denominator <= 0:
            return 0.0
        share = self.liquidity / denominator

        # Which token came in, and therefore which fee counter applies.
        if event.amount0 > 0:
            gross_in, protocol_cut, in_quote = event.amount0, event.protocol_fee0, False
        elif event.amount1 > 0:
            gross_in, protocol_cut, in_quote = event.amount1, event.protocol_fee1, True
        else:
            return 0.0

        total_fee = fee_amount_from_gross(gross_in, self.meta.fee_pips)
        lp_fee = max(0, total_fee - protocol_cut)  # P-1, read from chain

        raw = lp_fee / (10.0**self.meta.dec1 if in_quote else 10.0**self.meta.dec0)
        if not in_quote:
            raw *= self._price(event.sqrt_price_x96)

        return raw * share * self._range_fraction(event, previous)

    def _range_fraction(self, event: Event, previous: int) -> float:
        """How much of this swap's price travel happened inside our range.

        Takes the pre-swap price explicitly rather than reading the cursor: by
        the time fees are computed the cursor has already advanced, so reading
        it here compares the post-swap price against itself and silently returns
        all-or-nothing.
        """
        s0, s1 = previous, event.sqrt_price_x96
        if s0 == s1:
            return 1.0 if self._sqrt_a <= s0 <= self._sqrt_b else 0.0
        travelled = abs(s1 - s0)
        inside = abs(self._clamp(s1) - self._clamp(s0))
        return inside / travelled

    # --- the increment -----------------------------------------------------

    def absorb(self, event: Event) -> LvrIncrement | None:
        """Account one swap. Returns None for the first, which sets the cursor."""
        if event.kind != "swap":
            return None

        previous = self._sqrt_prev
        self._sqrt_prev = event.sqrt_price_x96
        if previous is None:
            return None

        self.swaps_seen += 1

        s0, s1 = self._clamp(previous), self._clamp(event.sqrt_price_x96)
        x0, y0 = self._holdings(s0)
        x1, y1 = self._holdings(s1)

        delta0 = (x1 - x0) / (10.0**self.meta.dec0)
        delta1 = (y1 - y0) / (10.0**self.meta.dec1)
        price_after = self._price(s1)

        # Equation (3). The post-swap price is not a choice: using the pre-swap
        # one flips the sign and makes every swap look profitable for the LP.
        lvr = -(delta1 + price_after * delta0)

        # Convexity says this cannot be negative. A negative one is not a market
        # event, it is a sign or decimals bug, so it is counted and surfaced
        # rather than clipped away.
        if lvr < 0.0:
            self.negative_increments += 1
            lvr = max(lvr, 0.0) if abs(lvr) < 1e-9 * max(1.0, abs(price_after)) else lvr

        fee = self._fee_share(event, previous)
        self.total_lvr += lvr
        self.total_fees += fee

        touched = s0 != s1
        return LvrIncrement(
            block=event.block,
            log_index=event.log_index,
            tx=event.tx,
            ts=event.ts,
            lvr_quote=lvr,
            fee_quote=fee,
            delta0=delta0,
            delta1=delta1,
            price_after=price_after,
            in_range=touched,
            fully_crossed=(s0 == self._sqrt_a and s1 == self._sqrt_b)
            or (s0 == self._sqrt_b and s1 == self._sqrt_a),
        )

    # --- what the tearsheet asks for ---------------------------------------

    @property
    def net_fee_minus_lvr(self) -> float:
        """Equation (4)'s numerator: what the position actually kept."""
        return self.total_fees - self.total_lvr


def closed_form_lvr(sqrt_before: int, sqrt_after: int, liquidity: int, scale: float = 1.0) -> float:
    """`LVR = L * (sqrt(Pb) - sqrt(Pa))^2 / sqrt(Pa)`, both endpoints in range.

    An independent derivation of the same quantity, used to check the curve
    implementation rather than to compute anything in production. Agreement
    between a per-holdings difference and a closed form is real evidence; each
    one alone is just an assertion.
    """
    a = sqrt_before / Q96
    b = sqrt_after / Q96
    return liquidity * (b - a) ** 2 / a * scale
