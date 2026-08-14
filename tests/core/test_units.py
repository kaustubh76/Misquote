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


# --- the tick range must stay mintable at the edges -------------------------


@pytest.mark.parametrize("centre_tick", [-887200, -880000, 0, 880000, 887200])
def test_a_range_near_the_edge_of_tick_space_stays_mintable(centre_tick: int) -> None:
    """MIN_TICK and MAX_TICK are not multiples of any Pancake tick spacing.

    `887272 % 10 == 2`, so clamping a bound to them yields a tick the pool
    rejects and the mint reverts. Worse, it breaks symmetry, so R1 would measure
    drift against a centre the policy never chose. The width shrinks instead.
    """
    from misquote.core.policy import target_range
    from misquote.core.tickmath import MAX_TICK, MIN_TICK
    from misquote.core.types import Observation, Params, PoolMeta, PositionState

    meta = PoolMeta(
        address="0x0",
        chain_id=56,
        token0="0x1",
        token1="0x2",
        dec0=18,
        dec1=18,
        fee_pips=500,
        tick_spacing=SPACING,
        fee_protocol=3400,
    )
    position = PositionState(
        lower=None,
        upper=None,
        liquidity=0,
        token_id=None,
        minted_ts=0,
        last_rebalance_ts=0,
        rebalances_today=0,
    )
    obs = Observation(
        t=0,
        tick=centre_tick,
        y=centre_tick * LN_TICK_BASE,
        sqrt_price_x96=get_sqrt_ratio_at_tick(centre_tick),
        pool_liquidity=10**24,
        q=0.0,
        sigma=0.5,  # deliberately violent, to push the width outward
        kappa=20.0,
        kappa_r2=0.9,
        kappa_is_fallback=False,
        T_t=24.0,
        gas_cost_quote=0.0,
        slippage_quote=0.0,
        fee_rate_per_liquidity_target=0.0,
        fee_rate_per_liquidity_current=0.0,
        target_liquidity=0,
        position_value_quote=0.0,
        rebalance_notional_quote=0.0,
        cex_gap=0.0,
        swap_imbalance_z=0.0,
        lvr_rate=0.0,
        fee_rate=0.0,
        toxic_streak=0,
        clear_streak=0,
        position=position,
    )

    lower, upper, centre, width, _, _ = target_range(obs, Params(), meta)

    assert MIN_TICK <= lower < upper <= MAX_TICK
    assert lower % SPACING == 0 and upper % SPACING == 0
    assert upper - centre == centre - lower == width, "symmetry is what R1 measures against"
    assert width >= W_MIN


def test_a_price_pinned_against_the_edge_is_refused_rather_than_quoted() -> None:
    """Not a degenerate rounding case — it is what a broken pool looks like.

    Chapel's WBNB/USDT 0.05% pool was initialized at MAX_TICK and never seeded,
    and sits at tick 887271 with zero liquidity. There is no room for even a
    minimum-width symmetric range, so quoting one would invent a position that
    cannot be minted. `AssumptionViolated` exists for exactly this and had never
    been raised anywhere.
    """
    from misquote.core.errors import AssumptionViolated
    from misquote.core.policy import _distance_to_edge, target_range
    from misquote.core.tickmath import MAX_TICK
    from misquote.core.types import Observation, Params, PoolMeta, PositionState

    assert _distance_to_edge(MAX_TICK - 2, SPACING) < W_MIN

    meta = PoolMeta(
        address="0x0",
        chain_id=97,
        token0="0x1",
        token1="0x2",
        dec0=18,
        dec1=18,
        fee_pips=500,
        tick_spacing=SPACING,
        fee_protocol=3400,
    )
    pinned = MAX_TICK - 2
    obs = Observation(
        t=0,
        tick=pinned,
        y=pinned * LN_TICK_BASE,
        sqrt_price_x96=get_sqrt_ratio_at_tick(pinned),
        pool_liquidity=0,
        q=0.0,
        sigma=0.02,
        kappa=500.0,
        kappa_r2=0.0,
        kappa_is_fallback=True,
        T_t=24.0,
        gas_cost_quote=0.0,
        slippage_quote=0.0,
        fee_rate_per_liquidity_target=0.0,
        fee_rate_per_liquidity_current=0.0,
        target_liquidity=0,
        position_value_quote=0.0,
        rebalance_notional_quote=0.0,
        cex_gap=0.0,
        swap_imbalance_z=0.0,
        lvr_rate=0.0,
        fee_rate=0.0,
        toxic_streak=0,
        clear_streak=0,
        position=PositionState(
            lower=None,
            upper=None,
            liquidity=0,
            token_id=None,
            minted_ts=0,
            last_rebalance_ts=0,
            rebalances_today=0,
        ),
    )

    with pytest.raises(AssumptionViolated, match="no mintable range"):
        target_range(obs, Params(), meta)


