"""Fee APR for a v3 position, and the two things it must refuse to do.

The interesting assertions here are negative. A fee APR is easy to compute and
easy to publish wrongly: gross of the protocol's cut, without its adverse
selection, or without saying which width it is about. Each of those produces a
larger, friendlier number, which is why each gets a test.
"""

from __future__ import annotations

import pytest

from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import Event, PoolMeta
from misquote.estimators.pool_apr import MIN_SWAPS, PoolAprEstimator

META = PoolMeta(
    address="0x36696169C63e42cd08ce11f5deeBbCeBae652050",
    chain_id=56,
    token0="0x55d398326f99059fF775485246999027B3197955",
    token1="0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    dec0=18,
    dec1=18,
    fee_pips=500,
    tick_spacing=10,
    fee_protocol=3400,  # LPs keep 66% on this pool
)
START = 1_700_000_000


def swaps(count: int, *, size: int = 10**21, tick: int = 0, step: int = 60):
    """A possible history: amounts agree with the tick, and the protocol takes its cut."""
    out = []
    ts = START
    for i in range(count):
        ts += step
        sqrt_price = get_sqrt_ratio_at_tick(tick)
        price = (sqrt_price / (1 << 96)) ** 2
        quote = int(size * price)
        fee = quote * META.fee_pips // 10**6
        cut = fee * META.fee_protocol // 10_000
        up = i % 2 == 0
        out.append(
            Event(
                block=1_000_000 + i,
                log_index=0,
                ts=ts,
                kind="swap",
                tx=f"0x{i:064x}",
                amount0=-size if up else size,
                amount1=quote if up else -quote,
                sqrt_price_x96=sqrt_price,
                liquidity=10**24,
                tick=tick,
                protocol_fee0=0 if up else cut,
                protocol_fee1=cut if up else 0,
            )
        )
    return out


def feed(est, events):
    for e in events:
        est.set_decision_time(e.ts)
        est.ingest(e)


# --- the refusals ----------------------------------------------------------


def test_a_fee_apr_without_a_width_is_refused_at_construction() -> None:
    """A v3 pool has no width-free yield.

    Two LPs in the same pool at the same moment earn different returns because
    they chose different widths, so "the APR of this pool" is not a well-formed
    quantity. A surface that prints one is quoting something that does not exist,
    and the cheapest place to make that impossible is the constructor.
    """
    for bad in (0, -1, -200):
        with pytest.raises(ValueError, match="needs a width"):
            PoolAprEstimator(META, reference_width_ticks=bad, capital_quote=1.0)


def test_capital_of_zero_is_refused_because_it_is_the_denominator() -> None:
    with pytest.raises(ValueError, match="denominator"):
        PoolAprEstimator(META, reference_width_ticks=200, capital_quote=0.0)


def test_a_thin_window_says_no_verdict_rather_than_a_small_number() -> None:
    """TSLAx/USDT has 85 swaps across the whole 30-day tape.

    Publishing an APR from a handful of them would turn "we have no idea" into a
    figure someone can sort a table by, which is the failure this project is
    named after.
    """
    est = PoolAprEstimator(META, reference_width_ticks=200, capital_quote=1.0)
    feed(est, swaps(MIN_SWAPS - 1))

    fit = est.fit()
    assert not est.ready
    assert not fit.is_ready
    assert "no verdict" in fit.label
    assert f"need {MIN_SWAPS}" in fit.label


# --- the arithmetic --------------------------------------------------------


def test_the_answer_carries_the_width_it_was_asked_about() -> None:
    est = PoolAprEstimator(META, reference_width_ticks=140, capital_quote=1.0)
    feed(est, swaps(MIN_SWAPS + 10))

    fit = est.fit()
    assert fit.is_ready
    assert fit.reference_width_ticks == 140
    assert "+/-140 ticks" in fit.label


def test_fees_are_net_of_the_protocol_cut_this_pool_actually_takes() -> None:
    """P-1: reconstructing fees from volume overstates LP earnings by 1.515x.

    The accountant reads `protocolFeesToken*` off each swap rather than modelling
    34%, because P-8 established no constant is right for both of our pools. This
    asserts the credited fees sit below the gross fee, which is the direction the
    error would go if the cut were ever dropped.
    """
    est = PoolAprEstimator(META, reference_width_ticks=200, capital_quote=1.0)
    events = swaps(MIN_SWAPS + 10)
    feed(est, events)
    fit = est.fit()

    gross = sum(abs(e.amount1) * META.fee_pips / 1e6 / 1e18 for e in events)
    assert 0.0 < fit.fees_quote < gross, "credited fees must sit below the gross fee"


