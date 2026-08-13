"""Dimensional contracts: the tests that would have caught V-1.

Every other policy test checks a *relationship* — wider with volatility, tighter
with kappa — or an exact equation value. All of them pass while `decide()`
returns a half-width of 35,450 ticks, a price band of plus or minus 3,363%, on a
pool whose whole usable range is a few hundred ticks wide. Relationships hold
perfectly well when every value is off by four orders of magnitude.

So this file asserts magnitudes and units instead. It is the difference between
"the formula is implemented" and "the formula is fed the right thing".
"""

from __future__ import annotations

import math

import pytest

from misquote.chain.addresses import TARGET_POOL
from misquote.core.liquidity import get_amounts_for_liquidity
from misquote.core.policy import (
    LN_TICK_BASE,
    half_width_logprice,
    half_width_ticks,
    inventory_imbalance,
)
from misquote.core.tickmath import Q96, get_sqrt_ratio_at_tick
from misquote.estimators.kappa import TICK_IN_LOGPRICE, KappaFit, fit_kappa

GAMMA = 0.8
WINDOW_HOURS = 24.0
SPACING = TARGET_POOL.tick_spacing
W_MIN = TARGET_POOL.w_min_ticks

# Volatility of BNB/USDT in log-price per sqrt-hour. A 3% daily move is about
# 0.006; a violent day is nearer 0.05. Anything the policy does at these inputs
# has to produce a range a v3 pool would actually accept.
REALISTIC_SIGMA = (0.006, 0.02, 0.05)

# A half-width outside this band is not a trading decision, it is a unit error.
# The floor is the spec's own anti-dust bound; the ceiling is roughly a plus or
# minus 25% price band, far wider than any sane 0.05% position and still four
# orders of magnitude below what a per-tick kappa produces.
PLAUSIBLE_MIN_TICKS = W_MIN
PLAUSIBLE_MAX_TICKS = 2500


# --- V-1: kappa's units ----------------------------------------------------


def test_one_tick_is_the_documented_amount_of_log_price() -> None:
    """The conversion factor the whole finding turns on."""
    assert TICK_IN_LOGPRICE == pytest.approx(math.log(1.0001))
    assert TICK_IN_LOGPRICE == pytest.approx(1.0e-4, rel=1e-3)
    assert 1.0 / TICK_IN_LOGPRICE == pytest.approx(10_000, rel=1e-3)


def test_a_fit_reports_both_unit_conventions_and_they_agree() -> None:
    """Equation (2) needs kappa per log-price; spec 5.2 fits it per tick.

    Carrying both, with one named conversion between them, is what stops the
    two ever being confused again.
    """
    fit = KappaFit(
        kappa_per_tick=0.05,
        ln_a=0.0,
        r_squared=0.9,
        buckets_used=6,
        swaps_used=5000,
        is_fallback=False,
    )
    assert fit.kappa_per_logprice == pytest.approx(0.05 / TICK_IN_LOGPRICE)
    assert fit.kappa_per_logprice == pytest.approx(500.0, rel=1e-3)
    assert fit.kappa_per_logprice / fit.kappa_per_tick == pytest.approx(1 / TICK_IN_LOGPRICE)


def test_feeding_equation_2_a_per_tick_kappa_is_absurd_by_four_orders_of_magnitude() -> None:
    """The bug this file exists for, pinned so it cannot come back quietly.

    A per-tick kappa of 0.05 makes `gamma/kappa` sixteen instead of 0.0016, so
    the fill term stops being a small correction and becomes the whole answer.
    """
    wrong = half_width_ticks(half_width_logprice(GAMMA, 0.02, WINDOW_HOURS, 0.05), SPACING, 4)
    right = half_width_ticks(
        half_width_logprice(GAMMA, 0.02, WINDOW_HOURS, 0.05 / TICK_IN_LOGPRICE), SPACING, 4
    )
    assert wrong > 30_000, "expected the documented absurd value"
    assert right < PLAUSIBLE_MAX_TICKS
    assert wrong / right > 500


@pytest.mark.parametrize("sigma", REALISTIC_SIGMA)
@pytest.mark.parametrize("kappa_per_tick", [0.01, 0.05, 0.2, 1.0])
def test_a_fitted_kappa_always_produces_a_range_a_v3_pool_would_accept(
    sigma: float, kappa_per_tick: float
) -> None:
    """The plausibility band. This is the assertion the audit was missing.

    Across every realistic volatility and every plausible fitted decay, the
    half-width must land somewhere a 0.05% position could actually sit.
    """
    kappa = kappa_per_tick / TICK_IN_LOGPRICE
    width = half_width_ticks(half_width_logprice(GAMMA, sigma, WINDOW_HOURS, kappa), SPACING, 4)

    assert PLAUSIBLE_MIN_TICKS <= width <= PLAUSIBLE_MAX_TICKS, (
        f"half-width {width} ticks (+/-{100 * (1.0001**width - 1):.1f}%) is a unit error, "
        f"not a trading decision"
    )
    assert width % SPACING == 0


