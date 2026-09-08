"""Put the agents up for sale on TermiX, and record which of them are.

    uv run python scripts/termix_listing.py                     # plan all, send nothing
    uv run python scripts/termix_listing.py --agent grid        # plan one
    uv run python scripts/termix_listing.py --create            # one POST per listable agent
    uv run python scripts/termix_listing.py --publish <id>      # take a draft live
    uv run python scripts/termix_listing.py --out               # record the state

## Why a flag rather than MISQUOTE_DRY_RUN

The same asymmetry `termix_login.py` names. `MISQUOTE_DRY_RUN` guards the
scripts that spend gas, and a listing spends none — so no environment variable
covers this one and the guard is at the call site instead. `--create` and
`--publish` are separate because the API separates them: creation leaves a draft
that can be read back and deleted, publication is what a buyer can see.

## What it will not do

Offer work the deployed service cannot produce. Every spec in
`registry/listings.py` names a live route, this reads that route first, and an
agent whose route does not answer is refused by name with the reason printed.
That is why `router` is in the registry and is never listed: nothing on the
service produces a venue comparison, so a listing for one would be a promise we
already know is false.

It also refuses an agent that already has a service, rather than creating a
second — a marketplace holding two of the same listing is the state this script
exists to avoid producing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

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
API_ARTIFACT = REPO / "apps" / "web" / "public" / "artifacts" / "api.json"


def service_api_base() -> str:
    """Where the deliverable comes from. Read, not assumed."""
    base = json.loads(API_ARTIFACT.read_text()).get("base")
    if not base:
        raise SystemExit("api.json records no live API base; nothing could deliver an order")
    return str(base).rstrip("/")


def probe(spec: listings.Listing) -> dict[str, Any] | None:
    """The live reading behind one listing, or None if the route will not answer."""
    if not spec.probe_path:
        return None
    try:
        response = httpx.get(service_api_base() + spec.probe_path, timeout=90)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        print(f"  probe failed: {type(error).__name__}: {str(error)[:120]}")
        return None


def connect() -> Web3:
    """A chain connection, only because `BscSigner` requires one to exist."""
    w3 = Web3(Web3.HTTPProvider("https://bsc-dataseed.bnbchain.org", request_kwargs={"timeout": 25}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--agent", choices=sorted(listings.SPECS), help="just this one")
    ap.add_argument("--create", action="store_true", help="send one POST per listable agent")
    ap.add_argument("--publish", metavar="LISTING_ID", help="take an existing draft live")
    ap.add_argument(
        "--sync",
        action="store_true",
        help="PATCH every live listing to match its spec, in place, field by field",
    )
    ap.add_argument("--out", nargs="?", const=str(RECORD), help="write the evidence record")
    args = ap.parse_args(argv)

    key = os.environ.get("MISQUOTE_OPERATOR_PRIVATE_KEY")
    if not key:
        raise SystemExit("MISQUOTE_OPERATOR_PRIVATE_KEY is not exported")

    chosen = [args.agent] if args.agent else list(listings.SPECS)
    print(f"platform  {api_base(BSC_MAINNET)}")
    print(f"service   {service_api_base()}")

    signer = BscSigner(connect(), key)
    client = auth.TermixSession(signer, BSC_MAINNET)
    client.authenticate()
    print(f"wallet    {signer.address}  (authenticated)\n")

    plans: list[tuple[listings.Listing, dict[str, Any], dict[str, Any]]] = []
    refused: list[tuple[str, str]] = []

    for slug in chosen:
        spec = listings.SPECS[slug]
        print(f"--- {slug} · {spec.name} · ERC-8004 token {spec.token_id} ---")

        if not spec.probe_path:
            print(f"  REFUSED: {spec.blocked}\n")
            refused.append((slug, spec.blocked))
            continue

        existing = listings.services(client, spec.agent_id)
        count = len(existing.get("items") or [])
        reading = probe(spec)
        if reading is None:
            why = f"{spec.probe_path} did not answer, so delivery is unproven"
            print(f"  REFUSED: {why}\n")
            refused.append((slug, why))
            continue

        body = listings.service_body(spec, reading)
        print(f"  probe     {spec.probe_path} answered")
        print(f"  title     {spec.title}")
        print(f"  price     {spec.price_usdc} USDC · {spec.delivery_days} day")
        print(f"  category  {spec.category}")
        print(f"  before    {count} service(s) on this agent")

        if count:
            why = f"already has {count} service(s); creating another would duplicate it"
            print(f"  SKIPPED: {why}\n")
            refused.append((slug, why))
            continue
        plans.append((spec, body, existing))
        print()

    print(f"listable: {len(plans)}   refused: {len(refused)}")

    if not (args.create or args.publish or args.sync or args.out):
        for spec, body, _ in plans:
            print(f"\n--- body for {spec.slug} ---")
            print(json.dumps(body, indent=2)[:900])
        print("\nNothing was sent. `--create` posts them; `--publish <id>` takes a draft live.")
        return 0

    created: dict[str, Any] = {}
    if args.create:
        for spec, body, _ in plans:
            reply = listings.create_service(client, spec, body)
            print(f"\ncreate {spec.slug} -> {json.dumps(reply)[:500]}")
            if isinstance(reply, dict) and reply.get("error"):
                print("  Refused. The message names what the body is missing.")
                continue
            created[spec.slug] = reply

    if args.publish:
        reply = listings.publish(client, args.publish)
        print(f"\npublish -> {json.dumps(reply)[:500]}")

    if args.sync:
        # In place, by id. Deleting and recreating would mint a new id, and the
        # id is what the evidence record and every link already name.
        #
        # Only the fields that actually differ are sent. A PATCH that rewrites
        # everything every time makes `updatedAt` move for no reason, which is
        # the field a reader uses to tell when the listing last really changed.
        for slug in chosen:
            spec = listings.SPECS[slug]
            if not spec.probe_path:
                continue
            for item in listings.services(client, spec.agent_id).get("items") or []:
                patch = listings.drift(spec, item)
                if not patch:
                    print(f"  {slug:9} already matches its spec")
                    continue
                reply = listings.update_listing(client, item["id"], patch)
                ok = not (isinstance(reply, dict) and reply.get("error"))
                shown = ", ".join(f"{k}={v!r}" for k, v in patch.items())
                print(f"  {slug:9} {shown[:110]}  {'ok' if ok else json.dumps(reply)[:200]}")

    # Read back rather than trusting the create response: the claim is that the
    # listing is *live*, and only the server can say that. `status` is what
    # separates a draft nobody can see from a thing a buyer can buy.
    live: dict[str, list[dict[str, Any]]] = {}
    for slug in chosen:
        spec = listings.SPECS[slug]
        if not spec.probe_path:
            continue
        live[slug] = [
            {
                "listing_id": item.get("id"),
                "status": item.get("status"),
                "base_price": item.get("basePrice"),
                "currency": item.get("currency"),
                "published_at": item.get("publishedAt"),
            }
            for item in (listings.services(client, spec.agent_id).get("items") or [])
        ]
    after = {slug: len(rows) for slug, rows in live.items()}
    print(f"\nafter     {after}")
    for slug, rows in live.items():
        for row in rows:
            print(f"  {slug:9} {row['listing_id']}  {row['status']}  {row['base_price']} {row['currency']}")

    if args.out:
        record = {
            "platform": api_base(BSC_MAINNET),
            "service": service_api_base(),
            "wallet": signer.address,
            "agents": {
                slug: {
                    "platform_id": spec.agent_id,
                    "erc8004_token_id": spec.token_id,
                    "name": spec.name,
                    "title": spec.title,
                    # A string, for the same reason the wire wants one: a
                    # Decimal is not JSON, and a float would put 0.15 into the
                    # record as 0.15000000000000002.
                    "price_usdc": str(spec.price_usdc),
                    "delivery_days": spec.delivery_days,
                    "category": spec.category,
                    "proved_by": spec.probe_path,
                }
                for slug, spec in listings.SPECS.items()
                if spec.probe_path
            },
            "refused": dict(refused),
            "services_after": after,
            "listings": live,
            "created": created,
            "read_at": int(time.time()),
            # The rule `termix-auth.json` sets: the bearer token is a credential
            # and this file is evidence, not a way to repeat the run.
            "token_recorded": False,
        }
        Path(args.out).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
