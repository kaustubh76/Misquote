"""Test T3, and the estimators that carry it.

The first class of tests here matters more than the numerics: it proves that an
estimator physically refuses information from after its decision time. Assumption
A3 says every decision uses trailing data only, and the frozen spec says that
must be enforced "in code, not in review". This is that enforcement, and these
are the tests that prove it fires.
"""

from __future__ import annotations

import math

import pytest

from misquote.core.errors import LookAheadError, OutOfOrderError
from misquote.core.tickmath import Q96, get_sqrt_ratio_at_tick
from misquote.core.types import Event
from misquote.estimators.base import TrailingEstimator
from misquote.estimators.kappa import (
    PROVISIONAL_KAPPA_PER_LOGPRICE,
    PROVISIONAL_KAPPA_PER_TICK,
    TICK_IN_LOGPRICE,
    KappaEstimator,
    fit_kappa,
    least_squares,
)
from misquote.estimators.sigma import (
    SigmaEstimator,
    ewma_variance,
    log_returns,
    shrink,
    winsorise,
)


def swap(block: int, ts: int, tick: int, log_index: int = 0) -> Event:
    return Event(
        block=block,
        log_index=log_index,
        ts=ts,
        kind="swap",
        tx=f"0x{block:064x}",
        amount0=10**18,
        amount1=-(10**18),
        sqrt_price_x96=get_sqrt_ratio_at_tick(tick),
        liquidity=10**24,
        tick=tick,
    )


class Counter(TrailingEstimator):
    """Minimal estimator, so the guard tests exercise the guard and nothing else."""

    __slots__ = ("total",)

    def __init__(self) -> None:
        super().__init__()
        self.total = 0

    def _absorb(self, event: Event) -> None:
        self.total += 1

    def value(self) -> float:
        return float(self.total)


# --- T3: the look-ahead guard ----------------------------------------------


def test_an_event_from_the_future_is_refused() -> None:
    """The single most important assertion in the codebase."""
    est = Counter()
    est.set_decision_time(1000)
    est.ingest(swap(1, 999, -64180))

    with pytest.raises(LookAheadError, match="after the decision time"):
        est.ingest(swap(2, 1001, -64170))

    assert est.total == 1, "the rejected event must not have been absorbed"


def test_an_event_exactly_at_the_decision_time_is_allowed() -> None:
    """The bound is `<=`, matching the spec's 'events <= t'. An off-by-one here
    would quietly discard every event in the deciding block."""
    est = Counter()
    est.set_decision_time(1000)
    est.ingest(swap(1, 1000, -64180))
    assert est.total == 1


def test_time_cannot_run_backwards() -> None:
    est = Counter()
    est.set_decision_time(2000)
    with pytest.raises(LookAheadError, match="moved backwards"):
        est.set_decision_time(1999)


def test_events_out_of_chain_order_are_refused() -> None:
    """Determinism needs a total order; (block, log_index) is it."""
    est = Counter()
    est.set_decision_time(10_000)
    est.ingest(swap(100, 900, -64180, log_index=5))

    with pytest.raises(OutOfOrderError):
        est.ingest(swap(100, 900, -64170, log_index=4))
    with pytest.raises(OutOfOrderError):
        est.ingest(swap(99, 800, -64170, log_index=0))


def test_the_same_event_cannot_be_counted_twice() -> None:
    """A duplicate is `<=` the last key, so the ordering guard catches it too —
    which matters because a re-run backfill can legitimately re-deliver one."""
    est = Counter()
    est.set_decision_time(10_000)
    event = swap(100, 900, -64180)
    est.ingest(event)
    with pytest.raises(OutOfOrderError):
        est.ingest(event)


def test_the_guard_is_not_conditional_on_anything() -> None:
    """No flag, no environment variable, no subclass hook can switch it off.

    If this test ever needs changing, the change is almost certainly wrong.
    """
    for est in (Counter(), SigmaEstimator(), KappaEstimator()):
        est.set_decision_time(500)
        with pytest.raises(LookAheadError):
            est.ingest(swap(1, 501, -64180))


# --- sigma ------------------------------------------------------------------


def test_log_returns_skip_non_positive_prices() -> None:
    """A zero price is a data defect, and log(0) would poison the window."""
    assert log_returns([1.0, 2.0, 4.0]) == pytest.approx([math.log(2), math.log(2)])
    assert log_returns([1.0, 0.0, 4.0]) == []
    assert log_returns([5.0]) == []


