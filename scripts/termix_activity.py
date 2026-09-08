"""Take part in the marketplace, so the dashboard stops reading zero.

    uv run python scripts/termix_activity.py              # read the counters, send nothing
    uv run python scripts/termix_activity.py --save       # bookmark listings we care about
    uv run python scripts/termix_activity.py --quote      # bid on one open brief
    uv run python scripts/termix_activity.py --brief      # post a request of our own
    uv run python scripts/termix_activity.py --buy <id>   # buy one listing
    uv run python scripts/termix_activity.py --out        # record before/after

## Why four flags and not one

Three of these spend or commit: a quote is a price we are held to, a brief
obligates us to pay whoever delivers, and a purchase moves money to a stranger.
`MISQUOTE_DRY_RUN` does not cover any of them — none is a chain write — so the
guard is at the call site, and they are separate because batching four
commitments behind one flag is how three of them get made by accident.

`--save` is the only free and reversible one, and it still has its own flag so
the default really does send nothing.

## What it will not do

Buy from ourselves. The dashboard would fill on both sides and the public jobs
feed would show it exactly as it shows every other order — one party hiring
another — which is demand we do not have. `--buy` refuses a listing belonging to
one of our own agents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
from misquote.registry import listings, marketplace  # noqa: E402
from misquote.registry.aacp import BSC_MAINNET, api_base  # noqa: E402

RECORD = REPO / "vetting" / "identity" / "termix-activity-56.json"

#: What makes a third-party listing worth bookmarking: it is about the thing
#: these agents are about. Matched on the listing's own words rather than a
#: hand-kept list, so the set moves as the marketplace does.
#:
#: Whole words, via a regex boundary. The first version matched the substrings
#: `" lp"` and `"v3 "`, which pulled in a speech-to-text listing through one of
#: its tags — harmless, and still four bookmarks that say nothing true about
#: what we do.
INTEREST = (
    "pancakeswap",
    "liquidity",
    "impermanent",
    "lp",
    "v3",
    "defi",
    "on-chain analytics",
    "amm",
)


def connect() -> Web3:
    w3 = Web3(Web3.HTTPProvider("https://bsc-dataseed.bnbchain.org", request_kwargs={"timeout": 25}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def public(path: str) -> dict[str, Any]:
    response = httpx.get(api_base(BSC_MAINNET) + path, timeout=60)
    response.raise_for_status()
    return response.json()


def ours() -> set[str]:
    return {spec.agent_id for spec in listings.SPECS.values()}


def interesting(limit: int = 4) -> list[dict[str, Any]]:
    """Third-party listings about our subject, cheapest first."""
    mine, found = ours(), []
    for page in range(1, 30):
        for item in public(f"/api/v1/listings?page={page}").get("items") or []:
            if (item.get("providerAgent") or {}).get("id") in mine:
                continue
            words = f"{item.get('title', '')} {' '.join(item.get('tags') or [])}".lower()
            if any(re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", words) for k in INTEREST):
                found.append(item)
        if len(found) >= limit:
            break
    return found[:limit]


def show(label: str, reply: Any) -> bool:
    """Print a reply and say whether it worked. A 400 names what is missing."""
    ok = not (isinstance(reply, dict) and reply.get("error"))
    print(f"  {label:22} {'ok' if ok else 'REFUSED'}  {json.dumps(reply)[:320]}")
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", action="store_true", help="bookmark the listings we care about")
    ap.add_argument("--quote", action="store_true", help="bid on the open brief we can serve")
    ap.add_argument("--brief", action="store_true", help="post our own request. Commits us to pay.")
    ap.add_argument("--buy", metavar="LISTING_ID", help="purchase one third-party listing")
    ap.add_argument(
        "--accept",
        metavar="OFFER_ID",
        help="accept an offer somebody made on our brief. Escrows its price.",
    )
    ap.add_argument("--out", nargs="?", const=str(RECORD), help="write the evidence record")
    args = ap.parse_args(argv)

    key = os.environ.get("MISQUOTE_OPERATOR_PRIVATE_KEY")
    if not key:
        raise SystemExit("MISQUOTE_OPERATOR_PRIVATE_KEY is not exported")

    signer = BscSigner(connect(), key)
    client = auth.TermixSession(signer, BSC_MAINNET)
    client.authenticate()
    print(f"platform  {api_base(BSC_MAINNET)}")
    print(f"wallet    {signer.address}  (authenticated)")

    before = marketplace.counters(marketplace.dashboard(client))
    print(f"\nbefore    {json.dumps(before)}")

    wallet = client.get("/api/v1/me/wallet/balance")
    usdc = ((wallet.get("balances") or {}).get("usdc") or {}).get("formatted")
    print(f"usdc      {usdc}")

    picks = interesting()
    print(f"\nlistings worth bookmarking ({len(picks)}):")
    for item in picks:
        print(f"  {str(item.get('basePrice')):>7} {item.get('currency')}  {str(item.get('title'))[:58]}")

    if not (args.save or args.quote or args.brief or args.buy or args.accept or args.out):
        print("\nNothing was sent. Each action has its own flag; three of them commit money.")
        return 0

    did: dict[str, Any] = {}

    if args.save:
        print("\nbookmarking:")
        saved = []
        for item in picks:
            if show(str(item.get("title"))[:20], marketplace.save_listing(client, item["id"])):
                saved.append(item["id"])
        did["saved"] = saved

    if args.quote:
        print("\nbidding on the impermanent-loss brief:")
        # `providerAgentId` is required and it is the interesting field: a bid
        # is made *by an agent*, not by an account, so the marketplace ties the
        # offer to the ERC-8004 identity that would do the work. Warden's, because
        # impermanent loss against holding is what its quote returns.
        body = {
            "providerAgentId": listings.SPECS["warden"].agent_id,
            "price": marketplace.IL_BID_USDC,
            "scope": marketplace.IL_SCOPE,
            "currency": "USDC",
            "deliveryDays": 1,
            "message": marketplace.IL_OFFER,
        }
        reply = marketplace.quote_on_brief(client, marketplace.IL_BRIEF_ID, body)
        if show("offer", reply):
            did["offer"] = reply

    if args.brief:
        print("\nposting our own brief:")
        # `clientAgentId` is required: a brief is posted *by an agent*, the same
        # way an offer is made by one. Sentinel's, because the four values being
        # re-read are the ones Sentinel's own listing publishes — the agent whose
        # work is under audit is the right one to be commissioning the audit.
        body = {
            "clientAgentId": listings.SPECS["sentinel"].agent_id,
            "title": marketplace.BRIEF_TITLE,
            "scope": marketplace.BRIEF_SCOPE,
            # A range, not a figure. The discover feed shows every brief with a
            # min and a max, and ours are the same number: the work is four
            # `eth_call`s and there is no scope to negotiate up into.
            "budgetMin": marketplace.BRIEF_BUDGET_USDC,
            "budgetMax": marketplace.BRIEF_BUDGET_USDC,
            # No `currency`: the endpoint refuses it as an unrecognised key.
            # Briefs are USDC-only, which the discover feed already showed on
            # every one of 822 of them.
            "proofMethod": "optimistic",
            "settlementType": "escrow",
        }
        reply = marketplace.create_brief(client, body)
        if show("brief", reply):
            did["brief"] = reply

    if args.buy:
        listing = public(f"/api/v1/listings/{args.buy}")
        if (listing.get("providerAgent") or {}).get("id") in ours():
            raise SystemExit(
                "refusing: that listing is one of ours. Buying from ourselves fills "
                "the dashboard and puts demand on the public feed that does not exist."
            )
        print(f"\nbuying  {str(listing.get('title'))[:60]}")
        print(f"        {listing.get('basePrice')} {listing.get('currency')} from "
              f"{(listing.get('seller') or {}).get('displayName')}")
        # `checkout/sessions` wants an `offerId`, not a `listingId`: on this
        # marketplace a purchase is always the acceptance of an *offer*, and a
        # listing is what gets a seller to make one. Buying a listing outright
        # therefore needs a conversation first, which needs the seller to
        # answer — so this reports rather than pretending it can force it.
        reply = marketplace.checkout(client, {"listingId": args.buy})
        if show("checkout", reply):
            did["checkout"] = reply

    if args.accept:
        brief = client.get(f"/api/v1/prepayment-orders/{marketplace.OUR_BRIEF_ID}")
        offer = next((o for o in brief.get("offers") or [] if o.get("id") == args.accept), None)
        if offer is None:
            raise SystemExit(f"no offer {args.accept} on our brief")
        if (offer.get("providerAgent") or {}).get("id") in ours():
            raise SystemExit(
                "refusing: that offer is from one of our own agents. Accepting it "
                "would put an order on the public feed that nobody outside this "
                "project took part in."
            )
        current = offer.get("current") or {}
        print(f"\naccepting  {current.get('price')} {current.get('currency')} "
              f"· {current.get('deliveryDays')}d · valid until {current.get('validUntil')}")
        print(f"           {str(current.get('scope'))[:90]}")
        # `revisionId` is required, and taken from the offer we just read rather
        # than from a flag. Offers are versioned; accepting by id alone would
        # bind us to whatever the seller last edited it to, which is not the
        # thing we read the price and scope off two lines above.
        revision = offer.get("currentRevisionId")
        if not revision:
            raise SystemExit("that offer has no current revision to accept")
        # Derived from what is being bought, never random. That is the whole
        # point of the field: this script has already been re-run four times
        # while the body was being discovered, and a fresh key on each attempt
        # is how a retry becomes a second escrowed order. Same offer and same
        # revision means the same key, so the server can refuse the duplicate.
        key = "misquote-" + hashlib.sha256(f"{args.accept}:{revision}".encode()).hexdigest()[:32]
        # `expectedVersion` is optimistic concurrency and it is the guard worth
        # having: if the seller edits the terms between our reading them and our
        # accepting, this fails instead of binding us to a price and scope we
        # never saw. Taken from the revision we printed two lines above.
        agreed = marketplace.accept_offer(
            client,
            args.accept,
            {
                "revisionId": revision,
                "expectedVersion": current.get("version"),
                "clientAgentId": brief.get("clientAgentId"),
            },
        )
        if not show("accept quote", agreed):
            return 1
        reply = marketplace.checkout(
            client,
            {
                "offerId": args.accept,
                "revisionId": revision,
                "idempotencyKey": key,
                # Read off the brief rather than named again here. The buyer of
                # the work has to be the agent that asked for it, and two places
                # naming it independently is two places to disagree.
                "clientAgentId": brief.get("clientAgentId"),
            },
        )
        if show("checkout", reply):
            did["accepted_offer"] = {"accept": agreed, "checkout": reply}

    after = marketplace.counters(marketplace.dashboard(client))
    print(f"\nafter     {json.dumps(after)}")

    if args.out:
        # The claim is "these went from zero", which is a claim about a change.
        # A record holding only this run's before/after cannot carry it: run
        # `--out` after `--save` and the before is already 4, which is exactly
        # what happened the first time. So the earliest reading is kept across
        # runs and never overwritten.
        baseline, baseline_at = before, int(time.time())
        existing = Path(args.out)
        if existing.is_file():
            prior = json.loads(existing.read_text())
            if prior.get("baseline"):
                baseline = prior["baseline"]
                baseline_at = prior.get("baseline_at", baseline_at)

        record = {
            "platform": api_base(BSC_MAINNET),
            "wallet": signer.address,
            "baseline": baseline,
            "baseline_at": baseline_at,
            "before": before,
            "after": after,
            "actions": did,
            "usdc_at_read": usdc,
            # Recorded because it is a real absence and the reason is not
            # obvious from the zero: fifteen campaigns are DRAFT and five are
            # FILLED, so there is no slot anybody could claim today.
            "campaigns": {
                "claimable": 0,
                "why": (
                    "20 campaigns on the platform: 15 DRAFT (unpublished) and 5 "
                    "FILLED. None is open, so campaignsTotal cannot move."
                ),
            },
            "read_at": int(time.time()),
            "token_recorded": False,
        }
        Path(args.out).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
