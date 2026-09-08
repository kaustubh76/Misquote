"""The listing may not promise what the service cannot deliver.

A marketplace listing is a promise with a price on it, and this repository's
whole argument is that it does not make claims its own evidence cannot carry.
The listing is where that argument is easiest to lose: sales copy is written
once, read by buyers, and checked by nobody — and it sits on a page where the
next reader is deciding whether to send money.

So the copy is generated from `/quote/preflight`, the live service's own answer
about what it can replay, and these assert the generation rather than the words.
The failure they exist for is a pool that stops clearing the evidence floor and
stays in the sales text because no one reread it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from misquote.registry import listings

REPO = Path(__file__).resolve().parents[2]
RECORD = REPO / "vetting" / "identity" / "termix-listing-live-56.json"

#: What `/api/v1/agents/{id}/services` refused until each was supplied, in the
#: order it named them. `category` is the **label**, not the `slug` that
#: `/api/v1/service-categories` returns beside it — a body sent with `"research"`
#: comes back with all eight labels listed.
CATEGORY_LABELS = frozenset(
    {
        "Code & Smart Contracts",
        "Security & Verification",
        "Data & Research",
        "Design & Brand",
        "Writing & Content",
        "Automation & Ops",
        "Market & Protocol Research",
        "Model & Dataset Ops",
    }
)

#: A preflight with one pool that clears the floor and one that does not. The
#: second is the whole point: it is present in the reading and must be absent
#: from the copy.
PREFLIGHT = {
    "chain_id": 56,
    "pools": [
        {
            "pool": "0x36696169c63e42cd08ce11f5deebbcebae652050",
            "label": "PancakeSwap v3 WBNB/USDT 0.05%",
            "quotable": True,
            "tape": {"swaps": 60853, "hours": 240.0},
        },
        {
            "pool": "0xdeadbeef00000000000000000000000000000000",
            "label": "Some pool with nothing behind it",
            "quotable": False,
            "why_not": ["fewer than 20 windows of 24h"],
            "tape": {"swaps": 3, "hours": 1.0},
        },
    ],
}


def test_the_copy_names_only_pools_the_service_will_quote() -> None:
    """A pool in the listing is a pool a buyer can order against."""
    text = listings.description(PREFLIGHT)
    assert "PancakeSwap v3 WBNB/USDT 0.05%" in text
    assert "60,853 swaps" in text
    assert "Some pool with nothing behind it" not in text, (
        "the listing advertises a pool the preflight refuses to quote — a buyer "
        "ordering against it has bought a refusal"
    )


def test_the_copy_carries_the_refusal_rather_than_only_the_offer() -> None:
    """The thing that makes this project's quote worth anything is in the sales text.

    Not decoration: the refusal is the differentiator on a marketplace where
    every other listing promises an answer. It is also the claim most likely to
    be trimmed by someone tightening the copy, which is why it is asserted.
    """
    text = listings.description(PREFLIGHT)
    assert "refusal" in text.lower()
    assert "/quote/preflight" in text, (
        "the copy tells a buyer they can check the pools before paying and does "
        "not say where; the whole claim rests on that read being public"
    )


def test_an_empty_preflight_produces_no_pool_claims() -> None:
    """No pools, no list of pools. The script refuses to publish in this state."""
    lines = listings.pool_lines({"pools": []})
    assert lines == []
    text = listings.description({"pools": []})
    assert "no pool currently clears the evidence floor" in text


def test_the_body_carries_what_the_api_requires() -> None:
    """`title` and `category` were named by the server, one 400 at a time."""
    body = listings.service_body(PREFLIGHT)
    assert body["title"]
    assert body["category"] in CATEGORY_LABELS, (
        f"{body['category']!r} is not one of the eight labels the API accepts; "
        "it refuses the slug form and lists these"
    )
    assert body["price"] > 0 and body["currency"] == "USDC"
    assert body["deliveryDays"] >= 1


def test_it_sells_for_the_warden_termix_actually_attributes_to_us() -> None:
    """Three Wardens exist on chain and only one of them is listable.

    323262 was minted by a delegate and transferred, and TermiX attributes an
    agent to its **minter** — so it is owned by the operator and invisible to
    their index. 331590 is an unintended duplicate. 331592 is the one
    `vetting/identity/56.json` records and the one their API returns as
    `Warden-3`. Getting this wrong lists nothing, or lists the duplicate.
    """
    assert listings.WARDEN_TOKEN_ID == "331592"
    assert listings.WARDEN_TOKEN_ID not in {"323262", "331590"}
    assert listings.WARDEN_AGENT_ID.startswith("cm"), "platform ids are cuids, not token ids"


def test_the_record_names_both_ids_and_no_credential() -> None:
    """Evidence, not a way to repeat the run.

    `termix-auth.json` sets the rule — `token_recorded: false`, the token never
    written to disk, an artifact or the journal — and a second record in the
    same directory must not be the one that breaks it.
    """
    if not RECORD.is_file():
        pytest.skip("no live listing has been created yet")
    record = json.loads(RECORD.read_text())

    assert record["agent"]["erc8004_token_id"] == listings.WARDEN_TOKEN_ID
    assert record["agent"]["platform_id"] == listings.WARDEN_AGENT_ID
    assert record.get("token_recorded") is False

    blob = json.dumps(record).lower()
    for leak in ("bearer", "accesstoken", "access_token", "refreshtoken", "jwt"):
        assert leak not in blob, f"{leak!r} appears in a published evidence record"

    # The claim the record exists to make: it went from nothing to something.
    assert record["before"]["services"] == 0
    assert record["after"]["services"] >= 1, (
        "the record says the listing was created and the read-back still shows "
        "no service on the agent"
    )
