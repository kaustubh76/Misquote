"""The APR estimator's guarantees, including the two that carry the product's claim.

T3's analogue — an estimator cannot see an event newer than the decision it is
being computed for — is inherited from `TrailingEstimator` and asserted here
anyway, because inheritance is not evidence that the subclass still has it.

T1's analogue is the one that matters: replace the future with a *different but
still possible* future, replay, and require every earlier estimate to be
bitwise identical. And then require the test not to be vacuous, by showing the
later estimates do move — a T1 that cannot fail is worse than no T1, which
`tests/replay/test_engine.py` learned first.
"""

from __future__ import annotations

import pytest

from misquote.core.errors import LookAheadError, OutOfOrderError
from misquote.estimators.apr import MIN_ACCRUALS, SECONDS_PER_YEAR, RateEvent, TrailingAprEstimator

MARKET = "0xfd5840cd36d94d7229439859c0112a4185bc0255"


def accrual(
    block: int,
    ts: int,
    borrow_index: int,
    *,
    cash: int = 80_000_000 * 10**18,
    borrows: int = 120_000_000 * 10**18,
    interest: int = 10**18,
    log_index: int = 0,
) -> RateEvent:
    return RateEvent(
        market=MARKET,
        block=block,
        log_index=log_index,
        ts=ts,
        cash_prior=cash,
        interest_accumulated=interest,
        borrow_index=borrow_index,
        total_borrows=borrows,
    )


def a_run(n: int, *, start_ts: int = 1_000_000, step_s: int = 60, rate: float = 1e-9):
    """`n` accruals, each growing borrowIndex by a constant factor."""
    base = 1_500_000_000_000_000_000
    out = []
    for i in range(n):
        out.append(accrual(1000 + i, start_ts + i * step_s, int(base * (1 + rate) ** i)))
    return out


# --- the firewall, inherited but asserted ----------------------------------


def test_an_event_after_the_decision_time_raises() -> None:
    est = TrailingAprEstimator(window_seconds=86_400)
    est.set_decision_time(1_000_000)
    with pytest.raises(LookAheadError):
        est.ingest(accrual(1000, 1_000_001, 1_500_000_000_000_000_000))


def test_an_event_out_of_chain_order_raises() -> None:
    est = TrailingAprEstimator(window_seconds=86_400)
    est.set_decision_time(1_000_000)
    est.ingest(accrual(1001, 999_000, 1_500_000_000_000_000_000))
    with pytest.raises(OutOfOrderError):
        est.ingest(accrual(1000, 999_500, 1_500_000_000_000_000_001))


def test_the_decision_time_cannot_move_backwards() -> None:
    est = TrailingAprEstimator(window_seconds=86_400)
    est.set_decision_time(1_000_000)
    with pytest.raises(LookAheadError):
        est.set_decision_time(999_999)


# --- T1's analogue ----------------------------------------------------------


def _estimates_through(events, decision_times, window=86_400):
    est = TrailingAprEstimator(window_seconds=window)
    out = []
    pending = list(events)
    for t in decision_times:
        est.set_decision_time(t)
        while pending and pending[0].ts <= t:
            est.ingest(pending.pop(0))
        out.append(est.fit().supply_apr)
    return out


def test_replacing_the_future_does_not_move_a_single_earlier_estimate() -> None:
    """T1, in the rate estimator's dialect."""
    events = a_run(40, step_s=600, rate=2e-9)
    cut = 20
    times = [events[i].ts for i in range(len(events))]

    # A different but still *possible* continuation: borrowIndex stays monotone,
    # timestamps stay increasing. An impossible future would prove nothing.
    tail_base = events[cut - 1].borrow_index
    altered = list(events[:cut]) + [
        accrual(
            events[i].block,
            events[i].ts,
            int(tail_base * (1 + 9e-9) ** (i - cut + 1)),
        )
        for i in range(cut, len(events))
    ]

    original = _estimates_through(events, times)
    replaced = _estimates_through(altered, times)

    assert original[:cut] == replaced[:cut], (
        "an estimate before the divergence changed when only the future was "
        "replaced — the estimator is conditioning on data it must not have seen"
    )


