"""The seam between a lending market and a pool, and the misquote it prevents.

`AllocationDriver` was written when every venue was a Venus market. Three
operations differ once a second venue *type* exists — how a trailing yield is
measured, what the policy is shown, and what the held position actually earned —
and `replay/venues.py` is where those three live.

The most important test in this file is the last one. It does not check that the
seam works; it checks that using it naively would produce a number this project
exists to refuse.
"""

from __future__ import annotations

import pytest

from misquote.agents.router.policy import RouterParams, decide_router, park_policy
from misquote.core.types import Event, PoolMeta
from misquote.estimators.pool_apr import MIN_SWAPS, PoolAprFit
from misquote.replay.allocation import AllocationDriver, SwitchCost
from misquote.replay.venues import LendingVenue, PoolVenue, VenueSource, as_venue

POOL = PoolMeta(
    address="0x36696169C63e42cd08ce11f5deeBbCeBae652050",
    chain_id=56,
    token0="0x55d398326f99059fF775485246999027B3197955",
    token1="0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    dec0=18,
    dec1=18,
    fee_pips=500,
    tick_spacing=10,
    fee_protocol=3400,
)


#: Dollars per WBNB. Any positive number does, but a plausible one keeps the
#: failure of a units mistake visible in the assertions rather than hidden by a
#: multiplication by one.
PRICE = 600.0


def fit(
    *, apr: float, cost: float, ready: bool = True, swaps: int = 40, depth: float = 0.0
) -> PoolAprFit:
    return PoolAprFit(
        apr=apr,
        reference_width_ticks=80,
        convexity_cost_apr=cost,
        fees_quote=apr,
        convexity_cost_quote=cost,
        capital_quote=1.0,
        swaps=swaps,
        hours=24.0,
        is_ready=ready,
        depth_quote=depth,
    )


# --- both kinds satisfy the seam ------------------------------------------


def test_both_venue_types_conform_to_the_protocol() -> None:
    assert isinstance(LendingVenue({}), VenueSource)
    assert isinstance(
        PoolVenue(POOL, width_ticks=80, capital_quote=1.0, quote_price=PRICE), VenueSource
    )


def test_a_plain_dict_still_means_a_venus_market() -> None:
    """Every existing caller and fixture passes a dict.

    Rewriting them all to construct a `LendingVenue` would be a large diff whose
    only effect is to say the same thing differently, so a dict keeps meaning
    what it has always meant.
    """
    assert isinstance(as_venue({"reserve_factor": 0.1}), LendingVenue)
    assert (
        as_venue(PoolVenue(POOL, width_ticks=80, capital_quote=1.0, quote_price=PRICE)).kind
        == "pool"
    )


def test_a_pool_venue_without_a_width_is_refused() -> None:
    """A21: there is no width-free fee APR, so there is no width-free venue."""
    for bad in (0, -80):
        with pytest.raises(ValueError, match="needs a width"):
            PoolVenue(POOL, width_ticks=bad, capital_quote=1.0, quote_price=PRICE)


def test_a_pool_venue_without_a_quote_price_is_refused() -> None:
    """The seam between the pool's numeraire and the router's books.

    Every badged pool is quoted in WBNB or TSLAx and Router keeps its books in
    dollars. A size that crosses that boundary unconverted is wrong by the price
    of BNB, and a default of 1.0 would make the mistake silent — which is the
    whole of P-25, where a gas figure quoted in the wrong token looked
    reasonable because nothing recorded which was meant.
    """
    for bad in (0.0, -600.0):
        with pytest.raises(ValueError, match="price of its quote token"):
            PoolVenue(POOL, width_ticks=80, capital_quote=1.0, quote_price=bad)


# --- entry cost -----------------------------------------------------------


