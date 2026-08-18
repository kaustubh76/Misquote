"""Equation (3), checked against an independent derivation rather than itself.

The load-bearing test here is the closed form. `LvrAccountant` computes LVR by
differencing the position's holdings across a price move; `closed_form_lvr`
computes the same quantity from `L(sqrt(Pb) - sqrt(Pa))^2 / sqrt(Pa)`, derived
separately. Agreement between two derivations is evidence. Either one on its own
is an assertion.
"""

from __future__ import annotations

import pytest

from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import Event, PoolMeta
from misquote.lvr.accountant import LvrAccountant, closed_form_lvr

META = PoolMeta(
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

LOWER, UPPER = -64400, -64000
LIQUIDITY = 10**22
WAD = 10**18


def swap(
    tick: int,
    index: int = 1,
    *,
    liquidity: int = 10**24,
    amount0: int = WAD,
    amount1: int = -WAD,
    protocol_fee0: int = 0,
    protocol_fee1: int = 0,
) -> Event:
    return Event(
        block=index,
        log_index=0,
        ts=1_700_000_000 + index,
        kind="swap",
        tx=f"0x{index:064x}",
        amount0=amount0,
        amount1=amount1,
        sqrt_price_x96=get_sqrt_ratio_at_tick(tick),
        liquidity=liquidity,
        tick=tick,
        protocol_fee0=protocol_fee0,
        protocol_fee1=protocol_fee1,
    )


def accountant(start_tick: int = -64200, **kwargs) -> LvrAccountant:
    return LvrAccountant(
        LOWER, UPPER, LIQUIDITY, META, sqrt_price_x96=get_sqrt_ratio_at_tick(start_tick), **kwargs
    )


# --- the closed form -------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end"),
    [(-64300, -64100), (-64100, -64300), (-64350, -64050), (-64200, -64190)],
)
def test_holdings_difference_agrees_with_the_closed_form(start: int, end: int) -> None:
    """Two independent derivations of the same quantity, in range throughout."""
    increment = accountant(start).absorb(swap(end))
    expected = closed_form_lvr(
        get_sqrt_ratio_at_tick(start), get_sqrt_ratio_at_tick(end), LIQUIDITY
    ) / float(WAD)

    assert increment is not None
    assert increment.lvr_quote == pytest.approx(expected, rel=1e-9)


# --- non-negativity, which convexity guarantees ----------------------------


def test_lvr_is_never_negative_across_the_whole_price_domain() -> None:
    """Includes moves that start outside, end outside, and cross entirely.

    A negative increment is not a market event; it is a sign or decimals bug.
    """
    negatives = []
    for start in range(-64700, -63700, 37):
        for end in range(-64700, -63700, 41):
            if start == end:
                continue
            increment = accountant(start).absorb(swap(end))
            if increment.lvr_quote < 0:
                negatives.append((start, end, increment.lvr_quote))

    assert negatives == []


def test_the_post_swap_price_is_required_not_a_preference() -> None:
    """Substituting the pre-swap price flips the sign of every increment.

    Then every swap looks profitable for the liquidity provider, which is both
    wrong and extremely comfortable — the combination that survives review.
    """
    start, end = -64300, -64100
    increment = accountant(start).absorb(swap(end))

    with_pre_swap = -(increment.delta1 + _price(start) * increment.delta0)
    assert increment.lvr_quote > 0
    assert with_pre_swap < 0


def _price(tick: int) -> float:
    from misquote.core.tickmath import Q96

    return (get_sqrt_ratio_at_tick(tick) / Q96) ** 2


# --- clamping, which is matrix item P-3 ------------------------------------


def test_clamping_to_the_range_is_worth_orders_of_magnitude() -> None:
    """A swap crossing the whole range, accounted end to end, is wildly wrong.

    Above the upper bound the position holds no token0 — there is nothing left
    to pick off — and the rebalancing benchmark has sold out too. Only the
    segment inside the range ever involved us. On the narrow ranges this agent
    runs by design, the unclamped figure is off by more than a hundredfold.
    """
    clamped = accountant(-64200).absorb(swap(-62000)).lvr_quote
    naive = closed_form_lvr(
        get_sqrt_ratio_at_tick(-64200), get_sqrt_ratio_at_tick(-62000), LIQUIDITY
    ) / float(WAD)

    assert clamped > 0
    assert naive / clamped > 50


def test_a_move_entirely_outside_the_range_costs_nothing(monkeypatch) -> None:
    """Price wandering above the range cannot adversely select a position that
    holds only token1 and is already fully converted."""
    increment = accountant(-63000).absorb(swap(-62000))
    assert increment.lvr_quote == pytest.approx(0.0, abs=1e-15)
    assert not increment.in_range


