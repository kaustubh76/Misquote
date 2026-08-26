"""The swap-imbalance z-score — spec section 3.4's second arm.

These assert **magnitudes**, not relationships. A test that only checked "more
one-way flow gives a bigger z" would pass just as happily on a statistic that was
off by a factor of ten thousand, which is exactly how the kappa units defect
survived a green suite for seven steps.
"""

from __future__ import annotations

import math
import random

import pytest

from misquote.core.errors import LookAheadError
from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import Event, Params
from misquote.estimators.imbalance import (
    DEFAULT_WINDOW_SWAPS,
    ImbalanceEstimator,
    imbalance_z,
)

ONE = 10**18


def swap(amount1: int, *, i: int, ts: int) -> Event:
    """One swap carrying `amount1` of signed quote volume."""
    return Event(
        block=1_000_000 + i,
        log_index=0,
        ts=ts,
        kind="swap",
        tx=f"0x{i:064x}",
        amount0=-amount1,
        amount1=amount1,
        sqrt_price_x96=get_sqrt_ratio_at_tick(-64180),
        liquidity=10**24,
        tick=-64180,
    )


# --- the arithmetic ---------------------------------------------------------


def test_all_one_way_hits_the_theoretical_ceiling_of_sqrt_m() -> None:
    """50 identical same-direction swaps give exactly sqrt(50) = 7.0710678...

    The extreme of the statistic, and the number `z_pull` has to sit below to be
    reachable at all. Checked to 12 decimal places rather than "greater than
    some threshold", because the ceiling is the thing that makes the parameter
    meaningful.
    """
    assert imbalance_z([1.0] * 50) == pytest.approx(math.sqrt(50), abs=1e-12)
    assert imbalance_z([-1.0] * 50) == pytest.approx(-math.sqrt(50), abs=1e-12)
    # Scale-free: the same pattern at a million times the size is the same z.
    assert imbalance_z([1e6] * 50) == pytest.approx(math.sqrt(50), abs=1e-9)


def test_perfectly_balanced_flow_is_zero() -> None:
    assert imbalance_z([1.0, -1.0] * 25) == pytest.approx(0.0, abs=1e-12)


def test_one_whale_is_not_toxic_flow() -> None:
    """A single dominant trade must not read as an emergency.

    Numerator and denominator both go with the whale, so z tends to 1 — far
    under any sane `z_pull`. This is the property that makes the statistic worth
    having rather than "sum of signed volume".
    """
    volumes = [1e9] + [1.0] * 49
    z = imbalance_z(volumes)
    assert z == pytest.approx(1.0, abs=1e-6)
    assert z < Params().z_pull, "one large trade must not trip the pull"


def test_thirty_four_of_fifty_is_the_edge_of_the_default_threshold() -> None:
    """Where `z_pull = 2.5` actually bites, stated as a trade count.

    34 one way and 16 the other gives (34-16)/sqrt(50) = 2.5456, just over. 33/17
    gives 2.2627, just under. An operator setting this parameter deserves to know
    it means "about two thirds of the last fifty swaps went one way".
    """
    assert imbalance_z([1.0] * 34 + [-1.0] * 16) == pytest.approx(18 / math.sqrt(50), abs=1e-12)
    assert imbalance_z([1.0] * 34 + [-1.0] * 16) > 2.5
    assert imbalance_z([1.0] * 33 + [-1.0] * 17) < 2.5


def test_the_statistic_is_bounded_by_sqrt_of_the_window() -> None:
    """|z| <= sqrt(M) for any input at all — Cauchy-Schwarz, checked."""
    rng = random.Random(11)
    for _ in range(200):
        n = rng.randint(2, 80)
        volumes = [rng.uniform(-1e6, 1e6) for _ in range(n)]
        assert abs(imbalance_z(volumes)) <= math.sqrt(n) + 1e-9


def test_zero_volume_returns_zero_rather_than_a_nan() -> None:
    """NaN here would make every downstream Decision unequal to itself.

    The same defect that made test T1 unpassable on the CEX-feed-down path.
    `Decision` is hashable so T1 can compare sequences bitwise, and a NaN
    anywhere in `reasons` destroys that.
    """
    z = imbalance_z([0.0] * 50)
    assert z == 0.0
    assert z == z, "NaN — this breaks T1's bitwise comparison"


