"""Liquidity <-> token amounts, ported from Uniswap v3 `SqrtPriceMath` and
`LiquidityAmounts`.

Two families live here and they are not interchangeable:

`get_amount0_delta` / `get_amount1_delta` are the **pool's** functions, which
take an explicit rounding direction. The pool always rounds in its own favour —
up when collecting from the user, down when paying out — and reproducing that
choice is what makes our numbers agree with the contract to the wei.

`get_amount0_for_liquidity` / `get_amount1_for_liquidity` are the **periphery's**
convenience functions, which always round down. `NonfungiblePositionManager`
reports position amounts with these, so a position read from chain must be
compared against these and not against the pool's.

Using the wrong family is a one-wei disagreement that only shows up under a
differential test, which is exactly why we run one.

References: v3-core `libraries/SqrtPriceMath.sol`, v3-periphery
`libraries/LiquidityAmounts.sol`.
"""

from __future__ import annotations

from misquote.core.tickmath import Q96


class LiquidityMathError(ValueError):
    """An argument the v3 math cannot accept, such as a zero sqrt price."""


def _ordered(sqrt_a: int, sqrt_b: int) -> tuple[int, int]:
    return (sqrt_a, sqrt_b) if sqrt_a <= sqrt_b else (sqrt_b, sqrt_a)


