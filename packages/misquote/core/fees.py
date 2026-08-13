"""Fee-growth accounting, ported from Uniswap v3 `Tick` and `Position`.

**Read this before touching anything here.**

v3's fee-growth accumulators are `uint256` counters that are *expected* to
overflow and wrap. The contracts do every subtraction on them inside `unchecked`
blocks, and correctness depends on that wraparound: only the difference between
two snapshots is meaningful, and modular arithmetic makes the difference come out
right even when the counter has wrapped between them.

Python's integers do not wrap. A direct translation of

    feeGrowthInside0X128 - _self.feeGrowthInside0LastX128

produces a large negative number instead of a small positive one, and the fee it
implies is silently, catastrophically wrong — not an exception, just a number
that looks plausible on a card. Every subtraction in this module is therefore
masked back into 256 bits by hand.

This is the single reason the tick math is a hand port rather than a dependency:
a library that gets this wrong fails in a way no unit test written against it
would notice.

References: v3-core `libraries/Tick.sol` (`getFeeGrowthInside`) and
`libraries/Position.sol` (`update`).
"""

from __future__ import annotations

MASK256 = (1 << 256) - 1
Q128 = 1 << 128


def sub256(a: int, b: int) -> int:
    """`a - b` as the EVM computes it: modulo 2^256, wrapping on underflow."""
    return (a - b) & MASK256


def fee_growth_inside(
    fee_growth_global0_x128: int,
    fee_growth_global1_x128: int,
    lower_outside0_x128: int,
    lower_outside1_x128: int,
    upper_outside0_x128: int,
    upper_outside1_x128: int,
    tick_current: int,
    tick_lower: int,
    tick_upper: int,
) -> tuple[int, int]:
    """Fee growth per unit of liquidity accrued inside [tick_lower, tick_upper].

    Each initialized tick stores the fee growth on the *other* side of itself
    from the current price, and flips that stored value when price crosses it.
    So "inside" is the global total minus what accrued below the lower tick and
    above the upper one, and which expression gives "below" or "above" depends on
    where the current tick sits relative to each bound.

    Every subtraction wraps, exactly as `Tick.getFeeGrowthInside` does.
    """
    if tick_current >= tick_lower:
        below0 = lower_outside0_x128
        below1 = lower_outside1_x128
    else:
        below0 = sub256(fee_growth_global0_x128, lower_outside0_x128)
        below1 = sub256(fee_growth_global1_x128, lower_outside1_x128)

    if tick_current < tick_upper:
        above0 = upper_outside0_x128
        above1 = upper_outside1_x128
    else:
        above0 = sub256(fee_growth_global0_x128, upper_outside0_x128)
        above1 = sub256(fee_growth_global1_x128, upper_outside1_x128)

    inside0 = sub256(sub256(fee_growth_global0_x128, below0), above0)
    inside1 = sub256(sub256(fee_growth_global1_x128, below1), above1)
    return inside0, inside1


def tokens_owed(
    fee_growth_inside_last_x128: int, fee_growth_inside_now_x128: int, liquidity: int
) -> int:
    """Fees a position earned between two snapshots of its inside fee growth.

        owed = (growth_now - growth_last) * L / 2^128

    The subtraction wraps. Without the mask this returns a huge negative number
    whenever the global accumulator has passed 2^256 since the last snapshot,
    and the position's fees are then reported as nonsense. Matches
    `Position.update`.
    """
    if liquidity < 0:
        raise ValueError("liquidity cannot be negative")
    return (sub256(fee_growth_inside_now_x128, fee_growth_inside_last_x128) * liquidity) >> 128


def fee_amount_for_swap(amount_in: int, fee_pips: int) -> int:
    """The fee a swap of `amount_in` pays, in input-token units.

    Pancake charges the fee on the way in, so this is a fraction of the gross
    input rather than of the amount that reaches the curve. `fee_pips` is
    hundredths of a basis point: 500 is 0.05%.
    """
    if not 0 <= fee_pips < 1_000_000:
        raise ValueError(f"fee_pips {fee_pips} outside [0, 1e6)")
    return amount_in * fee_pips // 1_000_000


def liquidity_share(position_liquidity: int, pool_liquidity: int, *, includes_self: bool) -> float:
    """The fraction of a swap's fees a position earns.

    `includes_self` is the flag that resolves matrix item D-1. A `Swap` event's
    `liquidity` field is the pool's *active* liquidity, which already contains a
    real position's contribution — so dividing by `pool + position` would count
    it twice. For a hypothetical position replayed over history it genuinely was
    not in the pool, and the spec's `L/(L_pool + L)` form is correct.

    The default is the spec form because it understates our fees, and an honest
    quote errs against itself.
    """
    if position_liquidity <= 0:
        return 0.0
    denominator = pool_liquidity if includes_self else pool_liquidity + position_liquidity
    if denominator <= 0:
        return 0.0
    return position_liquidity / denominator