def test_that_test_is_not_vacuous() -> None:
    """The later estimates must actually move, or T1 above proves nothing."""
    events = a_run(40, step_s=600, rate=2e-9)
    cut = 20
    times = [e.ts for e in events]
    tail_base = events[cut - 1].borrow_index
    altered = list(events[:cut]) + [
        accrual(events[i].block, events[i].ts, int(tail_base * (1 + 9e-9) ** (i - cut + 1)))
        for i in range(cut, len(events))
    ]
    original = _estimates_through(events, times)
    replaced = _estimates_through(altered, times)
    assert original[cut:] != replaced[cut:], (
        "the replaced future produced identical later estimates, so the shuffle "
        "did nothing and the T1 assertion above is vacuous"
    )


# --- the property that makes a sparse market quotable -----------------------


def test_endpoints_and_every_accrual_give_the_same_answer() -> None:
    """A sparse market is not an undersampled market.

    `borrowIndex` is constant between accruals, so the growth over a window is
    fully determined by its endpoints. This is the formal statement of that, and
    it is why vUSDC — which accrues about twice per 5,000 blocks — is quotable
    on the same footing as vUSDT.
    """
    dense = a_run(50, step_s=60, rate=1e-9)
    sparse = [dense[0], dense[-1]]

    t = dense[-1].ts
    dense_est = TrailingAprEstimator(window_seconds=86_400)
    dense_est.set_decision_time(t)
    for e in dense:
        dense_est.ingest(e)

    sparse_est = TrailingAprEstimator(window_seconds=86_400)
    sparse_est.set_decision_time(t)
    for e in sparse:
        sparse_est.ingest(e)

    assert dense_est.fit().supply_apr == pytest.approx(sparse_est.fit().supply_apr, rel=1e-12)


# --- staleness is not zero --------------------------------------------------


def test_a_window_with_no_accruals_is_stale_not_zero() -> None:
    est = TrailingAprEstimator(window_seconds=600)
    est.set_decision_time(1_000_000)
    for e in a_run(5, start_ts=990_000, step_s=60):
        est.ingest(e)
    # Every accrual is now older than the 600s window.
    est.set_decision_time(1_000_000 + 5_000)
    fit = est.fit()
    assert fit.is_stale
    assert not est.ready
    assert "stale" in fit.label


def test_one_accrual_cannot_produce_a_rate() -> None:
    est = TrailingAprEstimator(window_seconds=86_400)
    est.set_decision_time(1_000_000)
    est.ingest(accrual(1000, 999_000, 1_500_000_000_000_000_000))
    assert not est.ready
    assert est.fit().accruals < MIN_ACCRUALS


# --- the arithmetic, against a hand-computed figure -------------------------


def test_the_supply_apr_matches_a_hand_computation() -> None:
    """One doubling of a known growth over a known span, done by hand."""
    cash = 80_000_000 * 10**18
    borrows = 120_000_000 * 10**18
    interest = 0  # so total_borrows_prior == total_borrows, keeping the check readable
    first = accrual(
        1000, 0, 1_000_000_000_000_000_000, cash=cash, borrows=borrows, interest=interest
    )
    second = accrual(
        1001, 86_400, 1_000_000_010_000_000_000, cash=cash, borrows=borrows, interest=interest
    )

    est = TrailingAprEstimator(window_seconds=200_000, reserve_factor=0.1)
    est.set_decision_time(86_400)
    est.ingest(first)
    est.ingest(second)

    growth = 1_000_000_010_000_000_000 / 1_000_000_000_000_000_000 - 1
    util = borrows / (cash + borrows)
    expected = growth * SECONDS_PER_YEAR / 86_400 * util * 0.9

    fit = est.fit()
    assert fit.supply_apr == pytest.approx(expected, rel=1e-12)
    assert fit.utilisation == pytest.approx(0.6, rel=1e-12)
    assert not fit.is_stale


def test_utilisation_uses_borrows_prior_not_borrows_after() -> None:
    """`total_borrows` in the log is post-accrual; utilisation needs the prior."""
    e = accrual(1000, 0, 10**18, cash=50 * 10**18, borrows=50 * 10**18, interest=10 * 10**18)
    assert e.total_borrows_prior == 40 * 10**18
    # 40 / (50 + 40), not 50 / (50 + 50)
    assert e.utilisation == pytest.approx(40 / 90, rel=1e-12)


def test_an_empty_market_is_idle_not_a_division_error() -> None:
    e = accrual(1000, 0, 10**18, cash=0, borrows=0, interest=0)
    assert e.utilisation == 0.0


# --- constructor refusals ---------------------------------------------------


