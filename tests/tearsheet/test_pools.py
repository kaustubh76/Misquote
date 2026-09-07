"""Width bands, and the refusals that stop them becoming a leaderboard.

A leaderboard is the misquote: one number per row, sorted, hiding the sample it
rests on. These tests are mostly about the sentences this module produces when it
must not rank, because those sentences are the product.
"""

from __future__ import annotations

import pytest

from misquote.replay.ranges import MIN_SAMPLES
from misquote.tearsheet.pools import (
    WIDTH_LADDER,
    WidthBand,
    best_width,
    ladder_payload,
    separation,
)


def band(width: int, p25: float, p50: float, p75: float, *, obs: int = MIN_SAMPLES) -> WidthBand:
    return WidthBand(width, p25, p50, p75, obs, True, "")


def refused(width: int, note: str = "thin") -> WidthBand:
    return WidthBand(width, 0.0, 0.0, 0.0, 3, False, note)


# --- the ladder ------------------------------------------------------------


def test_the_ladder_brackets_the_derived_width_band() -> None:
    """A18 derives a floor of ~130 ticks and A19 a ceiling of ~244.

    The ladder has to reach past both ends, or it could only ever confirm the
    derivation — a sweep that cannot disagree with the thing it is checking is
    not a check.
    """
    assert min(WIDTH_LADDER) < 130, "must be able to find an optimum below A18's floor"
    assert max(WIDTH_LADDER) > 244, "must be able to find one above A19's ceiling"
    assert 130 in WIDTH_LADDER and 244 in WIDTH_LADDER, "and must price the band itself"
    assert list(WIDTH_LADDER) == sorted(WIDTH_LADDER), "ordered, so a card can render it as a curve"


# --- when it may rank, and when it may not ---------------------------------


def test_a_leader_whose_band_overlaps_the_runner_up_is_not_called_a_winner() -> None:
    """The whole difference between this and a leaderboard.

    Both bands below have the same shape a real measurement has; the leader's
    median is higher and its range still covers the runner-up's. Saying "80 wins"
    there would be asserting a difference the evidence does not carry.
    """
    leader, sentence = best_width([band(80, 0.20, 0.28, 0.35), band(200, 0.18, 0.26, 0.34)])

    assert leader is not None and leader.width_ticks == 80
    assert "not separated at this sample size" in sentence
    assert "overlaps" in sentence


def test_a_leader_with_a_clear_band_is_allowed_to_be_one() -> None:
    """The other half — a refusal that can never be lifted is not a refusal."""
    leader, sentence = best_width([band(80, 0.20, 0.28, 0.35), band(200, 0.05, 0.09, 0.12)])

    assert leader is not None and leader.width_ticks == 80
    assert "does not overlap" in sentence
    assert "not separated" not in sentence


def test_a_pool_with_no_usable_width_says_so_rather_than_ranking_noise() -> None:
    leader, sentence = best_width([refused(w) for w in WIDTH_LADDER])

    assert leader is None
    assert "no width has enough evidence" in sentence


def test_a_single_surviving_width_is_reported_as_such() -> None:
    """One observation is not a comparison, and must not read like one."""
    leader, sentence = best_width([band(130, 0.1, 0.2, 0.3), refused(80), refused(400)])

    assert leader is not None and leader.width_ticks == 130
    assert "only one width" in sentence


# --- the overlap predicate itself ------------------------------------------


def test_overlap_is_symmetric_and_inclusive_at_the_edges() -> None:
    a, b = band(80, 0.10, 0.20, 0.30), band(200, 0.30, 0.40, 0.50)

    assert a.overlaps(b) and b.overlaps(a), "touching at a boundary is not separation"

    c = band(400, 0.31, 0.40, 0.50)
    assert not a.overlaps(c) and not c.overlaps(a)


def test_a_refused_band_carries_its_reason_not_a_zero() -> None:
    """A zero that means 'no evidence' is indistinguishable from one that means
    'earned nothing', and a table sorted on it would put them together."""
    thin = refused(40, "3 usable windows, need 20")

    assert not thin.sufficient
    assert "need 20" in thin.note
    assert thin.to_dict()["sufficient"] is False


# --- who ties with whom, which only the emitter may decide -----------------


def test_every_pair_the_verdict_never_reached_gets_an_answer() -> None:
    """`best_width` compares the top two. A reader compares whichever two they like.

    The artifact carried seven bands and one sentence about two of them, so the
    question `/venue` exists to answer — is this width actually better than that
    one — had a published answer for exactly one pair.
    """
    bands = [
        band(40, 0.10, 0.15, 0.30),
        band(80, 0.13, 0.17, 0.28),
        band(800, 0.07, 0.11, 0.12),
    ]

    ties = separation(bands)

    assert ties[40] == [80, 800], "40 spans both of the others"
    assert ties[80] == [40], "80 clears 800 — its P25 sits above that band's P75"
    assert ties[800] == [40]


