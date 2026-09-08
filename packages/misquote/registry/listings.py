"""What Warden sells on TermiX, and the reads that say whether it is selling.

## The gap this closes

TermiX's explorer indexes every ERC-8004 mint — 340,954 of them across 17,048
pages — so our five agents appeared there the moment they were minted and it
meant nothing. `vetting/identity/termix-listing-56.json` answers "does a mainnet
mint list us"; **yes**, and being listed is not being open for business.

A seller on that marketplace sells a *listing*. Without one an agent cannot be
ordered from, cannot quote on an open brief, and cannot claim a campaign slot —
which is exactly the state the five were in: `completedJobs: 0`, `stake: "0"`,
`services: {"items": []}`, indistinguishable from the other 340,949.

## Why Warden, and why this text

Warden is the only one of the five with a delivery path that is up: the live API
serves `POST /quote` and `/worker` reports `workers_alive: 1` draining the
queue. A listing is a promise to deliver, and a listing that promises what its
seller cannot produce is the misquote this project is named after, sold on a
marketplace rather than merely published on a site.

So the copy names three things a buyer can check before paying: the pools it can
answer for, the tape behind them, and **the refusal**. `/quote/preflight`
publishes all three and will say `quotable: false` with a reason the day a pool
stops clearing the floor. Nothing here is written as marketing that the
preflight cannot back.

## What is deliberately not here

No stake. Sellers carry one and ours is `"0"`, which is visible and honest;
buying reputation with a deposit is a different decision and belongs to whoever
funds the wallet, not to this module.
"""

from __future__ import annotations

from typing import Any

#: The agent this sells for: Warden-3, ERC-8004 token 331592 on BSC mainnet.
#:
#: Not 323262 and not 331590, and the difference is recorded rather than
#: remembered. TermiX attributes an agent to the wallet that **minted** it, so
#: 323262 — minted by a delegate and transferred to the operator — is owned by
#: us and invisible to their index. 331590 is an unintended duplicate from a run
#: that was recorded as "nothing was sent" after a 403 on the *receipt read*,
#: which is not the same as nothing having been broadcast.
#: `vetting/identity/termix-listing-56.json` carries both findings.
WARDEN_AGENT_ID = "cmtl14z110cy8x901uxqdic1o"
WARDEN_TOKEN_ID = "331592"

#: Their enum, and it is the **label**, not the `slug` that
#: `/api/v1/service-categories` returns beside it. A body sent with `"research"`
#: is refused with the eight labels listed; discovered that way rather than
#: guessed, the way `WALLET_FIELDS` was.
CATEGORY = "Market & Protocol Research"

#: 25 USDC, and the number is not plucked. `/api/v1/listings/price-range` reports
#: the platform spanning 0.01 to 150,250 USDC over 567 listings, and the open
#: briefs in `/api/v1/prepayment-orders/discover` that ask for comparable
#: analysis sit between 21 and 103. This is an automated replay against a tape
#: that already exists, so it belongs at the bottom of that band rather than in
#: the middle of it.
PRICE_USDC = 25

#: The queue is drained by a worker, not by a person, and a replay of twenty
#: windows is minutes. One day is the honest ceiling with the API's cold start
#: in it, not a padded estimate.
DELIVERY_DAYS = 1

TITLE = "Liquidity position risk quote, replayed on real PancakeSwap swaps"

#: The pools `/quote/preflight` currently answers `quotable: true` for, with the
#: tape behind each. Read from the live service rather than hardcoded into the
#: copy — see `pool_lines`.
PREFLIGHT_PATH = "/quote/preflight"


def pool_lines(preflight: dict[str, Any]) -> list[str]:
    """One line per pool the service will actually quote, from its own preflight.

    The listing names the pools because a buyer who orders against a pool we
    cannot replay has bought a refusal. Generated from the live reading so the
    copy cannot outlive it: a pool that stops clearing the evidence floor drops
    out of this list the next time the listing is written, rather than staying
    in the sales text because nobody reread it.
    """
    lines: list[str] = []
    for pool in preflight.get("pools", []):
        if not pool.get("quotable"):
            continue
        tape = pool.get("tape") or {}
        swaps, hours = tape.get("swaps"), tape.get("hours")
        lines.append(f"- {pool.get('label')} — {swaps:,} swaps over {hours:g}h of tape")
    return lines


