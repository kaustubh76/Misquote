"""`pools.json` — the invariants that stop it becoming a leaderboard.

Unlike `venue.json`, this artifact is **not** a projection end to end: it reads
the indexed tape, so its bands cannot be re-derived without one. Only the ladder
is pure, and that field is checked in `test_artifact_projections.py` beside the
other projections.

What is left is the part that actually matters, and it is not arithmetic — it is
whether the document keeps the promises the assumption sheet makes for it. A21
says a fee APR carries the width it is about. A22 says pools are compared as
bands and only when the vetting layer clears them. Those are structural claims
about every row, and this is where they are enforced.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from misquote.replay.ranges import MIN_SAMPLES
from misquote.tearsheet.pools import WIDTH_LADDER

REPO = pathlib.Path(__file__).resolve().parents[2]
ARTIFACTS = REPO / "apps" / "web" / "public" / "artifacts"


@pytest.fixture(scope="module")
def report() -> dict:
    path = ARTIFACTS / "pools.json"
    if not path.exists():
        pytest.skip("no pool report; run `make pools`")
    return json.loads(path.read_text())


def published(report: dict) -> list[dict]:
    """Rows that carry a width ranking, as opposed to a refusal."""
    return [r for r in report["pools"] if r.get("ladder")]


def test_only_badged_pools_carry_a_ranking(report: dict) -> None:
    """A22. An absent or failing badge is a refusal, not a pass.

    The whole argument of the vetting layer is that a pool nobody checked is a
    pool nobody should be steered into. A row that ranked without a badge would
    invert it silently, which is worse than not having the layer.
    """
    for row in published(report):
        assert row["badged"] is True, f"{row['label']} ranks without a badge"


def test_an_unbadged_pool_still_says_why(report: dict) -> None:
    """A refusal with no reason is indistinguishable from an oversight."""
    for row in report["pools"]:
        if not row["badged"]:
            assert row["verdict"].startswith("not published:"), row["verdict"]
            assert row["ladder"] == [], "a refused pool must not carry bands"


def test_every_band_carries_the_width_it_is_about(report: dict) -> None:
    """A21. There is no width-free fee APR, so there is no width-free row."""
    for row in published(report):
        widths = [b["width_ticks"] for b in row["ladder"]]
        assert widths == list(WIDTH_LADDER), f"{row['label']} ladder is {widths}"


def test_a_band_is_ordered_and_carries_its_sample_size(report: dict) -> None:
    """P25 <= P50 <= P75, and the count that earned them.

    A range whose quartiles are out of order is a computation error; a range
    without its observation count is a point estimate wearing three numbers.
    """
    for row in published(report):
        for band in row["ladder"]:
            if not band["sufficient"]:
                continue
            assert band["p25"] <= band["p50"] <= band["p75"], f"{row['label']} {band}"
            assert band["observations"] >= MIN_SAMPLES, band


def test_a_refused_band_carries_a_reason_and_not_a_zero(report: dict) -> None:
    """A zero meaning "no evidence" sorts beside one meaning "earned nothing"."""
    for row in published(report):
        for band in row["ladder"]:
            if band["sufficient"]:
                continue
            assert band["note"], f"{row['label']} width {band['width_ticks']} refuses silently"
            assert "need" in band["note"], band["note"]


def test_a_leader_is_only_named_when_its_band_clears_the_runner_up(report: dict) -> None:
    """A22, and the line between this and a leaderboard.

    Where the top two bands overlap the verdict must say so. This is the
    assertion that would fail first if someone later sorted on the median and
    called the top row the winner.
    """
    for row in published(report):
        usable = [b for b in row["ladder"] if b["sufficient"]]
        if len(usable) < 2:
            continue
        top, second = sorted(usable, key=lambda b: b["p50"], reverse=True)[:2]
        overlap = not (top["p75"] < second["p25"] or second["p75"] < top["p25"])
        if overlap:
            assert "not separated" in row["verdict"], (
                f"{row['label']}: bands overlap but the verdict reads {row['verdict']!r}"
            )
        else:
            assert "does not overlap" in row["verdict"], row["verdict"]


def test_the_published_ties_agree_with_the_published_quartiles(report: dict) -> None:
    """The join `/venue` renders, checked against the numbers beside it.

    `components/WidthLadder.tsx` draws "not separated from ±40, ±130" out of
    `indistinguishable_from` and never recomputes it — that is the whole reason
    the field exists rather than four lines of TypeScript. Which means nothing
    in the browser can notice the day the field stops describing the quartiles
    it is published next to. This is the thing that notices.

    A missing field is a failure and not a skip: the page degrades to a ladder
    with no comparison, quietly, and a fixture that skipped here would report
    that silence as a pass.
    """
    for row in published(report):
        usable = [b for b in row["ladder"] if b["sufficient"]]
        for band in usable:
            assert "indistinguishable_from" in band, (
                f"{row['label']} +/-{band['width_ticks']} carries no ties — run `make pools`"
            )
            expected = sorted(
                other["width_ticks"]
                for other in usable
                if other["width_ticks"] != band["width_ticks"]
                and not (band["p75"] < other["p25"] or other["p75"] < band["p25"])
            )
            assert sorted(band["indistinguishable_from"]) == expected, (
                f"{row['label']} +/-{band['width_ticks']}: ties {band['indistinguishable_from']} "
                f"do not match its own P25-P75 against the rest of the ladder"
            )
        for band in row["ladder"]:
            if not band["sufficient"]:
                assert "indistinguishable_from" not in band, (
                    "a refused band with an empty tie list reads as separated from everything"
                )


def test_the_summary_counts_agree_with_the_rows(report: dict) -> None:
    """The header a reader trusts before scrolling has to match what follows."""
    summary = report["summary"]
    rows = report["pools"]

    assert summary["pools"] == len(rows)
    assert summary["badged"] == sum(1 for r in rows if r["badged"])
    quotable = [r for r in rows if r["badged"] and any(b["sufficient"] for b in r["ladder"])]
    assert summary["quotable"] == len(quotable)
    assert summary["refused"] == len(rows) - len(quotable)


def test_the_report_says_it_came_from_chain(report: dict) -> None:
    """A synthetic tape must never render as a measurement of a real pool."""
    assert report["build"]["source"] == "chain"
