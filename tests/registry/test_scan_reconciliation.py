"""The emitter-side half: two readings of one quantity, reconciled without being resolved.

`registry/scan8004.py` reads. `scripts/registry_report.py` decides what a pair of
readings may be published as, and those decisions are pure functions over dicts —
so they are testable here with no network and no API key, which is the same
construction `test_scan8004.py` uses and for the same reason.

The defect this file mostly exists for is not a wrong number. It is a **deleted**
one: the census became opt-in when the filtered counts arrived, and a build that
runs without it must carry the recorded walk forward rather than overwrite it
with a refusal. `read_survey`'s docstring names that failure in the sentence this
file borrows — *a build that deletes a measurement is worse than one that never
takes it* — and it had already happened once, to the chain survey, before anyone
noticed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Imported by path because `scripts/` is not a package. Same approach as
# `tests/web/test_third_party_listings.py`.
_spec = importlib.util.spec_from_file_location(
    "registry_report", REPO / "scripts" / "registry_report.py"
)
assert _spec and _spec.loader
registry_report = importlib.util.module_from_spec(_spec)
sys.modules["registry_report"] = registry_report
_spec.loader.exec_module(registry_report)


WALKED = {
    "available": True,
    "read_at": "2026-08-26T11:00:00+00:00",
    "counted": 278_500,
    "x402_supported": 66_562,
    "with_feedback": 510,
    "feedbacks_claimed": 11_681,
}

ASKED = {
    "available": True,
    "read_at": "2026-08-27T11:00:00+00:00",
    "baseline": 284_996,
    "filters": {
        "x402_supported": {"applied": True, "total": 66_517},
        "with_feedback": {"applied": True, "total": 436},
    },
}


def test_two_readings_of_one_share_carry_two_denominators() -> None:
    """278,500 and 284,996 are not the same population, and neither is wrong.

    The walk counted every row it saw; the ask was answered against the registry
    as it stood a day later. A single share computed across the two would be a
    third number nobody measured — so each count travels with the population it
    was actually taken from, and the hours between them travel too, because that
    is the fact deciding whether a gap is a finding or is growth.
    """
    result = registry_report._counts_cross_check(WALKED, ASKED)

    assert result["available"] is True
    assert result["hours_apart"] == 24.0

    x402 = next(r for r in result["rows"] if r["quantity"] == "x402_supported")
    assert x402["walked_of"] == 278_500
    assert x402["asked_of"] == 284_996
    assert x402["walked_of"] != x402["asked_of"]
    assert x402["agree"] is False
    assert x402["difference"] == 45


def test_a_disagreement_is_reported_rather_than_resolved() -> None:
    """Both numbers survive. Neither is chosen.

    One index, two routes to one quantity, and no reason for them to differ — so
    a difference is the index disagreeing with itself. Picking the larger, or
    averaging them, would be the misquote this project is named after.
    """
    result = registry_report._counts_cross_check(WALKED, ASKED)
    feedback = next(r for r in result["rows"] if r["quantity"] == "with_feedback")

    assert (feedback["walked"], feedback["asked"]) == (510, 436)
    assert feedback["agree"] is False
    assert "not resolved" in result["note"]


def test_a_filter_that_could_not_be_proven_is_not_a_disagreement() -> None:
    """Declining to read a quantity and reading it differently are different facts.

    A refused filter has no number, so a row claiming the census and the ask
    disagree about it would be inventing the second half of a comparison. It is
    recorded as `compared: false` with the refusal's own reason instead.
    """
    refused = {
        **ASKED,
        "filters": {
            **ASKED["filters"],
            "with_feedback": {"applied": False, "reason": "returned the whole population"},
        },
    }
    row = next(
        r
        for r in registry_report._counts_cross_check(WALKED, refused)["rows"]
        if r["quantity"] == "with_feedback"
    )

    assert row["compared"] is False
    assert "agree" not in row
    assert "asked" not in row
    assert row["reason"] == "returned the whole population"


def test_readings_that_did_not_stamp_themselves_report_no_interval() -> None:
    """None, not zero.

    Zero hours apart is a claim that two readings were simultaneous. A census
    recorded before `read_at` existed has said nothing about when it was taken,
    and the difference between "at the same moment" and "we do not know" is the
    whole value of publishing the interval.
    """
    assert registry_report._hours_between(None, "2026-08-27T11:00:00+00:00") is None
    assert registry_report._hours_between("not a timestamp", "2026-08-27T11:00:00+00:00") is None
    assert (
        registry_report._counts_cross_check({**WALKED, "read_at": None}, ASKED)["hours_apart"]
        is None
    )


def test_a_scan_without_a_census_carries_the_recorded_one_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect that had already happened once, held one file over.

    `make registry-scan` no longer walks the chain, so every fast run reaches the
    branch that decides what `census` is. If that branch writes a refusal, one
    three-minute build silently destroys a two-hour reading and takes six figures
    with it that no filter can answer.

    Carried forward **and** stamped: a census republished without a flag is a
    number claiming to be current.
    """
    from misquote.registry import scan8004

    monkeypatch.setenv("SCAN8004_API_KEY", "a-key")
    monkeypatch.setattr(
        scan8004, "population", lambda *a, **k: {"available": True, "population": 1}
    )
    monkeypatch.setattr(scan8004, "stats", lambda *a, **k: {"available": False})
    monkeypatch.setattr(scan8004, "counts", lambda *a, **k: {"available": False})
    monkeypatch.setattr(scan8004, "feedback_reach", lambda *a, **k: {"available": False})
    monkeypatch.setattr(scan8004, "census", lambda *a, **k: pytest.fail("no census was requested"))

    recorded = {"census": {"available": True, "counted": 278_500, "complete": True}}
    payload = registry_report.fetch_scan(census=False, previous=recorded)

    assert payload["census"]["counted"] == 278_500
    assert payload["census"]["carried_forward"] is True