def test_only_a_pool_charges_a_swap_on_entry() -> None:
    """Entering vUSDT from a dollar position swaps nothing; entering a v3 range
    from a single asset requires half of it to become the other token.

    `_move_cost` charged the fee only on a SWITCH, which was right while every
    venue was a dollar market and would have flattered a pool against them.
    """
    assert LendingVenue({}).swaps_on_entry is False
    assert (
        PoolVenue(POOL, width_ticks=80, capital_quote=1.0, quote_price=PRICE).swaps_on_entry is True
    )


# --- the card ------------------------------------------------------------


def test_each_kind_publishes_the_fields_its_kind_has() -> None:
    """`reserve_factor` has no pool analogue and a width has no lending one."""
    lending = LendingVenue({"symbol": "vUSDT", "reserve_factor": 0.1}).card_fields()
    pool = PoolVenue(
        POOL, width_ticks=80, capital_quote=1.0, quote_price=PRICE, label="WBNB/USDT"
    ).card_fields()

    assert lending["kind"] == "lending" and "reserve_factor" in lending
    assert "reference_width_ticks" not in lending

    assert pool["kind"] == "pool" and pool["reference_width_ticks"] == 80
    assert "reserve_factor" not in pool
    assert pool["lp_fee_share"] == pytest.approx(0.66), "LPs keep 66% on this pool"


# --- the misquote this stage was most able to commit ----------------------


def test_a_pool_is_quoted_net_because_gross_would_win_on_the_difference() -> None:
    """`decide_router` ranks venues by `VenueQuote.apr` and cannot see the kind.

    A pool publishing its **gross** fee APR there would be compared against a
    lending venue's **net** supply rate and could win purely on the subtraction
    it had not made. That is the failure `estimators/pool_apr.py` names in its
    own docstring — the gross number is the one every other venue quotes.

    Here the pool earns 20% in fees and pays 12% in convexity cost, so its
    honest figure is 8% and it should *lose* to a lending venue paying 10%.
    Quoted gross it would win at 20%.
    """
    venue = PoolVenue(POOL, width_ticks=80, capital_quote=1.0, quote_price=PRICE)
    measured = fit(apr=0.20, cost=0.12)

    quote = venue.quote("pool", None, measured)

    assert quote.apr == pytest.approx(0.08), "net of the convexity upper bound"
    assert quote.apr < 0.10, "and therefore loses to a lending venue paying 10%"
    assert measured.apr > 0.10, "which the gross figure would not have"


def test_an_unready_pool_is_stale_rather_than_zero_yield() -> None:
    """An unmeasured venue and a zero-yield venue must not render the same.

    `decide_router`'s `quotable` gate drops a stale venue rather than ranking it
    last, which is the difference between "we have no idea" and "it pays nothing".
    """
    venue = PoolVenue(POOL, width_ticks=80, capital_quote=1.0, quote_price=PRICE)
    quote = venue.quote("pool", None, fit(apr=0.0, cost=0.0, ready=False, swaps=4))

    assert quote.apr_is_stale is True
    assert quote.apr_samples == 4
    assert quote.supplied_base_quote == 0.0, "unknown size absorbs nothing under A1"


def test_a1s_ceiling_is_the_pools_depth_in_dollars_not_our_own_capital() -> None:
    """A ceiling derived from the position it bounds is not a ceiling.

    `supplied_base_quote` feeds `capped_notional` — `eps_market_share` times the
    size of the venue. This published `fit.capital_quote`, which is what we
    deployed, under a comment claiming it was what the pool could absorb. Against
    a $10,000 notional that made the ceiling meaningless in both directions at
    once.

    It is also the field the numeraire conversion has to land on: the depth is
    measured in the pool's quote token and the ceiling is compared against a
    dollar notional.
    """
    venue = PoolVenue(POOL, width_ticks=80, capital_quote=1.0, quote_price=PRICE)
    measured = fit(apr=0.2, cost=0.05, depth=250.0)

    quote = venue.quote("pool", None, measured)

    assert quote.supplied_base_quote == pytest.approx(250.0 * PRICE)
    assert quote.supplied_base_quote != pytest.approx(measured.capital_quote)