# --- sigma's units, and the scale factor nothing was guarding ---------------


def _oscillating_swaps(spacing_s: int, count: int, amplitude_ticks: int = 100):
    """A price alternating by a fixed amount, sampled every `spacing_s` seconds."""
    from misquote.core.types import Event

    for i in range(count):
        tick = -64180 + (amplitude_ticks if i % 2 else -amplitude_ticks)
        yield Event(
            block=i + 1,
            log_index=0,
            ts=i * spacing_s,
            kind="swap",
            tx=f"0x{i:064x}",
            amount0=10**18,
            amount1=-(10**18),
            sqrt_price_x96=get_sqrt_ratio_at_tick(tick),
            liquidity=10**24,
            tick=tick,
        )


def _sigma_at(spacing_s: int, count: int = 400) -> float:
    from misquote.estimators.sigma import SigmaEstimator

    est = SigmaEstimator()
    est.set_decision_time(count * spacing_s)
    for event in _oscillating_swaps(spacing_s, count):
        est.ingest(event)
    return est.value()


def test_the_same_moves_spread_over_more_time_are_less_volatile() -> None:
    """Variance is additive in time, so identical moves arriving an hour apart
    describe a calmer pool than the same moves a minute apart.

    Before this was fixed, all four of these returned *exactly* the same number:
    bars were appended only when a swap arrived, so an hour of silence became a
    single one-minute return and sigma was overstated by up to sqrt(gap).
    """
    per_minute = _sigma_at(60)
    per_five = _sigma_at(300)
    per_hour = _sigma_at(3600)

    assert per_minute > per_five > per_hour
    assert per_five / per_minute == pytest.approx(1 / math.sqrt(5), rel=0.15)
    assert per_hour / per_minute == pytest.approx(1 / math.sqrt(60), rel=0.20)


def test_the_per_sqrt_hour_scale_factor_is_pinned() -> None:
    """Nothing used to guard this.

    `SigmaEstimator.value()` multiplies a per-minute figure by
    `sqrt(3600/60) = sqrt(60)`. Changing that to `sqrt(3600)` — or deleting it —
    left the entire suite green while every range width in the system changed,
    because every other sigma assertion was an ordering or a one-sided bound.

    Here a series with a known per-minute volatility `r` is fed in, so the ratio
    of the output to `r` must be sqrt(60) = 7.75. sqrt(3600) would give 60 and
    no conversion at all would give 1; both are far outside the band.
    """
    from misquote.estimators.sigma import SigmaEstimator

    # The tick alternates +/-100 about a centre, so each *step* moves 200 ticks.
    # Every bar-to-bar log return therefore has magnitude 200 * ln(1.0001), the
    # EWMA variance is that squared, and the per-minute sigma is exactly it.
    amplitude = 100
    r = 2 * amplitude * LN_TICK_BASE
    est = SigmaEstimator(prior_sigma=r * math.sqrt(60))  # neutralise shrinkage
    est.set_decision_time(4000 * 60)
    for event in _oscillating_swaps(60, 4000, amplitude_ticks=amplitude):
        est.ingest(event)

    ratio = est.value() / r
    assert ratio == pytest.approx(math.sqrt(60), rel=0.02)
    assert not (50 < ratio < 70), "sqrt(3600) would land here"
    assert ratio > 5, "no conversion at all would land near 1"


# --- the integration nothing tested ----------------------------------------


