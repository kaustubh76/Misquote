"""Types for an agent that chooses a venue, not a range.

## Why these are siblings of `Decision` and `Observation` rather than reuses

`Decision` has eight fields and four of them — `target_lower`, `target_upper`,
`center_tick`, `half_width_ticks` — are positions on a tick grid. A yield router
has no tick grid. Filling them would put four numbers with no referent onto a
card, through `tearsheet/generate.py` and `AgentCard.tsx`, which is `Readme.md`
rule 6 broken inside the one product built to argue against breaking it.

Grid faced a weaker version of this and its code says so at `agents/grid/policy.py`:
it sets `r=obs.y` and `delta_star=float(width)` under the note that this "keeps
the journal schema identical without pretending the quantities mean what
Warden's do". That trade was available to Grid because Grid *is* a range policy —
a centre and a half-width mean the same thing to it as to Warden, and only two
A-S scalars had to be relabelled. Four of eight is not the same trade.

The input side is stronger still. `Observation`'s docstring is explicit:
"Scalars only… If you find yourself wanting to add a list or an object here,
that is the firewall working." A router needs a *vector* of venue rates. Adding
`aprs: tuple[...]` there would break the structural property that makes
look-ahead impossible rather than merely tested for; flattening it into
`apr_venue_0`, `apr_venue_1`, … would break it more quietly.

So: new types, same discipline. Frozen, slots, and a `__post_init__` that
refuses rather than degrades.

## The reason a refusal beats a clamp, restated for this agent

`Params.__post_init__` refuses a `z_pull` at or above `sqrt(M)` because such a
threshold reads as configured and can never fire — this repository shipped two
gates wired to nothing and found both by accident. The router's version is
`hurdle_apr` above the whitelist's observable spread: a boundary the venues
cannot cross renders identically to a boundary the market never approached, and
"never fired because the edge was not there" is a finding while "never fired
because the threshold was impossible" is a defect. They must not look the same,
so the second one refuses to construct.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

#: A venue's identity is its market address, lowercased. The same string the
#: rate tape keys on and the artifact renders, so nothing has to map between
#: three spellings of one venue.
VenueId = str


class AllocationAction(StrEnum):
    HOLD = "hold"
    ENTER = "enter"
    SWITCH = "switch"
    EXIT = "exit"


@dataclass(frozen=True, slots=True)
class VenueQuote:
    """One venue as the policy sees it at one instant.

    `apr` is the **realized** trailing rate from `estimators/apr.py`, derived by
    differencing an accumulator — never `supplyRatePerBlock()`, whose conversion
    to an annual figure needs a blocks-per-year constant that is not readable
    from chain and whose plausible values span 6.67x. A field named `apr` that
    silently carried the quoted number would be the misquote with our own logo
    on it.
    """

    venue_id: VenueId
    apr: float
    #: How many accruals the estimate rests on. Below the policy's floor the
    #: venue is not quotable, which is different from it yielding little.
    apr_samples: int
    #: True when the market has not accrued inside the trailing window. The
    #: analogue of `kappa_is_fallback`: an unmeasured venue and a zero-yield
    #: venue must not render the same, and the router refuses the first rather
    #: than ranking it last.
    apr_is_stale: bool
    #: Free liquidity in the market, in underlying units.
    #:
    #: This claimed to "bound how much can be routed here" and bounded nothing:
    #: `capped_notional`, the driver's A1 check and `RouterDetail.tsx` all use
    #: `supplied_base_quote`, and the artifact never carried this at all. A
    #: field whose docstring describes a guarantee it does not provide is worse
    #: than an absent one, so the sentence now matches the code.
    #:
    #: Kept because it is a real reading and the honest thing a router wants to
    #: know before supplying is whether it could *withdraw* — that is cash, not
    #: supplied base. Nothing asks yet; when something does, it asks this.
    cash_quote: float
    #: Total supplied base, the denominator A1's epsilon applies to.
    supplied_base_quote: float
    #: Whether `apr` is a lower bound rather than a point estimate.
    #:
    #: A lending rate is differenced from an accumulator and is the rate. A pool's
    #: is fees minus a convexity cost that A10 publishes as an **upper bound** on
    #: adverse selection, so the subtraction is a lower bound on what the position
    #: earned — the pessimistic end, never the middle.
    #:
    #: It exists because the floor below is right for one of those and wrong for
    #: the other. Differencing an accumulator genuinely cannot show a supplier
    #: losing more than they supplied. Annualising can: a range that gives up
    #: 0.75% of its capital to arbitrage in a day is at a rate of -273% a year,
    #: which is arithmetic rather than an accounting error, and rejecting it
    #: would force the pool venue to either clamp — the thing this project is
    #: named against — or lie about which quantity it had measured.
    #:
    #: Ranking a lower bound against a point estimate is conservative, so the
    #: policy needs no knowledge of it. The card does: it is the difference
    #: between the two numbers a reader is being shown side by side.
    apr_is_lower_bound: bool = False

    def __post_init__(self) -> None:
        if not self.venue_id:
            raise ValueError("a venue with no id cannot be journalled or rendered")
        if self.apr < -1.0 and not self.apr_is_lower_bound:
            raise ValueError(
                f"apr={self.apr} is below -100%: a supplied position cannot lose more "
                f"than it supplied, so this is an accounting error rather than a rate"
            )
        if self.apr_samples < 0:
            raise ValueError("apr_samples cannot be negative")
        if self.cash_quote < 0 or self.supplied_base_quote < 0:
            raise ValueError("a market cannot hold negative liquidity")


@dataclass(frozen=True, slots=True)
class AllocationObservation:
    """Everything the router may see, and nothing else.

    `venues` is a tuple of frozen scalar-only records rather than a list of
    handles. The firewall `Observation` maintains is about what the policy can
    *reach* — an object with a live connection behind it can reach the future.
    Frozen dataclasses of floats cannot, so the property survives the shape
    change, and this note is here because the shape looks like a violation of it.
    """

    t: int
    venues: tuple[VenueQuote, ...]
    held: VenueId | None
    notional_quote: float
    #: One round trip's gas, in quote units. Charged twice per switch — the
    #: redeem and the supply.
    gas_quote: float
    #: The cost of moving between venues' underlyings, in basis points. This is
    #: the **full** pool fee, not the LP's share of it: see `agents/router/policy.py`.
    switch_slippage_bps: float
    seconds_since_switch: int
    switches_today: int
    #: Consecutive prior samples on which the best venue beat the held one by
    #: more than the hurdle. The driver owns this counter, exactly as it owns
    #: `toxic_streak` for the Warden.
    edge_streak: int

    def __post_init__(self) -> None:
        if not self.venues:
            raise ValueError("a router with no venues has nothing to choose between")
        if self.notional_quote <= 0:
            raise ValueError("a position of zero size has no yield to optimise")
        if self.gas_quote < 0 or self.switch_slippage_bps < 0:
            raise ValueError("costs cannot be negative")
        if self.edge_streak < 0 or self.switches_today < 0 or self.seconds_since_switch < 0:
            raise ValueError("counters cannot be negative")
        if self.held is not None and all(v.venue_id != self.held for v in self.venues):
            raise ValueError(
                f"held venue {self.held} is not among the observed venues. A policy "
                f"asked to compare against a venue it cannot see would silently treat "
                f"the position as flat and re-enter on top of it."
            )

    def venue(self, venue_id: VenueId) -> VenueQuote | None:
        for v in self.venues:
            if v.venue_id == venue_id:
                return v
        return None

    @property
    def held_quote(self) -> VenueQuote | None:
        return self.venue(self.held) if self.held is not None else None


@dataclass(frozen=True, slots=True)
class AllocationDecision:
    """What the router decided, and every gate that was consulted to decide it.

    `reasons` is a tuple of pairs for the reason `Decision.reasons` is: the
    decision stays hashable, and a gate that did *not* fire is still journalled.
    An agent whose held-by-gate histogram has an empty column is an agent with a
    rule wired to nothing, and this repository has shipped two of those.
    """

    action: AllocationAction
    target_venue: VenueId | None
    held_venue: VenueId | None
    #: apr(best) - apr(held), gross of costs, per annum.
    edge_apr: float
    #: The switching boundary the edge was tested against, in the same units.
    hurdle_apr: float
    reasons: tuple[tuple[str, float], ...]

    @property
    def moves(self) -> bool:
        return self.action in (
            AllocationAction.ENTER,
            AllocationAction.SWITCH,
            AllocationAction.EXIT,
        )

    def reason(self, name: str) -> float | None:
        for key, value in self.reasons:
            if key == name:
                return value
        return None