def description(preflight: dict[str, Any]) -> str:
    """The listing body. Every claim in it is one `/quote/preflight` supports."""
    pools = pool_lines(preflight) or ["- (no pool currently clears the evidence floor)"]
    return "\n".join(
        [
            "Give me a PancakeSwap v3 position — a wallet address, or a pool with a "
            "range and a size — and I return what it would have done, replayed "
            "swap by swap over recorded BNB Smart Chain history.",
            "",
            "**What you get**",
            "",
            "- The share of time the position was in range, and the fees it accrued.",
            "- Impermanent loss against simply holding.",
            "- Twenty overlapping windows, reported as a P25-P75 band rather than "
            "one number, so you can see the spread and not just the median.",
            "- The decision journal behind it: every window, and the ones that "
            "were withheld.",
            "",
            "**Pools I can answer for today**",
            "",
            *pools,
            "",
            "**What you get instead of a number, when the evidence is thin**",
            "",
            "A refusal that names what is missing. If a pool's tape does not cover "
            "at least twenty windows of twenty-four hours, I will not quote it, and "
            "I will tell you that rather than interpolate a figure that looks "
            "precise. You can check this before ordering: the preflight at "
            "`/quote/preflight` on the service publishes every pool's coverage and "
            "its verdict, and it is a public read.",
            "",
            "**How to verify me before you pay**",
            "",
            "Everything behind this is published and third-party checkable: the "
            "agent's ERC-8004 identity is token "
            f"{WARDEN_TOKEN_ID} on BSC mainnet, and the replays, the tape coverage "
            "and the refusals are all readable without my cooperation.",
        ]
    )


def service_body(preflight: dict[str, Any]) -> dict[str, Any]:
    """The body for `POST /api/v1/agents/{id}/services`.

    Only `title` and `category` are known-required — the server validates one
    field at a time and named those two first. The rest are sent because a
    listing without a price or a delivery window is not a thing a buyer can act
    on, and an unknown key is refused loudly (`Unrecognized key(s)`), which is
    the good failure: it names itself.
    """
    return {
        "title": TITLE,
        "category": CATEGORY,
        "description": description(preflight),
        "price": PRICE_USDC,
        "currency": "USDC",
        "deliveryDays": DELIVERY_DAYS,
        "tags": ["DeFi", "Liquidity", "Risk Analysis"],
    }


def services(session, agent_id: str = WARDEN_AGENT_ID) -> dict[str, Any]:
    """What this agent already sells. `{"items": []}` is the before state."""
    return session.get(f"/api/v1/agents/{agent_id}/services")


def create_service(session, body: dict[str, Any], agent_id: str = WARDEN_AGENT_ID) -> Any:
    """One POST. Returns the response whether it validated or not.

    A `400` here is the useful answer, not an error: it names the field the body
    is missing, which is how the rest of this schema gets discovered. The caller
    decides whether to retry, because retrying in a loop is how a marketplace
    ends up holding six draft listings nobody meant to create.
    """
    return session.post(f"/api/v1/agents/{agent_id}/services", body)


def publish(session, listing_id: str) -> Any:
    """Take a draft live. Separate from creation because the API separates them.

    Two calls means a draft can be read back and deleted before anyone sees it,
    which is the only reason this is safe to run against production at all.
    """
    return session.post(f"/api/v1/listings/{listing_id}/publish", {})


__all__ = [
    "CATEGORY",
    "DELIVERY_DAYS",
    "PREFLIGHT_PATH",
    "PRICE_USDC",
    "TITLE",
    "WARDEN_AGENT_ID",
    "WARDEN_TOKEN_ID",
    "create_service",
    "description",
    "pool_lines",
    "publish",
    "service_body",
    "services",
]
