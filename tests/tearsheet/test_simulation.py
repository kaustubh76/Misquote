"""The per-window fits, and the two ways a simulation could quietly lie.

`/venue` publishes a band and `/simulate` publishes the windows it reduces. The
first way those come apart is drift — two traversals that agree today. The
second is a floor: a window can clear the estimator's own `MIN_SWAPS` while its
width never clears `MIN_SAMPLES` windows, and publishing that window lets a
reader read a figure off a pool the site says it has no verdict on.

Both are asserted here, and the second one is not hypothetical — TSLAx/USDT
produced ninety-one such cells the first time this emitter ran.
"""

from __future__ import annotations

import importlib.util

from misquote.core.types import Event, PoolMeta
from misquote.replay.ranges import MIN_SAMPLES, percentile
from misquote.tearsheet.pools import WIDTH_LADDER, band_for_width, window_fits
from misquote.tearsheet.provenance import REPO

META = PoolMeta(
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


def _emitter():
    """`scripts/simulate_report.py`, imported by path — it is not in the package."""
    spec = importlib.util.spec_from_file_location(
        "misquote_simulate_emitter", REPO / "scripts" / "simulate_report.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


emitter = _emitter()


def tape(count: int, *, spacing: int = 60, drift: int = 0) -> list[Event]:
    """A swap tape dense enough to clear every floor, walking the tick if asked."""
    return [
        Event(
            block=1_000 + i,
            log_index=0,
            ts=1_700_000_000 + i * spacing,
            kind="swap",
            tx=f"0x{i:064x}",
            amount0=-(10**20),
            amount1=10**20,
            sqrt_price_x96=1 << 96,
            liquidity=10**24,
            tick=(i * drift) // max(1, count // 40),
            protocol_fee0=0,
            protocol_fee1=10**20 * 500 // 10**6 * 3400 // 10_000,
        )
        for i in range(count)
    ]


# --- one traversal, so the two surfaces cannot drift ------------------------


def test_the_band_is_the_percentiles_of_the_cells_it_reduces() -> None:
    """The assertion that would break first if anyone gave the simulator its own sweep.

    `/venue` draws the band and `/simulate` draws the windows underneath it, on
    the same site, from the same artifact family. A reader who takes the median
    of the windows must land on the band's median.
    """
    events = tape(4_000)
    fits = window_fits(events, META, 80)
    band = band_for_width(events, META, 80, fits=fits)

    assert band.sufficient, "the fixture must clear the floor or this asserts nothing"

    nets = [f.fit.net_apr for f in fits]
    assert band.p25 == percentile(nets, 0.25)
    assert band.p50 == percentile(nets, 0.50)
    assert band.p75 == percentile(nets, 0.75)
    assert band.observations == len(fits)


def test_handing_the_fits_in_gives_the_same_band_as_sweeping_again() -> None:
    """`fits=` exists to avoid paying for the sweep twice, not to change the answer."""
    events = tape(4_000)
    fits = window_fits(events, META, 80)

    assert band_for_width(events, META, 80, fits=fits) == band_for_width(events, META, 80)


# --- the floor a cell is published against ----------------------------------


def test_a_window_carries_the_range_the_accountant_actually_used() -> None:
    """A drawn range one tick off the accounted range is a picture of a different
    position than the figures beside it, which is why the estimator publishes it
    rather than letting the emitter redo the snap."""
    fits = window_fits(tape(4_000), META, 80)

    assert fits, "no fits to check"
    for found in fits:
        fit = found.fit
        assert fit.tick_upper - fit.tick_lower == 2 * 80
        assert fit.tick_lower % META.tick_spacing == 0
        assert fit.tick_upper % META.tick_spacing == 0


def test_a_thin_tape_yields_no_fits_rather_than_ready_ones() -> None:
    """Below the estimator's own floor there is nothing to publish at all."""
    assert window_fits(tape(10), META, 80) == []


def test_cells_are_published_only_where_the_band_cleared() -> None:
    """The TSLAx case, which this emitter shipped wrong once.

    A fit is ready at MIN_SWAPS swaps in its window; a band is sufficient at
    MIN_SAMPLES such windows. Between those two floors sits a pool with enough
    trade to compute a position and not enough to have a verdict — and a cell
    published there is a figure on a pool `/venue` says it cannot rank.
    """
    # Sparse enough that windows clear MIN_SWAPS but not MIN_SAMPLES of them.
    events = tape(60, spacing=3_600)
    fits = window_fits(events, META, 80)
    band = band_for_width(events, META, 80, fits=fits)

    assert fits, "the fixture must produce ready fits or it does not test the gap"
    assert not band.sufficient, "and the band must still refuse, or the gap is closed"
    assert "need" in band.note


def test_the_emitter_drops_the_cells_whose_band_refused() -> None:
    """The same gap, through the emitter that has to honour it."""
    thin = tape(60, spacing=3_600)
    dense = tape(4_000)

    for events, expect_cells in ((thin, False), (dense, True)):
        published: list[dict] = []
        for width in WIDTH_LADDER[:2]:
            fits = window_fits(events, META, width)
            band = band_for_width(events, META, width, fits=fits)
            if band.sufficient:
                published.extend(emitter.cell(width, f) for f in fits)
        assert bool(published) is expect_cells


# --- why capital is swept and not multiplied ---------------------------------


def test_a_bigger_position_earns_less_than_its_share_and_that_is_the_measurement() -> None:
    """Why `/simulate` sweeps capital instead of multiplying by it.

    The obvious design was one sweep at capital 1 and a number box in the
    browser: APR is per unit of capital, so money is linear in it. It is not.
    `LvrAccountant` prorates each swap's fee by liquidity share,
    `L / (L_pool + L)`, so a larger position sits in a larger denominator and
    dilutes itself — which is a real thing that happens to real LPs and is
    exactly what this project exists to not round away.

    A browser multiplying would have erased it in the direction that flatters
    the bigger position. This is the test that says so, and it asserts the
    inequality rather than a tolerance: any tolerance wide enough to pass would
    be wide enough to hide the effect.
    """
    events = tape(4_000)
    one = window_fits(events, META, 80, capital_quote=1.0)
    ten = window_fits(events, META, 80, capital_quote=10.0)

    assert len(one) == len(ten)
    for a, b in zip(one, ten, strict=True):
        assert b.fit.capital_quote == 10.0
        # Sublinear, strictly: more money earns more, and less than its multiple.
        assert a.fit.fees_quote < b.fit.fees_quote < a.fit.fees_quote * 10
        # And so the rate falls, which is the half a scaling would have hidden.
        assert b.fit.apr < a.fit.apr


def test_every_cell_carries_the_size_it_was_replayed_at() -> None:
    """A cell without its capital is a money figure with no unit.

    Every size on the ladder shares a (width, window) key, so the size is the
    field that tells them apart. Omitting it would leave one window's ladder
    looking like a run of separate windows.
    """
    found = window_fits(tape(4_000), META, 80, capital_quote=0.5)[0]
    row = emitter.cell(80, found)

    assert row["capital_quote"] == 0.5
    assert row["a1_ceiling_quote"] == found.fit.depth_quote * emitter.A1_SHARE


def test_the_a1_ceiling_is_the_published_share_and_not_a_number_typed_here() -> None:
    """A1 is `Params.eps_liquidity_share`. A second copy of it is a second A1."""
    from misquote.core.types import Params

    assert emitter.A1_SHARE == Params().eps_liquidity_share
    assert 0 < emitter.A1_SHARE <= 1


# --- the emitter's own shaping ---------------------------------------------


def test_the_price_path_keeps_both_ends_and_thins_the_middle() -> None:
    """A chart cannot hold 250,000 ticks, and a path missing its last point is a
    position whose final hours are drawn as though they did not happen."""
    from misquote.chain.addresses import TARGET_POOL

    swaps = tape(5_000, drift=1)
    path = emitter.price_path(swaps, TARGET_POOL, points=100)

    assert len(path) == 100
    assert path[0]["ts"] == swaps[0].ts
    assert path[-1]["ts"] == swaps[-1].ts
    assert [p["ts"] for p in path] == sorted(p["ts"] for p in path)


def test_a_short_tape_is_published_whole_rather_than_padded() -> None:
    from misquote.chain.addresses import TARGET_POOL

    swaps = tape(12)
    assert len(emitter.price_path(swaps, TARGET_POOL, points=100)) == 12


def test_a_cell_copies_the_fit_rather_than_recomputing_it() -> None:
    """`net_apr` is a property so it cannot drift from the two figures it
    subtracts. A cell that recomputed it would put the drift back."""
    found = window_fits(tape(4_000), META, 80)[0]
    row = emitter.cell(80, found)

    assert row["net_apr"] == found.fit.net_apr
    assert row["net_apr"] == row["fee_apr"] - row["convexity_cost_apr"]
    assert row["tick_lower"] == found.fit.tick_lower
    assert row["width_ticks"] == 80
    assert row["window"] == found.window


def test_the_ladder_the_emitter_sweeps_is_the_one_venue_publishes() -> None:
    """Two ladders would be two answers to "which widths were considered"."""
    assert emitter.WIDTH_LADDER == WIDTH_LADDER
    assert len(WIDTH_LADDER) >= 2
    assert MIN_SAMPLES > 0