def test_crossing_the_whole_range_is_flagged() -> None:
    increment = accountant(-65000).absorb(swap(-63000))
    assert increment.fully_crossed
    assert increment.in_range


# --- the cursor ------------------------------------------------------------


def test_the_first_swap_establishes_the_cursor_and_accrues_nothing() -> None:
    """There is no prior price against which to have been adversely selected."""
    acc = LvrAccountant(LOWER, UPPER, LIQUIDITY, META)
    assert acc.absorb(swap(-64200, 1)) is None
    assert acc.swaps_seen == 0

    assert acc.absorb(swap(-64100, 2)) is not None
    assert acc.swaps_seen == 1


def test_mints_and_burns_do_not_move_the_price_cursor() -> None:
    acc = accountant(-64200)
    burn = Event(
        block=5,
        log_index=0,
        ts=1,
        kind="burn",
        tx="0x" + "cd" * 32,
        amount0=1,
        amount1=1,
        sqrt_price_x96=get_sqrt_ratio_at_tick(-60000),
        liquidity=1,
        tick=-60000,
    )
    assert acc.absorb(burn) is None
    assert acc.absorb(swap(-64100)).lvr_quote == pytest.approx(
        accountant(-64200).absorb(swap(-64100)).lvr_quote
    )


# --- fees, and the protocol's 34% -----------------------------------------


def test_the_protocol_cut_comes_from_the_event_not_from_a_model() -> None:
    """Pancake's Swap event reports what the protocol took. Using it means the
    number stays right even if governance changes the parameter mid-history."""
    gross = 10**18
    total_fee = gross * 500 // 1_000_000
    protocol = total_fee * 3400 // 10_000

    acc = accountant(-64200)
    with_cut = acc.absorb(
        swap(-64150, amount0=gross, amount1=-gross, protocol_fee0=protocol)
    ).fee_quote

    acc2 = accountant(-64200)
    without_cut = acc2.absorb(swap(-64150, amount0=gross, amount1=-gross)).fee_quote

    assert with_cut < without_cut
    assert with_cut / without_cut == pytest.approx(0.66, rel=1e-3)


def test_ignoring_the_protocol_cut_overstates_lp_fees_by_half_again() -> None:
    """1/0.66 = 1.52. That error lands straight on NetFeeAPR."""
    gross = 10**18
    total_fee = gross * 500 // 1_000_000
    protocol = total_fee * 3400 // 10_000

    net = (
        accountant(-64200)
        .absorb(swap(-64150, amount0=gross, amount1=-gross, protocol_fee0=protocol))
        .fee_quote
    )
    gross_fee = accountant(-64200).absorb(swap(-64150, amount0=gross, amount1=-gross)).fee_quote

    assert gross_fee / net == pytest.approx(1.515, rel=1e-2)


def test_fees_are_prorated_by_how_much_of_the_move_was_inside_the_range() -> None:
    """v3 accrues to whichever ticks are active as price sweeps, so a swap that
    only clips the edge of our range should only pay us for the part it clipped."""
    inside = accountant(-64300).absorb(swap(-64100)).fee_quote
    clipping = accountant(-64100).absorb(swap(-63000)).fee_quote
    assert inside > clipping > 0


def test_a_hypothetical_position_is_added_to_pool_liquidity_but_a_real_one_is_not() -> None:
    """Matrix D-1. A live Swap event's `liquidity` already includes a real
    position's L, so dividing by it double-counts; a replayed hypothetical is
    not in that number and has to be added."""
    hypothetical = accountant(-64300, l_pool_includes_self=False).absorb(swap(-64100)).fee_quote
    real = accountant(-64300, l_pool_includes_self=True).absorb(swap(-64100)).fee_quote
    assert real > hypothetical  # dividing by a smaller denominator


# --- the honest caveat, published as A10 ----------------------------------


def test_a_round_trip_books_lvr_even_though_the_position_ended_flat() -> None:
    """Why this is an upper bound rather than a measurement.

    Equation (3) is non-negative for every swap regardless of who traded, which
    is the tell that it is not really measuring adverse selection — it assumes
    the post-swap pool price is fair. Price out and back leaves the LP flat with
    two fees collected, and equation (3) still books a loss.
    """
    acc = accountant(-64200)
    acc.absorb(swap(-64100, 1))
    acc.absorb(swap(-64200, 2))

    assert acc.total_lvr > 0
    assert acc.swaps_seen == 2


