"""The quote: what it says, and — more importantly — when it refuses to say it.

These test `quote_from_results` against constructed replay outcomes rather than
by running sixty replays, because the arithmetic and the refusal rules are the
part that can be wrong. A full run across twenty windows and three perturbations
is a batch job measured in minutes; `test_engine.py` already proves the replays
themselves are honest.
"""

from __future__ import annotations

import dataclasses

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


# --- running the windows in parallel must change nothing ---------------------
#
# `quote` can spread its 20 windows x 3 perturbations across processes, because
# the replays are independent: each builds its own driver over its own tape and
# shares no state. On the 30-day chain tape a serial run is 4.6 hours per agent,
# measured, and 86% of that is the sigma estimator recomputing its whole ~841-bar
# window on every event.
#
# Parallelism was chosen over making sigma incremental for one reason: sigma's
# value feeds the policy, and T1/L1 compare decisions **bitwise**. An incremental
# EWMA changes summation order and therefore changes bits. Running the same
# arithmetic on eight cores cannot. This test is what makes that claim checkable
# rather than merely argued — and it demands exact equality, not approximate,
# because approximate is what the argument says is impossible.


# `quote` refuses a window shorter than the 24h policy horizon and refuses a
# quote built on fewer than MIN_SAMPLES replays. Each window covers half the
# history, so a usable tape has to span at least 48 hours and be cut into at
# least ceil(MIN_SAMPLES / 3) windows.
#
# `make_events` runs at a ~25s mean gap, so 48 hours of it is ~7,000 events and
# sixty replays of that is minutes per assertion. Stretching the gaps gets the
# span without the volume: only `ts` moves, so the price path, the amounts and
# every fee are bit-identical to the generator's. It is a quieter pool, not a
# different one.
_STRETCH = 12


def _sparse_tape(count: int = 1000, seed: int = 5):
    from _helpers import make_events

    events = make_events(count, seed=seed)
    first = events[0].ts
    return [dataclasses.replace(e, ts=first + (e.ts - first) * _STRETCH) for e in events]


def _quote_with(jobs: int | None, *, capital: float = 1000.0, events=None):
    from _helpers import META

    from misquote.ops.parallel import fork_map
    from misquote.replay.ranges import quote
    from misquote.replay.tape import MemoryTape

    tape = events if events is not None else _sparse_tape()

    def factory(start, end):
        if start is None:
            return MemoryTape(tape)
        return MemoryTape([e for e in tape if start <= e.ts <= end])

    return quote(
        META,
        factory,
        windows=7,
        capital_quote=capital,
        map_fn=fork_map(jobs) if jobs else None,
    )


@pytest.fixture(scope="module")
def both():
    """Computed once: twenty-one replays each, twice, is not free."""
    return _quote_with(None), _quote_with(4)


def test_parallel_windows_give_bitwise_identical_quotes(both) -> None:
    serial, parallel = both

    assert parallel == serial, "the parallel quote is not the serial quote"
    # Spelled out, because dataclass equality on floats is exact but a reader
    # should not have to know that to trust the line above.
    assert parallel.returns == serial.returns
    assert (parallel.p25, parallel.p50, parallel.p75) == (serial.p25, serial.p50, serial.p75)
    assert parallel.net_positive == serial.net_positive
    assert parallel.samples == serial.samples


def test_the_comparison_above_is_not_between_two_refusals(both) -> None:
    """Two quotes that both declined to quote are equal, and prove nothing.

    This guard has already earned itself once: the first version of the test
    above ran on a 1,200-event tape spanning eight hours, every window fell under
    the 24h horizon, and it compared two empty `Quote`s and passed.
    """
    serial, _ = both

    assert serial.sufficient, serial.note
    assert len(serial.returns) >= MIN_SAMPLES
    assert any(r != 0.0 for r in serial.returns), "every window returned exactly zero"


def test_progress_is_reported_once_per_replay() -> None:
    """A 45-minute run that prints nothing until it exits is the tail's P-10
    failure wearing different clothes."""
    seen: list[tuple[int, int]] = []

    from _helpers import META

    from misquote.replay.ranges import quote
    from misquote.replay.tape import MemoryTape

    tape = _sparse_tape(400)
    quote(
        META,
        lambda start, end: MemoryTape(
            tape if start is None else [e for e in tape if start <= e.ts <= end]
        ),
        windows=4,
        on_progress=lambda done, total: seen.append((done, total)),
    )

    assert seen, "no progress was reported at all"
    assert seen[-1][0] == seen[-1][1], "the last report did not say it had finished"
    assert [d for d, _ in seen] == list(range(1, len(seen) + 1)), "progress skipped or repeated"


def test_capital_reaches_the_division_it_is_the_denominator_of(monkeypatch) -> None:
    """`quote` replayed with the caller's capital and normalised by the default.

    `quote_from_results` turns net token1 into a return by dividing by
    `capital_quote`, whose default is 1000.0. `quote` accepted the parameter and
    passed it to every `ReplayDriver` — and then omitted it from that call, so
    `capital_quote=5000` replayed with 5,000 of capital and divided the result by
    1,000, reporting a return five times too high. The early-return path passed
    it and this one did not; both CLIs default to 1000.0, which is why nothing
    ever showed.

    Asserted on the forwarding rather than on the number, because the number is
    not scale-invariant and cannot be used as the check. Gas is a *fixed* cost
    per rebalance (`CostModel.gas_quote`), so a larger position genuinely earns a
    better return by amortising it — measured here, p50 moves -1.337 -> -1.107
    for a 5x position, and that is the cost model behaving correctly rather than
    a denominator being wrong. A test asserting invariance would have been
    asserting something false.
    """
    from misquote.replay import ranges

    seen: list[float] = []
    real = ranges.quote_from_results

    def spy(results, **kwargs):
        seen.append(kwargs["capital_quote"])
        return real(results, **kwargs)

    monkeypatch.setattr(ranges, "quote_from_results", spy)
    _quote_with(None, capital=7500.0, events=_sparse_tape(300))

    assert seen == [7500.0], f"capital_quote reached the division as {seen}"