def test_a_scan_with_no_census_on_record_refuses_rather_than_inventing_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And the refusal names the command that would fix it.

    Nothing is carried forward when nothing was recorded, and the keyed tier must
    not fall back to the hundred-row sample either — a share of 100 published
    beside `counts`' share of 284,996 is the comparison the census/sample
    exclusion has always existed to prevent, wearing a new name.
    """
    from misquote.registry import scan8004

    monkeypatch.setenv("SCAN8004_API_KEY", "a-key")
    monkeypatch.setattr(
        scan8004, "population", lambda *a, **k: {"available": True, "population": 1}
    )
    monkeypatch.setattr(scan8004, "stats", lambda *a, **k: {"available": False})
    monkeypatch.setattr(scan8004, "counts", lambda *a, **k: {"available": False})
    monkeypatch.setattr(scan8004, "feedback_reach", lambda *a, **k: {"available": False})
    monkeypatch.setattr(
        scan8004, "sample", lambda *a, **k: pytest.fail("no sample on the keyed tier")
    )

    payload = registry_report.fetch_scan(census=False, previous={})

    assert payload["census"]["available"] is False
    assert "registry-census" in payload["census"]["reason"]
    assert "sample" not in payload


INDEXED = {
    "available": True,
    "chain_id": 97,
    "owner": "0x0c501ee1924bfb91a028db4bcd68f4861b0ff6ee",
    "indexed_contract": "0x8004a818bfb912233c491871b3d84c89a494bd9e",
    "agents": [
        {
            "token_id": "1927",
            "name": "Warden",
            "owner_address": "0x0c501ee1924bfb91a028db4bcd68f4861b0ff6ee",
            "scan_total_feedbacks": 0,
            "scan_total_score": 0.0,
            "supported_protocols": [],
        }
    ],
}

RECORDED = {
    "owner": "0x0c501EE1924bfb91a028DB4BcD68f4861B0Ff6eE",
    "agents": [{"agent_id": 1927, "name": "Warden"}],
}


def test_our_own_rows_are_checked_field_by_field_against_the_record() -> None:
    """The one block on this page that could previously not be contradicted.

    Everything in `ours` is self-reported: we ran the registration, it wrote the
    file, the page renders the file. This reads the same four agents back from an
    index we do not run, so the claim becomes falsifiable — which is the only
    kind of claim this project is willing to make about anybody else.
    """
    result = registry_report._ours_cross_check(INDEXED, RECORDED)

    assert result["matched"] == 1
    assert result["same_contract"] is True
    assert result["disagreements"] == []
    assert {a["field"] for a in result["agreements"]} == {"name", "owner_address"}


def test_an_honest_negative_is_published_rather_than_dropped() -> None:
    """Zero feedbacks, zero score, no declared protocol — all three shipped.

    The survey holds 285,000 strangers to `assess()`. Ours are held to the same
    bar by the same index, and they fail parts of it. A block that published the
    agreements and quietly omitted the empty fields would be the misquote with
    our own name on it.
    """
    negatives = registry_report._ours_cross_check(INDEXED, RECORDED)["honest_negatives"]

    assert {n["field"] for n in negatives} == {
        "scan_total_feedbacks",
        "scan_total_score",
        "supported_protocols",
    }
    assert all(n["note"] for n in negatives)
    protocols = next(n for n in negatives if n["field"] == "supported_protocols")
    assert "not an indexing error" in protocols["note"].lower()


def test_an_agent_only_one_side_knows_about_is_a_finding_in_both_directions() -> None:
    """Neither is an error, and they mean opposite things.

    `recorded_only` is us claiming a registration the index has never seen.
    `indexed_only` is the index holding an agent for our owner that our own
    record does not mention. A single "mismatch" count would collapse two
    different problems into one number.
    """
    result = registry_report._ours_cross_check(
        {**INDEXED, "agents": [*INDEXED["agents"], {"token_id": "9999", "name": "Stranger"}]},
        {**RECORDED, "agents": [*RECORDED["agents"], {"agent_id": 1928, "name": "Grid"}]},
    )

    assert result["recorded_only"] == ["1928"]
    assert result["indexed_only"] == ["9999"]


def test_a_contract_mismatch_is_reported_rather_than_compared_through() -> None:
    """If the two are reading different registries the comparison is meaningless.

    `population()` already makes this check for the same reason — two counts of
    two different contracts are not a disagreement about anything.
    """
    result = registry_report._ours_cross_check(
        {**INDEXED, "indexed_contract": "0xdeadbeef"}, RECORDED
    )

    assert result["same_contract"] is False
