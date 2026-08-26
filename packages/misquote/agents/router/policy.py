"""Router: move only when the yield gained beats the cost of moving.

Warden asks where a range should be. Grid asks nothing and places a ladder.
Router asks a third kind of question — *which venue* — and it is the one of the
four that needed a second venue model, which is why it was cut once and recorded
on the ledger rather than faked.

## The rule

Over a horizon `H`, moving `N` of capital from the held venue to the best one
gains the rate difference and costs two transactions plus the slippage of
swapping one underlying for the other:

    gain   = (apr_best - apr_held) * N * H / year
    cost   = 2 * gas + N * slippage_bps / 10_000
    hurdle = cost * (1 + margin) / N * year / H        # cost, back in APR units

    move iff edge > hurdle
         and edge has held for `persistence_samples` consecutive samples
         and cooldown has elapsed
         and today's switch budget is not spent

Expressing the hurdle in APR units rather than comparing currency amounts is
deliberate: it is the number a card can print beside the edge, and a reader can
check the comparison without re-deriving the horizon.

## The switch cost uses the full pool fee, not the LP's share

`PoolMeta.lp_fee_bps` is what a liquidity provider *keeps* after PancakeSwap's
protocol cut — 66% of the headline tier on our pool, because the protocol takes
34% (P-1). A router **paying** to swap USDT for USDC pays the whole tier; the
protocol's share is a cost to it, not a rebate. Using `lp_fee_bps` here would
understate every switch by exactly that cut and make the router move more often
than it should — P-1 in a mirror, and the same magnitude.

## This is the myopic boundary, widened by a published margin

The optimal switching boundary under a mean-reverting rate spread is strictly
wider than break-even: paying to chase an edge that is about to close is a real
loss, and the option to move later has value. Solving that free boundary
properly needs a model of the spread this repository has not fitted and cannot
fit honestly on the tape it holds. So `switch_cost_margin` and
`persistence_samples` are a **stated approximation** of that widening rather
than a derivation of it, and they are published as an assumption. Assumption A9
does the same for equation (2) pricing no adverse selection.

## A dead gate is a result, not a bug to tune away

If the whitelist's spread never exceeds the hurdle over the tape, Router
publishes zero switches and a quote equal to its entry venue's. That is the
honest outcome and it is reported as one, with the measured maximum edge printed
beside the measured hurdle so a reader can see how far apart they were.

What is forbidden is lowering `switch_cost_margin` until activity appears.
`docs/FOR_JUDGES.md` states the rule: moving a parameter because it produced an
unflattering result is the fitting this project exists to refuse. Sentinel's
whole contribution was a rule that had never fired; the answer there was to find
out why, not to make it fire.
"""

from __future__ import annotations

from dataclasses import dataclass

from misquote.core.allocation import (
    AllocationAction,
    AllocationDecision,
    AllocationObservation,
    VenueQuote,
)
from misquote.core.types import SECONDS_PER_YEAR, Params
from misquote.tearsheet.generate import MIN_OBSERVATIONS


@dataclass(frozen=True, slots=True)
class RouterParams:
    """Every number Router needs, and nothing else."""

    #: What the edge is integrated over when pricing a move. A week: long enough
    #: that a switch has time to repay its cost, short enough that a rate
    #: measured over a day is still informative about it.
    horizon_hours: float = 168.0
    #: How many multiples of the round-trip cost the gain must clear. 1.0 means
    #: "the move must pay for itself twice over" — the stated stand-in for the
    #: free boundary this does not solve.
    switch_cost_margin: float = 1.0
    #: Consecutive samples the edge must hold. Same shape as `m_toxic`.
    persistence_samples: int = 3
    cooldown_s: int = 21_600
    max_switches_per_day: int = 4
    #: Below this many accruals a venue is not quotable.
    #:
    #: Imported rather than restated: `verdict(min_n=...)` sets the same floor
    #: for every reported rate here, and two spellings of one floor are two
    #: chances for them to drift.
    min_apr_samples: int = MIN_OBSERVATIONS
    #: A1's analogue: the largest share of a market's supplied base this agent
    #: will occupy. Beyond it the position moves the rate it was chosen for, and
    #: the replay stops being a replay.
    #:
    #: The same fraction `Params.eps_liquidity_share` applies to a pool, and read
    #: from it — A1 is one assumption, not one per venue type.
    eps_market_share: float = Params().eps_liquidity_share

    def __post_init__(self) -> None:
        if self.horizon_hours <= 0:
            raise ValueError("a horizon of zero prices every move as infinitely expensive")
        if self.switch_cost_margin < 0:
            raise ValueError(
                "a negative margin would move for a gain smaller than the cost of moving"
            )
        if self.persistence_samples < 1:
            raise ValueError("persistence must be at least one sample")
        if self.cooldown_s < 0:
            raise ValueError("cooldown cannot be negative")
        if self.max_switches_per_day < 1:
            raise ValueError(
                "a switch budget of zero is a router that can never route; if that is "
                "intended, do not list the agent"
            )
        if self.min_apr_samples < 2:
            raise ValueError(
                "a rate needs two accruals to difference, so a floor below two would "
                "admit venues whose APR is not defined"
            )
        if not 0 < self.eps_market_share <= 1:
            raise ValueError("eps_market_share must be a fraction of a market, in (0, 1]")


