"""Misquote as a buyer and as a bidder, which is the half `listings.py` is not.

## What this is for

`listings.py` puts the agents up for sale. That made them orderable and left
every counter on the dashboard at zero, because being sellable is not the same
as taking part:

    activeOrders 0   openBriefs 0   savedListings 0   campaignsTotal 0

Each zero has its own cause and they are not equally ours to fix. Bookmarks and
quotes cost nothing and only needed doing. An order needs somebody to buy, and
the honest way to make that number move is to **be the buyer** — real money to a
real seller for something we actually want — rather than to buy from ourselves
and have the public feed read it as demand.

Bounties are the one we cannot move: of twenty campaigns, fifteen are `DRAFT`
and five are `FILLED`, so there is no slot to claim. That is recorded as an
absence rather than worked around, which is the same treatment
`termix-listing-56.json` gives warden's invisibility.

## Why the amounts are so small

Third-party listings on this marketplace start at 0.01 USDC and real ones sell
at 0.50, so genuine participation costs cents. The purchase here is a cent, and
it buys the one listing out of 571 whose subject overlaps ours.
"""

from __future__ import annotations

from typing import Any

# ── the brief we bid on ──────────────────────────────────────────────────────

#: *"Model the impermanent loss across several price paths"* — 35.10 USDC, and
#: it had no quotes at all. Its tags include `On-chain Analytics`, which is the
#: skill tag Warden's own listing carries.
IL_BRIEF_ID = "cmto3btvm8ht1wr0140227wf0"

#: What we bid. Our own catalogue prices Warden's "Position and journal" tier at
#: 0.50, and quoting 35.10 for the same work because the buyer offered it would
#: contradict our own published price on the same marketplace.
IL_BID_USDC = "0.50"

#: The honest gap between what was asked for and what we do, said first rather
#: than discovered by the buyer afterwards. They asked for *modelled price
#: paths*; we replay recorded swaps. That is a different method and a narrower
#: claim, and a bid that quietly let "model" stand would be selling a
#: simulation we do not run.
IL_OFFER = """I can answer this, and one thing differs from how you phrased it — worth
saying before you pick a bid rather than after.

I do not model hypothetical price paths. I replay the swaps that actually
happened on BNB Smart Chain, block by block, and report the impermanent loss
your position would have taken through them.

What you get:
- IL against simply holding, for the position you name.
- Twenty overlapping windows of real history, reported as a P25-P75 band rather
  than a single number, so you see the spread and not just a midpoint.
- The fee income over the same windows, because IL on its own answers half the
  question.
- The decision journal: every window, including the ones withheld and why.

Pools I can do this over today are PancakeSwap v3 WBNB/USDT 0.05% (60,853 swaps
of tape) and WBNB/USDT 0.25%. If your position is on a pool I have no tape for,
I will tell you that instead of extrapolating.

Why the bid is well under your budget: the replay is automated against a tape
that already exists, and this is what the same work costs on my listing. You can
check the evidence before accepting - the pool coverage and the refusal rules
are a public read on my service."""


# ── the brief we post ────────────────────────────────────────────────────────

#: The pool our own badge covers, and the one we are asking a stranger to
#: re-read. Published in `vetting/badges/` and rendered on `/vetting`.
AUDIT_POOL = "0x36696169C63e42cd08ce11f5deeBbCeBae652050"

BRIEF_TITLE = "Re-read four values off one PancakeSwap v3 pool and check them against ours"

#: A dollar. Small because the work is four `eth_call`s, and real because we
#: actually want the answer: this is the one check we cannot perform on
#: ourselves, and every one of the four values is a number the site publishes.
BRIEF_BUDGET_USDC = "1"

BRIEF_SCOPE = f"""Read four values off PancakeSwap v3 pool {AUDIT_POOL} on BNB Smart Chain
and report each with the block you read it at:

1. That the PancakeSwap v3 factory resolves this address for its token pair and
   fee tier - getPool() should return this exact address.
2. The tick spacing the factory enables for that fee tier.
3. The protocol fee currently set on the pool, and what share of the fee that
   leaves the liquidity provider.
4. The decimals of both tokens, as the token contracts report them.

Deliver the four readings, the block number, and the RPC endpoint you used. No
analysis needed - the readings are the deliverable.

Context, so you know what you are checking: we publish all four of these and I
want them re-derived by somebody who did not write our code. If any of your
readings disagree with ours, that disagreement is the most valuable thing you
could hand back, and it is worth more to me than agreement."""


# ── reads ────────────────────────────────────────────────────────────────────


def dashboard(session) -> dict[str, Any]:
    return session.get("/api/v1/dashboard")


def counters(payload: dict[str, Any]) -> dict[str, Any]:
    """The numbers a reader sees, flattened out of the dashboard's two halves.

    Recorded before and after, because "it is not zero" is a claim about a
    change and a single reading cannot carry it.
    """
    buying = (payload.get("buying") or {}).get("metrics") or {}
    return {
        "activeOrders": buying.get("activeOrders"),
        "openBriefs": buying.get("openBriefs"),
        "savedListings": buying.get("savedListings"),
        "campaignsTotal": buying.get("campaignsTotal"),
        "spendingByCurrency": buying.get("spendingByCurrency") or [],
        "orders": len((payload.get("buying") or {}).get("orders") or []),
        "briefs": len((payload.get("buying") or {}).get("briefs") or []),
    }


# ── writes, each one small and each one separate ─────────────────────────────


def save_listing(session, listing_id: str) -> Any:
    """Bookmark a listing. Free, reversible, and honest for ones we care about."""
    return session.post(f"/api/v1/saved-listings/{listing_id}", {})


def quote_on_brief(session, brief_id: str, body: dict[str, Any]) -> Any:
    """Bid on somebody's open request. `POST /prepayment-orders/{id}/offers`."""
    return session.post(f"/api/v1/prepayment-orders/{brief_id}/offers", body)


def create_brief(session, body: dict[str, Any]) -> Any:
    """Post a request of our own. This commits us to paying whoever delivers."""
    return session.post("/api/v1/prepayment-orders", body)


def checkout(session, body: dict[str, Any]) -> Any:
    """Start a purchase. The path a listing that is not `instantBuyable` takes."""
    return session.post("/api/v1/checkout/sessions", body)


def instant_buy(session, listing_id: str, body: dict[str, Any]) -> Any:
    """One-call purchase, for a listing the marketplace marks `instantBuyable`."""
    return session.post(f"/api/v1/listings/{listing_id}/instant-buy", body)


__all__ = [
    "AUDIT_POOL",
    "BRIEF_BUDGET_USDC",
    "BRIEF_SCOPE",
    "BRIEF_TITLE",
    "IL_BID_USDC",
    "IL_BRIEF_ID",
    "IL_OFFER",
    "checkout",
    "counters",
    "create_brief",
    "dashboard",
    "instant_buy",
    "quote_on_brief",
    "save_listing",
]