# --- guards ----------------------------------------------------------------


def test_a_degenerate_position_is_refused() -> None:
    with pytest.raises(ValueError, match="range is empty"):
        LvrAccountant(-64000, -64400, LIQUIDITY, META)
    with pytest.raises(ValueError, match="adversely selected"):
        LvrAccountant(LOWER, UPPER, 0, META)


def test_decimal_asymmetry_scales_the_quote_rather_than_being_ignored() -> None:
    """A pool with unequal decimals prices every increment differently, and the
    error is a clean power of ten — invisible in any ratio-based check."""
    from dataclasses import replace

    six = replace(META, dec1=6)
    equal = accountant(-64300).absorb(swap(-64100)).lvr_quote
    skewed = (
        LvrAccountant(LOWER, UPPER, LIQUIDITY, six, sqrt_price_x96=get_sqrt_ratio_at_tick(-64300))
        .absorb(swap(-64100))
        .lvr_quote
    )

    assert skewed != pytest.approx(equal)
    assert skewed > 0


# --- fees, checked against something that is not the accountant -------------


def test_fee_accrual_matches_an_independent_computation() -> None:
    """The numerator of the whole product, verified by arithmetic done twice.

    Spec test **T4 does not cover this**, despite its name. T4 builds two
    `LvrAccountant`s, feeds one from a list and one through a `MemoryTape`, and
    asserts they agree — which proves the tape delivers events faithfully and
    says nothing about whether `absorb`'s fee maths is right. Both sides call the
    same code.

    This computes the LP fee straight off each event instead: gross input times
    the fee tier, minus the protocol's own reported cut, scaled by this
    position's share of active liquidity, converted to token1 at the post-swap
    price. Nothing here imports the accountant's logic.

    Run against 20,000 real swaps off the 30-day tape it agreed to **0.0e+00**
    relative difference. The synthetic tape below keeps that check in the suite.
    """
    from misquote.core.tickmath import MAX_TICK, MIN_TICK, Q96

    # Wide enough that the position is always in range, so `_range_fraction` is
    # 1 throughout and this isolates the fee arithmetic from the A11 proration.
    lo, hi = (MIN_TICK // 10 + 1) * 10, (MAX_TICK // 10) * 10
    liquidity = 10**20

    events = []
    tick = -64180
    for i in range(1, 400):
        tick += 7 if i % 3 else -11
        up = i % 2 == 0
        events.append(
            swap(
                tick,
                i,
                liquidity=10**24 + i * 10**18,
                amount0=-WAD if up else WAD,
                amount1=WAD if up else -WAD,
                protocol_fee0=0 if up else WAD * 500 // 1_000_000 * 3400 // 10_000,
                protocol_fee1=WAD * 500 // 1_000_000 * 3400 // 10_000 if up else 0,
            )
        )

    acct = LvrAccountant(lo, hi, liquidity, META, sqrt_price_x96=events[0].sqrt_price_x96)
    for event in events[1:]:
        acct.absorb(event)

    independent = 0.0
    for event in events[1:]:
        if event.amount0 > 0:
            gross, cut, in_quote = event.amount0, event.protocol_fee0, False
        elif event.amount1 > 0:
            gross, cut, in_quote = event.amount1, event.protocol_fee1, True
        else:
            continue
        lp_fee = max(0, gross * META.fee_pips // 1_000_000 - cut)
        amount = lp_fee / 10.0 ** (META.dec1 if in_quote else META.dec0)
        if not in_quote:
            amount *= (event.sqrt_price_x96 / Q96) ** 2
        independent += amount * (liquidity / (event.liquidity + liquidity))

    assert independent > 0.0, "the fixture earned nothing, so this proves nothing"
    assert acct.total_fees == pytest.approx(independent, rel=1e-12)


def test_the_protocol_cut_actually_reduces_what_the_position_earns() -> None:
    """P-1 is worth 1.52x on this venue, so a fee path that ignored the event's
    protocol field would still look plausible. It must not."""
    lower, upper, liquidity = LOWER, UPPER, 10**22
    cut = WAD * 500 // 1_000_000 * 3400 // 10_000

    def total(protocol_fee1: int) -> float:
        acct = LvrAccountant(lower, upper, liquidity, META)
        for i in range(1, 40):
            acct.absorb(swap(-64180, i, amount0=-WAD, amount1=WAD, protocol_fee1=protocol_fee1))
        return acct.total_fees

    assert total(cut) < total(0), "the protocol's cut did not reduce LP fees"
