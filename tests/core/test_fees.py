"""Fee-growth accounting, and the wraparound that makes it dangerous.

The first test in this file is the one that justifies the hand port. If it ever
fails, every fee number the product displays is wrong — and wrong in the worst
way, which is plausibly rather than obviously.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from misquote.core.fees import (
    MASK256,
    Q128,
    fee_amount_for_swap,
    fee_growth_inside,
    liquidity_share,
    sub256,
    tokens_owed,
)

uint256 = st.integers(min_value=0, max_value=MASK256)


def test_a_wrapped_accumulator_still_yields_the_right_fee() -> None:
    """v3's fee counters overflow on purpose, and the contracts subtract them
    inside `unchecked`. Python integers do not wrap, so a direct translation
    turns a small positive fee into an enormous negative one — silently.

    Here the global accumulator has passed 2^256 since the position's last
    snapshot: `last` is near the top of the range, `now` has wrapped past zero.
    """
    last = MASK256 - 100
    now = 99  # 200 units of growth later, having wrapped through zero
    liquidity = 10**24

    assert tokens_owed(last, now, liquidity) == (200 * liquidity) >> 128

    naive = ((now - last) * liquidity) >> 128
    assert naive < 0, "the trap this module exists to avoid"


@given(uint256, uint256)
@settings(max_examples=500)
def test_subtraction_always_lands_inside_the_word(a: int, b: int) -> None:
    result = sub256(a, b)
    assert 0 <= result <= MASK256
    assert (result + b) & MASK256 == a


@given(uint256, st.integers(min_value=0, max_value=10**30))
@settings(max_examples=300)
def test_tokens_owed_is_never_negative(last: int, liquidity: int) -> None:
    """Fees earned cannot be negative, whatever the accumulators did."""
    for delta in (0, 1, 10**20, MASK256 // 2):
        now = (last + delta) & MASK256
        assert tokens_owed(last, now, liquidity) >= 0


def test_no_growth_means_no_fees() -> None:
    assert tokens_owed(12345, 12345, 10**24) == 0


def test_fees_scale_with_liquidity() -> None:
    growth = 5 * Q128  # five whole tokens per unit of liquidity
    assert tokens_owed(0, growth, 1) == 5
    assert tokens_owed(0, growth, 1000) == 5000


def test_negative_liquidity_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        tokens_owed(0, Q128, -1)


# --- fee growth inside a range ---------------------------------------------

GLOBAL0, GLOBAL1 = 1000 * Q128, 2000 * Q128
LOWER, UPPER = -64400, -64000


def _inside(tick_current: int, lower_out: int = 0, upper_out: int = 0) -> tuple[int, int]:
    return fee_growth_inside(
        GLOBAL0,
        GLOBAL1,
        lower_out,
        lower_out,
        upper_out,
        upper_out,
        tick_current,
        LOWER,
        UPPER,
    )


def test_a_virgin_range_containing_price_has_earned_everything() -> None:
    """With both boundary ticks never crossed, inside growth is the global total."""
    assert _inside(-64200) == (GLOBAL0, GLOBAL1)


def test_growth_accrued_outside_the_range_is_excluded() -> None:
    """300 units accrued below the lower tick belong to somebody else's position."""
    below = 300 * Q128
    inside0, _ = fee_growth_inside(GLOBAL0, GLOBAL1, below, below, 0, 0, -64200, LOWER, UPPER)
    assert inside0 == GLOBAL0 - below


@pytest.mark.parametrize(
    ("tick_current", "lower_out", "upper_out"),
    [
        (-70000, 100 * Q128, 50 * Q128),  # below the range
        (-64200, 100 * Q128, 50 * Q128),  # inside it
        (-60000, 50 * Q128, 100 * Q128),  # above it
    ],
)
def test_inside_growth_never_exceeds_global(
    tick_current: int, lower_out: int, upper_out: int
) -> None:
    """Whichever side of the range price sits on, a position cannot have earned
    more than the pool did.

    The `feeGrowthOutside` values differ per case because the pool flips them as
    price crosses a tick, and the orderings that are reachable differ with it —
    above the range, inside growth reduces to `upper_out - lower_out`, so an
    `upper_out` below `lower_out` is not a state the pool can be in. Feeding one
    anyway underflows and wraps, exactly as the contract would.
    """
    inside0, inside1 = _inside(tick_current, lower_out=lower_out, upper_out=upper_out)
    assert inside0 <= GLOBAL0
    assert inside1 <= GLOBAL1