def hurdle_apr(obs: AllocationObservation, params: RouterParams) -> float:
    """The switching boundary, in APR units.

    Two transactions' gas plus the slippage of the swap, marked up by the
    margin, divided by the notional and annualised over the horizon — so it is
    directly comparable to an APR difference and can be printed beside one.
    """
    cost = 2.0 * obs.gas_quote + obs.notional_quote * obs.switch_slippage_bps / 10_000.0
    horizon_years = params.horizon_hours * 3600.0 / SECONDS_PER_YEAR
    return cost * (1.0 + params.switch_cost_margin) / obs.notional_quote / horizon_years


# `breakeven_horizon_hours` lived here and had no callers.
#
# It computed `horizon * hurdle(obs) / apr` from a single observation, while
# `replay/allocation.py` computes `horizon * hurdle_p50 / best_apr_seen` across
# a whole run — a different number, and the one every card and report actually
# prints. Two functions answering one question differently, with only the
# unreferenced one carrying the name.
#
# `tests/test_no_dead_definitions.py` could not see it: it collects
# `ast.Attribute.attr`, and `AllocationResult.breakeven_horizon_hours` is read
# as an attribute in three places, so the attribute name shadowed the function
# name in its `USED` set. `replay/driver.py` documents the same trap under
# `passive_result` — "dead code that answers a live question differently is a
# trap with a fuse in it" — and this was that trap, lit again.
#
# Deleted rather than wired. The driver's version is the published one.


def quotable(venue: VenueQuote, params: RouterParams) -> bool:
    """Whether a venue may be chosen at all.

    Staleness is disqualifying rather than merely unattractive. A market that
    has not accrued inside the window has an unmeasured rate, and an unmeasured
    rate ranked against measured ones is a guess competing with observations.
    """
    return not venue.apr_is_stale and venue.apr_samples >= params.min_apr_samples


def capped_notional(venue: VenueQuote, params: RouterParams) -> float:
    """The most this agent may route into a venue before it moves the rate.

    A1 says a replayed position large enough to move the price it is replayed
    against is not a backtest. Supplying into a lending market moves utilisation
    and therefore the rate, so the same ceiling applies with the market's
    supplied base in place of the pool's liquidity.
    """
    return params.eps_market_share * venue.supplied_base_quote