def test_the_estimator_hands_the_policy_the_unit_equation_2_expects() -> None:
    """End to end: what `fit_kappa` returns must be usable directly.

    A conversion that exists but is not applied on the real path is not a fix.
    """
    swaps = [
        (edge, 0)
        for edge in (1, 2, 5, 10, 20, 50, 100)
        for _ in range(max(1, int(30_000 * math.exp(-0.05 * edge))))
    ]
    fit = fit_kappa(swaps)
    assert not fit.is_fallback

    width = half_width_ticks(
        half_width_logprice(GAMMA, 0.02, WINDOW_HOURS, fit.kappa_per_logprice), SPACING, 4
    )
    assert PLAUSIBLE_MIN_TICKS <= width <= PLAUSIBLE_MAX_TICKS


# --- V-3: round, not floor -------------------------------------------------


def test_the_half_width_rounds_to_spacing_rather_than_flooring() -> None:
    """Spec 3.2 says round_to_spacing. Flooring makes the range up to 20%
    narrower than specified, and narrower means more time out of range."""
    # 58 raw ticks: rounding gives 60, flooring gives 50.
    delta_star = 58.0 * LN_TICK_BASE
    assert half_width_ticks(delta_star, 10, 4) == 60

    # 237 raw ticks at spacing 50: rounding gives 250, flooring gives 200.
    assert half_width_ticks(237.0 * LN_TICK_BASE, 50, 4) == 250


@pytest.mark.parametrize("raw", [41, 45, 46, 55, 58, 64, 75, 101, 237])
def test_rounding_never_lands_further_than_half_a_spacing_from_the_target(raw: int) -> None:
    """The defining property of rounding, which flooring does not have."""
    width = half_width_ticks(raw * LN_TICK_BASE, SPACING, 4)
    if width > W_MIN:
        assert abs(width - raw) <= SPACING / 2


def test_the_anti_dust_floor_still_wins_over_rounding() -> None:
    """w_min is a floor, not a suggestion: rounding must not go under it."""
    assert half_width_ticks(1e-9, SPACING, 4) == W_MIN
    assert half_width_ticks(12.0 * LN_TICK_BASE, SPACING, 4) == W_MIN


# --- V-4: the inventory imbalance ------------------------------------------


def test_q_reaches_both_ends_of_its_stated_range() -> None:
    """Spec section 2 states q is in [-1, 1] but writes a formula yielding
    [-0.5, 0.5]. The stated range is the testable claim, so it wins."""
    assert inventory_imbalance(100.0, 0.0) == pytest.approx(1.0)
    assert inventory_imbalance(0.0, 100.0) == pytest.approx(-1.0)
    assert inventory_imbalance(50.0, 50.0) == pytest.approx(0.0)


def test_q_is_positive_when_the_position_holds_excess_token0() -> None:
    """The sign drives equation (1): q > 0 must push the range down, making the
    position a keener seller of what it has too much of."""
    assert inventory_imbalance(80.0, 20.0) > 0
    assert inventory_imbalance(20.0, 80.0) < 0


def test_an_empty_position_is_balanced_rather_than_undefined() -> None:
    assert inventory_imbalance(0.0, 0.0) == 0.0


def test_q_spans_the_full_range_across_a_real_position() -> None:
    """Walk a real v3 position from below its range to above it and confirm q
    sweeps -1 to +1 monotonically."""
    lower, upper, liquidity = -64400, -64000, 10**22
    sa, sb = get_sqrt_ratio_at_tick(lower), get_sqrt_ratio_at_tick(upper)

    seen = []
    for tick in range(lower - 200, upper + 201, 40):
        sp = get_sqrt_ratio_at_tick(tick)
        amount0, amount1 = get_amounts_for_liquidity(sp, sa, sb, liquidity)
        price = (min(max(sp, sa), sb) / Q96) ** 2
        seen.append(inventory_imbalance((amount0 / 1e18) * price, amount1 / 1e18))

    assert seen[0] == pytest.approx(1.0)  # below the range: all token0
    assert seen[-1] == pytest.approx(-1.0)  # above it: all token1
    assert all(-1.0 <= q <= 1.0 for q in seen)
    # As price rises the position sells token0, so q only ever decreases.
    assert all(later <= earlier + 1e-12 for earlier, later in zip(seen, seen[1:], strict=False))