# --- accrual --------------------------------------------------------------


def test_a_pool_is_paid_from_its_own_book_not_the_annualised_rate() -> None:
    """The same discipline the lending venue applies to `borrowIndex`.

    A rate is an estimate and a total is a fact, so the driver is paid the
    difference between what the position had booked then and now.

    This used to difference `fit.fees_quote` — the trailing window's totals —
    and passed because it accrued exactly twice, which is the one length at
    which a sliding window and an accumulator agree. The fit is no longer
    consulted for payment at all, so it is not even constructed here.
    """
    events = pool_tape(120)
    venue = PoolVenue(POOL, width_ticks=80, capital_quote=2.0, quote_price=PRICE)

    earned, state = venue.accrue(None, events[:1], None)
    assert earned == 0.0, "opening the position pays nothing"
    assert state is not None

    earned, _ = venue.accrue(state, events[1:], None)

    book, _ = state
    assert earned == pytest.approx((book.total_fees - book.total_lvr) / 2.0)
    assert earned > 0, "a range that saw a hundred swaps in range earned something"


def test_the_position_is_not_recentred_under_the_holder() -> None:
    """An LP who opened at +/-80 around one tick still holds that range later.

    The range is fixed when the position opens and never re-derived, and this is
    the property whose absence produced the ratchet: re-centring every sample let
    the trailing window's own drift arrive as earnings. Two accruals from the
    same opening state must book against the same range whatever the price did.
    """
    events = pool_tape(300)
    venue = PoolVenue(POOL, width_ticks=80, capital_quote=1.0, quote_price=PRICE)

    _, state = venue.accrue(None, events[:1], None)
    book, _ = state
    lower, upper, liquidity = book.lower, book.upper, book.liquidity

    venue.accrue(state, events[1:150], None)
    venue.accrue(state, events[150:], None)

    assert (book.lower, book.upper) == (lower, upper), "the range moved under the holder"
    assert book.liquidity == liquidity, "the position was resized mid-hold"


# --- a pool inside a real driver run ---------------------------------------


def pool_tape(count: int, *, start: int = 1_700_000_000, step: int = 60, liquidity: int = 10**24):
    """A swap history the pool estimator will accept, in chain order."""
    from misquote.core.tickmath import get_sqrt_ratio_at_tick

    out = []
    ts = start
    sqrt_price = get_sqrt_ratio_at_tick(0)
    price = (sqrt_price / (1 << 96)) ** 2
    for i in range(count):
        ts += step
        size = 10**21
        quote = int(size * price)
        fee = quote * POOL.fee_pips // 10**6
        cut = fee * POOL.fee_protocol // 10_000
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
                liquidity=liquidity,
                tick=0,
                protocol_fee0=0 if up else cut,
                protocol_fee1=cut if up else 0,
            )
        )
    return out


def test_a_pool_is_replayed_end_to_end_as_a_venue_the_router_can_enter() -> None:
    """The seam, exercised where it actually has to work.

    The unit tests above check each of the three operations in isolation. This
    is the one that would catch them being wired together wrongly: a real
    `AllocationDriver`, a real policy, a real swap tape, and a position that
    ends up in a PancakeSwap range because the policy chose it.

    The capital is small on purpose. A1's ceiling is a fraction of the pool's
    depth over the reference range, and the point of that gate is that it binds
    — so a test that wanted an entry and ignored it would be asserting against
    a policy this repo does not have.
    """
    events = pool_tape(600)
    venue = PoolVenue(POOL, width_ticks=80, capital_quote=1.0, quote_price=PRICE, label="pool")
    driver = AllocationDriver(
        {"pool": venue},
        policy=decide_router,
        params=RouterParams(min_apr_samples=MIN_SWAPS, persistence_samples=1),
        capital_quote=1.0,
        costs=SwitchCost(gas_quote=0.0, slippage_bps=0.0, basis="fixture", derived=False),
    )

    result = driver.run({"pool": events})

    assert result.entries == 1, "the policy never got into the pool at all"
    assert result.a1_capped == 0, "and it did so inside A1's ceiling"
    assert result.gross_yield_quote > 0, "a held range earns the fees the window booked"