def decide_router(
    obs: AllocationObservation, params: RouterParams, _meta: object = None
) -> AllocationDecision:
    """Choose a venue, or decline to move, and say which gate decided it.

    Signature mirrors `decide` and `decide_grid` — observation, params, venue
    context — so the driver, the journal and the tearsheet need no knowledge of
    which agent produced the decision. The third argument is unused here and
    named so: a lending venue's static facts are already inside each
    `VenueQuote`, and inventing a `VenueMeta` to fill the slot would be shape
    for its own sake.
    """
    quoted = [v for v in obs.venues if quotable(v, params)]
    # A1, at the point of decision rather than in the post-mortem.
    #
    # `capped_notional` has existed and been tested since this policy was
    # written and nothing ever called it. The driver counted breaches into
    # `a1_capped` *after* the position was already there, and
    # `allocation_quote_from_results` then refused the whole quote. That is the
    # right refusal in the wrong place: a gate that only fires once the capital
    # has been committed is a gate structurally unable to prevent anything,
    # which is the defect `core/allocation.py` says this repo has shipped twice.
    #
    # It never bound because every venue was a Venus market holding hundreds of
    # millions, and one percent of that is far more than this agent routes. A
    # concentrated-liquidity range is the case that shows it: depth over +/-80
    # ticks of the flagship pool is ~$218k, so A1's ceiling is ~$2.2k and a
    # $10,000 notional is over it — not marginally, but by four and a half
    # times. Supplying it would move the very rate it was chosen for.
    #
    # Declining is not the same as the venue being poor, and the reason code
    # says which, so a card can report "the yield was there and the size was
    # not" rather than leaving a reader to infer a rate that never existed.
    live = [v for v in quoted if capped_notional(v, params) >= obs.notional_quote]
    hurdle = hurdle_apr(obs, params)

    reasons: list[tuple[str, float]] = [
        ("venues_observed", float(len(obs.venues))),
        ("venues_quotable", float(len(quoted))),
        ("venues_absorbing", float(len(live))),
        ("hurdle_apr", hurdle),
        ("notional_quote", obs.notional_quote),
    ]
    if quoted and not live:
        reasons.append(("reason_a1_no_venue_can_absorb", 1.0))

    # Leaving a venue the position has outgrown comes before everything else,
    # including the "nothing is measurable, so stay put" branch below.
    #
    # That branch is right about an *unmeasured* venue — moving on a guess is
    # worse than staying — and wrong about this one, which is measured and
    # measured as too small. Ordering it second would mean a position that had
    # outgrown the only venue on offer would be held there indefinitely, still
    # breaching the ceiling every sample, because no alternative was quotable.
    outgrown = obs.held_quote is not None and (
        capped_notional(obs.held_quote, params) < obs.notional_quote
    )
    if outgrown:
        reasons += [("held", 1.0), ("held_outgrew_venue", 1.0), ("reason_exit_a1_outgrown", 1.0)]
        return AllocationDecision(
            action=AllocationAction.EXIT,
            target_venue=None,
            held_venue=obs.held,
            edge_apr=0.0,
            hurdle_apr=hurdle,
            reasons=tuple(reasons),
        )

    if not live:
        # Every venue unmeasured. Not the same as every venue being poor, and
        # the position stays where it is rather than moving on a guess.
        reasons.append(("reason_no_quotable_venue", 1.0))
        return AllocationDecision(
            action=AllocationAction.HOLD,
            target_venue=None,
            held_venue=obs.held,
            edge_apr=0.0,
            hurdle_apr=hurdle,
            reasons=tuple(reasons),
        )

    best = max(live, key=lambda v: v.apr)
    reasons.append(("best_apr", best.apr))
    # Journalled because A1's ceiling is a fraction of it, and a ceiling whose
    # denominator is not recorded cannot be checked after the fact.
    reasons.append(("supplied_base_quote", best.supplied_base_quote))

    held = obs.held_quote
    if held is None:
        # Flat. Entering is priced against the same hurdle rather than waved
        # through: the first move costs as much as any other, and an agent that
        # enters free and switches dearly is two policies wearing one name.
        gain_apr = best.apr
        affordable = gain_apr > hurdle
        reasons += [("held", 0.0), ("edge_apr", gain_apr), ("entry_affordable", float(affordable))]
        if affordable:
            reasons.append(("reason_enter", 1.0))
            return AllocationDecision(
                action=AllocationAction.ENTER,
                target_venue=best.venue_id,
                held_venue=None,
                edge_apr=gain_apr,
                hurdle_apr=hurdle,
                reasons=tuple(reasons),
            )
        reasons.append(("reason_entry_below_hurdle", 1.0))
        return AllocationDecision(
            action=AllocationAction.HOLD,
            target_venue=None,
            held_venue=None,
            edge_apr=gain_apr,
            hurdle_apr=hurdle,
            reasons=tuple(reasons),
        )

    # Held, and the held venue may itself have gone stale — in which case it is
    # not in `live` and cannot be compared, so leaving is the only honest move.
    #
    # The A1 counterpart of this exit is handled above, before the "nothing is
    # measurable" branch, because a position that has outgrown its venue must
    # leave whether or not anything else is quotable.
    if not quotable(held, params):
        reasons += [("held", 1.0), ("held_stale", 1.0), ("reason_exit_unmeasurable", 1.0)]
        return AllocationDecision(
            action=AllocationAction.EXIT,
            target_venue=None,
            held_venue=held.venue_id,
            edge_apr=0.0,
            hurdle_apr=hurdle,
            reasons=tuple(reasons),
        )

    edge = best.apr - held.apr
    clears = edge > hurdle
    # `+ 1` counts this sample. Same off-by-one as `toxic_streak`, and the
    # driver owns the counter for the same reason: a policy that incremented
    # its own streak would be holding state across calls and would stop being
    # a pure function of the observation.
    persistent = (obs.edge_streak + 1) >= params.persistence_samples
    cooled = obs.seconds_since_switch >= params.cooldown_s
    budget = obs.switches_today < params.max_switches_per_day
    same = best.venue_id == held.venue_id

    reasons += [
        ("held", 1.0),
        ("held_apr", held.apr),
        ("edge_apr", edge),
        ("edge_clears_hurdle", float(clears)),
        ("edge_streak", float(obs.edge_streak)),
        ("persistence_met", float(persistent)),
        ("cooldown_met", float(cooled)),
        ("switches_today", float(obs.switches_today)),
        ("switch_budget_left", float(budget)),
        ("best_is_held", float(same)),
    ]

    if not same and clears and persistent and cooled and budget:
        reasons.append(("reason_switch", 1.0))
        return AllocationDecision(
            action=AllocationAction.SWITCH,
            target_venue=best.venue_id,
            held_venue=held.venue_id,
            edge_apr=edge,
            hurdle_apr=hurdle,
            reasons=tuple(reasons),
        )

    reasons.append(("reason_hold", 1.0))
    return AllocationDecision(
        action=AllocationAction.HOLD,
        target_venue=None,
        held_venue=held.venue_id,
        edge_apr=edge,
        hurdle_apr=hurdle,
        reasons=tuple(reasons),
    )


