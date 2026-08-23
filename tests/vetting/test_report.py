"""The badge emitter republishes what is on disk, and says so when nothing is.

`vetting/read.py` reads chain and writes `vetting/badges/<pool>.json`.
`scripts/vetting_report.py` carries those to the site. The split matters: the
emitter touches no network, which is why it can sit inside `make artifacts`
without an RPC, and why every pool it publishes carries the age of its own
reading instead of a freshness verdict this module would have had to invent.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "misquote_vetting_report", REPO / "scripts" / "vetting_report.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


report = _load()


def write_badge(directory: Path, address: str, **overrides) -> Path:
    badge = {
        "chain_id": 56,
        "pool": address,
        "label": "A pool",
        "verdict": "PASS",
        "safe_to_provide": True,
        "checks": [
            {
                "name": "factory resolves it",
                "status": "PASS",
                "detail": "getPool() agrees",
                "provenance": "P-6",
            }
        ],
        **overrides,
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{address.lower()}.json"
    path.write_text(json.dumps(badge))
    return path


def test_an_empty_directory_degrades_rather_than_reporting_zero(tmp_path: Path) -> None:
    """ "Nothing was checked" and "nothing failed" are different sentences.

    A `{"pools": 0}` with `surveyed: true` reads as a clean bill of health from a
    survey that never happened.
    """
    out = report.survey(56, tmp_path / "absent")

    assert out["surveyed"] is False
    assert "make vet" in out["reason"]
    assert out["pools"] == []


def test_a_listed_pool_with_no_badge_is_named_rather_than_omitted(tmp_path: Path) -> None:
    """An absent row and a clean row look identical once rendered."""
    write_badge(tmp_path, "0x36696169C63e42cd08ce11f5deeBbCeBae652050")
    out = report.survey(56, tmp_path)

    unbadged = [p for p in out["pools"] if not p["badged"]]
    assert unbadged, "every listed pool was badged; this fixture badges only one"
    for pool in unbadged:
        assert pool["label"], "an unbadged pool must still be named"
        assert "no badge" in pool["reason"]


def test_a_badge_for_an_unlisted_pool_is_still_published(tmp_path: Path) -> None:
    """Evidence does not stop being evidence when the registry moves on."""
    write_badge(tmp_path, "0x000000000000000000000000000000000000dEaD", label="Retired pool")
    out = report.survey(56, tmp_path)

    orphans = [p for p in out["pools"] if p.get("listed") is False]
    assert len(orphans) == 1
    assert orphans[0]["badged"] is True


def test_every_field_the_badge_writes_survives(tmp_path: Path) -> None:
    """The emitter may add, never drop.

    `badge.py` growing a field that this silently discards would put the page a
    revision behind the reading it claims to show.
    """
    write_badge(tmp_path, "0x36696169C63e42cd08ce11f5deeBbCeBae652050")
    original = json.loads(
        (tmp_path / "0x36696169c63e42cd08ce11f5deebbcebae652050.json").read_text()
    )

    published = next(p for p in report.survey(56, tmp_path)["pools"] if p.get("verdict") == "PASS")
    for key, value in original.items():
        assert published[key] == value, f"{key} did not survive republication"


def test_an_unknown_check_is_counted_and_never_cleared(tmp_path: Path) -> None:
    """`badge.py` treats UNKNOWN as blocking; the summary must agree."""
    write_badge(
        tmp_path,
        "0x36696169C63e42cd08ce11f5deeBbCeBae652050",
        verdict="UNKNOWN",
        safe_to_provide=False,
        checks=[
            {
                "name": "protocol fee read",
                "status": "UNKNOWN",
                "detail": "the node did not answer",
                "provenance": "P-1",
            }
        ],
    )
    summary = report.survey(56, tmp_path)["summary"]

    assert summary["unknown_checks"] == 1
    assert summary["cleared"] == 0
    assert summary["blocked"] == 1
    assert summary["worst"] == "UNKNOWN"


def test_the_age_of_each_reading_is_published(tmp_path: Path) -> None:
    write_badge(tmp_path, "0x36696169C63e42cd08ce11f5deeBbCeBae652050")
    pool = next(p for p in report.survey(56, tmp_path)["pools"] if p["badged"])

    assert "read_at" in pool and "age_hours" in pool
    assert pool["age_hours"] >= 0


def test_a_half_written_badge_reports_as_unbadged(tmp_path: Path) -> None:
    """Malformed JSON must not become a pass, and must not raise."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "0xdeadbeef.json").write_text("{ not json")

    out = report.survey(56, tmp_path)
    assert out["surveyed"] is False


def test_the_emitter_reads_no_chain() -> None:
    """The separation that lets this run inside `make artifacts` with no RPC."""
    source = (REPO / "scripts" / "vetting_report.py").read_text()
    for forbidden in ("web3", "Web3", "misquote.vetting.read", "HTTPProvider"):
        assert forbidden not in source, f"the emitter reaches for {forbidden}"


@pytest.mark.parametrize("chain", [56, 97])
def test_listed_pools_are_all_on_the_chain_asked_for(chain: int) -> None:
    for address, label in report.listed_pools(chain):
        assert address == address.lower()
        assert label


# --- the pool list must not fork again ---------------------------------------


def test_the_vetting_layer_lists_every_verified_pool_on_the_chain() -> None:
    """One derived list, because four hand-maintained ones diverged.

    `recorded_for`, `_known_pools`, `vetting_report.listed_pools` and
    `venue_report` each grew their own answer to "the pools we care about on
    this chain", and `TARGET_POOL_WIDE` was in none of them — so the advantage
    report's third task quoted on a pool the vetting layer had never heard of,
    while the README promises a badge for every pool a listed agent touches.

    Asserted against `known_pools_on` rather than a literal: a test that repeats
    the list is a fifth copy of the thing that broke.
    """
    from misquote.chain.addresses import known_pools_on
    from misquote.vetting.read import _known_pools

    for chain_id in (56, 97):
        assert [p.address for p in _known_pools(chain_id)] == [
            p.address for p in known_pools_on(chain_id)
        ], f"the vetting entrypoint's pool list has forked from KNOWN_POOLS on chain {chain_id}"


def test_every_listed_pool_can_have_its_recorded_values_compared() -> None:
    """`recorded_for` returning None silently drops the repo-versus-chain check.

    It does not fail — the badge simply stops comparing what we recorded against
    what the pool says, for exactly the pool whose `fee_protocol` differs from
    the flagship's. That is the comparison P-8 exists because of.
    """
    from misquote.chain.addresses import known_pools_on
    from misquote.vetting.read import recorded_for

    for pool in known_pools_on(56):
        recorded = recorded_for(pool.address)
        assert recorded is not None, f"{pool.label} has no recorded values to compare"
        assert recorded["fee_protocol"] == pool.fee_protocol
        assert recorded["tick_spacing"] == pool.tick_spacing
