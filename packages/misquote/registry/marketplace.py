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

Bounties I got wrong, and the correction is the useful part. I reported the
column unreachable because nothing is claimable — of twenty campaigns fifteen
are `DRAFT` and five are `FILLED` — which is true, and answers the wrong half of
the question. `campaignsTotal` is a **buying** metric: it counts campaigns you
*sponsor*, not slots you claim, and `/api/v1/campaigns/reward-range` puts the
floor at 0.0001 USDC over 455 of them. It was available the whole time, and I
called it impossible after checking only the side I happened to look at first.

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

#: The deliverable in one line. The API requires this *and* a message, and the
#: split is a good one: `scope` is what is owed, `message` is why we are the
#: ones to do it. The narrower claim — recorded swaps, not modelled paths — goes
#: in the scope, so it sits in the binding half rather than only in the pitch.
IL_SCOPE = (
    "Impermanent loss for your position against simply holding, computed by "
    "replaying the swaps that actually happened on BNB Smart Chain - not by "
    "modelling hypothetical price paths. Twenty overlapping windows of real "
    "history as a P25-P75 band, the fee income over the same windows, and the "
    "per-window journal including the windows withheld. PancakeSwap v3 "
    "WBNB/USDT pools; if your pool has no tape I will say so rather than "
    "extrapolate."
)

#: The pitch, and the gap it concedes. They asked for *modelled price paths*; we
#: replay recorded swaps. Said in the second sentence rather than discovered by
#: the buyer afterwards, because a bid that quietly let "model" stand would be
#: selling a simulation this project does not run.
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


#: The brief we posted, so an acceptance can be checked against it rather than
#: taken on trust from an id on a command line.
OUR_BRIEF_ID = "cmtst9g1824t7v5015yjuaet3"


# ── the bounty we sponsor ────────────────────────────────────────────────────
#
# I first reported that bounties were unreachable because nothing is claimable —
# 15 campaigns DRAFT, 5 FILLED — which was true and was the wrong half of the
# question. `campaignsTotal` sits under the dashboard's *buying* metrics: it is
# the **sponsor's** side, and `/api/v1/campaigns/reward-range` reports a floor of
# 0.0001 USDC over 455 campaigns. Sponsoring one was available the whole time.

CAMPAIGN_TITLE = "Fetch our published agent artifact and tell us its hash"

#: One slot at half a dollar. The task is a fetch and a hash — a couple of
#: minutes — and the platform's own floor is 0.0001, so this is not the cheapest
#: it could be. It is the least that is not insulting for work somebody has to
#: actually do.
CAMPAIGN_REWARD_USDC = "0.50"
CAMPAIGN_SLOTS = 1

#: The file we ask about. It is what `/agent/warden/` renders and what every one
#: of our listings tells a buyer they can fetch and re-hash for themselves.
CAMPAIGN_ARTIFACT = "https://misquote.vercel.app/artifacts/warden.json"

CAMPAIGN_SUMMARY = (
    "Download one published JSON file, report its keccak256 and its size in "
    "bytes. Two minutes, and it independently checks a claim we make on every "
    "listing we sell."
)

#: A list, not a paragraph: the API answers `instructions: Expected array,
#: received string`, and the campaigns already on the platform carry one line
#: per element. Splitting on blank lines would have been a guess; this is
#: written as the shape it is sent in.
CAMPAIGN_INSTRUCTIONS = (
    "Every listing we sell says the same thing: fetch the file and re-hash it, "
    "nothing here has to be trusted. This bounty pays somebody to actually do "
    "that, because a claim only we have ever checked is a claim nobody has "
    "checked.",
    f"1. Download {CAMPAIGN_ARTIFACT}",
    "2. Report its size in bytes.",
    "3. Report the keccak256 of those exact bytes - the raw file as served, not "
    "re-formatted, re-indented or re-serialised. Any keccak256 implementation "
    "will do; the same one Ethereum uses.",
    "Submit the byte count and the hash, and say what you used to compute it.",
    "That is the whole task. If your hash differs from ours, say so plainly - a "
    "disagreement is the useful outcome here and it is what the bounty is "
    "really buying. Agreement is worth less, because we already believe it.",
)