def park_policy(
    obs: AllocationObservation, params: RouterParams, _meta: object = None
) -> AllocationDecision:
    """The benchmark: supply to the best venue once, then never move.

    Router's analogue of `core.policy.passive_policy`, and it exists for the
    same reason that one does — a quote of "2.16%" answers nothing on its own,
    because the reader's alternative is not zero. It is picking the venue that
    looks best today and leaving it alone.

    Crucially it runs through the **same driver, the same tape, the same cost
    model and the same quote machinery**; the only thing that differs is the
    function returning a decision. That is what makes the delta a claim about
    the policy rather than about two differently-rigged programs — the argument
    `scripts/showcase.py` makes for the LP agents, transferred.

    It is charged for its one entry. An agent that enters free and switches
    dearly would beat a baseline that pays to enter, and the comparison would be
    measuring the accounting rather than the strategy.

    Note what it is *not*: it is not "hold cash". A router that never supplies
    anything is a worse baseline than a naive one, because beating it would
    prove only that lending pays more than not lending — which nobody disputes
    and which the agent is not for.
    """
    quoted = [v for v in obs.venues if quotable(v, params)]
    # A1 binds the baseline too, and for a stronger reason than it binds the
    # agent: this is what a person does *without* the agent, and a person cannot
    # put ten thousand dollars into a range that holds two thousand either.
    #
    # The gate was added to `decide_router` and not here, and the real tape found
    # it immediately. Parking picks the highest rate on offer, which on this tape
    # is a PancakeSwap range, and it took the position regardless — booking
    # 252.28 of fees on a $10,000 notional that A1 says is fiction, whereupon
    # `allocation_quote_from_results` refused the baseline outright and the whole
    # "vs doing it yourself" comparison went withheld.
    #
    # Refusing was correct. Never taking the position is better: the honest
    # baseline is a person supplying to the best venue they could actually have
    # used, which is a comparison rather than an absence.
    live = [v for v in quoted if capped_notional(v, params) >= obs.notional_quote]
    reasons: list[tuple[str, float]] = [
        ("park", 1.0),
        ("venues_quotable", float(len(quoted))),
        ("venues_absorbing", float(len(live))),
    ]

    if obs.held is not None or not live:
        reasons.append(("reason_hold", 1.0))
        return AllocationDecision(
            action=AllocationAction.HOLD,
            target_venue=None,
            held_venue=obs.held,
            edge_apr=0.0,
            hurdle_apr=hurdle_apr(obs, params),
            reasons=tuple(reasons),
        )

    best = max(live, key=lambda v: v.apr)
    reasons += [("best_apr", best.apr), ("reason_enter", 1.0)]
    return AllocationDecision(
        action=AllocationAction.ENTER,
        target_venue=best.venue_id,
        held_venue=None,
        edge_apr=best.apr,
        hurdle_apr=hurdle_apr(obs, params),
        reasons=tuple(reasons),
    )
