"""The quote: what it says, and — more importantly — when it refuses to say it.

These test `quote_from_results` against constructed replay outcomes rather than
by running sixty replays, because the arithmetic and the refusal rules are the
part that can be wrong. A full run across twenty windows and three perturbations
is a batch job measured in minutes; `test_engine.py` already proves the replays
themselves are honest.
"""

from __future__ import annotations

import pytest

from misquote.replay.driver import ReplayResult
from misquote.replay.ranges import (
    MIN_HOURS_TO_ANNUALISE,
    MIN_SAMPLES,
    MIN_WINDOW_HOURS,
    percentile,
    quote_from_results,
    rolling_windows,
)

HOUR = 3600


def result(net: float, *, hours: float = 48.0, in_range: float = 0.6, rebalances: int = 3):
    r = ReplayResult()
    r.total_fees = max(0.0, net)
    r.total_lvr = 0.0
    r.total_costs = max(0.0, -net)
    r.samples = 100
    r.in_range_samples = int(100 * in_range)
    r.rebalances = rebalances
    r.first_ts = 0
    r.last_ts = int(hours * HOUR)
    return r


def spread(values, **kwargs):
    return quote_from_results(
        [result(v, **kwargs) for v in values],
        windows=20,
        perturbation_count=3,
        capital_quote=1000.0,
    )


# --- the refusals ----------------------------------------------------------


def test_too_few_replays_is_a_refusal_not_a_wider_range() -> None:
    """Assumption A5's floor. A range computed from four windows describes the
    four windows, and widening it does not repair that."""
    q = spread([10.0] * (MIN_SAMPLES - 1))
    assert not q.sufficient
    assert "A5 requires" in q.note
    assert q.render().startswith("not enough history")


def test_windows_shorter_than_the_policy_horizon_do_not_count() -> None:
    """A window that ends before one decision cycle completes measures startup.

    Twenty of them are twenty measurements of nothing, and the sample count
    alone would happily wave them through.
    """
    q = spread([10.0] * 60, hours=MIN_WINDOW_HOURS / 4)
    assert not q.sufficient
    assert "shorter than the" in q.note


def test_enough_long_windows_does_produce_a_quote() -> None:
    q = spread([10.0] * MIN_SAMPLES, hours=MIN_WINDOW_HOURS + 1)
    assert q.sufficient
    assert q.samples == MIN_SAMPLES


# --- the arithmetic --------------------------------------------------------


def test_the_quote_is_a_return_on_capital_not_an_amount() -> None:
    """Otherwise the headline number scales with position size, which is a
    property of the wallet rather than of the strategy."""
    values = [10.0] * MIN_SAMPLES  # 10 token1 of net profit
    small = quote_from_results(
        [result(v) for v in values], windows=20, perturbation_count=3, capital_quote=1000.0
    )
    large = quote_from_results(
        [result(v) for v in values], windows=20, perturbation_count=3, capital_quote=10_000.0
    )
    assert small.p50 == pytest.approx(10 * large.p50, rel=1e-9)


def test_percentiles_bracket_the_median_and_track_the_data() -> None:
    q = spread([float(i) for i in range(1, 41)], hours=48.0)
    assert q.p25 < q.p50 < q.p75
    assert q.spread > 0


def test_an_agreeing_set_of_replays_quotes_a_narrow_range() -> None:
    """Width is the honest statement about how much the answer depends on when
    you started. When it genuinely does not depend on that, say so."""
    q = spread([10.0] * 40, hours=48.0)
    assert q.spread == pytest.approx(0.0, abs=1e-9)


def test_a_disagreeing_set_quotes_a_wide_one() -> None:
    q = spread([-50.0 if i % 2 else 50.0 for i in range(40)], hours=48.0)
    assert q.spread > 5.0


# --- annualising, and refusing to -----------------------------------------


def test_a_short_window_is_reported_over_its_own_period_not_annualised() -> None:
    """Multiplying an eight-hour result by a thousand does not make it an annual
    one. It makes a fixed rebalance cost look like a catastrophe."""
    q = spread([10.0] * 40, hours=MIN_WINDOW_HOURS + 1)
    assert q.sufficient
    assert not q.annualised
    assert "too short to annualise" in q.basis
    assert "too short to annualise" in q.render()


def test_a_long_window_is_annualised_and_says_so() -> None:
    q = spread([10.0] * 40, hours=MIN_HOURS_TO_ANNUALISE + 1)
    assert q.annualised
    assert q.basis == "annualised"
    assert q.render().endswith("annualised)")


def test_annualising_scales_by_the_window_length() -> None:
    """The scale factor is the only difference, and it should be exactly the
    ratio of a year to the window."""
    hours = MIN_HOURS_TO_ANNUALISE * 2
    q = spread([10.0] * 40, hours=hours)
    period_return = 100.0 * 10.0 / 1000.0
    assert q.p50 == pytest.approx(period_return * (365 * 24 / hours), rel=1e-9)


# --- the building blocks ---------------------------------------------------


def test_percentile_is_reproducible_arithmetic() -> None:
    """Written out rather than imported, because a reader has to be able to
    check it. `we called a library` is a worse answer than four lines."""
    assert percentile([1, 2, 3, 4], 0.25) == pytest.approx(1.75)
    assert percentile([1, 2, 3, 4], 0.5) == pytest.approx(2.5)
    assert percentile([1, 2, 3, 4], 0.75) == pytest.approx(3.25)
    assert percentile([5.0], 0.9) == 5.0
    assert percentile([], 0.5) == 0.0


def test_windows_span_the_history_and_overlap() -> None:
    windows = rolling_windows(0, 100 * HOUR, 20)
    assert len(windows) == 20
    assert windows[0][0] == 0
    assert windows[-1][1] == 100 * HOUR
    assert all(end > start for start, end in windows)
    # Overlapping, so each window is long enough to contain a decision cycle.
    assert windows[1][0] < windows[0][1]


def test_a_degenerate_history_yields_no_windows() -> None:
    assert rolling_windows(100, 100, 20) == []
    assert rolling_windows(0, 1000, 0) == []


def test_no_results_at_all_refuses_rather_than_dividing_by_zero() -> None:
    q = quote_from_results([], windows=20, perturbation_count=3)
    assert not q.sufficient
    assert q.p50 == 0.0
