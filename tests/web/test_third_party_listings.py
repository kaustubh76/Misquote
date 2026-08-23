"""A third-party listing may never carry a performance number.

Our four agents' cards are live mini-tearsheets: a P25-P75 range replayed from
thirty days of real chain history, with the assumption sheet one click away. A
third-party agent registered in ERC-8004 gets no such number and cannot — we do
not have its policy, so there is nothing to replay.

Every other marketplace fills that gap with a star rating, an install count or a
claimed APR. Filling it here would be the misquote the project is named after,
committed on our own surface.

Asserted against the **artifact** rather than the rendering, so it holds however
the page is rewritten, and against a whitelist rather than a blocklist, so a
field nobody thought of is refused by default.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ARTIFACT = REPO / "apps" / "web" / "public" / "artifacts" / "registry.json"

#: Anything that would read as "how well does this agent perform".
PERFORMANCE_SHAPED = (
    "p25",
    "p50",
    "p75",
    "apr",
    "return",
    "yield",
    "profit",
    "pnl",
    "sharpe",
    "rating",
    "stars",
    "score",
    "rank",
    "users",
    "installs",
    "tvl",
    "volume",
    "quote",
    "performance",
    "in_range",
    "fees",
)


@pytest.fixture(scope="module")
def listings() -> list[dict]:
    if not ARTIFACT.exists():
        pytest.skip("registry.json has not been generated")
    identity = json.loads(ARTIFACT.read_text()).get("identity", {})
    if not identity.get("surveyed"):
        pytest.skip("the registry was not surveyed, so there are no listings")
    return identity.get("agents", [])


def test_no_listing_carries_a_performance_field(listings) -> None:
    """The whole point. A listing describes a registration, never a result."""
    for agent in listings:
        for key in agent:
            lowered = key.lower()
            assert not any(word in lowered for word in PERFORMANCE_SHAPED), (
                f"agent {agent.get('agent_id')} carries {key!r}, which reads as a "
                "performance claim about an agent whose policy we cannot replay"
            )


def test_listings_carry_only_whitelisted_keys(listings) -> None:
    """A blocklist protects against the fields we thought of. The emitter has a
    whitelist so a new field has to be added deliberately, in both places."""
    import sys

    sys.path.insert(0, str(REPO / "scripts"))
    from registry_report import LISTING_KEYS  # noqa: PLC0415

    for agent in listings:
        unexpected = set(agent) - LISTING_KEYS
        assert not unexpected, f"agent {agent.get('agent_id')} carries {unexpected}"


def test_a_listing_says_whether_we_could_read_it_at_all(listings) -> None:
    """`resolvable` is what separates "this agent claims X" from "this agent's
    card 404s". Both are honest; conflating them is not."""
    for agent in listings:
        assert isinstance(agent.get("resolvable"), bool)
        assert isinstance(agent.get("substantive"), bool)
        if not agent["resolvable"]:
            assert not agent["substantive"], "an unreadable card cannot be substantive"


def test_the_sample_spans_the_population_rather_than_its_oldest_ids(listings) -> None:
    """A sample of ids 1..800 out of 272,145 describes the registry's oldest
    0.3% while reporting a share as though it were about the whole thing."""
    identity = json.loads(ARTIFACT.read_text())["identity"]
    population, ids = identity["population"], identity["sampled_ids"]

    assert population > 0
    assert max(ids) > population // 2, (
        f"the highest sampled id is {max(ids):,} of a population of {population:,} — "
        "this sample is drawn from the front of the registry, not across it"
    )


def test_the_card_count_is_not_the_sample_size(listings) -> None:
    """Both numbers are published, because they are different facts.

    The shares are computed from the whole sample; the cards are illustrative
    and bounded, because 400 of them is 226KB of artifact for a page that
    fetches it client-side. A reader who counted the cards and took that for the
    sample size would be reading a claim nobody made — so the artifact carries
    `sampled` and `listings_shown` separately.
    """
    import json

    identity = json.loads(ARTIFACT.read_text())["identity"]
    sampled = identity.get("sampled", 0)
    shown = identity.get("listings_shown", len(listings))

    assert shown == len(listings)
    assert sampled >= shown, "more cards than sampled agents is incoherent"
    if sampled > shown:
        assert identity.get("substantive", 0) <= sampled
        assert identity["substantive_share"] == pytest.approx(identity["substantive"] / sampled), (
            "the share must come from the sample, not from the published cards"
        )


def test_the_published_cards_span_the_sample(listings) -> None:
    """Every `step`-th, not the first N.

    Taking the head would cluster the cards at low agent ids — the same bias
    the sampler itself was fixed for, reintroduced one layer later where it
    would be harder to see.
    """
    import json

    identity = json.loads(ARTIFACT.read_text())["identity"]
    if identity.get("sampled", 0) <= len(listings):
        pytest.skip("nothing was dropped, so there is no spread to check")

    ids = [a["agent_id"] for a in listings]
    assert max(ids) > identity["population"] / 3, (
        f"the highest published card is #{max(ids):,} of a population of "
        f"{identity['population']:,} — these cards are the front of the registry"
    )


def test_every_published_share_carries_an_interval() -> None:
    """A share from a few hundred of ~280,000 is a range, and the range is the
    honest half. Asserted on the artifact so it survives a page rewrite."""
    import json

    identity = json.loads(ARTIFACT.read_text())["identity"]
    if not identity.get("surveyed"):
        pytest.skip("the registry was not surveyed")

    intervals = identity.get("intervals") or {}
    assert intervals, "a surveyed registry must publish its intervals"

    sampled = identity["sampled"]
    for name, bounds in intervals.items():
        point = identity[name] / sampled
        assert bounds["low"] <= point <= bounds["high"], f"{name}: interval excludes its point"
        assert bounds["high"] > bounds["low"] or sampled == 0, (
            f"{name}: a zero-width interval claims certainty from {sampled} observations"
        )
