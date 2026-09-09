"""Taking part in the marketplace, and not faking having taken part.

The dashboard reading zero is the honest state of an agent nobody has hired.
The dishonest fix is to buy from yourself, which fills every counter and puts
demand on a public feed that does not exist. These assert the difference.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from misquote.registry import listings, marketplace

REPO = Path(__file__).resolve().parents[2]
RECORD = REPO / "vetting" / "identity" / "termix-activity-56.json"
ARTIFACT = REPO / "apps" / "web" / "public" / "artifacts" / "registry.json"


def test_every_bid_concedes_something_before_it_names_a_price() -> None:
    """Each of these briefs asks for something adjacent to what the agent does.

    Router's asks for a comparison *of lending protocols* and we have two, on
    one chain. Sentinel's says "risk breakdown", which could mean a security
    audit, and nine chain reads are not one. Warden's asks somebody to *provide*
    liquidity and we only check it. In each case the gap goes in the message
    before the price, because a bid that lets the buyer's wording stand is
    selling their idea of the work rather than ours.
    """
    from decimal import Decimal

    assert marketplace.BIDS, "no bids to check"
    for bid in marketplace.BIDS:
        assert bid.concession, f"{bid.agent}'s bid on {bid.title[:30]} concedes nothing"
        # The concession is *in* the message, not merely recorded beside it.
        assert bid.concession.split()[0].lower() in bid.message.lower(), (
            f"{bid.agent} records a concession the buyer never reads"
        )
        # And early: before the halfway mark, not buried under the pitch.
        assert bid.message.lower().index(bid.concession.split()[0].lower()) < len(bid.message) / 2

        # Priced from our own catalogue, never from the buyer's budget. Quoting
        # 89.81 for work we publish at 0.40 would contradict our own listing on
        # the same marketplace.
        assert Decimal(bid.price_usdc) < Decimal(bid.budget_usdc)
        tiers = [Decimal(p["price"]) for p in listings.SPECS[bid.agent].packages]
        assert Decimal(bid.price_usdc) in tiers, (
            f"{bid.agent} bids {bid.price_usdc}, which is not a price it publishes"
        )


def test_no_bid_claims_work_its_agent_has_no_route_for() -> None:
    """A bid is a promise, held to the same standard as a listing.

    Every agent bidding must have a live probe — the thing that makes its
    listing honest makes its bid honest. This is the guard that would have
    stopped me bidding Sentinel on "Smart contract review by severity", which
    matches on keywords and is work this project does not do.
    """
    for bid in marketplace.BIDS:
        spec = listings.SPECS[bid.agent]
        assert spec.probe_path, f"{bid.agent} bids on {bid.title[:30]} with no route behind it"
    # One agent, one brief: two offers on one request at one price is a bot.
    pairs = [(b.agent, b.brief_id) for b in marketplace.BIDS]
    assert len(pairs) == len(set(pairs))


def test_the_brief_we_post_asks_somebody_to_check_us() -> None:
    """It has to be work we actually want, or it is a counter dressed as a request.

    This one asks a stranger to re-derive four values we publish. It is the one
    check we cannot perform on ourselves, and the scope says a disagreement is
    worth more to us than agreement — which is the whole reason to pay for it.
    """
    scope = marketplace.BRIEF_SCOPE
    assert marketplace.AUDIT_POOL in scope
    assert "disagree" in scope
    for reading in ("factory", "tick spacing", "protocol fee", "decimals"):
        assert reading in scope.lower(), f"the brief does not ask for {reading}"
    # A reading with no block behind it cannot be checked against ours.
    assert "block" in scope.lower()


def test_the_bounty_asks_for_something_that_can_be_checked() -> None:
    """A bounty whose approval is a matter of taste cannot be judged fairly.

    Every proof requirement here is a value that either matches or does not: a
    byte count, a hash, and the tool that produced it. That is the same standard
    this project holds its own refusals to — name the threshold rather than say
    "insufficient evidence".
    """
    assert marketplace.CAMPAIGN_PROOF, "the bounty demands no proof at all"
    for req in marketplace.CAMPAIGN_PROOF:
        for field in ("ordinal", "kind", "label", "required"):
            assert field in req, f"a proof requirement has no {field}"
        assert req["label"].strip()
    labels = " ".join(r["label"].lower() for r in marketplace.CAMPAIGN_PROOF)
    assert "keccak256" in labels and "bytes" in labels

    # And it invites the answer we would least like, which is the one worth
    # paying for: agreement we already believe.
    body = " ".join(marketplace.CAMPAIGN_INSTRUCTIONS).lower()
    assert "differs" in body or "disagree" in body
    assert marketplace.CAMPAIGN_ARTIFACT in body


def test_the_bounty_reward_is_a_real_offer_not_a_token_gesture() -> None:
    """The platform's floor is 0.0001 USDC and this is not sitting on it.

    A bounty priced at the minimum for work somebody has to actually do is a
    counter dressed as an offer. This is small because the task is small, and
    the test pins the relationship rather than the number.
    """
    from decimal import Decimal

    reward = Decimal(marketplace.CAMPAIGN_REWARD_USDC)
    assert reward >= Decimal("0.1"), "cheaper than the task deserves"
    assert reward < Decimal("1"), "these are demonstrations, not commerce"
    assert marketplace.CAMPAIGN_SLOTS >= 1


def test_it_refuses_to_buy_from_itself() -> None:
    """The refusal is in the script, and it is the point of the script.

    Buying our own listing fills the dashboard on both sides at once. It also
    appears on `/api/v1/explorer/jobs` exactly as every other order does — one
    party hiring another — and a reader has no way to tell it apart. That is
    the misquote this repository is named after, applied to its own dashboard.
    """
    source = (REPO / "scripts" / "termix_activity.py").read_text()
    assert "refusing: that listing is one of ours" in source
    assert "ours()" in source, "the guard exists and nothing computes what is ours"


def test_the_campaign_record_carries_both_halves_of_the_question() -> None:
    """I answered "can we move this column" by checking one side of it.

    Nothing was claimable — true — and I recorded that as the reason the column
    could not move. `campaignsTotal` counts campaigns *sponsored*, so it could,
    and did. The record now carries both halves so the next reader does not
    inherit the half-answer, and this asserts both are there.
    """
    if not RECORD.is_file():
        pytest.skip("no activity has been recorded yet")
    campaigns = (json.loads(RECORD.read_text()).get("campaigns")) or {}

    assert campaigns.get("claimable_by_us") == 0
    assert "DRAFT" in campaigns.get("why_none_claimable", "")
    assert campaigns.get("sponsored_by_us", 0) >= 1, (
        "the record says nothing was sponsored, and the dashboard says otherwise"
    )
    assert "buying" in campaigns.get("why_that_was_possible", "").lower()


def test_the_record_proves_a_change_and_not_just_a_state() -> None:
    """`before` is not enough once a run has already acted.

    Run `--out` after `--save` and this run's `before` is already 4 — which is
    what happened the first time, and why the earliest reading is kept
    separately and never overwritten.
    """
    if not RECORD.is_file():
        pytest.skip("no activity has been recorded yet")
    record = json.loads(RECORD.read_text())

    baseline, after = record["baseline"], record["after"]
    assert set(baseline) == set(after), "the two readings are not comparable"

    moved = {k for k in baseline if isinstance(after[k], int) and after[k] > (baseline[k] or 0)}
    assert moved, (
        "nothing on the dashboard moved off its baseline; the record claims "
        "participation and shows none"
    )
    assert baseline["savedListings"] == 0 and after["savedListings"] > 0


def test_the_record_carries_no_credential() -> None:
    """`termix-auth.json` sets the rule and every record here keeps it."""
    if not RECORD.is_file():
        pytest.skip("no activity has been recorded yet")
    record = json.loads(RECORD.read_text())
    assert record.get("token_recorded") is False
    blob = json.dumps(record).lower()
    for leak in ("bearer", "accesstoken", "access_token", "refreshtoken", "jwt"):
        assert leak not in blob


def test_the_page_cannot_publish_the_good_news_without_the_bad() -> None:
    """Four things happened on that marketplace and a fifth did not.

    Three listings, a bid, a brief that an autonomous agent answered, a bounty
    sponsored — and `activeOrders` still 0, because the accepted offer's escrow
    has never been sent and the campaign is unfunded.

    A block carrying the first four and omitting the fifth reads as a completed
    trade. This asserts the artifact carries it, so removing the sentence breaks
    a test rather than quietly improving the story.
    """
    if not ARTIFACT.is_file():
        pytest.skip("no registry artifact has been generated")
    part = (json.loads(ARTIFACT.read_text()).get("aacp") or {}).get("participation")
    if not part:
        pytest.skip("this artifact predates the participation block")

    outstanding = part.get("not_done") or []
    assert outstanding, "the block publishes what happened and not what did not"
    assert any("escrow" in why.lower() for why in outstanding)

    # Derived, not written down. The first version was a fixed sentence saying
    # the escrow had never been sent, and it stayed true on the page for the
    # minutes between that transaction mining and somebody rereading the prose.
    # A status that cannot go stale is one nobody has to remember to update.
    assert any("PENDING_ACCEPT" in why or "DRAFT" in why for why in outstanding), (
        "the outstanding list quotes no platform state, so it is a sentence rather than a reading"
    )

    # The claim is a change, so both readings have to be there. A block showing
    # only "now" cannot distinguish four bookmarks from four we always had.
    counters = part.get("counters") or {}
    assert counters.get("baseline") and counters.get("now")
    assert counters["baseline"]["savedListings"] == 0
    assert counters["now"]["savedListings"] > 0

    # The order exists and is escrowed; `activeOrders` counts the ones a
    # provider has accepted, which is theirs to do. Both facts are on the page.
    orders = part.get("orders") or []
    assert orders, "an order was paid for and the artifact carries none"
    for order in orders:
        assert order["chain_order_id"], "an order with no on-chain id cannot be checked"
        assert order["status"]

    # Router used to be here, refused. It is listed now — the refusal was mine
    # and wrong, and `/agents/router` had served its venue comparison all along.
    # So the guard is no longer "the refusal reaches the page" but the thing
    # that outlives it: whatever *is* refused must say why, and every agent the
    # page advertises must carry the identity a reader can check it by.
    for slug, why in (part.get("refused") or {}).items():
        assert why and len(why) > 20, f"{slug} is held back with no reason a reader can weigh"
    listed = part.get("listings") or []
    assert listed, "the page advertises nothing"
    for row in listed:
        assert row.get("erc8004_token_id"), f"{row.get('agent')} is listed with no identity"
        assert row.get("status") == "PUBLISHED", f"{row.get('agent')} is on the page as a draft"