def test_an_unreachable_tick_state_wraps_rather_than_inventing_a_negative() -> None:
    """Garbage in, wrapped garbage out — the same garbage the EVM would produce.

    This is not a defect to fix. Clamping here would hide a genuine indexer bug
    behind a plausible number, and the whole point of the accounting layer is
    that implausible inputs stay visibly implausible.
    """
    inside0, _ = fee_growth_inside(
        GLOBAL0, GLOBAL1, 100 * Q128, 100 * Q128, 50 * Q128, 50 * Q128, -60000, LOWER, UPPER
    )
    assert inside0 == sub256(0, 50 * Q128)
    assert inside0 > GLOBAL0  # unmistakably wrong, rather than quietly wrong


def test_price_below_and_above_the_range_use_the_mirrored_expressions() -> None:
    """The stored `feeGrowthOutside` flips meaning as price crosses a tick, so
    the same inputs must give different answers on either side."""
    lower_out, upper_out = 100 * Q128, 50 * Q128
    below = fee_growth_inside(
        GLOBAL0, GLOBAL1, lower_out, lower_out, upper_out, upper_out, -70000, LOWER, UPPER
    )
    inside = fee_growth_inside(
        GLOBAL0, GLOBAL1, lower_out, lower_out, upper_out, upper_out, -64200, LOWER, UPPER
    )
    above = fee_growth_inside(
        GLOBAL0, GLOBAL1, lower_out, lower_out, upper_out, upper_out, -60000, LOWER, UPPER
    )
    assert below != inside != above


@given(uint256, uint256, uint256, st.integers(min_value=-80000, max_value=-50000))
@settings(max_examples=400)
def test_inside_growth_stays_inside_the_word(
    global0: int, lower_out: int, upper_out: int, tick: int
) -> None:
    """Arbitrary accumulator states, including wrapped ones, must not escape uint256."""
    inside0, inside1 = fee_growth_inside(
        global0, global0, lower_out, lower_out, upper_out, upper_out, tick, LOWER, UPPER
    )
    assert 0 <= inside0 <= MASK256
    assert 0 <= inside1 <= MASK256


# --- swap fees and shares --------------------------------------------------


def test_fee_amount_matches_the_tier() -> None:
    """500 pips is 0.05%, charged on the gross input."""
    assert fee_amount_for_swap(10**18, 500) == 5 * 10**14
    assert fee_amount_for_swap(10**18, 100) == 10**14
    assert fee_amount_for_swap(10**18, 0) == 0


def test_absurd_fee_tiers_are_refused() -> None:
    for bad in (-1, 1_000_000, 2_000_000):
        with pytest.raises(ValueError, match="outside"):
            fee_amount_for_swap(10**18, bad)


def test_the_two_share_conventions_differ_and_the_default_is_the_cautious_one() -> None:
    """Matrix item D-1. A Swap event's `liquidity` already contains a real
    position's contribution, so dividing by pool+position double-counts it."""
    position, pool = 10**20, 10**22

    hypothetical = liquidity_share(position, pool, includes_self=False)
    real = liquidity_share(position, pool, includes_self=True)

    assert hypothetical < real, "the spec form understates our share, deliberately"
    assert real == pytest.approx(position / pool)
    assert hypothetical == pytest.approx(position / (pool + position))


def test_an_empty_position_earns_nothing() -> None:
    assert liquidity_share(0, 10**22, includes_self=False) == 0.0
    assert liquidity_share(-1, 10**22, includes_self=True) == 0.0


def test_an_empty_pool_does_not_divide_by_zero() -> None:
    assert liquidity_share(10**20, 0, includes_self=True) == 0.0
