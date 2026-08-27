"""The registration documents this project publishes about its own four agents.

Pure. No web3, no network, no key — `tests/registry/test_cards.py` walks the AST
and asserts it, the way `tests/registry/test_erc8183.py` does for the hire
model. A card is a claim about what an agent is; building one must not be able
to also be the thing that broadcasts it.

## The shape is not ours to choose

`erc8004.assess()` judges third-party registrations, and `Assessment.substantive`
is the property that decides whether the marketplace shows an agent as real or
as a registry row. It requires five things: the card resolves, it declares the
ERC-8004 registration schema, it declares itself active, it names a service
endpoint, and its description is not one token pasted until it looks like prose.

Those five requirements are why every field below exists. This project surveyed
four hundred agents and published how few of them clear that bar; registering
four of its own that would not clear it is the one outcome that would make the
survey worthless. So the cards are built to pass **our own** gate, and
`tests/registry/test_cards.py` asserts it by running `assess()` over them rather
than by re-listing the fields here — a second copy of the rule would drift from
the first the moment someone edited `assess()`.

## Why the endpoint is read rather than written

`services[].endpoint` is the only field that can be *wrong* in a way nobody
notices: a card naming a host that never answers still passes every offline
check and fails the moment a judge clicks it. So it is not a constant here. It
comes from `artifacts/api.json`'s `base`, which `make api-config` writes from
the environment, and `build_cards` **refuses** when that is null rather than
falling back to the site origin — `api.json`'s own note explains why that
fallback is wrong ("there is no API there, and requesting one would 404 against
the export").

## Why `data:` and not a URL

`AgentCard.on_chain` already records the distinction, and `assess()` adds the
note "the card is stored on chain, so it resolves by construction". A hosted URL
is a dependency on this project still paying for a domain on the day someone
checks; the base64 payload is a dependency on nothing. It also cannot be edited
after the fact, which is the property that makes it evidence rather than a
description — a claim you can revise after publication is a weaker claim.

The cost is bytes. `register(string)` charges calldata gas per byte, so the
descriptions are the shortest ones that still say what the agent does.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from misquote.registry.erc8004 import ERC8004_SCHEMA, IDENTITY_REGISTRY

#: One entry per agent the marketplace lists, in the order the site lists them.
#:
#: `journal` is the API route that answers for this agent, and is what the
#: card's endpoint is built from. Every one of the four has a journal — that is
#: what `make warden`, `make router` and the showcase write into — so an
#: endpoint here is a route that answers rather than a route that exists.
AGENTS: tuple[tuple[str, str, str], ...] = (
    (
        "warden",
        "Warden",
        "Rebalances a PancakeSwap v3 range using Avellaneda-Stoikov reservation "
        "prices. Reports fee APR net of realized convexity cost, not gross.",
    ),
    (
        "grid",
        "Grid",
        "Places a fixed ladder of v3 ranges and requotes on inventory skew. "
        "Reports spread capture in bps and the share of rungs that filled.",
    ),
    (
        "sentinel",
        "Sentinel",
        "Withdraws a position when swap-flow imbalance crosses a published "
        "threshold. Reports every false alarm it raised, including on noise.",
    ),
    (
        "router",
        "Router",
        "Moves stablecoin supply between Venus markets only when the rate gap "
        "clears gas plus slippage. Reports the moves it declined to make.",
    ),
)

#: What a listing shows for an agent with no `image`: nothing.
#:
#: Read off a live TermiX-indexed agent — their explorer surfaces the card's
#: `image` as `avatarUrl`, and a card without one renders blank beside agents
#: that have one. Points at this project's own social card, which is served from
#: the same deployment as everything else it links to, rather than at an asset
#: host that would be one more thing to keep alive.
CARD_IMAGE = "https://misquote.vercel.app/opengraph-image.png"

#: Whether these agents accept x402 payments. They do not.
#:
#: Carried explicitly rather than omitted. 8004scan counts about 66,500 of BSC's
#: ~285,000 agents as x402-capable — a share it will report on request, so the
#: field is one a reader may genuinely filter on, and an absent field reads as
#: unknown where `false` reads as answered.
#:
#: Undated figures go stale silently, so this one is deliberately rounded and
#: the live reading lives in `data/scan8004.json` under `counts`, stamped with
#: the moment it was taken.
X402_SUPPORTED = False

#: The registry charges calldata gas per byte and a card is written once,
#: forever. Not a limit anyone imposes on us — a tripwire, so a description
#: someone pads later shows up as a failing test rather than as a gas bill.
MAX_URI_BYTES = 2048


class NoServiceEndpoint(ValueError):
    """No live API is configured, so no card can name one.

    Deliberately an exception rather than an omitted field. A card without
    `services` fails our own `assess()` — but it fails it *after* being written
    to a chain that cannot forget it, which is several thousand times more
    expensive than failing here.
    """


@dataclass(frozen=True, slots=True)
class Card:
    """One agent's registration, and the URI it will be written to chain as."""

    agent: str
    name: str
    document: dict[str, object]
    token_uri: str

    @property
    def uri_bytes(self) -> int:
        return len(self.token_uri.encode())