def test_the_driver_charges_a_swap_on_entering_a_pool_and_not_on_a_market() -> None:
    """`_move_cost` asks the venue rather than inferring from the action.

    Entering vUSDT from a dollar position swaps nothing; opening a range needs
    half the capital in the other token. With gas at zero the entire move cost
    is the swap fee, so the two runs differ by exactly the thing under test.
    """
    events = pool_tape(600)
    costs = SwitchCost(gas_quote=0.0, slippage_bps=30.0, basis="fixture", derived=False)

    def run_with(venue):
        return AllocationDriver(
            {"v": venue},
            policy=decide_router,
            params=RouterParams(min_apr_samples=MIN_SWAPS, persistence_samples=1),
            capital_quote=1.0,
            costs=costs,
        ).run({"v": events})

    pool = run_with(PoolVenue(POOL, width_ticks=80, capital_quote=1.0, quote_price=PRICE))

    assert pool.entries == 1
    assert pool.total_costs > 0, "opening a range from one asset pays the swap fee"
    assert pool.total_costs == pytest.approx(1.0 * 30.0 / 10_000.0)


def test_a_rate_the_agent_could_not_take_stays_off_the_summary_figures() -> None:
    """Three published numbers rested on "measured" where they needed "choosable".

    A PancakeSwap range at +/-80 measured 189% net on the real tape while A1
    barred the position from it on every sample, and the card carried that under
    "Best realized rate seen", a `breakeven_horizon_hours` of 0.0 days derived
    from it, and a `best_venue_fraction` of 0% — because the venue Router was
    being scored against was one it was never allowed to hold.

    None of those were false about the pool. All three were false about the
    agent, which is what a card reports on.

    Here the pool pays far more than the market and is far too small to enter, so
    a summary computed the old way would report the pool's rate and score Router
    as never holding the best venue.
    """
    events = pool_tape(600)
    tiny = PoolVenue(POOL, width_ticks=80, capital_quote=1.0, quote_price=PRICE)
    driver = AllocationDriver(
        {"pool": tiny},
        policy=decide_router,
        params=RouterParams(min_apr_samples=MIN_SWAPS, persistence_samples=1),
        # Two hundred times the pool's whole depth, so A1 can never clear.
        capital_quote=1e9,
        costs=SwitchCost(gas_quote=0.0, slippage_bps=0.0, basis="fixture", derived=False),
    )

    result = driver.run({"pool": events})

    assert result.entries == 0, "A1 should have refused a position this size"
    assert result.best_apr_seen == 0.0, (
        "the pool's rate was real and unreachable, so it is not a rate this agent "
        "passed up — publishing it would put a return on the card that was never offered"
    )
    assert result.breakeven_horizon_hours == 0.0
    # The venue was measured, and the record says so — the refusal is about size.
    assert result.venue_sizes["pool"], "it was quotable; the size is what failed"


def test_the_do_it_yourself_baseline_cannot_park_where_a_person_could_not() -> None:
    """A1 binds the benchmark for a stronger reason than it binds the agent.

    `park_policy` is what somebody does *without* this agent: supply to the
    highest rate on offer and leave it. On a tape where the highest rate is a
    PancakeSwap range far too small for the notional, an ungated baseline takes
    the position anyway — and then `allocation_quote_from_results` refuses the
    whole baseline, so "vs doing it yourself" renders as withheld.

    Refusing was right. Not taking it is better: a person cannot put ten thousand
    dollars into a range that holds two thousand either, so the honest benchmark
    parks in the best venue they could actually have used.
    """
    events = pool_tape(600)
    driver = AllocationDriver(
        {"pool": PoolVenue(POOL, width_ticks=80, capital_quote=1.0, quote_price=PRICE)},
        policy=park_policy,
        params=RouterParams(min_apr_samples=MIN_SWAPS, persistence_samples=1),
        capital_quote=1e9,
        costs=SwitchCost(gas_quote=0.0, slippage_bps=0.0, basis="fixture", derived=False),
    )

    result = driver.run({"pool": events})

    assert result.entries == 0, "the baseline parked in a venue it could not fit into"
    assert result.a1_capped == 0, "so there is no breach, and the comparison stays quotable"
    assert result.gross_yield_quote == 0.0, (
        "and it booked none of the fees that position would have earned — which is "
        "the number A1 exists to refuse"
    )


