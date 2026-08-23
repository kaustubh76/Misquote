"""Search over the sample, lookup over the population, and the gap stated.

The registry is ~280,000 ids and the survey is 400 of them. Everything worth
testing here is about that ratio being visible rather than papered over.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi", reason="the `api` extra is not installed — `uv sync --extra api`")

from fastapi.testclient import TestClient  # noqa: E402

from misquote.api import registry as registry_routes  # noqa: E402
from misquote.api import service as api  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


@pytest.fixture
def survey_present() -> None:
    if not registry_routes.SURVEY.exists():
        pytest.skip("no registry survey on disk; run `make registry-survey`")


def _registry_report() -> Any:
    """`scripts/registry_report.py`, loaded by path.

    The same mechanism `tests/web/test_artifact_projections.py` uses. `scripts/`
    is not an importable package and `packages/misquote/api` deliberately does
    not depend on it — a driver reaching into a build tool — so the coupling is
    asserted here instead of imported there.
    """
    spec = importlib.util.spec_from_file_location(
        "registry_report_probe", REPO / "scripts" / "registry_report.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_live_card_keys_stay_a_subset_of_the_published_ones() -> None:
    """The one assertion holding the two whitelists together.

    `tests/web/test_third_party_listings.py` forbids any performance-shaped key
    — apr, rating, score, users, tvl — on an agent whose policy we cannot
    replay. It reads `registry.json`, so it cannot see this endpoint at all. If
    `LIVE_CARD_KEYS` drifted outside `LISTING_KEYS`, a live lookup could publish
    a field the artifact is forbidden and nothing would notice.
    """
    published = _registry_report().LISTING_KEYS
    extra = set(registry_routes.LIVE_CARD_KEYS) - set(published)
    assert not extra, (
        f"the live lookup would publish {sorted(extra)}, which registry.json may not carry. "
        "Add them to LISTING_KEYS and render them, or stop serving them here."
    )


def test_every_list_response_states_what_fraction_it_searched(
    client: TestClient, survey_present: None
) -> None:
    """Coverage in the body, not in documentation.

    A caller who never asks about coverage is exactly the caller who most needs
    telling that "search" reached 0.14% of the registry.
    """
    body = client.get("/registry/agents").json()
    coverage = body["coverage"]

    assert coverage["sampled"] < coverage["population"], "the survey is meant to be a sample"
    assert coverage["complete"] is False
    assert 0 < coverage["share_of_population"] < 1
    assert coverage["sampled_at_block"], "a sample without a block is not reproducible"
    assert coverage["seed"] is not None, "a sample without a seed is not reproducible"


def test_search_narrows_and_says_by_how_much(client: TestClient, survey_present: None) -> None:
    everything = client.get("/registry/agents", params={"per_page": 1}).json()
    assert everything["total_matching"] > 0

    nothing = client.get("/registry/agents", params={"q": "zzz-no-agent-is-called-this-zzz"}).json()
    assert nothing["total_matching"] == 0
    assert nothing["agents"] == []
    # An empty result still reports the coverage it searched — otherwise "no
    # matches" is indistinguishable from "nothing was searched".
    assert nothing["coverage"]["searched"] == everything["coverage"]["searched"]


def test_paging_partitions_the_matches(client: TestClient, survey_present: None) -> None:
    first = client.get("/registry/agents", params={"per_page": 5, "page": 1}).json()
    second = client.get("/registry/agents", params={"per_page": 5, "page": 2}).json()

    if first["total_matching"] <= 5:
        pytest.skip("survey too small to page")

    ids = [a["agent_id"] for a in first["agents"]]
    assert len(ids) == 5
    assert not set(ids) & {a["agent_id"] for a in second["agents"]}, "pages overlap"


def test_filters_are_applied_rather_than_accepted(client: TestClient, survey_present: None) -> None:
    body = client.get("/registry/agents", params={"substantive": True, "per_page": 200}).json()
    assert all(a["substantive"] for a in body["agents"])

    with_endpoint = client.get(
        "/registry/agents", params={"has_endpoint": True, "per_page": 200}
    ).json()
    assert all(a["endpoints"] for a in with_endpoint["agents"])


def test_a_sampled_agent_says_it_came_from_the_snapshot(
    client: TestClient, survey_present: None
) -> None:
    """The survey and the chain can disagree — a card is mutable."""
    listed = client.get("/registry/agents", params={"per_page": 1}).json()["agents"]
    if not listed:
        pytest.skip("empty survey")

    body = client.get(f"/registry/agents/{listed[0]['agent_id']}").json()
    assert body["source"] == "survey"
    assert body["sampled_at_block"]
    assert "mutable" in body["note"]


def test_an_unsampled_id_refuses_when_there_is_no_endpoint(
    client: TestClient, survey_present: None
) -> None:
    """`conftest` points every RPC at a blackhole, which is the interesting case.

    The refusal must say the *capability* is missing, not that the agent is —
    a 404 here would tell a reader an agent does not exist when the truth is
    that nothing was asked.
    """
    response = client.get("/registry/agents/999999999")
    assert response.status_code == 503

    detail = response.json()["detail"]
    assert detail["remedy"] == "set BSC_RPC_URL"
    # The wording is `rpc.connect`'s, shared by every route that reaches the
    # chain, so it says "result" rather than "agent". The distinction it draws
    # is the one that matters: nothing was asked, so nothing is absent but the
    # ability to ask.
    assert "absent capability, not an absent result" in detail["note"]
