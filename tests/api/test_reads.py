"""The live read routes: what the tape holds, and what the agents did.

These are the two questions a static host cannot answer, so they are the two
worth testing against real behaviour rather than a shape. The emphasis
throughout is the distinction the endpoints exist to preserve: **an absence is
not a zero**. A tape with no recorded coverage does not hold zero blocks, and an
agent with no journal has not made zero decisions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="the `api` extra is not installed — `uv sync --extra api`")

from fastapi.testclient import TestClient  # noqa: E402

from misquote.api import service as api  # noqa: E402
from misquote.api import vetting as vetting_routes  # noqa: E402
from misquote.api.locations import db_path, journal_dir  # noqa: E402
from misquote.chain.addresses import known_pools_on  # noqa: E402
from misquote.indexer.store import connect  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


# ── tape ─────────────────────────────────────────────────────────────────────


def test_no_tape_is_a_retry_not_a_fault(client: TestClient) -> None:
    """503, and it names the command that would create one.

    `_isolate_state` points DB_PATH at a file in tmp_path that nothing has
    created, which is exactly the state of a fresh clone.
    """
    response = client.get("/tape")
    assert response.status_code == 503

    detail = response.json()["detail"]
    assert "make indexer" in detail["remedy"]
    assert "absence" in detail["note"]


def test_an_empty_tape_reports_unknown_coverage_rather_than_zero(client: TestClient) -> None:
    """The distinction the whole endpoint exists for.

    `store.coverage` returns an empty list both for "this database recorded no
    coverage" and for "nothing was ever read". Reporting either as `0 blocks`
    would be a measurement where there is none, so `known` is a separate field
    and is checked before the runs are.
    """
    connect(db_path()).close()

    body = client.get("/tape").json()
    assert body["pools"], "no verified pool on chain 56"

    for pool in body["pools"]:
        assert pool["coverage"]["known"] is False
        assert pool["coverage"]["longest_contiguous"] is None
        assert pool["coverage"]["runs"] == []
        assert pool["summary"]["swaps"] == 0


def test_holes_between_recorded_runs_are_reported(client: TestClient) -> None:
    """Two runs with a gap are two runs and a hole, not one long span."""
    pool = known_pools_on(56)[0].address.lower()
    conn = connect(db_path())
    conn.execute(
        "INSERT INTO covered (pool, from_block, to_block) VALUES (?, ?, ?)", (pool, 100, 199)
    )
    conn.execute(
        "INSERT INTO covered (pool, from_block, to_block) VALUES (?, ?, ?)", (pool, 400, 499)
    )
    conn.close()

    body = client.get(f"/tape/{pool}").json()
    coverage = body["coverage"]

    assert coverage["known"] is True
    assert coverage["holes"] == [{"from_block": 200, "to_block": 399}]
    # The longest contiguous run, not the distance between the extremes. The
    # extremes span 400 blocks; the tape holds two runs of 100.
    assert coverage["longest_contiguous"]["blocks"] == 99


def test_an_unverified_pool_is_refused_with_the_ones_we_did_verify(client: TestClient) -> None:
    """Refusing is the point — an unchecked fee_protocol misprices every swap."""
    connect(db_path()).close()

    response = client.get("/tape/0x000000000000000000000000000000000000dead")
    assert response.status_code == 404

    detail = response.json()["detail"]
    assert detail["available"], "the refusal must name the pools that would work"
    assert "wrongly-denominated" in detail["note"]


# ── journal ──────────────────────────────────────────────────────────────────


def _write(agent: str, rows: list[dict[str, object]], *, trailing: str = "") -> Path:
    path = journal_dir() / f"{agent}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + trailing)
    return path


def test_an_agent_that_never_ran_is_absent_rather_than_empty(client: TestClient) -> None:
    body = client.get("/journal").json()
    assert body["agents"] == []
    assert "has not run" in body["note"]

    response = client.get("/journal/warden")
    assert response.status_code == 404

    detail = response.json()["detail"]
    assert detail["remedy"] == "make warden ENV=testnet"
    assert "empty journal" in detail["note"]


def test_rows_come_back_in_the_order_they_were_appended(client: TestClient) -> None:
    """A decision journal read out of order is a different document."""
    _write("warden", [{"action": "HOLD", "n": i} for i in range(5)])

    body = client.get("/journal/warden").json()
    assert [row["n"] for row in body["rows"]] == [0, 1, 2, 3, 4]
    assert body["total_rows"] == 5
    assert body["returned"] == 5


def test_the_tail_takes_the_newest_rows(client: TestClient) -> None:
    _write("warden", [{"n": i} for i in range(10)])

    body = client.get("/journal/warden", params={"tail": 3}).json()
    assert [row["n"] for row in body["rows"]] == [7, 8, 9]
    assert body["total_rows"] == 10, "the tail must not change the count of what exists"


def test_a_half_written_final_line_is_counted_not_raised(client: TestClient) -> None:
    """The writer appends while this reads.

    A torn last line is the normal state of a file an agent is actively writing,
    and a 500 there would make a healthy agent look broken. It is skipped and
    counted, never silently dropped.
    """
    _write("warden", [{"n": 0}], trailing='{"n": 1')

    body = client.get("/journal/warden").json()
    assert body["total_rows"] == 1
    assert body["unparsed_rows"] == 1


def test_the_summary_is_the_tearsheets_own(client: TestClient) -> None:
    """Not a second count of the same file.

    `read_journal` is what the tearsheet runs; if this endpoint counted actions
    itself there would be two implementations of "how often did it hold", and
    they would disagree.
    """
    # Lowercase, because that is the vocabulary the loop actually journals and
    # `read_journal` dispatches on. Writing "MINT" here would have produced a
    # summary of zero mints from a file containing one, and the test would have
    # been asserting against a journal shape no agent writes.
    _write(
        "warden",
        [
            {"action": "hold", "reasons": {}},
            {"action": "mint", "reasons": {}},
            {"action": "hold", "reasons": {}},
        ],
    )

    summary = client.get("/journal/warden").json()["summary"]
    assert summary["rows"] == 3
    assert summary["decisions"] == 3
    assert summary["mints"] == 1
    assert summary["holds"] == 2


def test_the_gate_counts_survive_serialisation(client: TestClient) -> None:
    """The bug this endpoint shipped with for exactly one smoke test.

    `JournalSummary.gate_blocks` is a `Counter`, and `dataclasses.asdict`
    rebuilds every container it recurses into as `type(obj)(pairs)`. For a
    `Counter` that means `Counter({"R1": 115})` is reconstructed from
    `[("R1", 115)]` — which counts the *pair* as one element and yields
    `{("R1", 115): 1}`. Served as JSON, a gate that blocked 115 times reported
    one block, in the shape of a real answer.

    Three holds blocked by R1 must therefore read as three, not as one.
    """
    _write("warden", [{"action": "hold", "reasons": {"R1": 0.0}} for _ in range(3)])

    gates = client.get("/journal/warden").json()["summary"]["gate_blocks"]
    assert gates == {"R1": 3}, gates


# ── vetting ──────────────────────────────────────────────────────────────────


def test_the_unbadged_known_pools_are_named_rather_than_omitted(client: TestClient) -> None:
    """A list of what we checked reads as completeness. The gap is the finding.

    `go_no_go.py` treats a verified-but-unbadged pool as amber, so the same
    absence has to be reachable here — otherwise the endpoint answers "these
    pools are fine" with a list that silently excludes the ones nobody looked at.
    """
    body = client.get("/vetting").json()

    badged = set(body["badged"])
    known = set(body["known_pools"])
    assert set(body["known_and_unbadged"]) == known - badged
    assert "not a clean bill of health" in body["note"]


def test_a_recorded_badge_is_served_as_recorded(client: TestClient) -> None:
    recorded = vetting_routes.badge_names()
    if not recorded:
        pytest.skip("no badges on disk; run `make vet`")

    address = recorded[0]
    body = client.get(f"/vetting/{address}").json()

    on_disk = json.loads((vetting_routes.BADGES / f"{address}.json").read_text())
    assert body == on_disk, "the badge was altered in transit"


def test_the_address_is_matched_case_insensitively(client: TestClient) -> None:
    """Addresses arrive checksummed from wallets and lowercased from our own files."""
    recorded = vetting_routes.badge_names()
    if not recorded:
        pytest.skip("no badges on disk; run `make vet`")

    assert client.get(f"/vetting/{recorded[0].upper()}").status_code == 200


def test_never_vetted_and_never_verified_are_different_refusals(client: TestClient) -> None:
    """Collapsing them would hide which absence is ours.

    A pool we verified and did not vet is a gap in our own work and says
    `make vet`. An address we never read at all has no badge because nothing
    ever looked at it, and no amount of running `make vet` would change that.
    """
    unverified = client.get("/vetting/0x000000000000000000000000000000000000dead")
    assert unverified.status_code == 404
    assert "nothing has ever looked at it" in unverified.json()["detail"]["note"]
    assert unverified.json()["detail"]["remedy"] != "make vet"
