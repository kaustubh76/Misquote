"""What each agent sells on TermiX, and the live route that proves it can.

## The gap this closes

TermiX's explorer indexes every ERC-8004 mint — 340,954 of them across 17,048
pages — so our agents appeared there the moment they were minted and it meant
nothing. `vetting/identity/termix-listing-56.json` answers "does a mainnet mint
list us"; **yes**, and being listed is not being open for business.

A seller on that marketplace sells a *listing*. Without one an agent cannot be
ordered from, cannot quote on an open brief, and cannot claim a campaign slot —
which is exactly the state all five were in: `completedJobs: 0`, `stake: "0"`,
`services: {"items": []}`, indistinguishable from the other 340,949.

## Every listing is checked against a live route before it is offered

A marketplace listing is a promise with a price on it. So each spec names the
route on the running service that produces its deliverable, and
`scripts/termix_listing.py` reads that route before it will create anything. An
agent whose route does not answer is **refused, not listed** — which is the
whole reason `Router` has a spec and no listing.

The copy is generated from the reading rather than written beside it, so a pool
that stops clearing the evidence floor drops out of the sales text instead of
surviving there because nobody reread it. `tests/registry/test_termix_listing.py`
is what holds that.

## What is deliberately not here

No stake. Sellers carry one and ours is `"0"`, which is visible and honest;
buying standing with a deposit is a different decision and belongs to whoever
funds the wallet, not to this module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

#: Their enum, and it is the **label**, not the `slug` that
#: `/api/v1/service-categories` returns beside it. A body sent with `"research"`
#: is refused with all eight listed; discovered that way rather than guessed,
#: the way `WALLET_FIELDS` was.
CATEGORIES = (
    "Code & Smart Contracts",
    "Security & Verification",
    "Data & Research",
    "Design & Brand",
    "Writing & Content",
    "Automation & Ops",
    "Market & Protocol Research",
    "Model & Dataset Ops",
)


#: Required by `POST /agents/{id}/services` (`coverImageUrl: Required`), and it
#: is the image TermiX already shows as every one of our agents' avatars — the
#: site's own Open Graph card, live and ours. Per-agent covers do not exist:
#: `/agent/{slug}/opengraph-image.png` is a 404 on the deployed site, and
#: pointing a listing at one would be advertising with a broken image.
COVER_IMAGE = "https://misquote.vercel.app/opengraph-image.png"


@dataclass(frozen=True, slots=True)
class Listing:
    """One agent's offer, and the route that has to answer before it is made.

    `probe_path` is not decoration. It is read live by the script, its reading
    is what generates `description`, and a spec whose probe returns nothing
    usable is refused — so an agent cannot be listed for work the deployed
    service has no way to produce.
    """

    slug: str
    #: TermiX's own id for the agent (a cuid), from an authenticated
    #: `GET /api/v1/agents`. Not the ERC-8004 token id.
    agent_id: str
    token_id: str
    name: str
    title: str
    category: str
    price_usdc: Decimal
    delivery_days: int
    tags: tuple[str, ...]
    #: The live route whose reading both proves delivery and writes the copy.
    #: `None` means nothing on the deployed service produces this, and the
    #: script refuses rather than listing it.
    probe_path: str | None
    describe: Callable[[dict[str, Any]], str]
    #: Why this one cannot be listed yet. Set only when `probe_path` is None.
    blocked: str = ""


# ── Warden: a position, replayed ─────────────────────────────────────────────


def _quotable(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in preflight.get("pools", []) if p.get("quotable")]


def pool_lines(preflight: dict[str, Any]) -> list[str]:
    """One line per pool the service will actually quote, from its own preflight."""
    lines = []
    for pool in _quotable(preflight):
        tape = pool.get("tape") or {}
        lines.append(
            f"- {pool.get('label')} — {tape.get('swaps'):,} swaps over {tape.get('hours'):g}h of tape"
        )
    return lines


def warden_description(preflight: dict[str, Any]) -> str:
    pools = pool_lines(preflight) or ["- (no pool currently clears the evidence floor)"]
    return "\n".join(
        [
            "Give me a PancakeSwap v3 position — a wallet address, or a pool with a "
            "range and a size — and I return what it would have done, replayed "
            "swap by swap over recorded BNB Smart Chain history.",
            "",
            "**What you get**",
            "",
            "- The share of time the position was in range, and the fees it accrued.",
            "- Impermanent loss against simply holding.",
            "- Twenty overlapping windows, reported as a P25-P75 band rather than "
            "one number, so you can see the spread and not just the median.",
            "- The decision journal behind it: every window, and the ones withheld.",
            "",
            "**Pools I can answer for today**",
            "",
            *pools,
            "",
            "**What you get instead of a number, when the evidence is thin**",
            "",
            "A refusal that names what is missing. If a pool's tape does not cover "
            "at least twenty windows of twenty-four hours, I will not quote it, and "
            "I will say so rather than interpolate a figure that looks precise. "
            "Check it before ordering: `/quote/preflight` publishes every pool's "
            "coverage and its verdict, and it is a public read.",
        ]
    )


# ── Grid: which width, and which widths are the same as it ───────────────────


def _sufficient_rungs(pools: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for pool in pools.get("pools", []):
        rungs = [r for r in (pool.get("ladder") or []) if r.get("sufficient")]
        if rungs:
            out.append({"pool": pool, "rungs": rungs})
    return out


def grid_description(pools: dict[str, Any]) -> str:
    ready = _sufficient_rungs(pools)
    lines = [
        f"- {e['pool'].get('label')} — {len(e['rungs'])} widths cleared the floor, "
        f"best {e['pool'].get('best_width_ticks')} ticks"
        for e in ready
    ] or ["- (no pool has enough observations to rank a width today)"]
    return "\n".join(
        [
            "Name a PancakeSwap v3 pool and I tell you what range width to set, "
            "from a ladder of widths each replayed over the same recorded swaps.",
            "",
            "**What you get**",
            "",
            "- A ladder of candidate widths, each with the fee return it earned as "
            "a P25-P75 band across twenty windows.",
            "- The width that ranked best, and — the part most tools omit — **which "
            "other widths are statistically indistinguishable from it**, so you are "
            "not sold a precision the data does not support.",
            "- The pool's own demand behind it: swap count, tick crossings, and the "
            "LP's share of the fee after the protocol takes its cut, read from the "
            "pool rather than assumed.",
            "",
            "**Pools I can rank today**",
            "",
            *lines,
            "",
            "**What you get instead of a ranking**",
            "",
            "A rung that has not been observed enough times is marked insufficient "
            "and is not ranked. If no rung clears, you get that answer and not a "
            "best guess. `/pools` publishes every ladder, every observation count "
            "and every sufficiency flag as a public read.",
        ]
    )


# ── Sentinel: what has actually been checked about a pool ────────────────────


def sentinel_description(vetting: dict[str, Any]) -> str:
    badged = vetting.get("badged") or []
    unbadged = vetting.get("known_and_unbadged") or []
    return "\n".join(
        [
            "Before you put capital in a PancakeSwap v3 pool, I tell you what has "
            "been read off the chain about it and what has not.",
            "",
            "**What you get**",
            "",
            "- Nine checks taken at one block: that the factory resolves the "
            "address, that the tick spacing matches the fee tier, the protocol fee "
            "actually set on that pool, and the token decimals as the contracts "
            "report them.",
            "- Each check carries its provenance — the finding that made it worth "
            "checking. The protocol fee is 3400 on one pool and 3200 on another, "
            "so no hardcoded constant is right, and a tool that assumes one is "
            "wrong about your fee income.",
            "- BSC's USDT and USDC are 18 decimals where Ethereum's are 6. That is "
            "read, never assumed; assuming it misprices by twelve orders of "
            "magnitude.",
            "",
            f"**Pools already examined:** {len(badged)}"
            + (f" · **known and not yet examined:** {len(unbadged)}" if unbadged else ""),
            "",
            "**What a badge is not**",
            "",
            "It is nine readings at one block, not a live monitor and not an audit. "
            "An unbadged pool has not been examined — that is an absence, not a "
            "clean bill of health, and I will say so rather than let silence read "
            "as approval. `/vetting` publishes every badge as a public read.",
        ]
    )


def _router_blocked(_: dict[str, Any]) -> str:  # pragma: no cover - never called
    raise AssertionError("Router has no probe; the script refuses before describing it")


#: Every agent, listable or not. Router is here **because** it is refused: a
#: registry that silently omitted it would be a registry that lost the reason.
SPECS: dict[str, Listing] = {
    "warden": Listing(
        slug="warden",
        # Not 323262 and not 331590. TermiX attributes an agent to the wallet
        # that **minted** it, so 323262 — minted by a delegate and transferred —
        # is owned by us and invisible to their index; 331590 is an unintended
        # duplicate from a run recorded as "nothing was sent" after a 403 on the
        # receipt read. `termix-listing-56.json` carries both findings.
        agent_id="cmtl14z110cy8x901uxqdic1o",
        token_id="331592",
        name="Warden-3",
        title="Liquidity position risk quote, replayed on real PancakeSwap swaps",
        category="Market & Protocol Research",
        # Fractions of a dollar, deliberately. `/api/v1/listings/price-range`
        # reports their floor at 0.01 USDC and there are live listings sitting
        # on it, so this is a supported price and not a loophole. These agents
        # are being demonstrated, and a real ask for a real dollar invites a
        # stranger to buy an evaluation. The ordering between the three is kept
        # because it still says something true about the work each order causes.
        price_usdc=Decimal("0.25"),
        delivery_days=1,
        tags=("DeFi", "Liquidity", "Risk Analysis"),
        probe_path="/quote/preflight",
        describe=warden_description,
    ),
    "grid": Listing(
        slug="grid",
        agent_id="cmthhi6te3am8tr01mamogmpb",
        token_id="323332",
        name="Grid",
        title="Which range width to set on a PancakeSwap v3 pool, and which are the same",
        category="Market & Protocol Research",
        # Below Warden's: this reads a ladder that has already been computed
        # rather than replaying a position the buyer describes.
        price_usdc=Decimal("0.20"),
        delivery_days=1,
        tags=("DeFi", "Market Making", "Liquidity"),
        probe_path="/pools",
        describe=grid_description,
    ),
    "sentinel": Listing(
        slug="sentinel",
        agent_id="cmthhibg73ap6tr01ie8puf1q",
        token_id="323333",
        name="Sentinel-323333",
        title="Pool due diligence: nine chain reads, with what each one is for",
        category="Security & Verification",
        # The cheapest of the three, and it should be: the badge is nine reads
        # taken at one block, already recorded. Pricing it like a replay would
        # be charging for work that is not being done per order.
        price_usdc=Decimal("0.15"),
        delivery_days=1,
        tags=("DeFi", "Security", "Due Diligence"),
        probe_path="/vetting",
        describe=sentinel_description,
    ),
    "router": Listing(
        slug="router",
        agent_id="cmthhic0c3aphtr01csjp8qjm",
        token_id="323334",
        name="Router",
        title="",
        category="Market & Protocol Research",
        price_usdc=Decimal("0"),
        delivery_days=0,
        tags=(),
        probe_path=None,
        describe=_router_blocked,
        blocked=(
            "no route on the deployed service produces a venue comparison — "
            "/venue, /venus and /route all answer 404, and the Venus rate tape "
            "lives in artifacts rather than behind an endpoint. Its journal is "
            "real (169 decisions, 168 of them holds) but a journal is evidence "
            "of past behaviour, not a thing a buyer can order. Listing it would "
            "sell work the service cannot perform on demand."
        ),
    ),
}

#: Listable today: a spec with a probe. Router is excluded by having none, which
#: is a fact about the deployment rather than a decision recorded here.
SELLABLE = tuple(slug for slug, spec in SPECS.items() if spec.probe_path)


def service_body(spec: Listing, reading: dict[str, Any]) -> dict[str, Any]:
    """The body for `POST /api/v1/agents/{id}/services`.

    Only `title` and `category` are known-required — the server validates one
    field at a time and named those two first. The rest are sent because a
    listing with no price or delivery window is not a thing a buyer can act on,
    and an unknown key is refused loudly (`Unrecognized key(s)`), which is the
    good failure: it names itself.
    """
    return {
        "title": spec.title,
        "category": spec.category,
        "description": spec.describe(reading),
        # `basePrice`, not `price`, and a **string**, not a number. Both named by
        # the server one at a time — `basePrice: Required`, then `basePrice:
        # Expected string, received number` — which is the same validation
        # `WALLET_FIELDS` was read off.
        #
        # `Decimal`, never `float`, and this is the reason the API wants a
        # string: 0.15 is not representable in binary, so a float round-trip
        # turns a price into 0.15000000000000002. Money is decimal, and the two
        # places it must not stop being decimal are the wire and the source.
        "basePrice": str(spec.price_usdc),
        "coverImageUrl": COVER_IMAGE,
        "currency": "USDC",
        "deliveryDays": spec.delivery_days,
        "tags": list(spec.tags),
    }


def services(session, agent_id: str) -> dict[str, Any]:
    """What this agent already sells. `{"items": []}` is the before state."""
    return session.get(f"/api/v1/agents/{agent_id}/services")


def create_service(session, spec: Listing, body: dict[str, Any]) -> Any:
    """One POST. Returns the response whether it validated or not.

    A `400` here is the useful answer, not an error: it names the field the body
    is missing, which is how the rest of this schema gets discovered. The caller
    decides whether to retry, because retrying in a loop is how a marketplace
    ends up holding six draft listings nobody meant to create.
    """
    return session.post(f"/api/v1/agents/{spec.agent_id}/services", body)


def update_listing(session, listing_id: str, body: dict[str, Any]) -> Any:
    """Edit a listing that is already live. `PATCH /api/v1/listings/{id}`.

    Used to reprice rather than to delete and recreate: a new listing would get
    a new id, and the id is what `termix-listing-live-56.json` and every link to
    it already name. Repricing in place keeps the record true.
    """
    return session.patch(f"/api/v1/listings/{listing_id}", body)


def publish(session, listing_id: str) -> Any:
    """Take a draft live. Separate from creation because the API separates them.

    Two calls means a draft can be read back and deleted before anyone sees it,
    which is the only reason this is safe to run against production at all.
    """
    return session.post(f"/api/v1/listings/{listing_id}/publish", {})


__all__ = [
    "CATEGORIES",
    "COVER_IMAGE",
    "SELLABLE",
    "SPECS",
    "Listing",
    "create_service",
    "grid_description",
    "pool_lines",
    "publish",
    "sentinel_description",
    "service_body",
    "update_listing",
    "services",
    "warden_description",
]