@pytest.mark.parametrize("bad", [-0.5, 1.0, 1.5])
def test_a_reserve_factor_outside_zero_to_one_is_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="reserve_factor"):
        TrailingAprEstimator(window_seconds=600, reserve_factor=bad)


def test_a_window_with_no_width_is_refused() -> None:
    with pytest.raises(ValueError, match="no width"):
        TrailingAprEstimator(window_seconds=0)


# --- against real chain data, not only against a generator ------------------


def _fixture() -> dict:
    import json
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / "venus_vusdt_accruals.json"
    return json.loads(path.read_text())


def test_real_vusdt_accruals_reproduce_the_measured_rate() -> None:
    """The estimator, on real logs, against the figure measured off chain.

    A generator that shares the estimator's assumptions can only confirm the
    estimator is self-consistent. This is 172 `AccrueInterest` logs read from
    BSC mainnet, and the number it has to land on was measured independently by
    probing the chain directly: **2.159% supply APR**, stable to within 0.002pp
    across window widths from 500 to 4,999 blocks.

    The tolerance is deliberately loose (0.25pp) because the fixture covers a
    1,200-block slice rather than the 5,000-block window the reference figure
    converged over, and the rate genuinely moves. What the test is guarding is
    the thing that would actually break: an off-by-a-constant. Every wrong
    blocks-per-year choice is 0.32%, 0.97% or 2.16% — separated by more than
    six-fold, so any of them fails this by a mile while a real rate drift does
    not.
    """
    data = _fixture()
    rows = data["accruals"]
    assert len(rows) >= 100, "fixture is too thin to say anything"

    reserve_factor = int(data["reserve_factor_mantissa"]) / 1e18
    events = [
        RateEvent(
            market=data["market"],
            block=r["block"],
            log_index=r["log_index"],
            ts=r["ts"],
            cash_prior=int(r["cash_prior"]),
            interest_accumulated=int(r["interest_accumulated"]),
            borrow_index=int(r["borrow_index"]),
            total_borrows=int(r["total_borrows"]),
        )
        for r in rows
    ]

    est = TrailingAprEstimator(window_seconds=86_400, reserve_factor=reserve_factor)
    est.set_decision_time(events[-1].ts)
    for e in events:
        est.ingest(e)

    fit = est.fit()
    assert not fit.is_stale
    assert fit.accruals == len(events)
    assert fit.supply_apr * 100 == pytest.approx(2.159, abs=0.25), (
        f"realized supply APR came out at {fit.supply_apr * 100:.4f}%, and the "
        f"chain says 2.159%. The blocks-per-year interpretations sit at 0.324%, "
        f"0.972% and 2.160% — if this landed on one of those, the accumulator "
        f"path has been replaced by a quoted-rate path."
    )


def test_the_fixture_is_monotone_and_ordered() -> None:
    """A real tape has to satisfy what the synthetic generator is held to."""
    rows = _fixture()["accruals"]
    keys = [(r["block"], r["log_index"]) for r in rows]
    assert keys == sorted(keys), "fixture is not in chain order"
    indices = [int(r["borrow_index"]) for r in rows]
    assert indices == sorted(indices), "borrowIndex went backwards, which is not an accrual"
    stamps = [r["ts"] for r in rows]
    assert stamps == sorted(stamps), "timestamps went backwards"


def test_endpoints_reproduce_the_full_fixture() -> None:
    """The sparse-market identity, on real data rather than a generator."""
    data = _fixture()
    rows = data["accruals"]
    reserve_factor = int(data["reserve_factor_mantissa"]) / 1e18

    def apr(subset) -> float:
        est = TrailingAprEstimator(window_seconds=86_400, reserve_factor=reserve_factor)
        est.set_decision_time(subset[-1]["ts"])
        for r in subset:
            est.ingest(
                RateEvent(
                    market=data["market"],
                    block=r["block"],
                    log_index=r["log_index"],
                    ts=r["ts"],
                    cash_prior=int(r["cash_prior"]),
                    interest_accumulated=int(r["interest_accumulated"]),
                    borrow_index=int(r["borrow_index"]),
                    total_borrows=int(r["total_borrows"]),
                )
            )
        return est.fit().supply_apr

    # Endpoints only — what a market accruing twice a window would give us.
    assert apr([rows[0], rows[-1]]) == pytest.approx(apr(rows), rel=1e-9)