def test_a_tie_is_symmetric_because_overlapping_is() -> None:
    """The one property a hand-written table of ties would get wrong first."""
    bands = [band(40, 0.10, 0.15, 0.30), band(80, 0.13, 0.17, 0.28), band(800, 0.07, 0.11, 0.12)]

    ties = separation(bands)
    for width, others in ties.items():
        for other in others:
            assert width in ties[other], f"±{width} ties ±{other} and not the reverse"


def test_a_refused_band_is_absent_from_the_ties_rather_than_tied_with_nothing() -> None:
    """An empty list would read as "separated from everything".

    A refused band's quartiles are the `0.0` placeholders `band_for_width` writes
    for "no evidence". Overlapping a placeholder means nothing, and the inversion
    is the dangerous direction: a width nobody could measure would render as the
    one width demonstrably unlike all the others.
    """
    bands = [band(40, 0.10, 0.15, 0.30), refused(80), band(800, 0.07, 0.11, 0.12)]

    ties = separation(bands)

    assert 80 not in ties
    assert set(ties) == {40, 800}


def test_the_payload_carries_the_ties_only_where_the_band_cleared_the_floor() -> None:
    bands = [band(40, 0.10, 0.15, 0.30), refused(80, "3 usable windows, need 20")]

    rows = ladder_payload(bands)

    assert rows[0]["indistinguishable_from"] == []
    assert "indistinguishable_from" not in rows[1]
    # The refusal survives the join, which is what the row is for.
    assert rows[1]["note"] == "3 usable windows, need 20"


# --- demand: busy is not the same as underserved ---------------------------


def test_fee_per_unit_liquidity_is_the_field_that_says_underserved() -> None:
    """Volume alone says a pool is busy. Busy and underserved are different.

    Two pools with identical flow but different depth must not read the same:
    an LP's return is proportional to fees *per unit of liquidity*, so that is
    the field the ranking rests on. This pins the direction — thinner depth on
    the same flow pays each unit more.
    """
    from misquote.core.types import PoolMeta
    from misquote.tearsheet.pools import demand_for_pool

    meta = PoolMeta(
        address="0x" + "11" * 20,
        chain_id=56,
        token0="0x" + "22" * 20,
        token1="0x" + "33" * 20,
        dec0=18,
        dec1=18,
        fee_pips=500,
        tick_spacing=10,
        fee_protocol=3400,
    )

    def flow(liquidity: int):
        from misquote.core.types import Event

        return [
            Event(
                block=1_000 + i,
                log_index=0,
                ts=1_700_000_000 + i * 60,
                kind="swap",
                tx=f"0x{i:064x}",
                amount0=-(10**21),
                amount1=10**21,
                sqrt_price_x96=1 << 96,
                liquidity=liquidity,
                tick=0,
                protocol_fee0=0,
                protocol_fee1=10**21 * 500 // 10**6 * 3400 // 10_000,
            )
            for i in range(40)
        ]

    deep = demand_for_pool(flow(10**25), meta)
    thin = demand_for_pool(flow(10**23), meta)

    assert deep.volume_quote == thin.volume_quote, "same flow, by construction"
    assert thin.fee_per_unit_liquidity > deep.fee_per_unit_liquidity, (
        "the same fees spread over less depth pay each unit more — that is what "
        "'underserved' means, and volume alone cannot see it"
    )


def test_demand_takes_the_protocol_cut_from_the_event_not_from_a_constant() -> None:
    """P-8: no modelled constant is right for both of our pools.

    The cut comes from each swap's own `protocolFeesToken*` fields, so credited
    fees must sit strictly below the gross fee whenever the pool charges one.
    """
    from misquote.core.types import Event, PoolMeta
    from misquote.tearsheet.pools import demand_for_pool

    meta = PoolMeta(
        address="0x" + "11" * 20,
        chain_id=56,
        token0="0x" + "22" * 20,
        token1="0x" + "33" * 20,
        dec0=18,
        dec1=18,
        fee_pips=500,
        tick_spacing=10,
        fee_protocol=3400,
    )
    quote = 10**21
    gross_each = quote * 500 // 10**6
    events = [
        Event(
            block=1_000 + i,
            log_index=0,
            ts=1_700_000_000 + i * 60,
            kind="swap",
            tx=f"0x{i:064x}",
            amount0=-quote,
            amount1=quote,
            sqrt_price_x96=1 << 96,
            liquidity=10**24,
            tick=0,
            protocol_fee0=0,
            protocol_fee1=gross_each * 3400 // 10_000,
        )
        for i in range(40)
    ]

    demand = demand_for_pool(events, meta)
    gross_total = 40 * gross_each / 1e18

    credited = demand.fee_per_unit_liquidity * demand.median_liquidity
    assert 0.0 < credited < gross_total, "the protocol's cut must have been removed"
    # 66% on this pool, so credited lands near two thirds of gross.
    assert credited == pytest.approx(gross_total * 0.66, rel=0.02)
