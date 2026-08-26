"""The tearsheet, and the sample-size floor that is the whole point of it.

`verdict` refuses to call a result below thirty observations. That refusal is the
single most important behaviour in this file, and it is the difference between
this product and the ones it argues against — anyone can print a win rate, and
almost anyone will print one computed from twelve trades.
"""

from __future__ import annotations

import json

import pytest

from misquote.tearsheet.generate import (
    MIN_OBSERVATIONS,
    build,
    read_journal,
    verdict,
    write_artifact,
)


def write_journal(path, rows) -> str:
    file = path / "warden.jsonl"
    file.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(file)


def decision_row(action="hold", ts=1_700_000_000, **reasons):
    base = {"R1": 1.0, "R2": 1.0, "R3": 1.0, "R4": 1.0}
    base.update(reasons)
    return {
        "ts": ts,
        "action": action,
        "lower": -64400,
        "upper": -64000,
        "centre": -64200,
        "half_width": 200,
        "r": -6.4,
        "delta_star": 0.02,
        "reasons": base,
        "note": "",
    }


# --- the refusal -----------------------------------------------------------


def test_a_thin_sample_gets_no_verdict_rather_than_a_flattering_one() -> None:
    """Twelve out of twelve is not a 100% success rate, it is twelve."""
    result = verdict(12, 12, 0.7)
    assert not result.called
    assert result.label == "no verdict"
    assert "need 30" in result.detail
    assert "100" not in str(result), "a refusal must not leak the rate it refused to state"


@pytest.mark.parametrize("total", [0, 1, 5, 29])
def test_the_floor_holds_all_the_way_up_to_it(total: int) -> None:
    assert not verdict(total, total, 0.5).called


def test_at_the_floor_a_verdict_is_finally_called() -> None:
    result = verdict(25, MIN_OBSERVATIONS, 0.7)
    assert result.called
    assert result.n == MIN_OBSERVATIONS


def test_a_called_verdict_says_pass_or_fail_against_the_threshold() -> None:
    assert "PASS" in verdict(80, 100, 0.7).label
    assert "FAIL" in verdict(60, 100, 0.7).label


def test_the_floor_is_the_ported_value() -> None:
    """Mission Control's `min_n=30`, unchanged. Lowering it would be the single
    cheapest way to make every card look better, which is why it is pinned."""
    assert MIN_OBSERVATIONS == 30


# --- reading the journal ---------------------------------------------------


def test_an_absent_journal_summarises_to_nothing_rather_than_raising(tmp_path) -> None:
    summary = read_journal(tmp_path / "does-not-exist.jsonl")
    assert summary.rows == 0
    assert summary.hours == 0.0


def test_the_journal_records_why_the_agent_held_not_just_that_it_did(tmp_path) -> None:
    """All four gates are on every row precisely so this is possible."""
    rows = [decision_row(R2=0.0) for _ in range(10)]
    rows += [decision_row(R3=0.0) for _ in range(4)]
    rows += [decision_row(action="rebalance")]

    summary = read_journal(write_journal(tmp_path, rows))
    assert summary.decisions == 15
    assert summary.holds == 14
    assert summary.rebalances == 1
    assert summary.gate_blocks["R2"] == 10
    assert summary.gate_blocks["R3"] == 4


def test_read_errors_are_counted_rather_than_hidden(tmp_path) -> None:
    """An agent that survived twenty rate limits did so; the card should say it
    rather than presenting a clean run it did not have."""
    rows = [decision_row(), {"event": "decide_error", "error": "429"}, decision_row()]
    summary = read_journal(write_journal(tmp_path, rows))
    assert summary.errors == 1
    assert summary.decisions == 2


def test_hours_come_from_the_timestamps_not_from_the_row_count(tmp_path) -> None:
    rows = [decision_row(ts=1_700_000_000), decision_row(ts=1_700_000_000 + 7200)]
    assert read_journal(write_journal(tmp_path, rows)).hours == pytest.approx(2.0)


