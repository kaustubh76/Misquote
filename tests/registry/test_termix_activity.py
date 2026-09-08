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


def test_the_bid_says_what_it_will_not_do_before_it_says_the_price() -> None:
    """The buyer asked to *model* price paths; we replay recorded ones.

    That is a different method, and a bid that let "model" stand would be
    selling a simulation this project does not run. The correction is in the
    offer text, near the top, and it is asserted because it is the sentence a
    rewrite for brevity would cut.
    """
    text = marketplace.IL_OFFER
    assert "do not model hypothetical price paths" in text
    assert "replay" in text.lower()
    # And it is said early, not buried under the sales pitch.
    assert text.index("do not model") < len(text) // 2

    # The bid is under the buyer's budget and equal to what our own listing
    # charges for the same tier — quoting 35.10 for work we publish at 0.50
    # would contradict our own price on the same marketplace.
    from decimal import Decimal

    warden = listings.SPECS["warden"]
    tier = next(p for p in warden.packages if p["id"] == "standard")
    assert Decimal(marketplace.IL_BID_USDC) == Decimal(tier["price"])
    assert Decimal(marketplace.IL_BID_USDC) < Decimal("35.1")


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


def test_the_counters_that_cannot_move_say_why() -> None:
    """An absence with a reason is evidence; a zero on its own is not.

    Campaigns cannot move: fifteen are unpublished drafts and five are full.
    Recorded the way `termix-listing-56.json` records warden's invisibility.
    """
    if not RECORD.is_file():
        pytest.skip("no activity has been recorded yet")
    record = json.loads(RECORD.read_text())
    campaigns = record.get("campaigns") or {}
    assert campaigns.get("claimable") == 0
    assert "DRAFT" in campaigns.get("why", ""), "the zero is recorded without its reason"


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
