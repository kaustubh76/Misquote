"""Put Warden up for sale on TermiX, and record that it is.

    uv run python scripts/termix_listing.py                   # plan it, send nothing
    uv run python scripts/termix_listing.py --create          # one POST, a draft
    uv run python scripts/termix_listing.py --publish <id>    # take the draft live
    uv run python scripts/termix_listing.py --out             # record the state

## Why a flag rather than MISQUOTE_DRY_RUN

The same asymmetry `termix_login.py` names. `MISQUOTE_DRY_RUN` guards the
scripts that spend gas, and a listing spends none — so no environment variable
covers this one and the guard is at the call site instead. `--create` and
`--publish` are separate because the API separates them: creation leaves a draft
that can be read back and deleted, publication is what a buyer can see.

## What it will not do

Publish something the delivery path cannot serve. `--create` reads
`/quote/preflight` on the live API first and refuses if no pool clears the
evidence floor, because the listing's central claim is a list of pools it can
answer for. A marketplace listing is a promise; this is the one check that keeps
it from being a promise we already know is false.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))

from misquote.chain.signer import BscSigner  # noqa: E402
from misquote.registry import authenticate as auth  # noqa: E402
from misquote.registry import listings  # noqa: E402
from misquote.registry.aacp import BSC_MAINNET, api_base  # noqa: E402

RECORD = REPO / "vetting" / "identity" / "termix-listing-live-56.json"

#: Where the deliverable actually comes from. Read, not assumed: a listing whose
#: seller cannot serve a quote is the failure this whole script is arranged
#: around.
API_ARTIFACT = REPO / "apps" / "web" / "public" / "artifacts" / "api.json"


def service_api_base() -> str:
    base = json.loads(API_ARTIFACT.read_text()).get("base")
    if not base:
        raise SystemExit("api.json records no live API base; nothing could deliver an order")
    return str(base).rstrip("/")


def preflight() -> dict:
    """The live service's own answer about what it can quote."""
    url = service_api_base() + listings.PREFLIGHT_PATH
    response = httpx.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def connect() -> Web3:
    """A chain connection, only because `BscSigner` requires one to exist."""
    w3 = Web3(Web3.HTTPProvider("https://bsc-dataseed.bnbchain.org", request_kwargs={"timeout": 25}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--create", action="store_true", help="send one POST, creating a draft")
    ap.add_argument("--publish", metavar="LISTING_ID", help="take an existing draft live")
    ap.add_argument("--out", nargs="?", const=str(RECORD), help="write the evidence record")
    args = ap.parse_args(argv)

    key = os.environ.get("MISQUOTE_OPERATOR_PRIVATE_KEY")
    if not key:
        raise SystemExit("MISQUOTE_OPERATOR_PRIVATE_KEY is not exported")

    plan = preflight()
    quotable = [p for p in plan.get("pools", []) if p.get("quotable")]
    body = listings.service_body(plan)

    print(f"platform  {api_base(BSC_MAINNET)}")
    print(f"agent     {listings.WARDEN_AGENT_ID}  (ERC-8004 token {listings.WARDEN_TOKEN_ID})")
    print(f"service   {service_api_base()}  — {len(quotable)} pool(s) quotable")
    for line in listings.pool_lines(plan):
        print(f"  {line}")
    print(f"price     {listings.PRICE_USDC} USDC · {listings.DELIVERY_DAYS} day")
    print(f"category  {listings.CATEGORY}")

    if not quotable:
        raise SystemExit(
            "\nrefusing: no pool clears the evidence floor, so the listing's own "
            "claim would be false on the day it went up."
        )

    signer = BscSigner(connect(), key)
    client = auth.TermixSession(signer, BSC_MAINNET)
    client.authenticate()
    print(f"wallet    {signer.address}  (authenticated)")

    before = listings.services(client)
    print(f"before    {len(before.get('items') or [])} service(s) on this agent")

    if not (args.create or args.publish or args.out):
        print("\n--- the body this would send ---")
        print(json.dumps(body, indent=2)[:1200])
        print("\nNothing was sent. `--create` posts it; `--publish <id>` takes a draft live.")
        return 0

    created: dict | None = None
    if args.create:
        reply = listings.create_service(client, body)
        print("\ncreate ->", json.dumps(reply)[:600])
        if isinstance(reply, dict) and reply.get("error"):
            print("\nRefused. The message names what the body is missing; fix it and re-run.")
            return 1
        created = reply if isinstance(reply, dict) else None

    if args.publish:
        reply = listings.publish(client, args.publish)
        print("\npublish ->", json.dumps(reply)[:600])
        if isinstance(reply, dict) and reply.get("error"):
            return 1

    after = listings.services(client)
    print(f"\nafter     {len(after.get('items') or [])} service(s) on this agent")

    if args.out:
        record = {
            "agent": {
                "platform_id": listings.WARDEN_AGENT_ID,
                "erc8004_token_id": listings.WARDEN_TOKEN_ID,
                "name": "Warden-3",
            },
            "wallet": signer.address,
            "platform": api_base(BSC_MAINNET),
            "endpoints": {
                "create": f"/api/v1/agents/{listings.WARDEN_AGENT_ID}/services",
                "publish": "/api/v1/listings/{id}/publish",
                "read_back": f"/api/v1/agents/{listings.WARDEN_AGENT_ID}/services",
            },
            "listing": {
                "title": listings.TITLE,
                "category": listings.CATEGORY,
                "price_usdc": listings.PRICE_USDC,
                "delivery_days": listings.DELIVERY_DAYS,
            },
            "delivery": {
                "service": service_api_base(),
                "route": "POST /quote",
                "quotable_pools": [
                    {
                        "pool": p.get("pool"),
                        "label": p.get("label"),
                        "swaps": (p.get("tape") or {}).get("swaps"),
                        "hours": (p.get("tape") or {}).get("hours"),
                    }
                    for p in quotable
                ],
            },
            "before": {"services": len(before.get("items") or [])},
            "after": {"services": len(after.get("items") or [])},
            "created": created,
            "read_at": int(time.time()),
            # The same rule `termix-auth.json` states: the bearer token is a
            # credential and this file is evidence, not a way to repeat the run.
            "token_recorded": False,
        }
        Path(args.out).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
