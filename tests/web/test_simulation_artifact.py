"""`simulation.json` — the invariants that stop it becoming a brochure.

`/simulate` lets a reader set a size and read a number off it, which is the most
dangerous shape anything on this site has taken. Three things make it honest and
each is asserted here: the figure is a cell the engine replayed rather than one
the page computed, the cell exists only where the evidence cleared the same floor
a quote is held to, and a size above A1's ceiling is refused rather than clamped.

`tests/tearsheet/test_simulation.py` holds the emitter's logic on synthetic
tapes. This holds the published file, which is the thing a reader actually gets.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from misquote.core.types import Params
from misquote.replay.ranges import MIN_SAMPLES
from misquote.tearsheet.pools import WIDTH_LADDER

REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO / "apps" / "web" / "public" / "artifacts"


@pytest.fixture(scope="module")
def report() -> dict:
    path = ARTIFACTS / "simulation.json"
    if not path.exists():
        pytest.skip("no simulation; run `make simulate`")
    return json.loads(path.read_text())


def cells(report: dict) -> list[dict]:
    return [c for pool in report["pools"] for c in pool["cells"]]


def test_the_report_says_it_came_from_chain(report: dict) -> None:
    """A synthetic tape must never render as a position somebody could have held."""
    assert report["build"]["source"] == "chain"


def test_only_badged_pools_carry_cells(report: dict) -> None:
    """A22. The due-diligence layer governs which pools an agent may enter, so it
    has to govern which pools a reader is invited to imagine capital in."""
    for pool in report["pools"]:
        if pool["cells"]:
            assert pool["badged"] is True, f"{pool['label']} simulates without a badge"


def test_an_unsimulable_pool_still_says_why(report: dict) -> None:
    """A refusal with no reason is indistinguishable from an oversight."""
    for pool in report["pools"]:
        if not pool["cells"]:
            assert pool["verdict"], pool["label"]
            # And nothing that looks like a result: no path to draw a range on.
            assert pool["price_path"] == [], (
                f"{pool['label']} has no answer and half a chart, which reads as "
                "an invitation with the refusal in small type"
            )


def test_cells_exist_only_at_widths_whose_band_cleared(report: dict) -> None:
    """The TSLAx gap, in the published file.

    A window can clear the estimator's own swap floor while its width never
    clears `MIN_SAMPLES` such windows. A cell published there is a figure on a
    width `/venue` reports as having no verdict.
    """
    for pool in report["pools"]:
        cleared = {b["width_ticks"] for b in pool["bands"] if b["sufficient"]}
        published = {c["width_ticks"] for c in pool["cells"]}
        assert published <= cleared, (
            f"{pool['label']} publishes cells at widths whose band refused: "
            f"{sorted(published - cleared)}"
        )


def test_every_cell_carries_its_width_its_window_and_its_size(report: dict) -> None:
    """Three keys identify a cell, and all three are what a reader chose.

    Dropping any one leaves cells that look like duplicates of each other — four
    sizes reading as four windows, or seven widths as seven runs.
    """
    for pool in report["pools"]:
        seen = set()
        for c in pool["cells"]:
            assert c["width_ticks"] in WIDTH_LADDER
            key = (c["width_ticks"], c["window"], c["capital_quote"])
            assert key not in seen, f"{pool['label']} publishes {key} twice"
            seen.add(key)


def test_the_capital_ladder_is_offered_and_not_interpolated(report: dict) -> None:
    """Every size in a cell is a size the emitter declared it would sweep."""
    ladder = set(report["capital_ladder"])
    assert ladder, "no sizes swept"
    for c in cells(report):
        assert c["capital_quote"] in ladder, (
            f"a cell at {c['capital_quote']} is not on the published ladder, so the "
            "page would offer a size nothing measured"
        )


def test_money_is_not_a_scaling_of_the_reference_size(report: dict) -> None:
    """The finding this whole design turns on, asserted on the real numbers.

    Fees are sublinear in capital because `LvrAccountant` prorates by liquidity
    share. If two sizes of the same window ever came out exactly proportional,
    either the dilution has stopped being modelled or somebody has replaced the
    sweep with a multiplication — and the page would be flattering large
    positions with nothing to say so.
    """
    checked = 0
    for pool in report["pools"]:
        by_key: dict[tuple[int, int], list[dict]] = {}
        for c in pool["cells"]:
            by_key.setdefault((c["width_ticks"], c["window"]), []).append(c)
        for group in by_key.values():
            group.sort(key=lambda c: c["capital_quote"])
            for small, large in zip(group, group[1:], strict=False):
                if small["fees_quote"] <= 0:
                    continue
                ratio = large["capital_quote"] / small["capital_quote"]
                scaled = small["fees_quote"] * ratio
                assert large["fees_quote"] < scaled, (
                    f"{pool['label']} +/-{large['width_ticks']} window "
                    f"{large['window']}: {large['capital_quote']} earns "
                    f"{large['fees_quote']}, which is not below {ratio}x the "
                    f"smaller size's {small['fees_quote']} — the dilution is gone"
                )
                checked += 1
    if checked == 0:
        pytest.skip("only one size per window in this report")


def test_mintability_agrees_with_the_tick_grid_it_is_about(report: dict) -> None:
    """The page marks rungs off this number, so it may not drift from the bounds.

    `PoolAprEstimator` snaps the *centre* to the spacing and then takes
    `centre +/- width` without snapping the width, so a range sits on the pool's
    grid only when `width % tick_spacing == 0`. The ladder is shared across
    pools whose spacings differ, which is how `/simulate` came to offer four
    widths the 0.25% pool would reject — the revert `/venue` documents as
    divergence five, on the page next door.

    Re-derived here from the bounds rather than trusted, because a `mintable`
    that stopped describing `tick_lower`/`tick_upper` would mark the wrong rungs
    and nothing in the browser could tell.
    """
    for pool in report["pools"]:
        spacing = pool["tick_spacing"]
        for c in pool["cells"]:
            on_grid = c["tick_lower"] % spacing == 0 and c["tick_upper"] % spacing == 0
            above_floor = (c["tick_upper"] - c["tick_lower"]) // 2 >= 4 * spacing
            assert c["mintable"] is (on_grid and above_floor), (
                f"{pool['label']} +/-{c['width_ticks']}: mintable={c['mintable']} but "
                f"[{c['tick_lower']}, {c['tick_upper']}] on a {spacing}-tick grid is "
                f"on_grid={on_grid}, above_floor={above_floor}"
            )


def test_an_unmintable_cell_says_why_and_a_mintable_one_does_not(report: dict) -> None:
    """A refusal with no reason is indistinguishable from an oversight, and a
    reason attached to something that was not refused is noise on the page."""
    for pool in report["pools"]:
        for c in pool["cells"]:
            if c["mintable"]:
                assert c["not_mintable_why"] == "", (
                    f"{pool['label']} +/-{c['width_ticks']} is mintable and carries a reason"
                )
            else:
                assert "could not be minted" in c["not_mintable_why"], c["not_mintable_why"]


def test_at_least_one_width_is_unmintable_somewhere(report: dict) -> None:
    """Both bounds on the finding, so this stops covering nothing silently.

    If every rung became mintable the marking is unreachable and this file has
    stopped testing it; if none were, the ladder would be entirely hypothetical
    and the page should say something much stronger than it does.
    """
    cells = [c for pool in report["pools"] for c in pool["cells"]]
    refused = [c for c in cells if not c["mintable"]]

    assert refused, "no width is unmintable — the marking on /simulate is unreachable"
    assert len(refused) < len(cells), "every width is unmintable — retarget this page"


def test_the_a1_ceiling_is_on_every_cell_and_is_the_published_share(report: dict) -> None:
    """The page refuses on this number, so it may not be a number the page invented."""
    share = report["a1_share"]
    assert share == Params().eps_liquidity_share
    for c in cells(report):
        assert c["a1_ceiling_quote"] == pytest.approx(c["depth_quote"] * share)


def test_a_cell_net_is_the_subtraction_and_not_a_third_measurement(report: dict) -> None:
    for c in cells(report):
        assert c["net_apr"] == pytest.approx(c["fee_apr"] - c["convexity_cost_apr"])


def test_a_published_band_rests_on_at_least_the_sample_floor(report: dict) -> None:
    for pool in report["pools"]:
        for band in pool["bands"]:
            if band["sufficient"]:
                assert band["observations"] >= MIN_SAMPLES
            else:
                assert band["note"], f"{pool['label']} refuses a width silently"


def test_the_price_path_is_thinned_rather_than_published_whole(report: dict) -> None:
    """250,000 ticks is eight megabytes to draw a line four hundred pixels wide."""
    limit = report["path_points"]
    for pool in report["pools"]:
        assert len(pool["price_path"]) <= limit, pool["label"]
        stamps = [p["ts"] for p in pool["price_path"]]
        assert stamps == sorted(stamps), f"{pool['label']} path is out of order"


def test_the_summary_counts_agree_with_the_rows(report: dict) -> None:
    summary = report["summary"]
    rows = report["pools"]

    assert summary["pools"] == len(rows)
    assert summary["badged"] == sum(1 for r in rows if r["badged"])
    assert summary["simulable"] == sum(1 for r in rows if r["cells"])
    assert summary["refused"] == len(rows) - summary["simulable"]
    assert summary["cells"] == sum(len(r["cells"]) for r in rows)