def as_data_uri(document: dict[str, object]) -> str:
    """The document, base64'd into a URI the registry can hold verbatim.

    `separators` is not cosmetic: the default `json.dumps` puts a space after
    every comma and colon, and each of those is a byte written to chain forever.
    `sort_keys` makes the encoding reproducible, which is what lets a test
    rebuild the card and compare it to what `tokenURI` returns.
    """
    packed = json.dumps(document, separators=(",", ":"), sort_keys=True)
    encoded = base64.b64encode(packed.encode()).decode()
    return f"data:application/json;base64,{encoded}"


def registration_entry(agent_id: int, chain_id: int) -> dict[str, object]:
    """The CAIP-style back-reference from a card to its own registry entry.

    ERC-8004 publishes this so a card found on its own — cached, mirrored,
    handed around — still says which registry and which id it belongs to. A
    card without it is a document that could be about anybody.

    `eip155:{chain}:{registry}` is the CAIP-10 form, lowercased, which is how
    every card observed in the live registry writes it.
    """
    registry = IDENTITY_REGISTRY[chain_id].lower()
    return {"agentId": agent_id, "agentRegistry": f"eip155:{chain_id}:{registry}"}


def build_card(
    agent: str,
    name: str,
    description: str,
    *,
    api_base: str,
    agent_id: int | None = None,
    chain_id: int = 97,
) -> Card:
    """One card, from the fields `assess()` requires plus the three a listing reads.

    `agent_id` is the chicken-and-egg: a card cannot name its own registry id
    before the registry has assigned one. Absent, this builds the card that gets
    registered; present, it builds the complete card that `setAgentURI` writes
    afterwards. One function rather than two, so the two shapes cannot drift —
    and `tests/registry/test_cards.py` asserts both still pass `assess()`.
    """
    base = (api_base or "").strip().rstrip("/")
    if not base:
        raise NoServiceEndpoint(
            f"no API base is configured, so {agent}'s card cannot name a service "
            "endpoint — and a card with no endpoint fails erc8004.assess(), which "
            "is this project's own test for whether an agent is real. Run "
            "`make api-config` with MISQUOTE_API_BASE set."
        )

    document: dict[str, object] = {
        # `is_erc8004_shaped` matches on the prefix of this exact string.
        "type": ERC8004_SCHEMA,
        "name": name,
        "description": description,
        # `declares_active`. An agent that omits this is read as saying "do not
        # hire me", which is the correct default and the wrong claim for us.
        "active": True,
        "services": [
            {
                "name": "journal",
                "endpoint": f"{base}/journal/{agent}",
                "description": "Every decision this agent recorded, with its inputs.",
            }
        ],
        # Becomes `avatarUrl` on a listing. See `CARD_IMAGE`.
        "image": CARD_IMAGE,
        "x402Support": X402_SUPPORTED,
        # Not read by `assess()`. Carried because a card is the only thing a
        # third party sees, and an agent whose method is unstated is the kind of
        # listing this project exists to argue against.
        "url": "https://misquote.vercel.app/agent?id=" + agent,
        "documentation": "https://misquote.vercel.app/methods",
    }

    if agent_id is not None:
        document["registrations"] = [registration_entry(agent_id, chain_id)]

    uri = as_data_uri(document)
    card = Card(agent=agent, name=name, document=document, token_uri=uri)
    if card.uri_bytes > MAX_URI_BYTES:
        raise ValueError(
            f"{agent}'s card is {card.uri_bytes} bytes, over the {MAX_URI_BYTES} "
            "byte tripwire. This is written to chain once and cannot be edited; "
            "shorten the description rather than raising the limit."
        )
    return card


def build_cards(
    *, api_base: str, ids: dict[str, int] | None = None, chain_id: int = 97
) -> tuple[Card, ...]:
    """All four, in listing order.

    `ids` maps agent slug to its registry id, for the complete cards written
    after registration. Omitted, these are the pre-registration cards.
    """
    ids = ids or {}
    return tuple(
        build_card(agent, name, why, api_base=api_base, agent_id=ids.get(agent), chain_id=chain_id)
        for agent, name, why in AGENTS
    )
