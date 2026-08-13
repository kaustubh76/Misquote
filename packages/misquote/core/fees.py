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


PROTOCOL_FEE_DENOMINATOR = 10_000


def fee_amount_from_gross(amount_in_gross: int, fee_pips: int) -> int:
    """Total fee on a swap, given the *gross* input the trader sent.

    `fee_pips` is hundredths of a basis point: 500 is 0.05%.
    """
    if not 0 <= fee_pips < 1_000_000:
        raise ValueError(f"fee_pips {fee_pips} outside [0, 1e6)")
    return amount_in_gross * fee_pips // 1_000_000


def fee_amount_from_net(amount_in_net: int, fee_pips: int) -> int:
    """Total fee, given the amount that actually reached the curve.

    This is v3 `SwapMath`'s target-reached branch, and the denominator is
    `1e6 - feePips`, not `1e6`:

        feeAmount = mulDivRoundingUp(amountIn, feePips, 1e6 - feePips)

    Because gross = net + fee, the two forms describe the same fee — but applying
    the gross formula to a net amount understates it by a factor of
    `(1e6 - feePips)/1e6`, which on a 0.05% pool is 0.05% of the fee on every
    swap that crosses a tick. Rounding is up, as the contract does.
    """
    if not 0 <= fee_pips < 1_000_000:
        raise ValueError(f"fee_pips {fee_pips} outside [0, 1e6)")
    denominator = 1_000_000 - fee_pips
    return -(-(amount_in_net * fee_pips) // denominator)


def lp_share_of_fee(total_fee: int, fee_protocol: int) -> int:
    """The part of a swap's fee that reaches liquidity providers.

    **PancakeSwap's protocol fee is on by default, and Uniswap's is not.** Our
    target pool (WBNB/USDT, 0.05%) reports `slot0.feeProtocol = 3400`, so the
    protocol takes 34% and LPs keep 66% — an effective fee of 0.033%, not 0.05%.
    Read from chain, not assumed: it is settable by governance per pool.

    This matters more than its size suggests. Reconstructing fees from `Swap`
    events times the fee tier — the natural way to write the replay engine —
    overstates what an LP actually earns by `1/0.66 = 1.52x`, and that error
    lands directly on NetFeeAPR, which is the headline number on every card. It
    also flows into the R2 recentre gate, making the agent rebalance more eagerly
    than the economics justify.

    Fee growth read from `feeGrowthInside` on chain is already net of this, so
    the two paths must not both apply it.

    v3 subtracts the protocol's share *before* updating the accumulators, so
    this rounds the same way the contract does — down, in the protocol's favour.
    """
    if not 0 <= fee_protocol <= PROTOCOL_FEE_DENOMINATOR:
        raise ValueError(f"fee_protocol {fee_protocol} outside [0, {PROTOCOL_FEE_DENOMINATOR}]")
    protocol_cut = total_fee * fee_protocol // PROTOCOL_FEE_DENOMINATOR
    return total_fee - protocol_cut


def unpack_fee_protocol(slot0_fee_protocol: int) -> tuple[int, int]:
    """`slot0.feeProtocol` -> (token0 numerator, token1 numerator), each out of 10,000.

    Pancake packs the two directions into one word, low half for token0. Our
    target pool reads 222,825,800, which unpacks to (3400, 3400).
    """
    return slot0_fee_protocol & 0xFFFF, slot0_fee_protocol >> 16


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
