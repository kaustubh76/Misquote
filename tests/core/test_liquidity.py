"""Liquidity <-> amount conversions, and the rounding directions that make them
agree with the contract to the wei."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from misquote.core.liquidity import (
    LiquidityMathError,
    get_amount0_delta,
    get_amount0_for_liquidity,
    get_amount1_delta,
    get_amount1_for_liquidity,
    get_amounts_for_liquidity,
    get_liquidity_for_amounts,
    get_signed_amount0_delta,
    get_signed_amount1_delta,
)
from misquote.core.tickmath import Q96, get_sqrt_ratio_at_tick

# A realistic band around the live pool: tick -64183, spacing 10.
LOWER, UPPER = -64400, -64000
SA = get_sqrt_ratio_at_tick(LOWER)
SB = get_sqrt_ratio_at_tick(UPPER)
SP = get_sqrt_ratio_at_tick(-64183)

# A position with single-digit liquidity is dust: its amounts round to zero, and
# w_min exists precisely so the policy never mints one. Properties about holdings
# are therefore stated over liquidity a real position could have.
liquidities = st.integers(min_value=10**15, max_value=10**30)
interior_ticks = st.integers(min_value=LOWER + 1, max_value=UPPER - 1)
in_range_ticks = st.integers(min_value=LOWER, max_value=UPPER)


def test_amount_deltas_are_order_independent() -> None:
    """The bounds are a set, not a sequence — passing them backwards is not an error."""
    for round_up in (True, False):
        assert get_amount0_delta(SA, SB, 10**20, round_up) == get_amount0_delta(
            SB, SA, 10**20, round_up
        )
        assert get_amount1_delta(SA, SB, 10**20, round_up) == get_amount1_delta(
            SB, SA, 10**20, round_up
        )


@given(liquidities)
@settings(max_examples=300)
def test_rounding_up_never_understates_and_never_overshoots_by_more_than_a_wei(
    liquidity: int,
) -> None:
    """The pool rounds in its own favour. We must reproduce which way, and by how much."""
    for fn in (get_amount0_delta, get_amount1_delta):
        down = fn(SA, SB, liquidity, False)
        up = fn(SA, SB, liquidity, True)
        assert down <= up <= down + 1


def test_a_zero_sqrt_price_is_refused_rather_than_dividing_by_zero() -> None:
    with pytest.raises(LiquidityMathError):
        get_amount0_delta(0, SB, 10**18, False)
    with pytest.raises(LiquidityMathError):
        get_amount0_for_liquidity(0, SB, 10**18)


# --- composition -----------------------------------------------------------


def test_a_position_below_its_range_is_all_token0() -> None:
    """Price under the range: the position is waiting to buy, holding only the risk asset."""
    amount0, amount1 = get_amounts_for_liquidity(SA - 1, SA, SB, 10**20)
    assert amount0 > 0
    assert amount1 == 0


def test_a_position_above_its_range_is_all_token1() -> None:
    """Price over the range: the position has sold out into the quote asset."""
    amount0, amount1 = get_amounts_for_liquidity(SB + 1, SA, SB, 10**20)
    assert amount0 == 0
    assert amount1 > 0


@given(interior_ticks, liquidities)
@settings(max_examples=300)
def test_a_position_strictly_inside_its_range_holds_both(tick: int, liquidity: int) -> None:
    """Strictly inside, not merely in range: at either boundary the position is
    entirely on one side, which the two tests above cover."""
    amount0, amount1 = get_amounts_for_liquidity(get_sqrt_ratio_at_tick(tick), SA, SB, liquidity)
    assert amount0 > 0
    assert amount1 > 0


def test_dust_liquidity_rounds_away_to_nothing() -> None:
    """Why w_min exists. A position this small holds no measurable tokens, so it
    pays no measurable fees while still costing a full rebalance in gas."""
    amount0, amount1 = get_amounts_for_liquidity(SP, SA, SB, 1)
    assert (amount0, amount1) == (0, 0)


@given(in_range_ticks)
@settings(max_examples=200)
def test_composition_shifts_monotonically_with_price(tick: int) -> None:
    """As price rises through a range the position sells token0 and accumulates
    token1 — continuously, which is the whole isomorphism to an ask ladder."""
    liquidity = 10**22
    lo_amount0, lo_amount1 = get_amounts_for_liquidity(
        get_sqrt_ratio_at_tick(tick), SA, SB, liquidity
    )
    hi_tick = min(tick + 20, UPPER)
    hi_amount0, hi_amount1 = get_amounts_for_liquidity(
        get_sqrt_ratio_at_tick(hi_tick), SA, SB, liquidity
    )
    assert hi_amount0 <= lo_amount0
    assert hi_amount1 >= lo_amount1


# --- inversion -------------------------------------------------------------


@given(in_range_ticks, st.integers(min_value=10**15, max_value=10**28))
@settings(max_examples=300)
def test_liquidity_survives_a_round_trip_through_amounts(tick: int, liquidity: int) -> None:
    """Solve for amounts, then solve back for liquidity.

    The periphery rounds amounts down, so the recovered liquidity can be a hair
    low but must never exceed what we started with — over-reporting liquidity is
    the direction that would overstate a position's fees.

    The size of that shortfall is not a guess. Each amount is truncated by less
    than one wei, and inverting multiplies that wei back up by the reciprocal of
    the range's width in sqrt-price space — so a narrow range amplifies the loss
    and a wide one barely notices it. Asserting a derived bound rather than a
    round number is what makes this test able to catch a real regression.
    """
    sqrt_price = get_sqrt_ratio_at_tick(tick)
    amount0, amount1 = get_amounts_for_liquidity(sqrt_price, SA, SB, liquidity)
    recovered = get_liquidity_for_amounts(sqrt_price, SA, SB, amount0, amount1)

    per_wei_of_token1 = Q96 // max(1, sqrt_price - SA)
    per_wei_of_token0 = (sqrt_price * SB // Q96) // max(1, SB - sqrt_price)
    tolerance = 2 + per_wei_of_token0 + per_wei_of_token1

    assert recovered <= liquidity
    assert liquidity - recovered <= tolerance


def test_liquidity_scales_linearly_with_amounts() -> None:
    base = get_liquidity_for_amounts(SP, SA, SB, 10**18, 10**18)
    doubled = get_liquidity_for_amounts(SP, SA, SB, 2 * 10**18, 2 * 10**18)
    assert doubled == pytest.approx(2 * base, rel=1e-12)


# --- signed deltas ---------------------------------------------------------


@given(liquidities)
@settings(max_examples=200)
def test_signed_deltas_flip_sign_with_liquidity(liquidity: int) -> None:
    """Burning a position is minting a negative one; the rounding flips with it."""
    assert get_signed_amount0_delta(SA, SB, liquidity) > 0
    assert get_signed_amount0_delta(SA, SB, -liquidity) < 0
    assert get_signed_amount1_delta(SA, SB, liquidity) > 0
    assert get_signed_amount1_delta(SA, SB, -liquidity) < 0

    # Removing what you added never returns more than you put in.
    assert abs(get_signed_amount0_delta(SA, SB, -liquidity)) <= get_signed_amount0_delta(
        SA, SB, liquidity
    )


def test_zero_width_range_is_refused_not_silently_zero() -> None:
    with pytest.raises(LiquidityMathError):
        get_liquidity_for_amounts(SA, SA, SA, 10**18, 10**18)


def test_amount1_at_price_one_is_liquidity_times_width() -> None:
    """A hand-checkable anchor: at Q96 scale, amount1 = L * (sqrtB - sqrtA) / 2^96."""
    liquidity = 10**18
    amount1 = get_amount1_for_liquidity(Q96, 2 * Q96, liquidity)
    assert amount1 == liquidity  # (2Q96 - Q96)/Q96 == 1


# --- A1's ceiling, read the other way ---------------------------------------


def test_the_capital_ceiling_is_the_boundary_the_cap_branch_uses() -> None:
    """`capital_for_liquidity_cap` must agree with `liquidity_for_capital`.

    The two describe one boundary from opposite sides — "did this breach?" and
    "at what capital does it start to?" — so a discrepancy would mean the report
    picks a capital the driver then refuses, or worse, one it silently caps.

    Checked by stepping across the boundary: just under it must not breach, and
    a little over it must.
    """
    from misquote.core.liquidity import capital_for_liquidity_cap, liquidity_for_capital
    from misquote.core.tickmath import get_sqrt_ratio_at_tick

    sqrt_price = get_sqrt_ratio_at_tick(-64_000)
    sqrt_a = get_sqrt_ratio_at_tick(-64_400)
    sqrt_b = get_sqrt_ratio_at_tick(-63_600)
    pool_liquidity = 1_252_831_372_941_186_525_611_792
    eps = 0.01

    ceiling = capital_for_liquidity_cap(
        sqrt_price, sqrt_a, sqrt_b, dec1=18, pool_liquidity=pool_liquidity, eps=eps
    )
    assert ceiling > 0

    def capped_at(capital: float) -> bool:
        _, capped = liquidity_for_capital(
            sqrt_price,
            sqrt_a,
            sqrt_b,
            capital_quote=capital,
            dec1=18,
            pool_liquidity=pool_liquidity,
            eps=eps,
        )
        return capped

    assert not capped_at(ceiling * 0.99), "just inside the ceiling must not breach A1"
    assert capped_at(ceiling * 1.01), "just outside it must"


def test_a_shallower_pool_has_a_lower_ceiling_in_proportion() -> None:
    """A1's ceiling is a property of the pool, which is the whole reason task 3
    cannot run both of its venues at one capital chosen for the deeper one."""
    from misquote.core.liquidity import capital_for_liquidity_cap
    from misquote.core.tickmath import get_sqrt_ratio_at_tick

    args = dict(
        sqrt_price_x96=get_sqrt_ratio_at_tick(-64_000),
        sqrt_a=get_sqrt_ratio_at_tick(-64_400),
        sqrt_b=get_sqrt_ratio_at_tick(-63_600),
        dec1=18,
        eps=0.01,
    )
    deep = capital_for_liquidity_cap(pool_liquidity=1_252_831_372_941_186_525_611_792, **args)
    shallow = capital_for_liquidity_cap(pool_liquidity=6_558_013_354_479_073_355_257, **args)

    assert deep > shallow
    assert deep / shallow == pytest.approx(191.0, rel=0.02), "linear in pool liquidity"


def test_an_empty_pool_admits_no_capital_rather_than_dividing_by_zero() -> None:
    from misquote.core.liquidity import capital_for_liquidity_cap
    from misquote.core.tickmath import get_sqrt_ratio_at_tick

    assert (
        capital_for_liquidity_cap(
            get_sqrt_ratio_at_tick(-64_000),
            get_sqrt_ratio_at_tick(-64_400),
            get_sqrt_ratio_at_tick(-63_600),
            dec1=18,
            pool_liquidity=0,
            eps=0.01,
        )
        == 0.0
    )