def _div_round_up(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


# --- the pool's amount deltas ----------------------------------------------


def get_amount0_delta(sqrt_a: int, sqrt_b: int, liquidity: int, round_up: bool) -> int:
    """Token0 needed to move a position's price between two sqrt ratios.

        amount0 = L * (1/sqrt(Pa) - 1/sqrt(Pb))

    Matches `SqrtPriceMath.getAmount0Delta` including its two-step rounding: the
    numerator rounds up first, then the division by the lower ratio rounds up
    again. Collapsing that into a single ceiling gives a different answer.
    """
    lo, hi = _ordered(sqrt_a, sqrt_b)
    if lo <= 0:
        raise LiquidityMathError("sqrt price must be positive")

    numerator1 = liquidity << 96
    numerator2 = hi - lo

    if round_up:
        return _div_round_up(_div_round_up(numerator1 * numerator2, hi), lo)
    return (numerator1 * numerator2 // hi) // lo


def get_amount1_delta(sqrt_a: int, sqrt_b: int, liquidity: int, round_up: bool) -> int:
    """Token1 needed to move a position's price between two sqrt ratios.

        amount1 = L * (sqrt(Pb) - sqrt(Pa))

    Matches `SqrtPriceMath.getAmount1Delta`.
    """
    lo, hi = _ordered(sqrt_a, sqrt_b)
    product = liquidity * (hi - lo)
    return _div_round_up(product, Q96) if round_up else product // Q96


def get_signed_amount0_delta(sqrt_a: int, sqrt_b: int, liquidity: int) -> int:
    """Signed token0 delta for a liquidity that may be negative.

    The sign convention follows the pool: negative liquidity rounds down, and the
    result carries the sign of the liquidity.
    """
    if liquidity < 0:
        return -get_amount0_delta(sqrt_a, sqrt_b, -liquidity, False)
    return get_amount0_delta(sqrt_a, sqrt_b, liquidity, True)


def get_signed_amount1_delta(sqrt_a: int, sqrt_b: int, liquidity: int) -> int:
    if liquidity < 0:
        return -get_amount1_delta(sqrt_a, sqrt_b, -liquidity, False)
    return get_amount1_delta(sqrt_a, sqrt_b, liquidity, True)


# --- the periphery's liquidity solvers -------------------------------------


def get_liquidity_for_amount0(sqrt_a: int, sqrt_b: int, amount0: int) -> int:
    """Liquidity a given token0 amount buys across a range that is entirely above price."""
    lo, hi = _ordered(sqrt_a, sqrt_b)
    if lo <= 0:
        raise LiquidityMathError("sqrt price must be positive")
    if hi == lo:
        raise LiquidityMathError("range has zero width")
    intermediate = lo * hi // Q96
    return amount0 * intermediate // (hi - lo)


def get_liquidity_for_amount1(sqrt_a: int, sqrt_b: int, amount1: int) -> int:
    """Liquidity a given token1 amount buys across a range that is entirely below price."""
    lo, hi = _ordered(sqrt_a, sqrt_b)
    if hi == lo:
        raise LiquidityMathError("range has zero width")
    return amount1 * Q96 // (hi - lo)


def get_liquidity_for_amounts(
    sqrt_price: int, sqrt_a: int, sqrt_b: int, amount0: int, amount1: int
) -> int:
    """Liquidity obtainable from both amounts at the current price.

    Below the range the position is all token0, above it all token1, and inside
    it the binding constraint is whichever side runs out first — hence the min.
    Matches `LiquidityAmounts.getLiquidityForAmounts`.
    """
    lo, hi = _ordered(sqrt_a, sqrt_b)

    if sqrt_price <= lo:
        return get_liquidity_for_amount0(lo, hi, amount0)
    if sqrt_price < hi:
        return min(
            get_liquidity_for_amount0(sqrt_price, hi, amount0),
            get_liquidity_for_amount1(lo, sqrt_price, amount1),
        )
    return get_liquidity_for_amount1(lo, hi, amount1)


def get_amount0_for_liquidity(sqrt_a: int, sqrt_b: int, liquidity: int) -> int:
    """Token0 a position holds across a range. Rounds down, periphery-style."""
    lo, hi = _ordered(sqrt_a, sqrt_b)
    if lo <= 0:
        raise LiquidityMathError("sqrt price must be positive")
    return ((liquidity << 96) * (hi - lo) // hi) // lo


def get_amount1_for_liquidity(sqrt_a: int, sqrt_b: int, liquidity: int) -> int:
    """Token1 a position holds across a range. Rounds down, periphery-style."""
    lo, hi = _ordered(sqrt_a, sqrt_b)
    return liquidity * (hi - lo) // Q96


def get_amounts_for_liquidity(
    sqrt_price: int, sqrt_a: int, sqrt_b: int, liquidity: int
) -> tuple[int, int]:
    """Both token amounts a position holds at the current price.

    This is what `NonfungiblePositionManager.positions()` implies, so it is the
    function the fork differential compares against. Matches
    `LiquidityAmounts.getAmountsForLiquidity`.
    """
    lo, hi = _ordered(sqrt_a, sqrt_b)

    if sqrt_price <= lo:
        return get_amount0_for_liquidity(lo, hi, liquidity), 0
    if sqrt_price < hi:
        return (
            get_amount0_for_liquidity(sqrt_price, hi, liquidity),
            get_amount1_for_liquidity(lo, sqrt_price, liquidity),
        )
    return 0, get_amount1_for_liquidity(lo, hi, liquidity)


def capital_for_liquidity_cap(
    sqrt_price_x96: int,
    sqrt_a: int,
    sqrt_b: int,
    *,
    dec1: int,
    pool_liquidity: int,
    eps: float,
) -> float:
    """The largest `capital_quote` that does **not** breach A1's ceiling here.

    The exact inverse of `liquidity_for_capital`'s cap branch: that function
    reports *whether* the ceiling bound the position, and this one answers *at
    what capital it starts to*. Same arithmetic, read the other way, so the two
    cannot disagree about where the boundary is.

    Why it is needed. A1's ceiling is `eps x pool_liquidity`, which is a property
    of the **pool**, not of the strategy. Comparing an agent across two venues at
    one capital therefore asks a question the shallower venue may be unable to
    answer: the flagship WBNB/USDT pool carries about 191x the median liquidity
    of the 0.25% tier, so a position that sits comfortably inside A1 on one
    breaches it on the other and A1 says such a quote is refused, not clamped.
    Picking the capital by hand until both clear would be fitting a published
    number to the answer it produces; deriving it is not.

    Returns a float because it is a boundary, not a position size. Callers that
    need to stay inside it should take a margin — a capital computed to land
    exactly on the ceiling breaches it on the first swap that removes liquidity.
    """
    reference = 10**24
    ref0, ref1 = get_amounts_for_liquidity(sqrt_price_x96, sqrt_a, sqrt_b, reference)
    price_raw = (sqrt_price_x96 / Q96) ** 2
    value_ref = ref0 * price_raw + ref1
    if value_ref <= 0 or pool_liquidity <= 0:
        return 0.0
    cap = pool_liquidity * eps
    return cap * value_ref / (reference * 10**dec1)


def liquidity_for_capital(
    sqrt_price_x96: int,
    sqrt_a: int,
    sqrt_b: int,
    *,
    capital_quote: float,
    dec1: int,
    pool_liquidity: int,
    eps: float,
) -> tuple[int, bool]:
    """Liquidity worth `capital_quote` in token1, and whether A1's cap bound it.

    Lives here because it lived in `ReplayDriver._size` **and**
    `WardenLive._size`, identically, and correcting one diverged the two drivers
    — which test L1 caught on the next run. That is the fifth time the answer has
    been *one implementation, both drivers*; the position bookkeeping, the fee
    window, the action cap and the gas constant were the others.

    Two things it fixes about the version it replaces:

    **It splits the capital.** The old code passed `capital_quote` as *both*
    token amounts and let `get_liquidity_for_amounts` take whichever bound. On a
    USDT/WBNB pool that is 1,000 USDT beside 1,000 WBNB — $1,000 beside $613,000
    — so the cheap leg bound and the position deployed roughly twice the stated
    capital while every return was divided by the stated figure. Amounts scale
    linearly in liquidity, so one evaluation at a reference gives the exchange
    rate and the split falls out.

    **It reports the A1 breach instead of swallowing it.** A1 says a quote that
    would breach epsilon is *refused rather than rendered*; the cap was applied
    silently and the quote published anyway.

    `price_raw` is token1 per token0 in raw units, which is exactly what
    `sqrtPriceX96` encodes, so no decimal conversion is needed here.
    """
    reference = 10**24
    ref0, ref1 = get_amounts_for_liquidity(sqrt_price_x96, sqrt_a, sqrt_b, reference)
    price_raw = (sqrt_price_x96 / Q96) ** 2
    value_ref = ref0 * price_raw + ref1
    if value_ref <= 0:
        return 1, False

    wanted = int(reference * (capital_quote * 10**dec1) / value_ref)
    cap = int(pool_liquidity * eps)
    return max(1, min(wanted, cap)), wanted > cap
