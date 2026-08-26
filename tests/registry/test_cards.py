"""Our own registrations, judged by the gate we judge everybody else with.

This repository surveyed four hundred ERC-8004 agents and published how few of
them clear `assess().substantive` — the count is the argument `/registry` makes.
Registering four of our own that would not clear it is the single outcome that
would make that argument worthless, so the bar is applied here rather than
described here.

The tests deliberately run the **third-party code path**: they build the URI the
way the script will, hand it to `IdentityRegistry._decode_data_uri` — the same
method that decodes a stranger's on-chain card — and run `assess()` on the
result. Asserting the fields directly would be a second copy of the rule, and
the copy would stop agreeing with `assess()` the day somebody edits it.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from misquote.registry import erc8004
from misquote.registry.cards import (
    AGENTS,
    CARD_IMAGE,
    MAX_URI_BYTES,
    Card,
    NoServiceEndpoint,
    as_data_uri,
    build_card,
    build_cards,
    registration_entry,
)

API = "https://misquote-api.onrender.com"
SOURCE = Path(erc8004.__file__).parent / "cards.py"


def decode(card: Card) -> erc8004.AgentCard:
    """Through the reader that decodes strangers' cards, not around it."""
    registry = object.__new__(erc8004.IdentityRegistry)
    return erc8004.IdentityRegistry._decode_data_uri(registry, 0, card.token_uri)


@pytest.fixture(scope="module")
def cards() -> tuple[Card, ...]:
    return build_cards(api_base=API)


def test_there_is_one_card_per_listed_agent(cards: tuple[Card, ...]) -> None:
    assert [c.agent for c in cards] == ["warden", "grid", "sentinel", "router"]


@pytest.mark.parametrize("agent", [a for a, _, _ in AGENTS])
@pytest.mark.parametrize("agent_id", [None, 1927], ids=["pre-registration", "complete"])
def test_every_card_passes_the_bar_we_hold_other_agents_to(
    agent: str, agent_id: int | None
) -> None:
    """The one that matters, for BOTH shapes.

    A card is registered before it can name its own id and rewritten afterwards,
    so there are two documents per agent and either could be the one a reader
    fetches — the second only exists if `setAgentURI` succeeded. Both are held
    to the same bar.
    """
    card = build_card(*next(a for a in AGENTS if a[0] == agent), api_base=API, agent_id=agent_id)
    assessment = erc8004.assess(decode(card))
    assert assessment.substantive, (
        f"{agent}'s own registration would be filtered out of our own listing: {assessment.notes}"
    )


def test_a_card_survives_the_placeholder_detector(cards: tuple[Card, ...]) -> None:
    """`_looks_repetitive` is what caught agent 100's description of "8004AI"
    twenty times. A description written to fill a field would trip it."""
    for card in cards:
        assert not erc8004._looks_repetitive(str(card.document["description"]))


def test_the_endpoint_is_the_configured_api_and_not_a_baked_in_host(
    cards: tuple[Card, ...],
) -> None:
    for card in cards:
        services: Any = card.document["services"]
        assert services[0]["endpoint"] == f"{API}/journal/{card.agent}"


def test_no_api_base_refuses_rather_than_writing_a_card_with_no_endpoint() -> None:
    """A card with no `services` fails `assess()` — but it would fail it after
    being written to a chain that cannot forget it."""
    with pytest.raises(NoServiceEndpoint, match="assess"):
        build_card("warden", "Warden", "does a thing", api_base="")


def test_the_uri_round_trips_to_the_document_it_was_built_from(
    cards: tuple[Card, ...],
) -> None:
    """What `tokenURI` will return has to decode back to what we meant. The
    read-back check in the script compares against exactly this."""
    for card in cards:
        assert decode(card).card == card.document


def test_the_encoding_is_reproducible() -> None:
    """`sort_keys` plus tight separators, so rebuilding a card months later
    yields the same bytes and the read-back comparison is meaningful."""
    document = {"b": 1, "a": [2, 3]}
    assert as_data_uri(document) == as_data_uri({"a": [2, 3], "b": 1})
    assert " " not in as_data_uri(document)


