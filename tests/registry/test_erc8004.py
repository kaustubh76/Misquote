"""The registry read, the placeholder filter, and the SSRF guard.

Most of this runs offline against constructed cards, because the behaviour worth
pinning is the judgement — what counts as a real agent, and what gets called a
placeholder. Two `chainfork` tests read the live registry, because the claim that
these addresses are real and answer is only checkable against the chain.
"""

from __future__ import annotations

import base64
import json

import pytest

from misquote.registry.erc8004 import (
    IDENTITY_REGISTRY,
    REPUTATION_IS_NOT_DISPLAYED,
    AgentCard,
    UnsafeURL,
    _assert_fetchable,
    _looks_repetitive,
    assess,
    survey,
)


def card(agent_id: int = 1, *, fetched: bool = True, on_chain: bool = True, **fields) -> AgentCard:
    body = {
        "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
        "name": "ClawNews",
        "description": "A real description of a real service that does a real thing.",
        "services": [{"name": "web", "endpoint": "https://clawnews.io"}],
        "active": True,
    }
    body.update(fields)
    return AgentCard(
        agent_id=agent_id,
        uri="data:application/json;base64," + base64.b64encode(json.dumps(body).encode()).decode(),
        on_chain=on_chain,
        fetched=fetched,
        card=body,
    )


# --- what counts as a real agent -------------------------------------------


def test_a_complete_card_is_substantive() -> None:
    verdict = assess(card())
    assert verdict.substantive
    assert verdict.resolvable and verdict.describes_a_service
    assert not verdict.looks_like_a_placeholder


def test_an_agent_with_no_endpoint_is_not_a_service() -> None:
    """The study's headline: only ~4% expose a working service endpoint. An
    agent that declares none is a registry row, not something you can hire."""
    verdict = assess(card(services=[]))
    assert not verdict.describes_a_service
    assert not verdict.substantive
    assert "no service endpoint" in " ".join(verdict.notes)


def test_a_card_that_could_not_be_fetched_is_not_resolvable() -> None:
    verdict = assess(
        AgentCard(
            agent_id=7, uri="https://gone.example", on_chain=False, fetched=False, error="HTTP 404"
        )
    )
    assert not verdict.resolvable
    assert not verdict.substantive
    assert "404" in " ".join(verdict.notes)


def test_an_on_chain_card_says_so_rather_than_claiming_it_was_reached() -> None:
    """A `data:` URI cannot 404 — nothing was fetched. Reporting it as
    "resolvable" alongside an HTTP card that actually answered would conflate
    two different claims."""
    verdict = assess(card(on_chain=True))
    assert "stored on chain" in " ".join(verdict.notes)


def test_an_inactive_agent_is_not_substantive_however_complete_its_card() -> None:
    """It is saying "do not hire me". A live sample of the registry returned one
    marked substantive whose own notes said it was inactive, which is what
    prompted tightening the definition."""
    verdict = assess(card(active=False))
    assert not verdict.declares_active
    assert not verdict.substantive
    assert "declares itself inactive" in " ".join(verdict.notes)


def test_a_card_without_the_erc8004_schema_is_not_substantive() -> None:
    verdict = assess(card(type="https://example.com/some-other-thing"))
    assert not verdict.declares_schema
    assert not verdict.substantive
    assert "does not declare the ERC-8004 registration schema" in " ".join(verdict.notes)


# --- placeholder detection -------------------------------------------------


def test_a_description_that_is_one_token_repeated_is_a_placeholder() -> None:
    """Registered agent 100's description is literally "8004AI" twenty times.

    That is not a description, and rendering it as one lends it credibility it
    did not earn.
    """
    assert _looks_repetitive("8004AI" * 20)
    assert _looks_repetitive("abc" * 30)
    assert _looks_repetitive("test test test test test test test test test test ")


def test_real_prose_is_not_mistaken_for_a_placeholder() -> None:
    """A filter that flags genuine descriptions is worse than none: it would
    hide the few agents that are real."""
    assert not _looks_repetitive(
        "Hacker News for AI agents - built by agents, for agents. ClawNews is the "
        "premier news aggregation and community platform where autonomous agents "
        "share, discover, and engage with content."
    )
    assert not _looks_repetitive("A market making agent for concentrated liquidity on BNB Chain.")
    assert not _looks_repetitive("short")


