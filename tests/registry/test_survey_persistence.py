"""A build may not destroy a measurement it did not take.

`make registry` ran `scripts/registry_report.py` with no `--sample`, and the
flag defaults to 0, which the script reads as *"survey not requested"* and
returns `surveyed: false` for. So `make artifacts` did not merely skip the
survey — it **overwrote a real one with a refusal**, taking every third-party
listing with it. The survey that existed did so only because somebody ran the
script by hand.

The fix is the split `make vet` / `make vetting` already uses: the chain read is
occasional and writes to disk, the publish is cheap and reads from disk. These
assert the property that split exists for.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def report():
    spec = importlib.util.spec_from_file_location(
        "misquote_registry_report", REPO / "scripts" / "registry_report.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_recorded_survey_is_republished_without_a_chain(report, tmp_path) -> None:
    """The property the whole split exists for."""
    path = tmp_path / "registry_survey.json"
    path.write_text(
        json.dumps(
            {
                "surveyed": True,
                "sampled": 400,
                "population": 272_322,
                "substantive": 120,
                "agents": [{"agent_id": 1, "name": "x"}],
            }
        )
    )

    identity = report.read_survey(path)

    assert identity["surveyed"] is True
    assert identity["sampled"] == 400
    assert identity["agents"], "the listings must survive a republish"
    # The static half is merged in rather than recorded twice.
    assert identity["identity_registry"], "registry addresses come from the module"


def test_no_recorded_survey_is_a_refusal_that_says_what_to_run(report, tmp_path) -> None:
    """Absence is still `surveyed: false` with a reason — that branch was always
    right, and `/registry` renders it. It was the precondition that was wrong."""
    identity = report.read_survey(tmp_path / "nothing.json")

    assert identity["surveyed"] is False
    assert "registry-survey" in identity["reason"], "a refusal should name its remedy"


def test_an_unreadable_record_does_not_masquerade_as_an_empty_registry(report, tmp_path) -> None:
    """A corrupt file and a registry with nothing in it are different facts."""
    path = tmp_path / "registry_survey.json"
    path.write_text("{ not json")

    identity = report.read_survey(path)
    assert identity["surveyed"] is False
    assert "unreadable" in identity["reason"]


def test_republishing_cannot_turn_a_survey_into_a_refusal(report, tmp_path) -> None:
    """The exact regression `make artifacts` used to cause, asserted directly.

    Republishing is idempotent: whatever was recorded is what comes back, however
    many times the artifact is rebuilt.
    """
    path = tmp_path / "registry_survey.json"
    path.write_text(json.dumps({"surveyed": True, "sampled": 400, "substantive": 120}))

    first = report.read_survey(path)
    second = report.read_survey(path)

    assert first["surveyed"] is True
    assert second["surveyed"] is True
    assert first == second


def test_the_default_mode_reads_no_chain(report) -> None:
    """`make artifacts` must not need an RPC. The reading is a separate command.

    Asserted on the source rather than by running it, because the failure this
    guards against is a future edit putting a chain read back into the publish
    path — which would pass any test that mocks the chain.
    """
    source = (REPO / "scripts" / "registry_report.py").read_text()
    publish = source[source.index("def read_survey(") : source.index("def survey_chain(")]

    for forbidden in ("_connect(", "IdentityRegistry(", "highest_agent_id("):
        assert forbidden not in publish, (
            f"the republish path calls {forbidden} — it must read disk, not chain"
        )
