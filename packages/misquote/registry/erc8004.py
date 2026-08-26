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

#: Where the registry's behaviour actually lives, per chain.
#:
#: `IDENTITY_REGISTRY` is 130 bytes on both chains — an EIP-1967 proxy, which is
#: why `registry_report.py` binary-searches `ownerOf` instead of calling
#: `totalSupply()`. The proxy forwards, so a selector that decides whether this
#: repository can register anything is present or absent *there*, not here.
#:
#: Read from the EIP-1967 implementation slot rather than from a block explorer,
#: for the reason `addresses.py` states about everything in it: nothing was taken
#: on trust from documentation. See `IDENTITY_IMPLEMENTATION_EVIDENCE`.
IDENTITY_IMPLEMENTATION = {
    56: "0x7274e874CA62410a93Bd8bf61c69d8045E399c02",
    97: "0x7274e874CA62410a93Bd8bf61c69d8045E399c02",
}

#: The EIP-1967 slot the two addresses above were read out of.
#: `keccak256("eip1967.proxy.implementation") - 1`.
IMPLEMENTATION_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"

#: What was read to justify each entry, and when. Modelled on
#: `erc8183.py::JOB_ESCROW_EVIDENCE` — an address without its readings is a
#: number somebody typed.
IDENTITY_IMPLEMENTATION_EVIDENCE: dict[int, tuple[str, ...]] = {
    56: (
        "Read 2026-08-25 at block 117,999,514 from the EIP-1967 implementation "
        "slot of 0x8004A169FB4a3325136EB29fA0ceB6D2e539a432.",
        "14,474 bytes of code at the implementation, against 130 at the proxy.",
        "Carries register(string), safeTransferFrom, ownerOf and tokenURI.",
    ),
    97: (
        "Read 2026-08-25 at block 127,142,901 from the same slot of "
        "0x8004A818BFB912233c491871b3d84c89A494BD9e.",
        "Byte-identical implementation address to chain 56 — the same "
        "deterministic deployment on both networks, which is the reading that "
        "makes a chapel rehearsal evidence about mainnet rather than about chapel.",
        "Same four selectors present.",
    ),
}

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


def wilson_interval(successes: int, trials: int, *, z: float = 1.96) -> tuple[float, float]:
    """A 95% confidence interval for a share, by the Wilson score method.

    ## Why an interval at all

    The survey samples a few hundred of ~272,000 agents. "30% substantive" from
    forty observations carries a 95% interval of roughly 18-46%, and a share
    published without that is exactly the false precision this project is named
    against — printed, of all places, on the card that criticises other
    marketplaces for doing it.

    ## Why Wilson and not the normal approximation

    Because the normal interval is `p +/- z*sqrt(p(1-p)/n)`, which is **zero
    wide** when `p` is 0 or 1. The placeholder rate in the first survey was
    0 of 40, and the normal method would have reported that as certainty from
    forty observations — a stronger claim than any amount of data of that size
    can support. Wilson does not degenerate at the boundaries, and it is
    well-behaved for the small samples this actually runs at.

    Returns `(low, high)` clamped to [0, 1]. A sample of zero returns the whole
    interval, which is the honest answer to a question nobody asked.
    """
    if trials <= 0:
        return 0.0, 1.0

    phat = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (phat + z * z / (2 * trials)) / denominator
    margin = (
        z * ((phat * (1.0 - phat) / trials + z * z / (4.0 * trials * trials)) ** 0.5) / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def highest_agent_id(registry, *, ceiling: int = 2_000_000) -> int:
    """The largest agent id the registry resolves, by binary search on `ownerOf`.

    ## Why this is not `totalSupply()`

    Because `totalSupply()` reverts on this contract — it is a 130-byte proxy and
    not `ERC721Enumerable`, so the obvious read is unavailable and the population
    has to be probed. `ownerOf` reverts for an unminted id and returns for a
    minted one, which is exactly the predicate a binary search needs.

    ## Why the population matters

    The README's open D1 item says: *"ERC-8004 registry population counted on
    BscScan. Decision rule: **< ~15 real agents** -> third-party auto-cards
    demote immediately to a plain registry view."* Nobody had counted. Measured
    on BSC mainnet, the answer is **270,765** — four orders of magnitude above
    the number the rule was written around.

    That figure is not recorded as a constant here on purpose. It moves every
    time somebody registers an agent, and a constant would be a claim that goes
    stale silently; a caller that wants the number reads it.

    ## Why it is needed for sampling

    `survey()` characterises the registry from a sample, and a sample is only
    about the population it was drawn from. Drawing ids 1..800 out of 270,765
    describes the oldest 0.3% of registrations — which are systematically the
    ones most likely to differ — while reporting a share as though it were about
    the registry. The bound is what makes an honest draw possible.

    Assumes ids are contiguous from 1, which is what a mint-sequential ERC-721
    gives. A registry with holes would make this a lower bound rather than the
    maximum, and it is named for what it measures.
    """

    def exists(agent_id: int) -> bool:
        try:
            registry.owner(agent_id)
        except Exception:  # noqa: BLE001 — a revert is the answer, not an error
            return False
        return True

    if not exists(1):
        return 0

    low, high = 1, 1
    while exists(high) and high < ceiling:
        low, high = high, high * 4
    high = min(high, ceiling)

    while low + 1 < high:
        mid = (low + high) // 2
        if exists(mid):
            low = mid
        else:
            high = mid
    return low


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

    # The agents themselves, not just how many of them there were.
    #
    # This aggregated and discarded the cards, which is all `/registry` needed
    # while it rendered a single percentage. Listing third-party agents needs
    # what each one actually says — and the listing is the more honest surface,
    # because a share of 270,765 is a statistic and a card is a claim somebody
    # made that a reader can go and check.
    #
    # Carried as (AgentCard, Assessment) pairs so the registration and our
    # verdict on it travel together and cannot be recombined wrongly downstream.
    agents: tuple[tuple[AgentCard, Assessment], ...] = ()

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
    assessed: list[tuple[AgentCard, Assessment]] = []

    for agent_id in agent_ids:
        card = registry.card(agent_id)
        verdict = assess(card)
        assessed.append((card, verdict))
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
        agents=tuple(assessed),
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