def test_an_empty_card_counts_as_a_placeholder() -> None:
    verdict = assess(card(name="", description=""))
    assert verdict.looks_like_a_placeholder
    assert not verdict.substantive


def test_a_placeholder_is_refused_even_with_a_working_endpoint() -> None:
    verdict = assess(card(description="8004AI" * 20))
    assert verdict.describes_a_service
    assert not verdict.substantive, "an endpoint does not redeem a fake description"


# --- the SSRF guard --------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:8545",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://[::1]/",
    ],
)
def test_urls_pointing_inward_are_refused(url: str) -> None:
    """This fetches URLs chosen by strangers — anyone can register an agent and
    put any URI in it. Without this, indexing the registry is a request-forgery
    primitive and the attacker picks the target."""
    with pytest.raises(UnsafeURL):
        _assert_fetchable(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://x/"])
def test_non_http_schemes_are_refused(url: str) -> None:
    with pytest.raises(UnsafeURL, match="scheme"):
        _assert_fetchable(url)


def test_a_hostname_that_does_not_resolve_is_refused_not_attempted() -> None:
    with pytest.raises(UnsafeURL):
        _assert_fetchable("https://this-host-should-not-exist-misquote-test.invalid/card.json")


# --- the survey ------------------------------------------------------------


class FakeRegistry:
    def __init__(self, cards) -> None:
        self._cards = cards

    def card(self, agent_id: int) -> AgentCard:
        return self._cards[agent_id]


def test_a_survey_reports_the_unflattering_share() -> None:
    """The count is the number every marketplace will quote. This is the number
    that means something."""
    cards = {
        1: card(1),
        2: card(2),
        3: card(3, services=[]),
        4: card(4, description="8004AI" * 20),
        5: AgentCard(agent_id=5, uri="https://gone", on_chain=False, fetched=False, error="404"),
        6: card(6, active=False),
    }
    result = survey(FakeRegistry(cards), list(cards))

    assert result.sampled == 6
    assert result.substantive == 2
    assert result.substantive_share == pytest.approx(2 / 6)
    assert result.placeholders == 1
    assert result.resolvable == 5  # only the 404 failed to resolve

    text = result.render()
    assert "substantive" in text
    assert "33%" in text


def test_the_survey_of_an_empty_sample_does_not_divide_by_zero() -> None:
    result = survey(FakeRegistry({}), [])
    assert result.sampled == 0
    assert result.substantive_share == 0.0
    assert "0" in result.render()


# --- the thing we refuse to display ---------------------------------------


def test_reputation_is_not_rendered_and_the_card_says_why() -> None:
    """Showing a star rating computed from 29,444 reviews by 76 reviewers would
    be exactly the misquote this project is named after."""
    assert "77.9%" in REPUTATION_IS_NOT_DISPLAYED
    assert "76 unique" in REPUTATION_IS_NOT_DISPLAYED
    assert "arXiv" in REPUTATION_IS_NOT_DISPLAYED

    from misquote.registry import erc8004

    assert not hasattr(erc8004, "reputation_score")
    assert not hasattr(erc8004, "star_rating")


# --- against the live registry --------------------------------------------


@pytest.mark.chainfork
def test_the_identity_registry_is_where_we_say_it_is() -> None:
    from web3 import Web3

    from misquote.indexer.reader import connect
    from misquote.registry.erc8004 import IdentityRegistry

    w3 = connect(56)
    address = Web3.to_checksum_address(IDENTITY_REGISTRY[56])
    assert len(w3.eth.get_code(address)) > 0, "no contract at the identity registry address"

    registry = IdentityRegistry(w3, 56)
    assert registry.contract.functions.name().call() == "AgentIdentity"
    assert registry.contract.functions.symbol().call() == "AGENT"


@pytest.mark.chainfork
def test_a_real_agent_card_resolves_and_is_assessed() -> None:
    """Agent 1 is ClawNews, whose card is held on chain as a data: URI."""
    from misquote.indexer.reader import connect
    from misquote.registry.erc8004 import IdentityRegistry

    registry = IdentityRegistry(connect(56), 56)
    real = registry.card(1)

    assert real.fetched and real.on_chain
    assert real.is_erc8004_shaped
    assert real.name
    assert real.endpoints
    assert assess(real).substantive


@pytest.mark.chainfork
def test_the_registry_really_does_contain_placeholders() -> None:
    """Agent 100's description is one token repeated. Not a hypothetical."""
    from misquote.indexer.reader import connect
    from misquote.registry.erc8004 import IdentityRegistry

    registry = IdentityRegistry(connect(56), 56)
    verdict = assess(registry.card(100))
    assert verdict.looks_like_a_placeholder
    assert not verdict.substantive


# --- the population bound ----------------------------------------------------


class _FakeRegistry:
    """A registry with `population` contiguous ids, and nothing else."""

    def __init__(self, population: int) -> None:
        self.population = population
        self.reads = 0

    def owner(self, agent_id: int) -> str:
        self.reads += 1
        if 1 <= agent_id <= self.population:
            return "0x" + "11" * 20
        raise ValueError("execution reverted: ERC721: invalid token ID")


def test_the_bound_is_found_by_search_not_by_totalsupply() -> None:
    """`totalSupply()` reverts on this registry — it is a proxy, not Enumerable —
    so the population has to be probed with the predicate that does work."""
    from misquote.registry.erc8004 import highest_agent_id

    for population in (1, 2, 15, 800, 270_765):
        registry = _FakeRegistry(population)
        assert highest_agent_id(registry) == population, population


def test_an_empty_registry_reports_zero_rather_than_one() -> None:
    """The search brackets upward from id 1, so id 1 must be checked first or an
    empty registry reports a population of one."""
    from misquote.registry.erc8004 import highest_agent_id

    assert highest_agent_id(_FakeRegistry(0)) == 0


def test_the_search_is_logarithmic_and_therefore_affordable() -> None:
    """It runs against a public endpoint one `eth_call` at a time. Linear
    probing over 270,765 ids would be a quarter of a million requests."""
    from misquote.registry.erc8004 import highest_agent_id

    registry = _FakeRegistry(270_765)
    highest_agent_id(registry)

    assert registry.reads < 60, f"{registry.reads} reads is not a binary search"


# --- the interval a share is worth -------------------------------------------


def test_a_share_from_forty_observations_is_not_a_point() -> None:
    """The reason this exists. "30% substantive" from n=40 spans 18-46%, and
    publishing the point alone is the false precision this project is named
    against — on the card that criticises other marketplaces for it."""
    from misquote.registry.erc8004 import wilson_interval

    low, high = wilson_interval(12, 40)
    assert low == pytest.approx(0.181, abs=0.005)
    assert high == pytest.approx(0.454, abs=0.005)


def test_more_observations_narrow_it() -> None:
    """The same share at ten times the sample must say more, or the sample cost
    bought nothing."""
    from misquote.registry.erc8004 import wilson_interval

    small = wilson_interval(12, 40)
    large = wilson_interval(120, 400)

    assert (large[1] - large[0]) < (small[1] - small[0]) / 2


def test_a_zero_count_is_not_certainty() -> None:
    """Why Wilson and not the normal approximation.

    The normal interval is `p ± z·sqrt(p(1-p)/n)`, which is **exactly zero wide**
    at p=0. The first survey found 0 placeholders in 40, and reporting that as
    certainty would be a stronger claim than forty observations can support in
    principle.
    """
    from misquote.registry.erc8004 import wilson_interval

    low, high = wilson_interval(0, 40)
    assert low == 0.0
    assert high > 0.05, "zero of forty cannot bound the rate below five percent"


def test_a_full_count_is_not_certainty_either() -> None:
    from misquote.registry.erc8004 import wilson_interval

    low, high = wilson_interval(40, 40)
    assert high == 1.0
    assert low < 0.95


def test_an_empty_sample_admits_everything() -> None:
    """Nothing was measured, so nothing is excluded."""
    from misquote.registry.erc8004 import wilson_interval

    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_the_interval_always_contains_the_point() -> None:
    from misquote.registry.erc8004 import wilson_interval

    for successes in range(0, 41):
        low, high = wilson_interval(successes, 40)
        assert low <= successes / 40 <= high, successes