def test_an_estimator_chain_end_to_end_produces_a_usable_range() -> None:
    """No test connected an estimator to the policy, which is precisely why a
    10,000x unit error in kappa was invisible to a green suite.

    This drives real swap events through both estimators, builds an Observation
    the way a driver would, and asserts the resulting range is one a pool would
    accept.
    """
    from misquote.core.policy import decide
    from misquote.core.types import Observation, Params, PoolMeta, PositionState
    from misquote.estimators.kappa import KappaEstimator
    from misquote.estimators.sigma import SigmaEstimator

    meta = PoolMeta(
        address=TARGET_POOL.address,
        chain_id=TARGET_POOL.chain_id,
        token0=TARGET_POOL.token0,
        token1=TARGET_POOL.token1,
        dec0=TARGET_POOL.dec0,
        dec1=TARGET_POOL.dec1,
        fee_pips=TARGET_POOL.fee_pips,
        tick_spacing=TARGET_POOL.tick_spacing,
        fee_protocol=TARGET_POOL.fee_protocol,
    )

    sigma_est, kappa_est = SigmaEstimator(), KappaEstimator()
    horizon = 3000 * 60
    sigma_est.set_decision_time(horizon)
    kappa_est.set_decision_time(horizon)

    # Enough swaps, moving enough, for both estimators to be ready.
    for event in _oscillating_swaps(60, 3000, amplitude_ticks=40):
        sigma_est.ingest(event)
        kappa_est.ingest(event)

    assert sigma_est.ready and kappa_est.ready

    position = PositionState(
        lower=-64400,
        upper=-64000,
        liquidity=10**22,
        token_id=1,
        minted_ts=0,
        last_rebalance_ts=0,
        rebalances_today=0,
    )
    obs = Observation(
        t=horizon,
        tick=-64183,
        y=-64183 * LN_TICK_BASE,
        sqrt_price_x96=get_sqrt_ratio_at_tick(-64183),
        pool_liquidity=10**24,
        q=0.0,
        sigma=sigma_est.value(),
        kappa=kappa_est.value(),  # must already be per log-price
        kappa_r2=kappa_est.fit().r_squared,
        kappa_is_fallback=kappa_est.fit().is_fallback,
        T_t=24.0,
        gas_cost_quote=0.5,
        slippage_quote=0.2,
        fee_rate_per_liquidity_target=1e-20,
        fee_rate_per_liquidity_current=0.0,
        target_liquidity=10**22,
        position_value_quote=200.0,
        rebalance_notional_quote=40.0,
        cex_gap=0.0,
        swap_imbalance_z=0.0,
        lvr_rate=0.0,
        fee_rate=1.0,
        toxic_streak=0,
        clear_streak=99,
        position=position,
    )

    decision = decide(obs, Params(), meta)
    assert PLAUSIBLE_MIN_TICKS <= decision.half_width_ticks <= PLAUSIBLE_MAX_TICKS, (
        f"estimator chain produced a {decision.half_width_ticks}-tick half-width"
    )
    assert decision.half_width_ticks % SPACING == 0


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


# --- the daily cap has to actually be daily --------------------------------


def test_the_rebalance_budget_refreshes_when_the_day_rolls_over() -> None:
    """Spec section 8 caps rebalances *per day*, which is a rate limit.

    The stored counter only ever increased, so the cap behaved as a limit for
    the lifetime of the position: after eight moves the agent froze and could
    never recentre again however far price drifted. A 62-hour replay is what
    surfaced it — exactly eight moves, then 14.6% in range for the remainder.

    Over a few hours the bug is invisible, which is why every test missed it
    until a run was long enough to cross midnight.
    """
    from misquote.core.position import SECONDS_PER_DAY, rebalances_today
    from misquote.core.types import PositionState

    day_one = 1_700_000_000
    spent = PositionState(
        lower=-64400,
        upper=-64000,
        liquidity=10**22,
        token_id=1,
        minted_ts=day_one,
        last_rebalance_ts=day_one,
        rebalances_today=8,
    )

    assert rebalances_today(spent, day_one + 60) == 8, "same day: the budget is spent"
    assert rebalances_today(spent, day_one + SECONDS_PER_DAY) == 0, "next day: refreshed"


def test_the_budget_survives_a_pull_so_it_cannot_be_reset_by_churning() -> None:
    """Otherwise an agent could clear its own daily limit by pulling and
    re-minting, which is the opposite of what a churn cap is for."""
    from misquote.core.position import apply_decision, rebalances_today
    from misquote.core.types import Action, PositionState

    day_one = 1_700_000_000
    spent = PositionState(
        lower=-64400,
        upper=-64000,
        liquidity=10**22,
        token_id=1,
        minted_ts=day_one,
        last_rebalance_ts=day_one,
        rebalances_today=8,
    )
    pulled = apply_decision(spent, Action.PULL, day_one + 120)
    assert rebalances_today(pulled, day_one + 180) == 8


def test_a_move_after_midnight_starts_counting_from_one() -> None:
    from misquote.core.position import SECONDS_PER_DAY, apply_decision
    from misquote.core.types import Action, PositionState

    day_one = 1_700_000_000
    spent = PositionState(
        lower=-64400,
        upper=-64000,
        liquidity=10**22,
        token_id=1,
        minted_ts=day_one,
        last_rebalance_ts=day_one,
        rebalances_today=8,
    )
    moved = apply_decision(
        spent,
        Action.RECENTER,
        day_one + SECONDS_PER_DAY,
        lower=-64300,
        upper=-63900,
        liquidity=10**22,
    )
    assert moved.rebalances_today == 1