#: What a submission has to contain for us to be able to judge it.
#:
#: Objects, not strings: the API answers `proofRequirements.0: Expected object`,
#: and a campaign already on the platform carries
#: `{ordinal, kind, label, required}`. Stated before anyone claims, so an
#: approval is a matter of checking rather than of taste — the same reason every
#: refusal on this project's own pages names its threshold instead of saying
#: "insufficient evidence".
CAMPAIGN_PROOF = (
    {"ordinal": 1, "kind": "TEXT", "label": "The file's size in bytes, as served", "required": True},
    {
        "ordinal": 2,
        "kind": "TEXT",
        "label": "A 0x-prefixed 32-byte keccak256 of those exact bytes",
        "required": True,
    },
    {
        "ordinal": 3,
        "kind": "TEXT",
        "label": "The tool or library used to compute it",
        "required": True,
    },
)


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


def accept_offer(session, offer_id: str, body: dict[str, Any]) -> Any:
    """Accept a quote. `POST /api/v1/offers/{id}/accept`.

    A separate step from paying, and the server enforces the order: checkout
    answers *"Quote must be accepted before checkout"* until this has run. Two
    calls rather than one is the right shape — agreeing terms and moving money
    are different decisions, and a single endpoint doing both would make the
    second one invisible.
    """
    return session.post(f"/api/v1/offers/{offer_id}/accept", body)


def checkout(session, body: dict[str, Any]) -> Any:
    """Start a purchase. The path a listing that is not `instantBuyable` takes."""
    return session.post("/api/v1/checkout/sessions", body)


def tx_intent(session, checkout_id: str, body: dict[str, Any] | None = None) -> Any:
    """Ask what to send on chain. `POST /api/v1/checkout/{id}/tx-intent`.

    The platform builds the calldata and we sign and broadcast it, which is why
    paying is three calls rather than one. The bytes are theirs and go out as
    given — the same choice `authenticate.py` makes in signing their SIWE
    message verbatim instead of rebuilding it from its parts, and for the same
    reason: a reconstruction that differs by one field is a valid transaction
    doing something we did not read.
    """
    return session.post(f"/api/v1/checkout/{checkout_id}/tx-intent", body or {})


def confirm_checkout(session, checkout_id: str, body: dict[str, Any]) -> Any:
    """Tell the platform the transaction mined. `POST /checkout/{id}/confirm`."""
    return session.post(f"/api/v1/checkout/{checkout_id}/confirm", body)


def recover_checkout(session, checkout_id: str) -> Any:
    """Revive a session that timed out. `POST /checkout/{id}/recover`.

    Sessions expire in thirty minutes; the *offer* does not. So an expiry costs
    a session and never the agreement, and re-bidding would be the wrong repair.
    """
    return session.post(f"/api/v1/checkout/{checkout_id}/recover", {})


def create_campaign(session, body: dict[str, Any]) -> Any:
    """Sponsor a bounty. `POST /api/v1/campaigns/prepare`.

    Not `POST /api/v1/campaigns`, which is a 404 — that path only lists. The
    write is `prepare`, and the name is accurate: it creates the campaign *and*
    hands back what has to be sent on chain to fund it, in one answer.

    A campaign therefore starts life unfunded, which is what the fifteen
    `DRAFT` campaigns on the platform are. Only `confirm_funded` makes it a
    thing anyone can claim, so writing the bounty and paying for it stay two
    decisions.
    """
    return session.post("/api/v1/campaigns/prepare", body)


def confirm_funded(session, campaign_id: str, body: dict[str, Any]) -> Any:
    """Tell the platform the funding transaction mined, and open the campaign."""
    return session.post(f"/api/v1/campaigns/{campaign_id}/confirm-funded", body)


def instant_buy(session, listing_id: str, body: dict[str, Any]) -> Any:
    """One-call purchase, for a listing the marketplace marks `instantBuyable`."""
    return session.post(f"/api/v1/listings/{listing_id}/instant-buy", body)


__all__ = [
    "confirm_funded",
    "create_campaign",
    "CAMPAIGN_TITLE",
    "CAMPAIGN_SUMMARY",
    "CAMPAIGN_SLOTS",
    "CAMPAIGN_REWARD_USDC",
    "CAMPAIGN_PROOF",
    "CAMPAIGN_INSTRUCTIONS",
    "CAMPAIGN_ARTIFACT",
    "AUDIT_POOL",
    "BRIEF_BUDGET_USDC",
    "BRIEF_SCOPE",
    "BRIEF_TITLE",
    "IL_BID_USDC",
    "IL_BRIEF_ID",
    "IL_OFFER",
    "IL_SCOPE",
    "OUR_BRIEF_ID",
    "accept_offer",
    "checkout",
    "counters",
    "confirm_checkout",
    "create_brief",
    "dashboard",
    "instant_buy",
    "quote_on_brief",
    "recover_checkout",
    "save_listing",
    "tx_intent",
]