def test_a_corrupt_line_does_not_lose_the_whole_journal(tmp_path) -> None:
    file = tmp_path / "warden.jsonl"
    file.write_text(
        json.dumps(decision_row()) + "\n{ not json\n" + json.dumps(decision_row()) + "\n"
    )
    assert read_journal(file).decisions == 2


# --- the assembled card ----------------------------------------------------


def test_the_caveats_are_present_even_when_everything_went_well(tmp_path) -> None:
    """These are not decoration. Each one makes the headline less flattering
    than it could have been, and omitting them on a good run is exactly when it
    would matter most."""
    sheet = build(
        agent="Warden",
        pool="PancakeSwap v3 WBNB/USDT 0.05%",
        journal_path=write_journal(tmp_path, [decision_row() for _ in range(50)]),
        in_range_samples=45,
        in_range_total=50,
        net_positive_windows=40,
        total_windows=60,
    )

    joined = " ".join(sheet.caveats)
    assert "upper bound" in joined, "the LVR caveat (A10) must always appear"
    assert "66%" in joined, "the protocol fee (P-1) must always appear"
    assert sheet.in_range.called


def test_a_fallback_heavy_run_says_so_on_the_card(tmp_path) -> None:
    rows = [decision_row(kappa_is_fallback=1.0, using_onchain_fallback=1.0) for _ in range(40)]
    sheet = build(
        agent="Warden",
        pool="pool",
        journal_path=write_journal(tmp_path, rows),
        in_range_total=40,
        in_range_samples=30,
    )
    joined = " ".join(sheet.caveats)
    assert "fell back to a default" in joined
    assert "CEX price feed was unavailable" in joined


def test_no_replay_means_no_quote_rather_than_a_zero(tmp_path) -> None:
    sheet = build(agent="Warden", pool="pool", journal_path=write_journal(tmp_path, []))
    assert sheet.quote_line == "no replay yet"
    assert not sheet.quote_sufficient


def test_an_insufficient_quote_is_withheld_and_explained(tmp_path) -> None:
    class ThinQuote:
        sufficient = False

        def render(self) -> str:
            return "not enough history to quote (4 usable replays, assumption A5 requires 20)"

    sheet = build(
        agent="Warden",
        pool="pool",
        journal_path=write_journal(tmp_path, [decision_row()]),
        quote=ThinQuote(),
    )
    assert not sheet.quote_sufficient
    assert any("withheld" in c for c in sheet.caveats)


def test_the_rendered_card_reports_the_refusals_plainly(tmp_path) -> None:
    sheet = build(
        agent="Warden",
        pool="PancakeSwap v3 WBNB/USDT 0.05%",
        journal_path=write_journal(tmp_path, [decision_row(R2=0.0) for _ in range(12)]),
        in_range_samples=10,
        in_range_total=12,
    )
    text = sheet.render()
    assert "no verdict" in text
    assert "12 observations, need 30" in text
    assert "held back by" in text and "R2 12" in text
    assert "THINGS THIS NUMBER DOES NOT KNOW" in text

    # The basis, before the number. `docs/TEARSHEET.md` quoted Warden at
    # +36.88% while `warden.json` quoted the same agent on the same pool at
    # -52.18%; both were right, and nothing on either said they were different
    # measurements. A ninety-point contradiction between two of this project's
    # own outputs is worth one line of provenance.
    assert "BASIS" in text
    assert "live journal" in text
    assert "not the published card" in text
    assert text.index("BASIS") < text.index("QUOTE"), "the basis has to arrive first"


def test_the_artifact_is_json_the_web_app_can_read_without_python(tmp_path) -> None:
    """The Next.js app reads precomputed artifacts, so the site stays statically
    deployable even when every backend process is down — the state a demo is
    most likely to find them in."""
    sheet = build(
        agent="Warden",
        pool="pool",
        journal_path=write_journal(tmp_path, [decision_row() for _ in range(40)]),
        in_range_samples=35,
        in_range_total=40,
    )
    path = write_artifact(sheet, tmp_path / "artifacts" / "warden.json")
    loaded = json.loads(path.read_text())

    assert loaded["agent"] == "Warden"
    assert loaded["verdicts"]["in_range"]["called"] is True
    assert loaded["caveats"]
    assert loaded["provenance"]["every_number_derived"] is True
    assert loaded["activity"]["decisions"] == 40


