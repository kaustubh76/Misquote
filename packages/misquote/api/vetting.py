"""The due-diligence badges, and an honest answer for pools that have none.

`vetting/badges/<address>.json` is written by `make vet`, which reads each pool
from chain and runs the nine checks in `vetting/badge.py`. Those files are
already published — `vetting.json` aggregates them and `/vetting` renders it.
What that aggregate cannot do is answer "what about *this* address", which is
the question a reader arrives with when they are looking at a pool.

## Why there is no live-read parameter

An earlier draft of this took `?refresh=1` and called `vetting.read.badge_for`
against a live RPC. It is not here, for a reason worth recording: a badge is
nine chain readings taken at one block, and `read_pool` degrades field by field
when an endpoint refuses — `_try` returns `None` and the badge downgrades rather
than failing. Served from an HTTP handler with a 15-second RPC timeout on a free
tier, that produces a *different, weaker* badge than `make vet` produced, at the
same URL, with nothing in the response saying which one you got.

Recorded badges say when they were taken and what took them. Regenerating one is
`make vet`, which is a deliberate act with a commit attached.
"""

from __future__ import annotations

import json
from typing import Any

from misquote.api.errors import refuse
from misquote.api.locations import REPO
from misquote.chain.addresses import known_pools_on, pool_by_address

#: Where `make vet` writes. Read per call so a test can point it elsewhere.
BADGES = REPO / "vetting" / "badges"

DEFAULT_CHAIN_ID = 56


def badge_names() -> list[str]:
    """Every address with a recorded badge, lowercased, sorted."""
    if not BADGES.is_dir():
        return []
    return sorted(p.stem.lower() for p in BADGES.glob("*.json"))


def vetting() -> dict[str, Any]:
    """Which pools have a badge, and which verified pools do not.

    The second half is the part worth serving. A list of what we checked reads
    as completeness; the pools we know about and have *not* checked are the
    thing a reader cannot otherwise discover, and `go_no_go.py` treats an
    unbadged known pool as amber for exactly that reason.
    """
    recorded = badge_names()
    known = [ref.address.lower() for ref in known_pools_on(DEFAULT_CHAIN_ID)]
    return {
        "directory": str(BADGES),
        "badged": recorded,
        "known_pools": known,
        "known_and_unbadged": [address for address in known if address not in recorded],
        "note": (
            "A badge is nine readings taken at one block by `make vet`, not a live "
            "check. An unbadged pool has not been examined — that is an absence, "
            "not a clean bill of health."
        ),
    }


def badge(address: str) -> dict[str, Any]:
    """One pool's recorded badge, or a refusal that distinguishes the two ways it can be missing."""
    wanted = address.lower()
    recorded = badge_names()

    if wanted not in recorded:
        # Two different absences, and collapsing them would be the mistake this
        # whole surface exists to avoid: a pool we verified and never vetted is
        # a gap in our own work, and a pool we never verified is a refusal to
        # index it at all.
        try:
            pool_by_address(wanted)
        except ValueError:
            raise refuse(
                404,
                error=f"no verified pool at {address!r}",
                remedy="record it in chain/addresses.py and run `make vet`",
                available=recorded,
                note=(
                    "This address is not one this repository has read. It has no badge "
                    "because nothing has ever looked at it."
                ),
            ) from None

        raise refuse(
            404,
            error=f"no badge recorded for {address!r}",
            remedy="make vet",
            available=recorded,
            note=(
                "This is a pool this repository has verified and not vetted. The "
                "absence is ours, and `make go-no-go` reports it as amber."
            ),
        )

    path = BADGES / f"{wanted}.json"
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise refuse(
            503,
            error=f"{path.name} is on disk and could not be read: {error}",
            remedy="make vet",
            note="An emitter may be writing it. This is a transient state, not a failure.",
        ) from error