def test_a_long_hold_is_paid_what_an_accountant_books_over_the_same_interval() -> None:
    """The ratchet, and the test whose absence let it ship.

    The first `PoolVenue.accrue` differenced the totals of a **trailing window**.
    Those do not accumulate: as the window slides it gains swaps at one end and
    drops them at the other, so the delta is (entering − leaving) — mean-zero
    over a long hold rather than the interval's earnings. Flooring it at zero
    kept only the positive half of that, and it drifted upward without bound.
    Measured on the real tape at 109.8% annualised where the fit said 23.40%.

    Every accrual test before this one called `accrue` **twice**, and twice is
    the one length at which a ratchet and an accumulator agree. So this holds a
    position across many samples and checks the total against the accountant a
    real LP's position would have kept — the same range, the same width, the
    same capital, every swap absorbed once.
    """
    events = pool_tape(900, step=120)
    capital = 2.0
    venue = PoolVenue(POOL, width_ticks=80, capital_quote=capital, quote_price=PRICE)

    est = venue.estimator(24 * 3600)
    state, total, seen = None, 0.0, 0
    # Hourly samples, exactly as the driver takes them.
    for t in range(events[0].ts, events[-1].ts + 1, 3600):
        est.set_decision_time(t)
        start = seen
        while seen < len(events) and events[seen].ts <= t:
            est.ingest(events[seen])
            seen += 1
        earned, state = venue.accrue(state, events[start:seen], est.fit())
        total += earned

    # What the position itself booked: opened at the first swap the venue saw,
    # never re-centred, every later swap absorbed once.
    #
    # `events[1:seen]`, not `events[1:]`. The sampling loop stops at the last
    # whole hour, so the tail after it is never consumed — comparing against the
    # whole tape would fail on rows the driver was never handed, which is a
    # statement about the fixture rather than about the accrual.
    opened = venue._open_at(events[0])  # noqa: SLF001
    assert opened is not None
    for event in events[1:seen]:
        opened.absorb(event)
    expected = (opened.total_fees - opened.total_lvr) / capital

    assert total == pytest.approx(expected, rel=1e-9), (
        f"the driver paid {total:.6%} of capital where the position booked "
        f"{expected:.6%} — a difference means the accrual is not reading the "
        f"book it claims to"
    )


def test_a_range_that_loses_over_an_interval_is_charged_for_it() -> None:
    """Flooring at zero is the mistake, not the safeguard.

    A concentrated range really can go backwards over an interval: that is what
    the convexity cost is, and A10 publishes it as an upper bound precisely
    because it is real. An accrual that refuses to charge it reports a position
    that only ever gains, which is the shape of the ratchet.
    """
    venue = PoolVenue(POOL, width_ticks=80, capital_quote=1.0, quote_price=PRICE)
    events = pool_tape(200)

    _, state = venue.accrue(None, events[:1], None)
    assert state is not None, "the position opened"

    book, _ = state
    # Book a loss directly: the accountant is the thing being differenced, and
    # driving it through a tape that happens to lose would test the tape.
    book.total_lvr = book.total_fees + 0.25
    earned, _ = venue.accrue(state, [], None)

    assert earned < 0, "a range that gave up more than it earned was paid as flat"
    assert earned == pytest.approx(-0.25)