def test_empty_input_is_zero() -> None:
    assert imbalance_z([]) == 0.0


# --- the estimator ----------------------------------------------------------


def test_no_verdict_until_the_window_is_full() -> None:
    """A z-score from four swaps is a number, not evidence."""
    est = ImbalanceEstimator(dec1=18, window_swaps=DEFAULT_WINDOW_SWAPS)
    est.set_decision_time(2_000_000)
    for i in range(DEFAULT_WINDOW_SWAPS - 1):
        est.ingest(swap(ONE, i=i, ts=1_700_000 + i))
        assert not est.ready
        assert est.value() == 0.0, "a partial window must not publish a verdict"

    est.ingest(swap(ONE, i=99, ts=1_800_000))
    assert est.ready
    assert est.value() == pytest.approx(math.sqrt(DEFAULT_WINDOW_SWAPS), abs=1e-12)


def test_sign_follows_which_token_the_pool_received() -> None:
    """Positive z means the pool is being bought, because `amount1 > 0` means it
    took token1 in. The direction is the event's own convention, not something
    reconstructed — there is nothing here to get backwards."""
    buys = ImbalanceEstimator(dec1=18, window_swaps=10)
    sells = ImbalanceEstimator(dec1=18, window_swaps=10)
    buys.set_decision_time(2_000_000)
    sells.set_decision_time(2_000_000)
    for i in range(10):
        buys.ingest(swap(ONE, i=i, ts=1_700_000 + i))
        sells.ingest(swap(-ONE, i=i, ts=1_700_000 + i))

    assert buys.value() == pytest.approx(math.sqrt(10), abs=1e-12)
    assert sells.value() == pytest.approx(-math.sqrt(10), abs=1e-12)


def test_the_window_rolls_so_old_flow_stops_counting() -> None:
    """Fifty sells followed by fifty buys must read as buying, not as balanced."""
    est = ImbalanceEstimator(dec1=18, window_swaps=50)
    est.set_decision_time(2_000_000)
    for i in range(50):
        est.ingest(swap(-ONE, i=i, ts=1_700_000 + i))
    assert est.value() == pytest.approx(-math.sqrt(50), abs=1e-12)

    for i in range(50, 100):
        est.ingest(swap(ONE, i=i, ts=1_700_000 + i))
    assert est.value() == pytest.approx(math.sqrt(50), abs=1e-12)


def test_decimals_scale_out_entirely() -> None:
    """The statistic is a ratio, so the decimal convention cannot change it.

    Worth pinning: the kappa defect was a units error that produced a
    plausible-looking number, and this estimator also takes a `dec1`.
    """
    a = ImbalanceEstimator(dec1=18, window_swaps=10)
    b = ImbalanceEstimator(dec1=6, window_swaps=10)
    a.set_decision_time(2_000_000)
    b.set_decision_time(2_000_000)
    for i in range(10):
        e = swap(ONE if i % 3 else -ONE, i=i, ts=1_700_000 + i)
        a.ingest(e)
        b.ingest(e)
    assert a.value() == pytest.approx(b.value(), rel=1e-12)


def test_non_swap_events_are_ignored() -> None:
    """A mint is not flow. Counting one would let liquidity churn read as
    directional trading — and on a busy pool, mints and burns outnumber swaps."""
    import dataclasses

    swaps = ImbalanceEstimator(dec1=18, window_swaps=4)
    mints = ImbalanceEstimator(dec1=18, window_swaps=4)
    swaps.set_decision_time(2_000_000)
    mints.set_decision_time(2_000_000)

    for i in range(4):
        event = swap(ONE, i=i, ts=1_700_000 + i)
        swaps.ingest(event)
        mints.ingest(dataclasses.replace(event, kind="mint"))

    assert swaps.ready
    assert not mints.ready, "mints must not fill the window"
    assert mints.value() == 0.0


