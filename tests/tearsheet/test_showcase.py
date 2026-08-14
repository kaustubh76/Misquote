"""Showcase Mode, and the badge that must never come off.

Matrix item D-2: this project's wallet has a real BSC trading record containing
no liquidity positions at all, so a "here is what I earned" card would be a
fabrication. What Showcase Mode produces is a replay — and the difference has to
be visible on the artifact, not buried in a footnote.

So the badge is a field, asserted here, rather than a sentence someone remembers
to render.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from showcase import (  # noqa: E402
    COUNTERFACTUAL_BADGE,
    COUNTERFACTUAL_NOTE,
    emit,
    run_agent,
    synthetic_events,
)


@pytest.fixture(scope="module")
def replayed():
    events = synthetic_events(400)
    return run_agent("Warden", events, capital=1000.0)


def test_the_artifact_is_badged_counterfactual(replayed, tmp_path) -> None:
    """A replay presented as a record is precisely the failure this project is
    named after, so the badge is structural rather than editorial."""
    path = emit(replayed, tmp_path, tmp_path / "artifacts", source="synthetic")
    payload = json.loads(path.read_text())

    assert payload["counterfactual"] is True
    assert payload["badge"] == COUNTERFACTUAL_BADGE
    assert "not held" in payload["badge"]
    assert any(COUNTERFACTUAL_NOTE in caveat for caveat in payload["caveats"])


def test_a_synthetic_tape_is_labelled_as_one(replayed, tmp_path) -> None:
    """A card built from generated data must never be mistakable for one built
    from chain data. `source` says which, on the artifact itself."""
    synthetic = json.loads(emit(replayed, tmp_path, tmp_path / "a", source="synthetic").read_text())
    from_chain = json.loads(emit(replayed, tmp_path, tmp_path / "b", source="chain").read_text())

    assert synthetic["source"] == "synthetic"
    assert from_chain["source"] == "chain"


def test_the_artifact_carries_the_replay_numbers_it_claims(replayed, tmp_path) -> None:
    payload = json.loads(
        emit(replayed, tmp_path, tmp_path / "artifacts", source="synthetic").read_text()
    )
    replay = payload["replay"]

    assert replay["samples"] > 0
    assert replay["mints"] >= 1
    assert replay["lvr_quote_upper_bound"] >= 0
    assert replay["net_quote"] == pytest.approx(
        replay["fees_quote"] - replay["lvr_quote_upper_bound"] - replay["costs_quote"], abs=1e-6
    )


def test_adverse_selection_is_named_as_an_upper_bound_in_the_artifact(replayed, tmp_path) -> None:
    """`lvr_quote` would be a claim the measure cannot support. The field name
    itself carries assumption A10."""
    payload = json.loads(
        emit(replayed, tmp_path, tmp_path / "artifacts", source="synthetic").read_text()
    )
    assert "lvr_quote_upper_bound" in payload["replay"]
    assert "lvr_quote" not in payload["replay"]


def test_the_artifact_is_plain_json_with_no_python_needed(replayed, tmp_path) -> None:
    """The web app reads these files directly, so the site survives every backend
    process being down — which is the state a demo is most likely to find them."""
    path = emit(replayed, tmp_path, tmp_path / "artifacts", source="synthetic")
    reparsed = json.loads(path.read_text())
    assert json.loads(json.dumps(reparsed)) == reparsed


def test_two_agents_produce_two_separate_artifacts(tmp_path) -> None:
    from misquote.agents.grid.policy import GridParams, decide_grid

    events = synthetic_events(300)
    warden = run_agent("Warden", events, capital=1000.0)
    grid = run_agent(
        "Grid",
        events,
        policy=lambda obs, params, meta: decide_grid(obs, GridParams(), meta),
        capital=1000.0,
    )

    out = tmp_path / "artifacts"
    warden_path = emit(warden, tmp_path, out, source="synthetic")
    grid_path = emit(grid, tmp_path, out, source="synthetic")

    assert warden_path.name == "warden.json"
    assert grid_path.name == "grid.json"
    assert json.loads(warden_path.read_text())["agent"] == "Warden"
    assert json.loads(grid_path.read_text())["agent"] == "Grid"