def test_ewma_weights_recent_bars_more() -> None:
    quiet_then_wild = ewma_variance([0.0] * 50 + [0.1], 0.9)
    wild_then_quiet = ewma_variance([0.1] + [0.0] * 50, 0.9)
    assert quiet_then_wild > wild_then_quiet


def test_winsorising_clips_a_spike_without_moving_the_body() -> None:
    """One thin-pool print that reverts should not widen the range all day."""
    normal = [0.001, -0.001, 0.0012, -0.0009] * 5
    spiked = [*normal, 0.5]
    clipped = winsorise(spiked)

    assert max(clipped) < 0.5
    assert clipped[: len(normal)] == pytest.approx(normal)


def test_winsorising_uses_the_median_not_the_deviation() -> None:
    """A standard-deviation threshold would be inflated by the very outlier it
    is supposed to clip, so the outlier would survive."""
    returns = [0.001] * 20 + [1.0]
    clipped = winsorise(returns, k=5.0)
    assert clipped[-1] == pytest.approx(0.005)


def test_shrinkage_defers_to_the_prior_on_thin_data() -> None:
    assert shrink(1.0, 0.02, n_obs=0) == 0.02
    thin = shrink(1.0, 0.02, n_obs=2)
    thick = shrink(1.0, 0.02, n_obs=10_000)
    assert 0.02 < thin < thick < 1.0


def test_sigma_is_not_ready_until_it_has_enough_bars() -> None:
    """Not ready still returns a value — the caller must label it rather than
    have a default silently substituted."""
    est = SigmaEstimator()
    est.set_decision_time(10_000)
    assert not est.ready
    assert est.value() == pytest.approx(0.02)


def test_a_volatile_pool_measures_hotter_than_a_calm_one() -> None:
    def run(amplitude: int) -> float:
        est = SigmaEstimator()
        est.set_decision_time(200 * 60)
        for i in range(200):
            tick = -64180 + (amplitude if i % 2 else -amplitude)
            est.ingest(swap(i + 1, i * 60, tick))
        return est.value()

    assert run(50) > run(2)


def test_swaps_inside_one_minute_collapse_into_one_bar() -> None:
    """Otherwise a busy hour would look more volatile than a quiet one at the
    same price range, which measures trading frequency rather than volatility."""
    est = SigmaEstimator()
    est.set_decision_time(3600)
    for i in range(60):
        est.ingest(swap(i + 1, 100, -64180 + i, log_index=i))
    assert est.bars == 0  # all inside the bar in progress
    assert est.events_seen == 60


def test_a_flat_pool_has_almost_no_volatility() -> None:
    est = SigmaEstimator()
    est.set_decision_time(200 * 60)
    for i in range(200):
        est.ingest(swap(i + 1, i * 60, -64180))
    assert est.value() < 0.02  # shrunk toward the prior from below


# --- kappa ------------------------------------------------------------------


def test_least_squares_recovers_a_known_line() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [3.0 - 2.0 * x for x in xs]
    slope, intercept, r2 = least_squares(xs, ys)
    assert slope == pytest.approx(-2.0)
    assert intercept == pytest.approx(3.0)
    assert r2 == pytest.approx(1.0)


def test_a_flat_line_reports_no_fit_rather_than_a_perfect_one() -> None:
    """`1 - ss_res/ss_tot` with a zero denominator would claim r^2 = 1 for data
    that explains nothing. That is how a meaningless kappa gets believed."""
    _, _, r2 = least_squares([1.0, 2.0, 3.0, 4.0], [5.0, 5.0, 5.0, 5.0])
    assert r2 == 0.0


def test_kappa_is_recovered_from_a_synthetic_exponential_decay() -> None:
    """Build swaps whose depth distribution decays at a known rate, then check
    the fit finds it."""
    true_kappa = 0.05
    swaps: list[tuple[int, int]] = []
    for edge in (1, 2, 5, 10, 20, 50, 100, 200):
        count = max(1, int(20_000 * math.exp(-true_kappa * edge)))
        swaps.extend((edge, 0) for _ in range(count))

    fit = fit_kappa(swaps)
    assert not fit.is_fallback
    assert fit.kappa_per_tick == pytest.approx(true_kappa, rel=0.35)
    assert fit.r_squared > 0.9


def test_too_few_swaps_falls_back_and_says_so() -> None:
    fit = fit_kappa([(5, 0)] * 10)
    assert fit.is_fallback
    assert fit.kappa_per_tick == PROVISIONAL_KAPPA_PER_TICK
    assert "default" in fit.label


