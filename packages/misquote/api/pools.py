"""Which PancakeSwap pool, at what width — served, with its refusals intact.

`make pools` writes `pools.json`; this serves it. The split is deliberate and is
the same one `api/vetting.py` argues for at length: the artifact is a measurement
taken over a 30-day tape at a known commit, and recomputing it inside an HTTP
handler would produce a *weaker* answer at the same URL with nothing in the
response saying which one you got.

The one thing this layer adds is the per-pool lookup. `pools.json` is a list, and
the question a reader actually arrives with is about one pool — usually the one
they already hold a position in.

## The refusals are the payload, not an error path

A pool with too little tape has no width ranking, and that is a result rather
than a failure: `verdict` says so in words and the row still carries its demand
figures. So an unquotable pool returns **200 with its refusal**, not a 4xx. A
reader asking about TSLAx/USDT — 85 swaps across the whole tape — should be told
that in the body they were going to read anyway.

404 is reserved for an address this deployment has never verified, and 503 for
the artifact being absent, which is a deployment fault rather than an answer.
"""

from __future__ import annotations

import json
from typing import Any

from misquote.api.errors import refuse
from misquote.api.locations import REPO
from misquote.chain.addresses import pool_by_address

ARTIFACT = REPO / "apps" / "web" / "public" / "artifacts" / "pools.json"


def _payload() -> dict[str, Any]:
    if not ARTIFACT.exists():
        raise refuse(
            503,
            error="no pool report has been published",
            remedy="make pools",
            note=(
                "The report is derived from the indexed tape and the recorded "
                "badges, so it exists only after `make indexer` and `make vet`."
            ),
        )
    try:
        return json.loads(ARTIFACT.read_text())
    except json.JSONDecodeError as error:
        # Half-written by a run that was interrupted. Transient, not absent.
        raise refuse(
            503,
            error=f"{ARTIFACT.name} is not readable JSON",
            remedy="make pools",
            note="A partially written artifact reads as corrupt rather than as empty.",
        ) from error


def pools() -> dict[str, Any]:
    """Every verified pool, its demand, and its width ladder where it has one."""
    return _payload()


def pool(address: str) -> dict[str, Any]:
    """One pool, by address.

    Resolved through `pool_by_address` first, so an address this deployment has
    never verified is a 404 before the artifact is even opened — the same rule
    `api/vetting.py` and `api/tape.py` follow. A ranking for a pool nobody
    checked is exactly what the badge gate exists to prevent.
    """
    try:
        ref = pool_by_address(address)
    except (KeyError, ValueError) as error:
        raise refuse(
            404,
            error=f"{address} is not a pool this deployment has verified",
            remedy="GET /pools for the ones it has",
            note=(
                "Addresses are not resolved dynamically. A pool reaches this list "
                "by being verified on chain and badged, never by being asked for."
            ),
        ) from error

    payload = _payload()
    for row in payload.get("pools", []):
        if row.get("address", "").lower() == ref.address.lower():
            return {
                "chain_id": payload.get("chain_id"),
                "capital_quote": payload.get("capital_quote"),
                "width_ladder": payload.get("width_ladder"),
                "build": payload.get("build"),
                **row,
            }

    raise refuse(
        503,
        error=f"{ref.label} is verified but absent from the published report",
        remedy="make pools",
        note="The artifact predates this pool being added to the verified set.",
    )
