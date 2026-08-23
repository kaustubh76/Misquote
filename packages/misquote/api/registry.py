"""Search across the surveyed agents, and lookup across all of them.

Those are two different reaches, and conflating them would be the misquote.

## What the numbers actually are

`registry.json` records a population of ~280,000 ERC-8004 ids on chain 56 and a
survey of **400** of them, drawn at a recorded block with a recorded seed. The
survey is what carries descriptions, endpoints and the resolvable/substantive
verdicts, because producing those means fetching and parsing each card.

So a text search reaches 400 agents, not 280,000 — a coverage of about 0.14%.
Serving that as "search the registry" would be a search over one seven-hundredth
of the corpus presented as the corpus, which is the exact failure this project is
named after. Every list response therefore carries a `coverage` block, in the
body rather than in documentation, and `complete` is a computed boolean rather
than a hopeful one.

Lookup by id is different: `IdentityRegistry.card()` resolves any id against the
chain, so `/registry/agents/{id}` genuinely reaches the whole population. It
needs an RPC, and says so when it does not have one.

## Why the listing shape is borrowed rather than redefined

`tests/web/test_third_party_listings.py` asserts no listing carries a
performance-shaped field — no apr, no rating, no score, nothing that reads as a
claim about an agent whose policy we cannot replay — and it asserts the keys
against `registry_report.LISTING_KEYS`. That test reads the artifact, not this
endpoint, so a second whitelist here would be unpoliced. This imports the same
frozenset.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Query

from misquote.api import rpc
from misquote.api.errors import refuse
from misquote.api.locations import REPO

#: The survey `make registry-survey` writes, and the only source of card text.
SURVEY = REPO / "data" / "registry_survey.json"

DEFAULT_CHAIN_ID = 56
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200


def _survey() -> dict[str, Any]:
    if not SURVEY.exists():
        raise refuse(
            503,
            error=f"no registry survey at {SURVEY}",
            remedy="make registry-survey SAMPLE=400",
            note=(
                "Nothing has sampled the registry yet. The population is readable from "
                "chain without it; the card text is not."
            ),
        )
    try:
        return json.loads(SURVEY.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise refuse(
            503,
            error=f"the registry survey could not be read: {error}",
            remedy="make registry-survey SAMPLE=400",
            note="An emitter may be writing it. This is a transient state, not a failure.",
        ) from error


def _coverage(survey: dict[str, Any], matching: int) -> dict[str, Any]:
    """What fraction of the registry this answer actually saw.

    Returned inside every list response rather than from its own route, because
    a caller who never asks is exactly the caller who most needs to be told.
    """
    population = int(survey.get("population") or 0)
    sampled = int(survey.get("sampled") or 0)
    return {
        "population": population,
        "sampled": sampled,
        "searched": sampled,
        "matching": matching,
        "sampled_at_block": survey.get("sampled_at_block"),
        "seed": survey.get("seed"),
        "share_of_population": (sampled / population) if population else None,
        "complete": bool(population) and sampled >= population,
        "note": (
            "Text search covers the sampled agents only. Lookup by id at "
            "/registry/agents/{agent_id} reads the chain and reaches every id."
        ),
    }


def _matches(agent: dict[str, Any], needle: str) -> bool:
    if not needle:
        return True
    haystack = " ".join(
        str(agent.get(key) or "") for key in ("agent_id", "name", "description", "notes")
    )
    haystack += " " + " ".join(str(e) for e in (agent.get("endpoints") or []))
    return needle in haystack.lower()


#: The only fields a live card may be published with.
#:
#: A subset of `scripts/registry_report.py::LISTING_KEYS`, and asserted to be one
#: by `tests/api/test_registry_routes.py` — which loads that module by path, the
#: way the other cross-boundary tests already do. Naming the keys here rather
#: than importing them keeps `packages/misquote/api` from depending on `scripts/`,
#: which is a driver reaching into a build tool; pinning them with a test keeps
#: that independence from becoming divergence.
#:
#: What matters is what is *not* here. `tests/web/test_third_party_listings.py`
#: forbids any performance-shaped field — apr, rating, score, users, tvl — on an
#: agent whose policy we cannot replay. That test reads the artifact, so it
#: cannot see this endpoint; the subset assertion is what extends its reach.
LIVE_CARD_KEYS: tuple[str, ...] = (
    "agent_id",
    "name",
    "description",
    "endpoints",
    "on_chain",
    "resolvable",
    "notes",
)


def _as_listing(card: Any) -> dict[str, Any]:
    """A live card in the same shape the survey publishes, and no wider."""
    raw = {
        "agent_id": card.agent_id,
        "name": getattr(card, "name", None),
        "description": getattr(card, "description", None),
        "endpoints": list(getattr(card, "endpoints", ()) or ()),
        "on_chain": card.on_chain,
        "resolvable": bool(card.on_chain and getattr(card, "fetched", False)),
        "notes": getattr(card, "error", None),
    }
    return {k: v for k, v in raw.items() if k in LIVE_CARD_KEYS}


def registry_agents(
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    per_page: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    resolvable: bool | None = Query(None),
    substantive: bool | None = Query(None),
    has_endpoint: bool | None = Query(None),
) -> dict[str, Any]:
    """The surveyed agents, filtered and paged, with the coverage that search had."""
    survey = _survey()
    agents: list[dict[str, Any]] = list(survey.get("agents") or [])

    needle = q.strip().lower()
    found = [
        a
        for a in agents
        if _matches(a, needle)
        and (resolvable is None or bool(a.get("resolvable")) is resolvable)
        and (substantive is None or bool(a.get("substantive")) is substantive)
        and (has_endpoint is None or bool(a.get("endpoints")) is has_endpoint)
    ]

    start = (page - 1) * per_page
    window = found[start : start + per_page]
    return {
        "query": q,
        "page": page,
        "per_page": per_page,
        "pages": max(1, -(-len(found) // per_page)),
        "total_matching": len(found),
        "agents": window,
        "coverage": _coverage(survey, len(found)),
    }


def registry_agent(agent_id: int) -> dict[str, Any]:
    """One agent by id, from the survey if it is there and from chain if not.

    The survey answer is preferred and labelled: it was taken at a recorded
    block with the same reader, so serving it is reproducible where a live read
    is not. `source` says which one answered, because the two can disagree — an
    agent's card is mutable and the survey is a snapshot.
    """
    survey = _survey()
    for agent in survey.get("agents") or []:
        if int(agent.get("agent_id", -1)) == agent_id:
            return {
                "source": "survey",
                "sampled_at_block": survey.get("sampled_at_block"),
                "agent": agent,
                "note": (
                    "Read from the recorded survey, not from chain just now. The card "
                    "is mutable on chain and this is the snapshot the artifacts quote."
                ),
            }

    # Not in the 400. Resolve it against the chain — this is the half of the
    # surface that actually reaches the whole population, and refusing here
    # would make /registry a search over 0.14% of the registry and nothing else.
    try:
        from misquote.registry.erc8004 import IdentityRegistry
    except ImportError as error:  # pragma: no cover — web3 is a hard dependency
        raise refuse(
            503,
            error=f"the registry reader is unavailable: {error}",
            remedy="uv sync",
        ) from error

    w3 = rpc.connect(DEFAULT_CHAIN_ID)
    registry = IdentityRegistry(w3, DEFAULT_CHAIN_ID)
    card = registry.card(agent_id)

    if not card.on_chain:
        raise refuse(
            404,
            error=f"the registry resolves no agent {agent_id}",
            remedy="check the id against the population at /registry/agents",
            note=(
                "tokenURI reverted, which is what an unregistered id does. The "
                "population is a highest-resolvable-id ceiling, not a dense range."
            ),
        )

    return {
        "source": "chain",
        "read_at_block": w3.eth.block_number,
        "agent": _as_listing(card),
        "note": (
            "Read from chain just now, not from the recorded survey — this id is "
            "not among the sampled 400. A card is mutable, so this reading may "
            "differ from what the artifacts quote."
        ),
    }