def test_every_card_is_under_the_byte_tripwire(cards: tuple[Card, ...]) -> None:
    """Written once, to a chain, forever. The limit is ours, not the registry's,
    and it exists so padding shows up as a red test rather than a gas bill."""
    for card in cards:
        assert card.uri_bytes <= MAX_URI_BYTES, f"{card.agent}: {card.uri_bytes} bytes"


def test_an_oversized_card_is_refused() -> None:
    with pytest.raises(ValueError, match="tripwire"):
        build_card("warden", "Warden", "x " * MAX_URI_BYTES, api_base=API)


def test_the_document_is_json_the_registry_can_hold(cards: tuple[Card, ...]) -> None:
    for card in cards:
        assert json.loads(json.dumps(card.document))


def test_this_module_cannot_sign_anything() -> None:
    """The guard `tests/registry/test_erc8183.py` puts on the hire model, for the
    same reason: building a claim about an agent must not also be the thing that
    can broadcast it. `registry/identity.py` is where signing lives, and it is
    one import away — which is exactly why this is asserted rather than assumed.
    """
    tree = ast.parse(SOURCE.read_text(), filename=str(SOURCE))

    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            if node.module.startswith("misquote."):
                imported.add(node.module)
        elif isinstance(node, ast.Call):
            func = node.func
            called.add(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", ""))

    for forbidden in ("web3", "eth_account", "httpx", "requests", "misquote.chain"):
        assert not any(name.startswith(forbidden) for name in imported), (
            f"{forbidden!r} imported into cards.py — this must stay unable to sign"
        )
    for forbidden in ("send_raw_transaction", "sign_transaction", "transact", "send"):
        assert forbidden not in called, f"{forbidden!r} called — this must stay unsigned"


# --- the three fields a listing reads --------------------------------------
#
# `assess()` does not require any of them, which is exactly why they need their
# own tests: nothing else in this repository would notice them disappearing.


def test_every_card_carries_an_image(cards: tuple[Card, ...]) -> None:
    """Without one, a listing renders the agent with a blank avatar beside
    agents that have one."""
    for card in cards:
        assert card.document["image"] == CARD_IMAGE


def test_x402_support_is_stated_rather_than_omitted(cards: tuple[Card, ...]) -> None:
    """`false` is an answer; an absent field is not. These agents take no x402
    payments and the card should say so rather than leave it to be guessed."""
    for card in cards:
        assert card.document["x402Support"] is False


def test_a_card_without_an_id_makes_no_registration_claim() -> None:
    """The pre-registration shape. A card cannot name its own registry id before
    the registry has assigned one, and inventing one would be a claim about an
    entry that may belong to somebody else."""
    card = build_card("warden", "Warden", "does a thing", api_base=API)
    assert "registrations" not in card.document


def test_the_complete_card_points_back_at_its_own_registry_entry() -> None:
    card = build_card("warden", "Warden", "does a thing", api_base=API, agent_id=1927)
    entry = card.document["registrations"][0]  # type: ignore[index]
    assert entry["agentId"] == 1927
    assert entry["agentRegistry"] == registration_entry(1927, 97)["agentRegistry"]


def test_the_registry_in_the_back_reference_is_the_one_we_actually_write_to() -> None:
    """A back-reference naming a registry we do not use would be worse than
    none: it is a confident, checkable, wrong statement."""
    from misquote.registry.erc8004 import IDENTITY_REGISTRY

    for chain_id in (56, 97):
        entry = registration_entry(1, chain_id)
        assert entry["agentRegistry"] == f"eip155:{chain_id}:{IDENTITY_REGISTRY[chain_id].lower()}"


def test_the_complete_card_is_still_under_the_byte_tripwire() -> None:
    """`registrations` and `image` are ~250 bytes, and the complete card is what
    actually gets written the second time."""
    for card in build_cards(api_base=API, ids={a: 999999 for a, _, _ in AGENTS}):
        assert card.uri_bytes <= MAX_URI_BYTES, f"{card.agent}: {card.uri_bytes} bytes"
