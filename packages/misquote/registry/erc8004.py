"""Reading the ERC-8004 identity registry, and being honest about what is there.

BNB Chain has more registered agents than any other chain — 266,191 at the time
of writing, four times the next. That number is the headline every marketplace
will quote, and it is close to meaningless: a peer-reviewed study
([arXiv:2606.26028](https://arxiv.org/abs/2606.26028)) found that only about
**4% expose a working service endpoint**, and that after removing Sybil-flagged
feedback, **77.9% of rated BSC agents had no valid feedback left** — 29,444
reviews from 76 unique reviewers.

So this module does the thing the count does not: it resolves each agent's card,
checks whether the agent describes anything real, and reports what it found
including the unflattering parts. That is the same discipline the tearsheet
applies to our own agent, turned outward.

Two facts about the registry that a doc will not tell you, both read from the
deployed contract:

**`totalSupply()` reverts.** It is an ERC-721 without enumeration, so there is no
cheap on-chain count. Any total comes from indexing Transfer events or from an
external indexer, and should be labelled with which.

**`tokenURI` returns two different shapes.** Most cards are
`data:application/json;base64,...` — held on chain, so they always resolve. Some
are `https://...`, which may or may not still exist. Conflating the two would
report a card as "resolvable" when nothing was ever fetched.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from web3 import Web3

# Verified on BSC mainnet: name() == "AgentIdentity", symbol() == "AGENT".
IDENTITY_REGISTRY = {
    56: "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
    97: "0x8004A818BFB912233c491871b3d84c89A494BD9e",
}
REPUTATION_REGISTRY = {
    56: "0x8004BAa17C55a88189AE136b182e5fdA19dE9b63",
    97: "0x8004B663056A597Dffe9eCcC1965A193B7388713",
}

IDENTITY_ABI = json.loads("""[
 {"name":"name","type":"function","stateMutability":"view","inputs":[],
  "outputs":[{"type":"string"}]},
 {"name":"symbol","type":"function","stateMutability":"view","inputs":[],
  "outputs":[{"type":"string"}]},
 {"name":"tokenURI","type":"function","stateMutability":"view",
  "inputs":[{"type":"uint256"}],"outputs":[{"type":"string"}]},
 {"name":"ownerOf","type":"function","stateMutability":"view",
  "inputs":[{"type":"uint256"}],"outputs":[{"type":"address"}]}
]""")

ERC8004_SCHEMA = "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"

MAX_CARD_BYTES = 256 * 1024
FETCH_TIMEOUT_S = 5.0


class UnsafeURL(ValueError):
    """A URI we will not fetch. See `_assert_fetchable`."""


def _assert_fetchable(url: str) -> None:
    """Refuse anything that could turn a registry read into an internal probe.

    This fetches URLs chosen by strangers — anyone can register an agent and put
    any URI in it. Without these guards, indexing the registry is a
    server-side request forgery primitive pointed at our own network, and the
    attacker chooses the target.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURL(f"refusing scheme {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeURL("no host")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as error:
        raise UnsafeURL(f"cannot resolve {host}") from error

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            raise UnsafeURL(f"{host} resolves to a non-public address ({address})")


@dataclass(frozen=True, slots=True)
class AgentCard:
    """One agent's self-description, and where it came from."""

    agent_id: int
    uri: str
    on_chain: bool  # a data: URI, so it can never 404
    fetched: bool
    card: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @property
    def name(self) -> str:
        return str(self.card.get("name", "")).strip()

    @property
    def description(self) -> str:
        return str(self.card.get("description", "")).strip()

    @property
    def endpoints(self) -> list[str]:
        out = []
        for service in self.card.get("services", []) or []:
            endpoint = (service or {}).get("endpoint")
            if isinstance(endpoint, str) and endpoint.strip():
                out.append(endpoint.strip())
        return out

    @property
    def declares_active(self) -> bool:
        return bool(self.card.get("active", False))

    @property
    def is_erc8004_shaped(self) -> bool:
        return str(self.card.get("type", "")).startswith("https://eips.ethereum.org/EIPS/eip-8004")


@dataclass(frozen=True, slots=True)
class Assessment:
    """What we can actually say about an agent, and what we cannot."""

    agent_id: int
    resolvable: bool
    describes_a_service: bool
    looks_like_a_placeholder: bool
    declares_active: bool
    declares_schema: bool
    notes: list[str]

    @property
    def substantive(self) -> bool:
        """Worth showing as a real agent rather than as a registry row.

        Every clause here was earned by looking at real registrations. An earlier
        version omitted `declares_active` and `declares_schema`, and a sample of
        the live registry promptly returned an agent marked substantive whose own
        notes said it was inactive and did not use the ERC-8004 schema. An agent
        that declares itself inactive is saying "do not hire me", and a card that
        does not claim to be an ERC-8004 registration is not one.
        """
        return (
            self.resolvable
            and self.describes_a_service
            and self.declares_active
            and self.declares_schema
            and not self.looks_like_a_placeholder
        )


def _looks_repetitive(text: str, *, min_length: int = 40) -> bool:
    """Detect a description that is one token pasted until it looks like prose.

    Registered agent 100's description is literally "8004AI" repeated twenty
    times. That is not a description, and a marketplace that renders it as one is
    lending it credibility it did not earn.
    """
    stripped = "".join(text.split())
    if len(stripped) < min_length:
        return False
    for size in range(3, 21):
        unit = stripped[:size]
        if unit and stripped.startswith(unit * 3):
            return True
    return False


def assess(card: AgentCard) -> Assessment:
    """Judge a card on what it contains, not on what the registry implies."""
    notes: list[str] = []

    if not card.fetched:
        notes.append(card.error or "the card could not be fetched")
    elif not card.is_erc8004_shaped:
        notes.append("the card does not declare the ERC-8004 registration schema")

    endpoints = card.endpoints if card.fetched else []
    if card.fetched and not endpoints:
        notes.append("no service endpoint is declared")

    placeholder = card.fetched and (
        _looks_repetitive(card.description) or (not card.name and not card.description)
    )
    if placeholder:
        notes.append("the description looks like placeholder text")

    if card.fetched and not card.declares_active:
        notes.append("the agent declares itself inactive")

    if card.on_chain:
        notes.append("the card is stored on chain, so it resolves by construction")

    return Assessment(
        agent_id=card.agent_id,
        resolvable=card.fetched,
        describes_a_service=bool(endpoints),
        looks_like_a_placeholder=placeholder,
        declares_active=card.fetched and card.declares_active,
        declares_schema=card.fetched and card.is_erc8004_shaped,
        notes=notes,
    )


class IdentityRegistry:
    """Reads agent cards, resolving both URI shapes and refusing unsafe ones."""

    __slots__ = ("w3", "chain_id", "contract", "_session")

    def __init__(self, w3: Web3, chain_id: int, session: Any = None) -> None:
        if chain_id not in IDENTITY_REGISTRY:
            raise ValueError(f"no known ERC-8004 identity registry for chain {chain_id}")
        self.w3 = w3
        self.chain_id = chain_id
        self.contract = w3.eth.contract(
            address=Web3.to_checksum_address(IDENTITY_REGISTRY[chain_id]), abi=IDENTITY_ABI
        )
        self._session = session

    def token_uri(self, agent_id: int) -> str:
        return self.contract.functions.tokenURI(agent_id).call()

    def owner(self, agent_id: int) -> str:
        return self.contract.functions.ownerOf(agent_id).call()

    def card(self, agent_id: int) -> AgentCard:
        """Fetch and parse one agent's card.

        A `data:` URI is decoded in place — it is on chain, so it cannot fail and
        no request is made. An `https:` URI is fetched, with the guards in
        `_assert_fetchable`, a timeout, and a size cap.
        """
        try:
            uri = self.token_uri(agent_id)
        except Exception as error:  # noqa: BLE001 — an unregistered id is normal
            return AgentCard(
                agent_id=agent_id,
                uri="",
                on_chain=False,
                fetched=False,
                error=f"tokenURI reverted: {type(error).__name__}",
            )

        if uri.startswith("data:"):
            return self._decode_data_uri(agent_id, uri)
        return self._fetch_remote(agent_id, uri)

    def _decode_data_uri(self, agent_id: int, uri: str) -> AgentCard:
        try:
            header, _, payload = uri.partition(",")
            raw = base64.b64decode(payload) if "base64" in header else payload.encode()
            return AgentCard(
                agent_id=agent_id,
                uri=uri,
                on_chain=True,
                fetched=True,
                card=json.loads(raw),
            )
        except Exception as error:  # noqa: BLE001
            return AgentCard(
                agent_id=agent_id,
                uri=uri,
                on_chain=True,
                fetched=False,
                error=f"on-chain card is not valid JSON: {type(error).__name__}",
            )

    def _fetch_remote(self, agent_id: int, uri: str) -> AgentCard:
        try:
            _assert_fetchable(uri)
        except UnsafeURL as error:
            return AgentCard(
                agent_id=agent_id, uri=uri, on_chain=False, fetched=False, error=str(error)
            )

        session = self._session
        if session is None:
            import requests

            session = requests
        try:
            response = session.get(uri, timeout=FETCH_TIMEOUT_S, allow_redirects=True)
            if response.status_code != 200:
                return AgentCard(
                    agent_id=agent_id,
                    uri=uri,
                    on_chain=False,
                    fetched=False,
                    error=f"HTTP {response.status_code}",
                )
            body = response.content[:MAX_CARD_BYTES]
            return AgentCard(
                agent_id=agent_id,
                uri=uri,
                on_chain=False,
                fetched=True,
                card=json.loads(body),
            )
        except Exception as error:  # noqa: BLE001 — a dead endpoint is the finding
            return AgentCard(
                agent_id=agent_id,
                uri=uri,
                on_chain=False,
                fetched=False,
                error=f"{type(error).__name__}: {str(error)[:120]}",
            )


@dataclass(frozen=True, slots=True)
class RegistrySurvey:
    """What a sample of the registry actually contains."""

    sampled: int
    resolvable: int
    with_endpoint: int
    placeholders: int
    declared_active: int
    on_chain_cards: int

    @property
    def substantive_share(self) -> float:
        return self.substantive / self.sampled if self.sampled else 0.0

    substantive: int = 0

    def render(self) -> str:
        return "\n".join(
            [
                f"  sampled              {self.sampled:,}",
                f"  card resolves        {self.resolvable:,} "
                f"({self.resolvable / max(1, self.sampled):.0%})",
                f"  declares an endpoint {self.with_endpoint:,} "
                f"({self.with_endpoint / max(1, self.sampled):.0%})",
                f"  placeholder text     {self.placeholders:,}",
                f"  declares itself live {self.declared_active:,}",
                f"  card held on chain   {self.on_chain_cards:,}",
                "",
                f"  substantive          {self.substantive:,} ({self.substantive_share:.0%})",
            ]
        )


def survey(registry: IdentityRegistry, agent_ids) -> RegistrySurvey:
    """Assess a sample and report the aggregate, including the awkward parts."""
    sampled = resolvable = with_endpoint = placeholders = active = on_chain = substantive = 0

    for agent_id in agent_ids:
        card = registry.card(agent_id)
        verdict = assess(card)
        sampled += 1
        resolvable += verdict.resolvable
        with_endpoint += verdict.describes_a_service
        placeholders += verdict.looks_like_a_placeholder
        active += verdict.declares_active
        on_chain += card.on_chain
        substantive += verdict.substantive

    return RegistrySurvey(
        sampled=sampled,
        resolvable=resolvable,
        with_endpoint=with_endpoint,
        placeholders=placeholders,
        declared_active=active,
        on_chain_cards=on_chain,
        substantive=substantive,
    )


# The reputation registry is deliberately not read.
#
# After removing Sybil-flagged feedback, 77.9% of rated BSC agents had no valid
# feedback left — 29,444 entries from 76 unique reviewers (arXiv:2606.26028).
# Rendering that as a star rating would be exactly the misquote this project is
# named after, so the card says why the field is blank instead of filling it.
REPUTATION_IS_NOT_DISPLAYED = (
    "On-chain reputation is not shown. A peer-reviewed study of this registry "
    "(arXiv:2606.26028) found that after removing Sybil-flagged feedback, 77.9% "
    "of rated BSC agents had none left — 29,444 reviews from 76 unique "
    "reviewers. A rating computed from that would look precise and mean nothing."
)