def test_it_inherits_the_look_ahead_guard() -> None:
    """T3 applies here too, unconditionally, like every trailing estimator."""
    est = ImbalanceEstimator(dec1=18)
    est.set_decision_time(1_700_000)
    with pytest.raises(LookAheadError):
        est.ingest(swap(ONE, i=0, ts=1_700_060))


def test_a_window_shorter_than_two_is_refused() -> None:
    with pytest.raises(ValueError, match="not a z-score"):
        ImbalanceEstimator(dec1=18, window_swaps=1)


# --- A16: the threshold is calibrated to the statistic's own distribution ---


def _feed(est, volumes, *, start_ts=1_000_000, step=5):
    """One swap per sample, advancing the clock the way `Engine.step` does.

    Order matters and is the whole no-look-ahead argument: `set_decision_time`
    first — which is where a reading is recorded — then the events belonging to
    that sample. So the history can only ever hold values that were already
    public when they were recorded.
    """
    from misquote.core.types import Event

    ts = start_ts
    for i, v in enumerate(volumes):
        ts += step
        est.set_decision_time(ts)
        est.ingest(
            Event(
                block=1_000_000 + i,
                log_index=0,
                ts=ts,
                kind="swap",
                tx=f"0x{i:064x}",
                amount0=-int(v * 10**18),
                amount1=int(v * 10**18),
                sqrt_price_x96=1 << 96,
                liquidity=10**24,
                tick=0,
                protocol_fee0=0,
                protocol_fee1=0,
            )
        )


def test_the_threshold_falls_back_until_it_has_a_distribution_to_read() -> None:
    """A quantile of forty numbers is the largest of forty numbers.

    Below the floor the estimator says so rather than returning a threshold the
    caller cannot tell apart from a calibrated one.
    """
    from misquote.estimators.imbalance import MIN_CALIBRATION_SAMPLES, ImbalanceEstimator

    est = ImbalanceEstimator(dec1=18)
    _feed(est, [1.0, -1.0] * 200)

    assert not est.threshold_ready
    assert est.threshold(0.95) == 0.0, "an unready quantile must be unmistakable"
    assert MIN_CALIBRATION_SAMPLES > 200


def test_the_threshold_is_the_quantile_of_what_the_pool_actually_produced() -> None:
    """The point of A16: the bar comes from the measured distribution.

    Balanced two-way flow keeps |z| small, so the 95th percentile of it lands far
    below the spec's constant 2.5 — and on the real pool it lands far *above*,
    which is the same mechanism reading a different tape. Either way the number
    is one the pool produced rather than one transplanted from a distribution
    this statistic does not have.
    """
    import random

    from misquote.estimators.imbalance import MIN_CALIBRATION_SAMPLES, ImbalanceEstimator

    est = ImbalanceEstimator(dec1=18, calibration_samples=4_000, calibration_stride=100)
    rng = random.Random(11)
    _feed(est, [rng.choice((1.0, -1.0)) for _ in range(MIN_CALIBRATION_SAMPLES + 500)])

    assert est.threshold_ready
    bar = est.threshold(0.95)

    assert 0.0 < bar <= est.ceiling
    # Every reading in the history is bounded by sqrt(M), so the quantile is too.
    assert est.ceiling == pytest.approx(50**0.5)
    # And a higher quantile is a higher bar — the property that makes it a knob.
    assert est.threshold(0.99) >= bar


def test_the_quantile_is_deterministic_across_identical_streams() -> None:
    """T1 compares decisions bitwise and this number reaches them, so two runs
    over the same prefix must calibrate identically — including *when* they
    recalibrate, which is why the cache is keyed on the reading count and not on
    a clock."""
    import random

    from misquote.estimators.imbalance import MIN_CALIBRATION_SAMPLES, ImbalanceEstimator

    def run() -> float:
        est = ImbalanceEstimator(dec1=18, calibration_samples=4_000, calibration_stride=100)
        rng = random.Random(7)
        _feed(est, [rng.choice((1.0, -1.0, 2.0)) for _ in range(MIN_CALIBRATION_SAMPLES + 300)])
        return est.threshold(0.95)

    assert run() == run()