def test_a_depth_distribution_with_no_decay_falls_back() -> None:
    """Spec section 5.2: r^2 below 0.5 means use the default and label it.

    Every swap here moved exactly 500 ticks, so every bucket up to 500 holds the
    same count and `ln(rate)` is flat. There is no decay to measure, the fitted
    slope is zero, and reporting `kappa = 0` would tell equation (2) that fee
    flow never thins out with distance.
    """
    fit = fit_kappa([(500, 0)] * 400)
    assert fit.is_fallback
    assert fit.kappa_per_tick == PROVISIONAL_KAPPA_PER_TICK
    assert fit.r_squared == 0.0


def test_a_real_fit_is_reported_in_both_units_and_only_the_right_one_is_usable() -> None:
    """This test used to read `assert fit.kappa > 0.0 or fit.is_fallback`.

    Both branches of `fit_kappa` return something positive — a fitted kappa that
    has already passed its own `<= 0` guard, or the positive default — so the
    left disjunct was unconditionally true and the assertion could not fail for
    any input whatsoever. It sat there looking like coverage.

    Worse, the fixture it was given produces a *successfully fitted, non-fallback*
    per-tick kappa near 0.01, which is exactly the value that, fed straight into
    equation (2), yields a 35,000-tick range. A tautology was standing guard over
    the one number that most needed guarding.
    """
    fit = fit_kappa([(d, 0) for d in (1, 2, 5, 10, 20, 50, 100, 200) for _ in range(50)])

    assert not fit.is_fallback
    assert 0.001 < fit.kappa_per_tick < 0.1, "a plausible per-tick decay for this shape"
    assert fit.kappa_per_logprice == pytest.approx(fit.kappa_per_tick / TICK_IN_LOGPRICE)

    # The property that actually matters, rather than a threshold on the number
    # itself: the converted value has to produce a range a pool would accept,
    # and the unconverted one must not.
    from misquote.core.policy import half_width_logprice, half_width_ticks

    good = half_width_ticks(half_width_logprice(0.8, 0.02, 24.0, fit.kappa_per_logprice), 10, 4)
    bad = half_width_ticks(half_width_logprice(0.8, 0.02, 24.0, fit.kappa_per_tick), 10, 4)
    assert 40 <= good <= 2500
    assert bad > 30_000


def test_the_label_distinguishes_a_fitted_kappa_from_a_guessed_one() -> None:
    """A range computed from a guessed parameter is a different claim from one
    computed from data, and the card has to say which."""
    good = fit_kappa(
        [
            (edge, 0)
            for edge in (1, 2, 5, 10, 20, 50)
            for _ in range(max(1, int(9000 * math.exp(-0.06 * edge))))
        ]
    )
    bad = fit_kappa([(5, 0)] * 10)
    assert "fitted" in good.label and "default" not in good.label
    assert "default" in bad.label


def test_the_estimator_evicts_swaps_older_than_its_window() -> None:
    est = KappaEstimator(window_seconds=3600)
    est.set_decision_time(300)
    for i in range(300):
        est.ingest(swap(i + 1, i, -64180 + (i % 7)))
    assert est.ready

    est.set_decision_time(100_000)  # far beyond the one-hour window
    assert not est.ready
    assert est.value() == pytest.approx(PROVISIONAL_KAPPA_PER_LOGPRICE)


def test_refitting_at_the_same_instant_cannot_change_the_answer() -> None:
    """A second call at the same decision time returning a different number
    would make replay non-deterministic in a way that is very hard to see."""
    est = KappaEstimator()
    est.set_decision_time(10_000)
    for i in range(400):
        est.ingest(swap(i + 1, i, -64180 + (i % 23)))
    assert len({est.value() for _ in range(10)}) == 1


def test_kappa_uses_swap_depth_not_absolute_tick() -> None:
    """Depth is movement from the previous tick. A pool sitting still at tick
    -64180 has zero depth however many swaps it prints."""
    est = KappaEstimator()
    est.set_decision_time(10_000)
    for i in range(500):
        est.ingest(swap(i + 1, i, -64180))
    assert not est.ready  # no swap moved the price, so there is nothing to fit
    assert est.value() == pytest.approx(PROVISIONAL_KAPPA_PER_LOGPRICE)


# --- price conversion -------------------------------------------------------


def test_sqrt_ratio_squares_back_to_the_price() -> None:
    from misquote.estimators.sigma import price_from_sqrt_ratio

    assert price_from_sqrt_ratio(Q96) == pytest.approx(1.0)
    assert price_from_sqrt_ratio(2 * Q96) == pytest.approx(4.0)
