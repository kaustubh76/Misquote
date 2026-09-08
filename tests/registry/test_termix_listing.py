"""A listing may not promise what the service cannot deliver.

A marketplace listing is a promise with a price on it, and this repository's
whole argument is that it does not make claims its own evidence cannot carry.
The listing is where that argument is easiest to lose: sales copy is written
once, read by buyers, and checked by nobody — and it sits on the page where the
next reader decides whether to send money.

So each spec names a live route, the copy is generated from that route's
reading, and these assert the generation rather than the words. The failure they
exist for is a pool that stops clearing the evidence floor and stays in the
sales text because no one reread it.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from misquote.registry import listings

REPO = Path(__file__).resolve().parents[2]
RECORD = REPO / "vetting" / "identity" / "termix-listing-live-56.json"

#: A preflight with one pool that clears the floor and one that does not. The
#: second is the point: present in the reading, and it must be absent from copy.
PREFLIGHT = {
    "pools": [
        {
            "label": "PancakeSwap v3 WBNB/USDT 0.05%",
            "quotable": True,
            "tape": {"swaps": 60853, "hours": 240.0},
        },
        {
            "label": "Some pool with nothing behind it",
            "quotable": False,
            "why_not": ["fewer than 20 windows of 24h"],
            "tape": {"swaps": 3, "hours": 1.0},
        },
    ]
}

#: Same shape for Grid: one pool with sufficient rungs, one with none.
POOLS = {
    "pools": [
        {
            "label": "PancakeSwap v3 WBNB/USDT 0.05%",
            "best_width_ticks": 80,
            "ladder": [
                {"width_ticks": 40, "observations": 20, "sufficient": True},
                {"width_ticks": 80, "observations": 20, "sufficient": True},
            ],
        },
        {
            "label": "A pool nobody has watched",
            "best_width_ticks": None,
            "ladder": [{"width_ticks": 40, "observations": 2, "sufficient": False}],
        },
    ]
}

VETTING = {
    "badged": ["0xaaa", "0xbbb", "0xccc"],
    "known_and_unbadged": ["0xddd"],
}


# ── the registry itself ──────────────────────────────────────────────────────


def test_every_sellable_agent_names_the_route_that_proves_it() -> None:
    """A listing without a live route behind it is a promise with no basis."""
    assert listings.SELLABLE, "nothing is sellable, so this suite proves nothing"
    for slug in listings.SELLABLE:
        spec = listings.SPECS[slug]
        assert spec.probe_path, f"{slug} is sellable and names no probe"
        assert spec.title.strip(), f"{slug} has no title"
        assert spec.price_usdc > 0, f"{slug} is offered for nothing"
        assert spec.delivery_days >= 1
        assert spec.category in listings.CATEGORIES, (
            f"{slug} uses {spec.category!r}, which is not one of the eight labels "
            f"the API accepts — it refuses the slug form and lists these"
        )


def test_every_agent_is_sellable_and_none_is_refused_on_a_guess() -> None:
    """All four, and the fourth is here because I refused it on a bad reading.

    Router carried no listing for hours because `/venue`, `/venus` and `/route`
    all answer 404 — three spellings I invented — while `/agents/router` served
    the venue comparison the whole time, in a `venues` block naming vUSDT, vUSDC
    and two PancakeSwap v3 ranges. I searched for a route named after the thing
    instead of a route that provides it, and the same session had already
    produced that error on bounties: checked whether a campaign could be
    *claimed*, found none, called the column unreachable without checking
    whether one could be *sponsored*.

    So a `blocked` spec is no longer allowed to mean "I did not find the route".
    Anything refused must name the probe it was refused for, and that probe must
    be a path this repository actually asked the service about.
    """
    assert set(listings.SELLABLE) == set(listings.SPECS), (
        f"{sorted(set(listings.SPECS) - set(listings.SELLABLE))} carry no probe; "
        f"before adding a `blocked` reason, check whether an existing route "
        f"already serves the deliverable under a different name"
    )
    for slug, spec in listings.SPECS.items():
        if spec.probe_path:
            assert spec.probe_path.startswith("/"), f"{slug}'s probe is not a path"
        else:
            assert spec.blocked, f"{slug} is refused and does not say why"


def test_routers_copy_comes_from_the_route_that_serves_it() -> None:
    """The venues named in the listing are the venues the card compares.

    Generated, not typed, for the same reason Warden's pools are: a list written
    beside the code outlives the thing it describes. And the differentiator is
    asserted because it is the sentence a rewrite would cut — a router that
    reports only the times it acted is hiding its denominator.
    """
    card = {
        "venues": [
            {"symbol": "vUSDT", "kind": "lending", "quotable_samples": 251},
            {"symbol": "vUSDC", "kind": "lending", "quotable_samples": 250},
            {"symbol": "a venue nobody sampled", "kind": "pool", "quotable_samples": 0},
        ]
    }
    text = listings.router_description(card)
    assert "vUSDT (lending) — 251 quotable samples" in text
    assert "a venue nobody sampled" not in text, (
        "a venue with no samples is offered as comparable"
    )
    assert "168" in text and "declined" in text.lower()


def test_no_two_specs_point_at_the_same_agent() -> None:
    """Two specs on one agent lists it twice, which is the duplicate we avoid."""
    ids = [s.agent_id for s in listings.SPECS.values()]
    assert len(ids) == len(set(ids))


def test_it_sells_for_the_warden_termix_actually_attributes_to_us() -> None:
    """Three Wardens exist on chain and only one of them is listable.

    323262 was minted by a delegate and transferred, and TermiX attributes an
    agent to its **minter** — so it is owned by the operator and invisible to
    their index. 331590 is an unintended duplicate. 331592 is the one
    `vetting/identity/56.json` records and their API returns as `Warden-3`.
    Getting this wrong lists nothing, or lists the duplicate.
    """
    warden = listings.SPECS["warden"]
    assert warden.token_id == "331592"
    assert warden.token_id not in {"323262", "331590"}
    for spec in listings.SPECS.values():
        assert spec.agent_id.startswith("cm"), "platform ids are cuids, not token ids"


# ── the copy, against a reading ──────────────────────────────────────────────


def test_warden_names_only_pools_the_service_will_quote() -> None:
    text = listings.warden_description(PREFLIGHT)
    assert "PancakeSwap v3 WBNB/USDT 0.05%" in text
    assert "60,853 swaps" in text
    assert "Some pool with nothing behind it" not in text, (
        "the listing advertises a pool the preflight refuses to quote — a buyer "
        "ordering against it has bought a refusal"
    )


def test_grid_names_only_pools_it_can_actually_rank() -> None:
    text = listings.grid_description(POOLS)
    assert "PancakeSwap v3 WBNB/USDT 0.05%" in text
    assert "best 80 ticks" in text
    assert "A pool nobody has watched" not in text, (
        "a pool whose every rung is insufficient is offered as rankable"
    )


def test_grid_sells_the_indistinguishability_rather_than_hiding_it() -> None:
    """The honest half is the differentiator, so it is the half that is asserted.

    Any tool can name a best width. Saying which other widths are statistically
    the same as it is the claim that stops a buyer over-reading one number, and
    it is the first thing a rewrite for brevity would cut.
    """
    text = listings.grid_description(POOLS)
    assert "indistinguishable" in text.lower()
    assert "/pools" in text


def test_sentinel_refuses_to_let_silence_read_as_approval() -> None:
    """An unbadged pool is an absence, not a clean bill of health.

    The live `/vetting` route says exactly that in its own note. A listing that
    dropped it would be selling a safety signal it does not have.
    """
    text = listings.sentinel_description(VETTING)
    assert "absence" in text.lower()
    assert "not an audit" in text.lower() or "not a live monitor" in text.lower()
    assert "3" in text, "the count of examined pools is what the buyer is choosing from"


def test_warden_carries_the_refusal_and_says_where_to_check_it() -> None:
    """The whole claim rests on the preflight being a read the buyer can make."""
    text = listings.warden_description(PREFLIGHT)
    assert "refusal" in text.lower()
    assert "/quote/preflight" in text


@pytest.mark.parametrize(
    ("describe", "reading"),
    [
        (listings.warden_description, {"pools": []}),
        (listings.grid_description, {"pools": []}),
    ],
)
def test_an_empty_reading_makes_no_claim(describe, reading) -> None:
    """No pools, no list of pools. The script refuses to create in this state."""
    text = describe(reading)
    assert "- PancakeSwap" not in text
    assert "no pool" in text.lower()


def test_the_body_carries_what_the_api_requires() -> None:
    """`title` and `category` were named by the server, one 400 at a time."""
    for slug, reading in (("warden", PREFLIGHT), ("grid", POOLS), ("sentinel", VETTING)):
        body = listings.service_body(listings.SPECS[slug], reading)
        assert body["title"] and body["category"] in listings.CATEGORIES
        # A string, because the API refuses a number here.
        assert body["basePrice"] == str(listings.SPECS[slug].price_usdc)
        assert float(body["basePrice"]) > 0 and body["currency"] == "USDC"
        assert body["deliveryDays"] >= 1
        assert len(body["description"]) > 400, f"{slug}'s copy is too thin to be a listing"


# ── the record, once there is one ────────────────────────────────────────────


def test_the_record_names_the_ids_and_no_credential() -> None:
    """Evidence, not a way to repeat the run.

    `termix-auth.json` sets the rule — `token_recorded: false`, the token never
    written to disk, an artifact or the journal — and a second record in the
    same directory must not be the one that breaks it.
    """
    if not RECORD.is_file():
        pytest.skip("no live listing has been created yet")
    record = json.loads(RECORD.read_text())

    assert record.get("token_recorded") is False
    blob = json.dumps(record).lower()
    for leak in ("bearer", "accesstoken", "access_token", "refreshtoken", "jwt"):
        assert leak not in blob, f"{leak!r} appears in a published evidence record"

    for slug in listings.SELLABLE:
        spec = listings.SPECS[slug]
        entry = record["agents"][slug]
        assert entry["erc8004_token_id"] == spec.token_id
        assert entry["platform_id"] == spec.agent_id
        assert entry["proved_by"] == spec.probe_path

    # No refusals left: Router's was mine, not the platform's, and it went when
    # `/agents/router` turned out to serve the comparison. What the record does
    # carry are the duplicate skips from re-running, which are not refusals.
    for slug in listings.SELLABLE:
        assert slug in record["services_after"], f"{slug} is missing from the read-back"
    assert any(n >= 1 for n in record["services_after"].values()), (
        "the record says listings were created and every read-back shows none"
    )

    # The claim is not "a listing exists" but "a buyer can see it". A DRAFT is
    # invisible to everyone but us, and recording one as evidence of being open
    # for business is the shape of misquote this repository is named after.
    published = [
        row
        for rows in record["listings"].values()
        for row in rows
        if row.get("status") == "PUBLISHED"
    ]
    assert published, (
        "every recorded listing is a draft; nothing here is visible to a buyer"
    )
    for row in published:
        assert row["listing_id"] and Decimal(row["base_price"]) > 0
        assert row["currency"] == "USDC"


def test_the_live_price_is_the_price_the_spec_asks_for() -> None:
    """A spec edited without `--reprice` leaves the marketplace on the old price.

    Compared as `Decimal`, not as strings, and that is the whole subtlety: we
    send `"0.20"` and the server stores `"0.2"`. Those are the same amount, and
    a string comparison would report a drift that is not one — then get
    "fixed" by loosening the check that would have caught a real one.
    """
    if not RECORD.is_file():
        pytest.skip("no live listing has been created yet")
    record = json.loads(RECORD.read_text())

    checked = 0
    for slug, rows in record["listings"].items():
        want = Decimal(record["agents"][slug]["price_usdc"])
        for row in rows:
            assert Decimal(row["base_price"]) == want, (
                f"{slug} is listed at {row['base_price']} and the spec asks "
                f"{want} — run `termix_listing.py --reprice`"
            )
            checked += 1
    assert checked, "no live listing was compared, so this proved nothing"


def test_every_sellable_listing_offers_tiers_a_buyer_can_pick_between() -> None:
    """`packages: []` is why a listing cannot be bought instantly.

    Measured over 571 listings: every one of the 18 buyable ones sampled in
    detail carries at least one package, and not one listing with no packages
    is buyable. Necessary, not sufficient — six non-buyable listings do have
    packages and all six were under a fortnight old against a buyable median of
    55 days — but the necessary half is the half we can set.
    """
    for slug in listings.SELLABLE:
        spec = listings.SPECS[slug]
        assert spec.packages, f"{slug} offers nothing to buy"
        ids = [p["id"] for p in spec.packages]
        assert len(ids) == len(set(ids)), f"{slug} repeats a package id"
        for row in spec.packages:
            for field in ("id", "name", "price", "delivery", "scope"):
                assert row.get(field), f"{slug}'s {row.get('id')} tier has no {field}"


def test_the_tiers_differ_in_what_is_delivered_and_not_only_in_price() -> None:
    """Three prices for one job is a pricing trick, not a set of packages.

    Scopes must be distinct, and the price must rise with them — a premium tier
    that costs more and says the same thing is the shape this repository would
    call a misquote if it found it on somebody else's page.
    """
    from decimal import Decimal

    for slug in listings.SELLABLE:
        spec = listings.SPECS[slug]
        scopes = [p["scope"] for p in spec.packages]
        assert len(set(scopes)) == len(scopes), f"{slug} sells one scope at several prices"
        prices = [Decimal(p["price"]) for p in spec.packages]
        assert prices == sorted(prices), f"{slug}'s tiers do not ascend: {prices}"
        assert prices[0] == spec.price_usdc, (
            f"{slug}'s cheapest tier is {prices[0]} and the listing advertises "
            f"{spec.price_usdc}; the headline price must be one a buyer can pay"
        )
        # Everything stays under a dollar: these are demonstrations.
        assert max(prices) < Decimal("1"), f"{slug} asks {max(prices)} for a tier"


def test_prices_are_exact_decimals_and_never_floats() -> None:
    """0.15 is not representable in binary, and money is not a float.

    The API wants `basePrice` as a string for this reason. A spec holding
    `0.15` as a float sends `"0.15000000000000002"`, which is both wrong and
    the kind of wrong that survives review because it looks like a rounding
    detail rather than a price.
    """
    for slug in listings.SELLABLE:
        price = listings.SPECS[slug].price_usdc
        assert isinstance(price, Decimal), f"{slug}'s price is a {type(price).__name__}"
        body = listings.service_body(listings.SPECS[slug], PREFLIGHT)
        assert "0000000" not in body["basePrice"], body["basePrice"]
