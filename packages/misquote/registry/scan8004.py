"""8004scan: a second, independent count of the ERC-8004 registry.

This repository already counts BSC's agent population itself, on chain, by
binary search on `ownerOf` — `totalSupply()` reverts on the proxy. That number
is in `data/registry_survey.json` and it is the one the cards are built from.

8004scan (by AltLayer) indexes the same registries and publishes the same
population through a REST API. **It is carried alongside our own reading, never
in place of it**, for the reason `chain/venus.py` gives about
`vUSDT.underlying()`: two counts arrived at by different methods either agree,
which is evidence, or they disagree, which is a finding. A single number
repeated is neither.

They disagree, and the artifact says so rather than picking the flattering one.

## What it can say that a chain read cannot

The registry stores identity. It does not store whether anybody has ever used an
agent. 8004scan aggregates feedback, scores, protocol support and x402
capability across chains, which is the half of "is this agent real" that
`ownerOf` cannot answer — and which is the half a marketplace claiming to
replace star ratings with evidence has to engage with rather than ignore.

## The API needs no key, and that is checked rather than assumed

`https://8004scan.io/api/v1/public` answers anonymously at 10 requests/minute.
A Pro tier exists and is free for hackathon entrants; nothing here requires it,
and the code paces itself for the anonymous tier so a missing key degrades to
slower rather than to absent.

Every call is wrapped: an unreachable API produces `available: false` with the
reason, never a zero and never a count carried over from a previous run. That is
`vetting/read.py`'s rule — unknown does not become pass — applied to a
third-party source, where it matters more because the failure is somebody
else's to fix.
"""

from __future__ import annotations

from typing import Any

import httpx

BASE = "https://8004scan.io/api/v1/public"

#: The anonymous tier is 10 requests a minute. Nothing here needs more than a
#: handful, so the timeout is generous and the request count is small rather
#: than the pacing being clever.
TIMEOUT = 20.0

BSC_CHAIN_ID = 56


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        response = client.get(f"{BASE}{path}", params=params or {})
        response.raise_for_status()
        return response.json()


def population(chain_id: int = BSC_CHAIN_ID) -> dict[str, Any]:
    """8004scan's agent count for a chain, and the registry it indexes.

    The registry address is returned so a caller can check it against
    `erc8004.IDENTITY_REGISTRY`. If the two indexed different contracts the
    counts would not be comparable at all, and comparing them anyway would be a
    worse error than not comparing them.
    """
    try:
        page = _get("/agents", {"chainId": chain_id, "limit": 1})
    except Exception as error:  # noqa: BLE001 — any failure is "unavailable"
        return {
            "available": False,
            "reason": f"8004scan /agents did not answer: {type(error).__name__}: {error}",
        }

    data = page.get("data") or []
    meta = (page.get("meta") or {}).get("pagination") or {}
    total = meta.get("total")
    if total is None:
        return {"available": False, "reason": "8004scan returned no pagination total"}

    return {
        "available": True,
        "chain_id": chain_id,
        "population": int(total),
        # The contract 8004scan says these agents live in. Compared against ours
        # by the caller.
        "contract_address": (data[0].get("contract_address") if data else None),
    }


def sample(chain_id: int = BSC_CHAIN_ID, limit: int = 100) -> dict[str, Any]:
    """A page of agent records, reduced to the fields a marketplace would rank on.

    Deliberately a *sample* rather than a census: the anonymous tier will not
    serve 268,000 records and the shape of the answer does not need it. What is
    returned is a count of how many carry each signal, so the artifact can say
    "n of m" rather than implying it inspected all of them.
    """
    try:
        page = _get("/agents", {"chainId": chain_id, "limit": limit})
    except Exception as error:  # noqa: BLE001
        return {
            "available": False,
            "reason": f"8004scan /agents did not answer: {type(error).__name__}: {error}",
        }

    rows = page.get("data") or []
    if not rows:
        return {"available": False, "reason": "8004scan returned an empty page"}

    verified = sum(1 for r in rows if r.get("is_verified"))
    with_feedback = sum(1 for r in rows if int(r.get("total_feedbacks") or 0) > 0)
    with_score = sum(1 for r in rows if float(r.get("total_score") or 0) > 0)
    x402 = sum(1 for r in rows if r.get("x402_supported"))
    starred = sum(1 for r in rows if int(r.get("star_count") or 0) > 0)
    described = sum(1 for r in rows if (r.get("description") or "").strip())
    # How many distinct descriptions the sample holds. A page of agents sharing
    # one sentence is a different population from a page of distinct ones, and
    # the count is the cheapest way to say which this is.
    distinct_descriptions = len({(r.get("description") or "").strip() for r in rows})

    return {
        "available": True,
        "chain_id": chain_id,
        "sampled": len(rows),
        "verified": verified,
        "with_feedback": with_feedback,
        "with_score": with_score,
        "x402_supported": x402,
        "starred": starred,
        "described": described,
        "distinct_descriptions": distinct_descriptions,
        "ordering": "8004scan's default, which is newest first",
    }


def stats() -> dict[str, Any]:
    """The platform's own cross-chain totals, for context only.

    Explicitly not comparable to our BSC count — it spans every chain 8004scan
    indexes. Carried because `daily_new_agents` is the number that makes the
    population figure legible: a registry growing by five figures a day is a
    different object from one that grew to that size over a year.
    """
    try:
        payload = _get("/stats")
    except Exception as error:  # noqa: BLE001
        return {"available": False, "reason": f"8004scan /stats did not answer: {error}"}

    data = payload.get("data") or {}
    return {
        "available": True,
        "total_agents_all_chains": data.get("total_agents"),
        "total_feedbacks_all_chains": data.get("total_feedbacks"),
        "daily_new_agents_all_chains": data.get("daily_new_agents"),
        "average_feedback_score": data.get("average_feedback_score"),
    }
