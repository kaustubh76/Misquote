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
from decimal import Decimal
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

#: What TermiX prices orders in on BSC. Not typed from a docs page: their own
#: `/api/v1/me/wallet/balance` names this address under `usdc`.
USDC = "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d"

ERC20_ABI = json.loads(
    '[{"name":"decimals","type":"function","stateMutability":"view","inputs":[],'
    '"outputs":[{"type":"uint8"}]},'
    '{"name":"allowance","type":"function","stateMutability":"view",'
    '"inputs":[{"type":"address"},{"type":"address"}],"outputs":[{"type":"uint256"}]},'
    '{"name":"approve","type":"function","stateMutability":"nonpayable",'
    '"inputs":[{"type":"address"},{"type":"uint256"}],"outputs":[{"type":"bool"}]}]'
)

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


def _iso(offset_seconds: int) -> str:
    """An absolute UTC timestamp, the way the platform reports its own."""
    from datetime import UTC, datetime, timedelta

    when = datetime.now(UTC) + timedelta(seconds=offset_seconds)
    return when.strftime("%Y-%m-%dT%H:%M:%S.000Z")


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
        "--bounty",
        action="store_true",
        help="sponsor a campaign. Creates it as a draft; funding is --fund-bounty.",
    )
    ap.add_argument(
        "--pay",
        metavar="CHECKOUT_ID",
        help="send the escrow transaction for an accepted offer. SPENDS USDC.",
    )
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

    if not (
        args.save or args.quote or args.brief or args.buy or args.accept or args.pay
        or args.bounty or args.out
    ):
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

    if args.bounty:
        print("\nsponsoring a bounty:")
        # Sponsored by Warden: the file under scrutiny is `warden.json`, and the
        # claim being checked — "fetch it and re-hash it, nothing here has to be
        # trusted" — is on Warden's own listing. The agent making the claim is
        # the right one to be paying somebody to test it.
        body = {
            "clientAgentId": listings.SPECS["warden"].agent_id,
            "title": marketplace.CAMPAIGN_TITLE,
            "summary": marketplace.CAMPAIGN_SUMMARY,
            "instructions": list(marketplace.CAMPAIGN_INSTRUCTIONS),
            "proofRequirements": list(marketplace.CAMPAIGN_PROOF),
            "category": "Data & Research",
            "rewardPerSlot": marketplace.CAMPAIGN_REWARD_USDC,
            "totalSlots": marketplace.CAMPAIGN_SLOTS,
            "currency": "USDC",
            # Open now, closed in a week. A campaign with no end is one nobody
            # can plan around and one we could never reclaim the escrow from;
            # `reclaim-expired/confirm` exists precisely because they end.
            "opensAt": _iso(0),
            "closesAt": _iso(7 * 24 * 3600),
        }
        reply = marketplace.create_campaign(client, body)
        if show("campaign", reply):
            did["campaign"] = reply

    if args.pay:
        w3 = connect()
        row = client.get(f"/api/v1/checkout/{args.pay}")
        print(
            f"\nsession    {row.get('status')} · {row.get('amount')} "
            f"{row.get('currency')} · expires {row.get('expiresAt')}"
        )

        intent = marketplace.tx_intent(client, args.pay)
        if isinstance(intent, dict) and intent.get("error"):
            # A session times out in thirty minutes and the *offer* does not, so
            # an expiry costs a session and never the agreement. Reviving it is
            # the repair; re-bidding would be redoing a deal that still stands.
            print(f"  tx-intent refused: {intent['error'].get('message')}")
            show("recover", marketplace.recover_checkout(client, args.pay))
            intent = marketplace.tx_intent(client, args.pay)
            if isinstance(intent, dict) and intent.get("error"):
                show("tx-intent", intent)
                return 1

        escrow = Web3.to_checksum_address(intent["contract"])
        print(f"  intent   {intent['action']} -> {escrow} (chain {intent['chainId']})")

        erc20 = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_ABI)
        scale = 10 ** int(erc20.functions.decimals().call())
        need = int(Decimal(str(row["amount"])) * scale)
        allowance = int(erc20.functions.allowance(signer.address, escrow).call())
        print(f"  allowance {allowance / scale:.6f} · need {need / scale:.6f}")

        if allowance < need:
            # Exactly what this order costs, and not a token more. An unbounded
            # allowance to an escrow nobody here has audited is the standing
            # risk this project would refuse to accept on somebody else's page.
            # The ContractFunction itself, not its `build_transaction(...)`
            # output: `BscSigner.build` estimates gas off the call and builds the
            # transaction itself, so handing it a finished dict skipped the
            # estimate and lost the revert-before-signing it exists for.
            call = erc20.functions.approve(escrow, need)
            sent = signer.send(signer.build(call))
            print(f"  approve  {sent.tx_hash}")

        # Their calldata, sent as given. Rebuilding the call from field names
        # would be a valid transaction doing something we never read — the same
        # reason `authenticate.py` signs their SIWE message verbatim.
        sent = signer.send(
            signer.build(
                {"to": escrow, "data": intent["callData"], "value": int(intent["value"])}
            )
        )
        print(f"  escrow   {sent.tx_hash}  gas {sent.gas_used:,}")
        reply = marketplace.confirm_checkout(
            client, args.pay, {"txIntentId": intent["id"], "txHash": sent.tx_hash}
        )
        if show("confirm", reply):
            did["paid"] = {"tx": sent.tx_hash, "intent": intent["id"], "checkout": args.pay}

    after = marketplace.counters(marketplace.dashboard(client))
    print(f"\nafter     {json.dumps(after)}")

    if args.out:
        # Read every id back from the server rather than reporting what we sent.
        # A create response says what we asked for; only this says what exists,
        # and the difference is the whole reason the listing record reads
        # services back too.
        live: dict[str, Any] = {}
        for label, path in (
            ("our_brief", f"/api/v1/prepayment-orders/{marketplace.OUR_BRIEF_ID}"),
            ("our_bid", f"/api/v1/prepayment-orders/{marketplace.IL_BRIEF_ID}"),
            ("checkout", f"/api/v1/checkout/{marketplace.OUR_CHECKOUT_ID}"),
            ("campaign", f"/api/v1/campaigns/{marketplace.OUR_CAMPAIGN_ID}"),
        ):
            try:
                live[label] = client.get(path)
            except Exception as error:  # noqa: BLE001 - an absence is a reading
                live[label] = {"unreadable": f"{type(error).__name__}: {str(error)[:120]}"}

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
            "on_the_platform": {
                "brief": {
                    "id": marketplace.OUR_BRIEF_ID,
                    "status": (live.get("our_brief") or {}).get("status"),
                    "quotes": (live.get("our_brief") or {}).get("offers")
                    and len(live["our_brief"]["offers"]),
                    "budget": (live.get("our_brief") or {}).get("budget"),
                },
                "bid": {
                    "offer_id": marketplace.OUR_OFFER_ID,
                    "on_brief": marketplace.IL_BRIEF_ID,
                    "brief_status": (live.get("our_bid") or {}).get("status"),
                    "price_usdc": marketplace.IL_BID_USDC,
                },
                "inbound_offer": {
                    "offer_id": marketplace.INBOUND_OFFER_ID,
                    "checkout_id": marketplace.OUR_CHECKOUT_ID,
                    "checkout_status": (live.get("checkout") or {}).get("status"),
                    "amount": (live.get("checkout") or {}).get("amount"),
                },
                "bounty": {
                    "id": marketplace.OUR_CAMPAIGN_ID,
                    "status": (live.get("campaign") or {}).get("status"),
                    "reward_per_slot": (live.get("campaign") or {}).get("rewardPerSlot"),
                    "funded_tx": (live.get("campaign") or {}).get("fundedTxHash"),
                    "escrow": (live.get("campaign") or {}).get("escrowContract"),
                },
            },
            # The half that is not done, named rather than left to be inferred
            # from a zero. A block showing three completed things and omitting
            # this reads as a completed trade.
            "not_done": {
                "activeOrders": 0,
                "why": (
                    "the accepted offer's escrow transaction has never been sent, "
                    "and the sponsored campaign is DRAFT because its reward has "
                    "not been funded on chain. Both are one transaction away and "
                    "neither has been made."
                ),
            },
            "usdc_at_read": usdc,
            # Recorded because it is a real absence and the reason is not
            # obvious from the zero: fifteen campaigns are DRAFT and five are
            # FILLED, so there is no slot anybody could claim today.
            # Both halves, because I first recorded only one and called the
            # column unreachable on the strength of it.
            "campaigns": {
                "claimable_by_us": 0,
                "why_none_claimable": (
                    "20 campaigns on the platform when this was read: 15 DRAFT "
                    "(unpublished) and 5 FILLED. No slot was open to claim."
                ),
                "sponsored_by_us": 1,
                "why_that_was_possible": (
                    "campaignsTotal is a *buying* metric — it counts campaigns "
                    "sponsored, not slots claimed. The reward floor is 0.0001 "
                    "USDC across 455 campaigns, so sponsoring one was available "
                    "the whole time and the first reading here missed it by "
                    "checking only the claiming side."
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