def test_the_convexity_cost_is_reported_beside_the_fee_apr_never_folded_in() -> None:
    """A10. A fee APR published alone is the gross number every other venue quotes.

    `net_apr` is a property over the two parts rather than a stored third
    measurement, so it cannot drift from them.
    """
    est = PoolAprEstimator(META, reference_width_ticks=200, capital_quote=1.0)
    feed(est, swaps(MIN_SWAPS + 10))
    fit = est.fit()

    assert fit.convexity_cost_apr >= 0.0, "an upper bound on adverse selection is non-negative"
    assert fit.net_apr == pytest.approx(fit.apr - fit.convexity_cost_apr)
    assert "convexity cost" in fit.label


def test_a_larger_position_earns_a_slightly_lower_rate_because_it_dilutes_itself() -> None:
    """An APR is a rate, so quadrupling the capital must not quadruple it — but it
    must not leave it *identical* either, and the difference is the point.

    A position earns `L_self / (L_pool + L_self)` of each swap's fee, so a bigger
    position is a bigger share of its own denominator. The rate therefore falls
    with size. That is not a rounding artefact; it is the reason A1 caps a
    replayed position at 1% of pool liquidity, and an estimator that reported
    perfect invariance would be one that had dropped the self-term.

    Measured here: 8.7158 at capital 1.0 against 8.7145 at capital 4.0.
    """
    a = PoolAprEstimator(META, reference_width_ticks=200, capital_quote=1.0)
    b = PoolAprEstimator(META, reference_width_ticks=200, capital_quote=4.0)
    events = swaps(MIN_SWAPS + 10)
    feed(a, events)
    feed(b, events)

    small, large = a.fit().apr, b.fit().apr

    # A rate, not a total: four times the capital does not earn four times the rate.
    assert large == pytest.approx(small, rel=1e-3)
    # But strictly lower, because the position is part of the liquidity it splits with.
    assert large < small, "a larger position must dilute itself"
    assert b.fit().capital_quote == 4.0


def test_the_look_ahead_guard_applies_here_too() -> None:
    """Inherited from `TrailingEstimator`, and worth pinning: a fee APR is exactly
    the kind of number it would be easy to compute over a window containing the
    future and never notice."""
    from misquote.core.errors import LookAheadError

    est = PoolAprEstimator(META, reference_width_ticks=200, capital_quote=1.0)
    future = swaps(1)[0]
    est.set_decision_time(future.ts - 1)
    with pytest.raises(LookAheadError):
        est.ingest(future)


# --- depth, and the cache ---------------------------------------------------


def test_the_fit_carries_the_pools_depth_not_only_our_position() -> None:
    """A1 needs the size of the venue, which cannot be the size of the position.

    `depth_quote` is what the pool's own liquidity over the reference range is
    worth. Without it a pool venue had nothing to offer `capped_notional` but
    the capital it had just deployed, which is a ceiling made out of the thing
    it is meant to bound.
    """
    est = PoolAprEstimator(META, reference_width_ticks=80, capital_quote=1.0)
    feed(est, swaps(MIN_SWAPS + 10))
    got = est.fit()

    assert got.depth_quote > 0.0
    assert got.depth_quote > got.capital_quote, (
        "the pool is deeper than the one unit of capital replayed into it, and a "
        "ceiling that were not would cap every sample"
    )


def test_the_cached_fit_is_dropped_when_the_window_moves() -> None:
    """The memo is only safe while the window it was taken over is unchanged.

    A fit is a pure function of the trailing events, and they change in exactly
    two places — an event absorbed and an event aged out. This asserts the second
    of those, because it is the one with no new data to make a stale answer
    obvious: the window empties, and an estimator that kept answering would keep
    publishing a rate for a period it can no longer see.
    """
    events = swaps(MIN_SWAPS + 10, step=60)
    est = PoolAprEstimator(META, reference_width_ticks=80, capital_quote=1.0, window_seconds=3600)
    feed(est, events)

    warm = est.fit()
    assert warm.is_ready
    assert est.fit() is warm, "an unchanged window answers from the memo"

    # Far enough ahead that every event has aged out of the window.
    est.set_decision_time(events[-1].ts + 86_400)
    after = est.fit()

    assert after is not warm, "the memo did not survive the window emptying"
    assert not after.is_ready
    assert after.swaps == 0


def test_the_memo_answers_exactly_what_recomputing_would() -> None:
    """A cache that returns a different number is a bug wearing a speedup's name."""
    events = swaps(MIN_SWAPS + 20)
    est = PoolAprEstimator(META, reference_width_ticks=80, capital_quote=1.0)
    fresh = PoolAprEstimator(META, reference_width_ticks=80, capital_quote=1.0)
    feed(est, events)
    feed(fresh, events)

    cached = est.fit()
    est.fit()  # a second ask, served from the memo

    assert est.fit() == fresh.fit() == cached