def test_every_number_on_the_card_comes_from_the_journal(tmp_path) -> None:
    """`Readme.md`'s definition of done: regenerating changes a number only if
    the underlying evidence changed."""
    rows = [decision_row(action="rebalance", ts=1_700_000_000 + i * 60) for i in range(7)]
    rows += [decision_row(ts=1_700_000_000 + i * 60) for i in range(7, 50)]
    path = write_journal(tmp_path, rows)

    first = build(agent="W", pool="p", journal_path=path).to_dict()
    second = build(agent="W", pool="p", journal_path=path).to_dict()
    assert first == second, "the same journal must produce the same card"
    assert first["activity"]["rebalances"] == 7


# --- one decision, one count ------------------------------------------------


def _journal(tmp_path, rows):
    path = tmp_path / "warden.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def test_a_decision_journalled_twice_is_counted_once(tmp_path) -> None:
    """The first real journal this project produced showed one mint as "3 mint".

    The loop journals a decision when it is made and **again** when it is
    executed, and the entrypoint writes a third row recording that nothing was
    broadcast. All three carry `action: "mint"`. Counting rows instead of
    decisions put the failure this product is named after onto its own card.
    """
    path = _journal(
        tmp_path,
        [
            {"event": "run_start", "pool": "0xabc"},
            {
                "ts": 100,
                "action": "mint",
                "lower": -64220,
                "upper": -64140,
                "note": "",
                "reasons": {},
            },
            {"event": "action_not_broadcast", "action": "mint", "at_ts": 100},
            {
                "ts": 100,
                "action": "mint",
                "lower": -64220,
                "upper": -64140,
                "note": "executed",
                "reasons": {},
            },
            {"ts": 105, "action": "hold", "note": "", "reasons": {"R1": 0.0}},
        ],
    )
    summary = read_journal(path)

    assert summary.mints == 1, "one mint, journalled three times, must count once"
    assert summary.decisions == 2  # the mint and the hold
    assert summary.executed == 1
    assert summary.rows == 5, "every line is still accounted for"


def test_execution_outcomes_are_reported_rather_than_discarded(tmp_path) -> None:
    """A decision dropped as stale or refused by the daily cap still happened.
    Keeping it out of the action counts must not mean losing it."""
    path = _journal(
        tmp_path,
        [
            {"ts": 1, "action": "recenter", "note": "", "reasons": {}},
            {"ts": 1, "action": "recenter", "note": "stale by 40s, dropped", "reasons": {}},
            {"ts": 2, "action": "recenter", "note": "", "reasons": {}},
            {"ts": 2, "action": "recenter", "note": "failed: nonce too low", "reasons": {}},
            {"ts": 3, "action": "recenter", "note": "", "reasons": {}},
            {"ts": 3, "action": "recenter", "note": "daily action cap reached", "reasons": {}},
        ],
    )
    summary = read_journal(path)

    assert summary.decisions == 3
    assert summary.dropped == 2, "stale and cap-refused"
    assert summary.failed == 1
    assert summary.executed == 0


def test_lifecycle_rows_are_not_decisions(tmp_path) -> None:
    """`run_start`, `run_end` and `action_not_broadcast` describe the run, not a
    decision — and one of them carries an `action` field."""
    path = _journal(
        tmp_path,
        [
            {"event": "run_start", "can_sign": False},
            {"event": "action_not_broadcast", "action": "pull", "at_ts": 7},
            {"event": "kill_switch", "path": "ops/KILL"},
            {"event": "run_end", "decisions": 1},
        ],
    )
    summary = read_journal(path)

    assert summary.decisions == 0
    assert summary.pulls == 0, "a lifecycle row counted as a pull"
    assert summary.rows == 4
