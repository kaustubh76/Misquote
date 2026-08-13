"""Tick math must be exact, not close.

These tests run offline against hand-known constants and structural properties.
The stronger check — every value compared against the real Solidity — lives in
`test_vectors.py` (golden vectors) and `tests/fork/` (live differential).
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from misquote.core.tickmath import (
    MAX_SQRT_RATIO,
    MAX_TICK,
    MIN_SQRT_RATIO,
    MIN_TICK,
    Q96,
    TickMathError,
    floor_to_spacing,
    get_sqrt_ratio_at_tick,
    get_tick_at_sqrt_ratio,
    nearest_usable_tick,
    price_to_tick,
    sqrt_ratio_to_price,
    tick_to_price,
)

ticks = st.integers(min_value=MIN_TICK, max_value=MAX_TICK)


def test_tick_zero_is_exactly_one() -> None:
    """Price 1.0 in Q64.96 is 2^96 on the nose. If this drifts, everything has."""
    assert get_sqrt_ratio_at_tick(0) == Q96 == 79228162514264337593543950336


def test_the_range_endpoints_are_the_published_constants() -> None:
    assert get_sqrt_ratio_at_tick(MIN_TICK) == MIN_SQRT_RATIO
    assert get_sqrt_ratio_at_tick(MAX_TICK) == MAX_SQRT_RATIO


def test_ticks_outside_the_range_are_refused() -> None:
    with pytest.raises(TickMathError):
        get_sqrt_ratio_at_tick(MAX_TICK + 1)
    with pytest.raises(TickMathError):
        get_sqrt_ratio_at_tick(MIN_TICK - 1)


def test_sqrt_ratios_outside_the_range_are_refused() -> None:
    with pytest.raises(TickMathError):
        get_tick_at_sqrt_ratio(MIN_SQRT_RATIO - 1)
    # MAX_SQRT_RATIO is the ratio *above* MAX_TICK, so the bound is exclusive.
    with pytest.raises(TickMathError):
        get_tick_at_sqrt_ratio(MAX_SQRT_RATIO)
    assert get_tick_at_sqrt_ratio(MAX_SQRT_RATIO - 1) == MAX_TICK - 1


@given(st.integers(min_value=MIN_TICK, max_value=MAX_TICK - 1))
@settings(max_examples=800)
def test_round_trip_is_the_identity(tick: int) -> None:
    """A tick is recoverable from its own sqrt ratio, exactly.

    MAX_TICK is excluded on purpose rather than by oversight: its ratio *is*
    MAX_SQRT_RATIO, which is the exclusive upper bound of the inverse function's
    domain. v3 has the same asymmetry, and a position can never sit there.
    """
    assert get_tick_at_sqrt_ratio(get_sqrt_ratio_at_tick(tick)) == tick


def test_max_tick_sits_outside_the_inverse_domain() -> None:
    """The one point where the round trip legitimately does not close."""
    assert get_sqrt_ratio_at_tick(MAX_TICK) == MAX_SQRT_RATIO
    with pytest.raises(TickMathError):
        get_tick_at_sqrt_ratio(get_sqrt_ratio_at_tick(MAX_TICK))


@given(st.integers(min_value=MIN_TICK, max_value=MAX_TICK - 1))
@settings(max_examples=500)
def test_strictly_increasing(tick: int) -> None:
    assert get_sqrt_ratio_at_tick(tick) < get_sqrt_ratio_at_tick(tick + 1)


@given(st.integers(min_value=MIN_SQRT_RATIO, max_value=MAX_SQRT_RATIO - 1))
@settings(max_examples=500)
def test_recovered_tick_brackets_the_ratio(ratio: int) -> None:
    """`get_tick_at_sqrt_ratio` returns the floor: the tick at or below the price."""
    tick = get_tick_at_sqrt_ratio(ratio)
    assert get_sqrt_ratio_at_tick(tick) <= ratio
    if tick < MAX_TICK:
        assert ratio < get_sqrt_ratio_at_tick(tick + 1)


@given(st.integers(min_value=1, max_value=MAX_TICK - 1))
@settings(max_examples=300)
def test_negative_ticks_are_reciprocals_of_positive_ones(tick: int) -> None:
    """1.0001^(-t) * 1.0001^t = 1, to within the rounding of both sides.

    The bound is derived rather than guessed. Both ratios round up by at most one
    ulp, so the product overshoots by at most `up + down + 1` and never
    undershoots. A fixed relative tolerance would be wrong at the extremes, where
    the smaller ratio is a 33-bit number and one ulp is a large fraction of it.
    """
    up = get_sqrt_ratio_at_tick(tick)
    down = get_sqrt_ratio_at_tick(-tick)
    error = up * down - Q96 * Q96
    assert 0 <= error <= up + down + 1


# --- spacing ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("tick", "spacing", "expected"),
    [
        (0, 10, 0),
        (4, 10, 0),
        (5, 10, 0),  # ties round to even, so 0.5 -> 0
        (6, 10, 10),
        (-4, 10, 0),
        (-6, 10, -10),
        (-64183, 10, -64180),
        (17, 50, 0),
        (26, 50, 50),
    ],
)
def test_nearest_usable_tick(tick: int, spacing: int, expected: int) -> None:
    assert nearest_usable_tick(tick, spacing) == expected


@given(ticks, st.sampled_from([1, 10, 50, 200]))
@settings(max_examples=400)
def test_rounded_ticks_are_usable_and_in_range(tick: int, spacing: int) -> None:
    """A tick the pool would reject is worse than no tick at all."""
    got = nearest_usable_tick(tick, spacing)
    assert got % spacing == 0
    assert MIN_TICK <= got <= MAX_TICK
    assert abs(got - tick) <= spacing


@pytest.mark.parametrize(
    ("tick", "spacing", "expected"),
    [(0, 10, 0), (9, 10, 0), (10, 10, 10), (-1, 10, -10), (-64183, 10, -64190)],
)
def test_floor_to_spacing_goes_down_on_both_signs(tick: int, spacing: int, expected: int) -> None:
    """Truncation toward zero would round negative ticks the wrong way."""
    assert floor_to_spacing(tick, spacing) == expected


def test_zero_or_negative_spacing_is_refused() -> None:
    for bad in (0, -10):
        with pytest.raises(TickMathError):
            nearest_usable_tick(0, bad)
        with pytest.raises(TickMathError):
            floor_to_spacing(0, bad)


# --- display conversions ---------------------------------------------------


def test_price_helpers_round_trip_on_equal_decimals() -> None:
    for tick in (-64183, -1000, 0, 1000, 64183):
        price = tick_to_price(tick, 18, 18)
        assert price_to_tick(price, 18, 18) == pytest.approx(tick, abs=1)


def test_sqrt_ratio_and_tick_agree_on_price() -> None:
    tick = -64183
    from_tick = tick_to_price(tick, 18, 18)
    from_ratio = sqrt_ratio_to_price(get_sqrt_ratio_at_tick(tick), 18, 18)
    assert from_ratio == pytest.approx(from_tick, rel=1e-9)


def test_the_live_pool_price_is_the_right_order_of_magnitude() -> None:
    """A sanity anchor on real state, so a decimals mistake cannot pass quietly.

    The target pool is USDT/WBNB with both tokens at 18 decimals, so the price
    is BNB per dollar — a number well below one. Reading it as dollars per BNB
    would put it in the hundreds, which is the shape of a decimals bug.
    """
    observed_sqrt_price = 3200722388915492693232066486  # slot0, block 115,653,558
    price = sqrt_ratio_to_price(observed_sqrt_price, 18, 18)
    assert 0.0005 < price < 0.005
    assert 200 < 1 / price < 2000  # the same number as dollars per BNB
