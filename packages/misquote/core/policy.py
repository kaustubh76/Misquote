"""The Warden's policy: Avellaneda-Stoikov, mapped onto v3 ranges.

The design heuristic the agent is built on: a concentrated-liquidity position on
[P_l, P_u] behaves *like* a pair of limit orders. As price rises through the
range the position continuously sells the risk asset, as it falls it continuously
buys. So the market-making solution maps across term by term:

    reservation price r    ->  range centre, inventory-skewed
    optimal half-spread    ->  range half-width
    inventory penalty      ->  the recentre trigger
    adverse selection      ->  LVR, since arbitrage flow is the informed flow
    quote pull on toxicity ->  range withdrawal

**A heuristic, not an isomorphism** — matrix item P-5. Uniswap's own documentation
says range orders "approximate" limit orders and rules out stops entirely, and
the literature characterises AMMs as market makers that *do not* update their
quotes: inventory here is a deterministic function of price rather than a
controlled state, and there is no queue, no cancellation, and no declining a
fill. The mapping motivates the design and produces sane ranges; it does not make
the two objects the same. Equation (2) also prices no adverse selection at all
(assumption A9), which is why sections 3.4 and 4 exist.

Everything here is pure. `decide()` takes an Observation of scalars and returns
a Decision; it cannot read a clock, a socket, or a database, which is what makes
the live agent and the replay engine provably the same policy.

A note on notation, because it has already caused one bug elsewhere: `kappa` in
this file is the Avellaneda-Stoikov order-arrival parameter — fill intensity
decays as exp(-kappa * delta). PolyLambda, which this is re-derived from, calls
that parameter `k` and uses `kappa` for an unrelated jump-premium weight. See
matrix item D-3.

References: frozen spec sections 3.1 through 3.4.
"""

from __future__ import annotations

import math
from functools import lru_cache

from misquote.core.errors import AssumptionViolated
from misquote.core.position import rebalances_today, reentries_today
from misquote.core.tickmath import MAX_TICK, MIN_TICK, nearest_usable_tick
from misquote.core.types import Action, Decision, Observation, Params, PoolMeta, Tick

# One tick is a factor of 1.0001 in price, so this converts log-price to ticks.
LN_TICK_BASE = math.log(1.0001)

# Sentinel for "the CEX feed was down, so no gap was measured". A gap is an
# absolute magnitude and is never negative, so this cannot collide with a real
# reading. Deliberately not NaN — see `toxicity`.
GAP_NOT_MEASURED = -1.0

# Where staying in range stops being the binding constraint on a width. A19.
#
# Read through `sigmas_for_inrange`, so it is the same derivation as the floor
# with the target moved to the other end: 1.4395 sigmas holds 70% of the horizon,
# 3.03 sigmas holds 99%, and the ticks between them are the only ones where
# widening buys measurable in-range time. Past it a band is paying fee density
# for time it already has.
IN_RANGE_SATURATION = 0.99


# --- equations (1) and (2) -------------------------------------------------


def reservation_logprice(
    y: float, q: float, gamma: float, sigma: float, t_remaining: float
) -> float:
    """Equation (1): the inventory-skewed centre of the range, in log-price.

        r = y - q * gamma * sigma^2 * (T - t)

    Holding excess token0 (q > 0) pushes the range *down*, which makes the
    position a keener seller of the excess — the Avellaneda-Stoikov skew,
    unchanged. The skew grows with volatility and with how long the position
    still has to run, because both increase what the imbalance can cost.
    """
    return y - q * gamma * sigma * sigma * t_remaining


def half_width_logprice(gamma: float, sigma: float, t_remaining: float, kappa: float) -> float:
    """Equation (2): the optimal half-width, in log-price.

        delta* = 1/2 * [ gamma*sigma^2*(T-t) + (2/gamma)*ln(1 + gamma/kappa) ]

    First term is inventory-risk compensation: more volatility, wider range.
    Second is the fill-rate trade-off: when fee flow is rich near the mid (large
    kappa) the range tightens to sit in it.

    The one-half is already applied. Halving the return of this function again
    is the mistake matrix item D-3 exists to prevent, because the function it
    was ported from returns a *total* spread.
    """
    if gamma <= 0:
        raise ValueError("gamma must be positive")
    if kappa <= 0:
        raise ValueError("kappa must be positive")
    inventory_term = gamma * sigma * sigma * t_remaining
    fill_term = (2.0 / gamma) * math.log1p(gamma / kappa)
    return 0.5 * (inventory_term + fill_term)


def _round_to_spacing(value: float, tick_spacing: int) -> int:
    """The spec's `round_to_spacing`: nearest multiple of the spacing, once.

    Rounding to an integer tick first and *then* to the spacing grid is not the
    same function — the intermediate rounding can push a value across the
    midpoint between two grid points. Measured over 200,000 draws, the
    double-rounded form disagreed with this one on 4.95% of inputs, each by a
    full tick spacing. Sections 3.1 and 3.2 both name the same operation, so it
    is defined once here and used by both.
    """
    return int(round(value / tick_spacing)) * tick_spacing


def center_tick(r: float, tick_spacing: int) -> Tick:
    """Log-price -> the usable tick nearest it (spec section 3.1)."""
    raw = r / LN_TICK_BASE
    snapped = _round_to_spacing(max(float(MIN_TICK), min(float(MAX_TICK), raw)), tick_spacing)
    return nearest_usable_tick(max(MIN_TICK, min(MAX_TICK, snapped)), tick_spacing)


@lru_cache(maxsize=32)
def _band_survival(a: float) -> float:
    """P(a driftless walk never leaves +/- `a` standard deviations over the horizon).

    The classical two-sided first-passage series:

        P = (4/pi) * sum_k (-1)^k/(2k+1) * exp(-(2k+1)^2 * pi^2 / (8 a^2))

    Alternating and dominated by its first term; sixty terms is far past machine
    precision for any `a` this is asked about. Cached because it is inverted once
    per distinct in-range floor and then read on every sample of a 500,000-sample
    replay.
    """
    if a <= 0.0:
        return 0.0
    total = 0.0
    for k in range(60):
        m = 2 * k + 1
        total += ((-1) ** k / m) * math.exp(-(m * m) * math.pi * math.pi / (8.0 * a * a))
    return (4.0 / math.pi) * total


@lru_cache(maxsize=32)
def sigmas_for_inrange(inrange_floor: float) -> float:
    """How many horizon-sigmas wide a range must be to meet the in-range floor.

    **This is a derivation, not a parameter.** It inverts `_band_survival` at
    G-3's published floor, so the only number entering it is one the assumption
    sheet already carries. At the spec's 70% it returns 1.4395.

    Why this replaced a constant: `w_min = w_min_mult * tick_spacing` is 40 ticks
    on the flagship pool, which is **0.795** sigmas of a 24-hour move — a band a
    random walk leaves 81% of the time. The measured in-range fraction was 6.1%.
    A floor expressed in tick spacings is a statement about dust, and dust is a
    real constraint, but it says nothing about whether the range can stay where
    it is long enough to earn. Those are different questions and the code asked
    only the first (P-17).

    Bisection rather than a closed form because the series has no elementary
    inverse, and monotonicity in `a` makes bisection exact to machine precision
    in a fixed 200 steps.
    """
    if not 0.0 < inrange_floor < 1.0:
        raise ValueError(f"in-range floor must lie strictly in (0, 1), got {inrange_floor}")
    lo, hi = 1e-6, 20.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _band_survival(mid) < inrange_floor:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def volatility_floor_ticks(
    sigma: float,
    t_remaining: float,
    inrange_floor: float,
    max_price_band: float = 0.0,
) -> int:
    """The narrowest range that can hold the in-range floor over the horizon.

    Half-width in ticks, unrounded and unsnapped — `half_width_ticks` owns the
    grid. Returns 0 when sigma is not yet measured, which leaves the dust floor
    in charge rather than letting an unready estimator widen the range to nothing
    or to everything.

    Capped at `max_price_band` when one is given, for the reason recorded on
    `Params.w_max_price_band`: `sigma * sqrt(T)` is a random-walk excursion, and
    mean-reverting flow produces a large sigma without going anywhere. The cap
    binds on oscillating tapes and not on the flagship pool, where the floor is
    72 ticks against a ceiling of 2,231.
    """
    if sigma <= 0.0 or t_remaining <= 0.0:
        return 0
    logprice = sigmas_for_inrange(inrange_floor) * sigma * math.sqrt(t_remaining)
    if max_price_band > 0.0:
        logprice = min(logprice, math.log1p(max_price_band))
    return int(logprice / LN_TICK_BASE)


def half_width_ticks(
    delta_star: float,
    tick_spacing: int,
    w_min_mult: int,
    *,
    sigma: float = 0.0,
    t_remaining: float = 0.0,
    inrange_floor: float = 0.0,
    max_price_band: float = 0.0,
) -> int:
    """Half-width in log-price -> half-width in ticks, floored against dust.

    Spec section 3.2: `w_t = max(w_min, round_to_spacing(δ*/ln(1.0001)))`. It
    rounds, and it used to floor here — which made every range systematically
    narrower than specified, by an average of 4.4 ticks and up to a full
    spacing. Narrower means more time out of range, so the bias was toward more
    rebalancing and more gas, silently.

    `w_min = w_min_mult * tick_spacing`. That floor is not a rounding detail: a
    range narrower than it earns fees on a position too small to matter while
    still paying a full rebalance in gas every time price drifts.

    **There are two floors, and they answer different questions.** The dust floor
    above asks whether a position is big enough to be worth holding. The
    volatility floor asks whether the range can stay where it is long enough to
    earn anything, and it is the one that was missing: equation (2) returns 2.86
    to 4.75 ticks across the entire published gamma range against a dust floor of
    40, so the dust floor bound by a factor of 8 to 14 and the model contributed
    nothing to the width at all (P-17). A9 already records why equation (2) runs
    narrow — it prices no adverse selection whatsoever — so leaving it under a
    floor chosen for a different purpose hid a known defect behind an unrelated
    constant.

    The volatility floor is off by default so that a caller with no sigma to hand
    gets exactly the old behaviour. Every live caller passes one.
    """
    w_min = w_min_mult * tick_spacing
    chosen = _round_to_spacing(delta_star / LN_TICK_BASE, tick_spacing)
    if inrange_floor <= 0.0:
        return max(w_min, chosen)

    # Rounded *up* to the grid, not to nearest. A floor that rounds down is not a
    # floor, and at spacing 50 nearest-rounding would shave a whole spacing off
    # the width the in-range target asked for.
    needed = volatility_floor_ticks(sigma, t_remaining, inrange_floor, max_price_band)
    w_min = max(w_min, -((-needed) // tick_spacing) * tick_spacing)

    # And a ceiling, from the same derivation read at the other end. A19.
    #
    # Equation (2)'s width is dominated by kappa, and kappa is not stable to
    # within an order of magnitude: fitted 3,600.91 per log-price over the
    # 30-day tape and about 7 over a 40,000-swap slice of the same pool — a 500x
    # swing that moves the half-width from 2.9 ticks to 1,350. A8 already records
    # that the estimator fits a functional form the data does not have; this is
    # that defect setting the range rather than merely being disclosed.
    #
    # The bound is not a cap on kappa but a statement about what width can still
    # buy anything. `IN_RANGE_SATURATION` of the horizon's move is where staying
    # in range stops being the binding constraint; past it a wider band trades
    # fee density for in-range time it already has. On the real tape the agent
    # opened a +/-14.45% range — wider than the pool's entire 11.6% move for the
    # month — sat in range 100% of the time, never moved again, and earned 2.4x
    # *less* in fees than the passive baseline it had become.
    ceiling = volatility_floor_ticks(sigma, t_remaining, IN_RANGE_SATURATION, max_price_band)
    ceiling = (ceiling // tick_spacing) * tick_spacing
    if ceiling >= w_min:
        chosen = min(chosen, ceiling)
    return max(w_min, chosen)


def inventory_imbalance(value0_quote: float, value1_quote: float) -> float:
    """Spec section 2's `q`, normalised so it actually spans [-1, 1].

        q = (v0 - v1) / (v0 + v1)

    The spec states two incompatible things: this quantity is "(value of token0
    held − target 50/50 value) / total position value", *and* it lies in
    [−1, 1]. Read literally the formula gives [−0.5, +0.5] — a position entirely
    in token0 yields 0.5, not 1. Since `q` multiplies straight into equation (1),
    the two readings skew the range centre by a factor of two.

    The stated range is the more testable claim and the one adopted, so a
    position entirely in token0 gives exactly +1 and one entirely in token1
    gives −1. Recorded in the requirements matrix.
    """
    total = value0_quote + value1_quote
    if total <= 0.0:
        return 0.0
    return (value0_quote - value1_quote) / total


def _distance_to_edge(centre: Tick, tick_spacing: int) -> int:
    """How wide a symmetric range around `centre` can be and stay usable.

    Bounded by the nearest representable tick on either side, rounded down to the
    spacing grid so both bounds remain mintable.
    """
    room = min(centre - MIN_TICK, MAX_TICK - centre)
    return (room // tick_spacing) * tick_spacing


def target_range(
    obs: Observation, params: Params, meta: PoolMeta
) -> tuple[Tick, Tick, Tick, int, float, float]:
    """The range the policy wants right now.

    Returns (lower, upper, centre, half_width, r, delta_star) so callers can
    report the intermediate values without recomputing them — every one of them
    ends up in the journal.
    """
    r = reservation_logprice(obs.y, obs.q, params.gamma, obs.sigma, obs.T_t)
    # `kappa_scale` is 1.0 everywhere except under A5's perturbation sweep, where
    # it is the half of "(gamma, kappa) +/- 25%" that had no way to be applied.
    delta_star = half_width_logprice(
        params.gamma, obs.sigma, obs.T_t, obs.kappa * params.kappa_scale
    )

    centre = center_tick(r, meta.tick_spacing)
    width = half_width_ticks(
        delta_star,
        meta.tick_spacing,
        params.w_min_mult,
        sigma=obs.sigma,
        t_remaining=obs.T_t,
        inrange_floor=params.inrange_floor,
        max_price_band=params.w_max_price_band,
    )

    # Shrink the width until both bounds fit, rather than clamping them.
    #
    # MIN_TICK and MAX_TICK are +/-887272, which is not a multiple of any Pancake
    # tick spacing (887272 % 10 == 2). Clamping a bound to them therefore
    # produces a tick the pool rejects, so the mint reverts — and it also
    # destroys the symmetry that R1 relies on, since `(lower + upper) // 2` would
    # no longer be the centre the policy computed, and drift would be measured
    # against a range that does not exist.
    w_min = params.w_min_mult * meta.tick_spacing
    room = _distance_to_edge(centre, meta.tick_spacing)
    if room < w_min:
        # No symmetric range of the minimum legal width fits. This is not a
        # degenerate rounding case — it means the price is pinned against the
        # edge of representable tick space, which is what a pool initialized at
        # MAX_TICK and never seeded looks like. Chapel's WBNB/USDT 0.05% pool is
        # in exactly this state. Quoting anything here would be inventing a
        # position that cannot be minted, so refuse.
        raise AssumptionViolated(
            f"price at tick {centre} leaves only {room} ticks to the edge of tick space, "
            f"less than w_min={w_min}: no mintable range exists"
        )

    width = max(w_min, min(width, room))
    return centre - width, centre + width, centre, width, r, delta_star


# --- section 3.4: the toxicity pull ----------------------------------------


def gap_condition_holds(obs: Observation, params: Params, meta: PoolMeta) -> bool:
    """Does the CEX-gap arm's *condition* hold on this sample?

    Separate from `toxicity`'s verdict, which additionally requires the condition
    to have persisted for `m` samples. A driver maintaining that streak needs the
    condition, not the verdict — reading the verdict could never let the streak
    reach `m`.

    It lives here, as a function of the observation, because the alternative was
    the engine parsing values back out of `Decision.reasons` by name. That worked
    for Warden and broke the moment a second agent produced a decision without
    those keys, which is precisely the coupling a marketplace claiming to run
    any agent's policy cannot afford.
    """
    if obs.cex_gap is None:
        return obs.lvr_rate > obs.fee_rate
    return abs(obs.cex_gap) * 10_000.0 > meta.fee_bps + params.arb_cost_bps


def reentry_affordable(obs: Observation, params: Params) -> tuple[bool, int]:
    """Whether the position can afford to come back, and what it has spent today.

    One function, consulted by every agent that can leave the market, because
    Warden and Sentinel each keeping their own copy of a rule is exactly how V-12
    happened — the policy tested `imb > z_pull` while the engine tested
    `|imb| > z_pull`, and nothing could notice.

    It happened again here and immediately. The re-entry budget went into
    Warden's `decide` and not into `decide_sentinel`, so the fixed run capped
    Warden at 249 round trips and left Sentinel at 1,761 — the same defect, on
    the same tape, in the same run, because the rule existed twice. The rule
    written down in P-12 that morning was *move it into the shared layer rather
    than maintain it twice*, and this is what ignoring it costs.

    Returns the verdict and the count, because every caller wants to publish the
    count in its reasons and recomputing it separately is how the two would
    drift apart again.

    It reads the *re-entry* budget, not the recentre one. Those were the same
    counter until P-20 priced the difference: every return from a defensive pull
    spent a move the agent then could not make, so on the 30-day tape re-entry
    was refused on 90.2% of HOLD decisions and the position was out of the market
    94% of the time. Coming back is not churn.
    """
    spent = reentries_today(obs.position, obs.t)
    return spent < params.max_reentries_per_day, spent


def width_inputs_trustworthy(obs: Observation, params: Params) -> tuple[bool, dict[str, float]]:
    """Are sigma and kappa measured well enough to size a position by? A20.

    **The one decision nothing re-examines.** A range is opened once and its width
    is never revisited: R1 asks whether the *centre* has drifted, R2 whether a move
    pays, R3 about cooldown, R4 about toxicity. None of them asks whether the width
    is still right — and because R1's threshold is `theta * w`, an over-wide range
    raises its own bar against the recentre that would correct it. So the opening
    sizing is effectively permanent, and it was being made on the first sample of
    the tape.

    On the first sample `sigma` is not an estimate. `estimators.sigma.shrink`
    returns the prior outright when there are no returns yet, and A7 records that
    prior as "roughly 190% annualised, which is hot for BNB (typically 50-70%)".
    This pool's realized sigma is 0.00178 per sqrt-hour — about **17%**. The prior
    is 11x too hot, and equation (2) is evaluated against it.

    Measured consequence on the 30-day tape: Warden opened at **+/-14.45% on a pool
    that moved 11.6% for the entire month**, sat in range 100% of the time, never
    moved again, and earned **0.00727 in fees against a fixed 200-tick ladder's
    0.04836** — 6.7x less, while being indistinguishable from the passive baseline
    it is supposed to beat.

    The condition is on sigma only: `sigma_confidence >= min_sigma_confidence`,
    the shrinkage weight, which asks how much of sigma is measurement. Deliberately
    not `sigma.ready`, which is a bar count — at the readiness threshold the weight
    is 0.6, so a ready sigma is still 40% prior.

    **Kappa is deliberately not in this gate, and the first version of it was
    backwards.** The intuition was that a fallback kappa makes the width a
    constant, so a fallback should block the open. The arithmetic says the
    opposite. The fallback *is* the published fit, 3,600.91 per log-price, and at
    that value equation (2) returns about 3 ticks — far below the A18 floor, so the
    floor sets the width and the result is the well-behaved case. The width that
    opened at +/-14.45% came from kappa ~= 7, which is `is_fallback=False`: a
    genuine fit on a slice, clearing r-squared 0.5, and wrong by 500x. Blocking on
    the flag would have refused the safe case and admitted the dangerous one.

    A19's ceiling already handles kappa, and handles it in the direction that
    matters: it bounds what equation (2) may widen to, whether the number came from
    a fit or a fallback. With sigma correct the band is 130 to 240 ticks and
    kappa's 500x swing moves the width 1.8x inside it.

    A test found this. `fit()` refits at most daily, so on a tape shorter than 24
    hours the flag is stuck at its initial fallback and the agent would never have
    opened a position at all.
    """
    sigma_ok = obs.sigma_confidence >= params.min_sigma_confidence
    return sigma_ok, {
        "sigma_confidence": obs.sigma_confidence,
        "sigma_confident": float(sigma_ok),
    }


def pull_pays_for_itself(obs: Observation, params: Params) -> tuple[bool, dict[str, float]]:
    """Does withdrawing save more than the round trip costs? Assumption A17.

    **R2 for the exit.** Section 3.3 will not let the agent recentre unless the
    expected fee gain clears gas, slippage and the MEV haircut. Nothing asked the
    same question of a withdrawal, so the toxicity arm could cycle the position
    at whatever rate the daily budget allowed — and did: on the 30-day tape, 653
    pull/re-mint round trips costing 9.6% of capital against 4.8% of fees earned.
    The round trips, not the strategy, are the loss.

    The test is the one R2 makes. Withdrawing avoids the trailing bleed — realized
    adverse selection net of realized fees — for as long as the position stays
    out, which is at least the `m_clear` samples re-entry requires. Leaving costs
    a full exit now and a full entry later, and the MEV haircut falls on the whole
    position because a pull unwinds all of it, not on the rebalanced notional A4
    charges for a recentre.

    **This narrows a rule the code deliberately left wide, so the argument against
    it belongs here.** `decide` says the budget "gates coming back, never leaving",
    because an agent forbidden to exit is held inside the flow the rule exists to
    escape. That reasoning is right and this does not contradict it: a budget
    refuses on an allowance already spent, which says nothing about the danger,
    while this refuses only when the pool is not measurably costing more than it
    pays. If flow is genuinely toxic the bleed is large, the gate opens on the
    first sample, and nothing is held anywhere. What it blocks is the speculative
    pull — the one where the signal fired and the pool was not actually hurting.

    *Direction of the error:* toward staying in the market. That is a real
    exposure change, and it is the one A10 makes conservative rather than
    dangerous — `lvr_rate` is an upper bound on adverse selection, so the bleed
    this compares against is overstated and the gate opens **sooner** than a
    truer measure would open it.
    """
    # Two estimates of what leaving saves, because the two arms of section 3.4
    # know different things and only one of them carries a magnitude.
    #
    # The CEX-gap arm *leads*: it says an arbitrageur is coming and prices the
    # trade, because a gap of g against a position worth V is arbitraged for
    # about V*g. Judging that arm by trailing realized LVR would refuse the pull
    # precisely when the signal is doing its job — the damage has not happened
    # yet, which is the entire point of a leading indicator.
    #
    # The fallback and imbalance arms *lag* and carry no magnitude at all. All
    # they can be judged against is the bleed already measured.
    hours_out = params.m_clear * params.sample_interval_s / 3600.0
    bleed_per_hour = obs.lvr_rate - obs.fee_rate
    from_bleed = max(0.0, bleed_per_hour) * hours_out
    from_gap = abs(obs.cex_gap) * obs.position_value_quote if obs.cex_gap is not None else 0.0
    saved = max(from_bleed, from_gap)

    # A pull unwinds the whole position and a re-entry rebuilds it, so the
    # haircut is on `position_value_quote` rather than A4's rebalanced notional,
    # and the leg is paid twice.
    leg = (
        obs.gas_cost_quote
        + obs.slippage_quote
        + obs.position_value_quote * params.mev_haircut_bps / 10_000.0
    )
    round_trip = 2.0 * leg

    return saved > round_trip, {
        "pull_bleed_per_hour": bleed_per_hour,
        "pull_saving_from_bleed": from_bleed,
        "pull_saving_from_gap": from_gap,
        "pull_hours_out": hours_out,
        "pull_saving": saved,
        "pull_round_trip_cost": round_trip,
    }


def imbalance_toxic(obs: Observation, params: Params) -> bool:  # noqa: ARG001
    """Section 3.4's second arm: is flow running one way hard enough to pull?

    **The threshold is `obs.swap_imbalance_threshold`, not `params.z_pull`.**
    `z` is a permutation-null statistic bounded by sqrt(M), not a normal score,
    so the spec's constant 2.5 is a number calibrated for a distribution this
    quantity does not have — on the flagship pool it fires on 41.94% of samples
    and on 42.8% of a pool eighty-four times shallower (P-19, P-23). The engine
    now measures the statistic's own trailing distribution and hands the policy
    the quantile of it; `z_pull` remains the fallback until enough has been
    measured. See `estimators/imbalance.py` and assumption A16.

    `params` stays in the signature because `Policy` callers pass it positionally
    and the symmetry with every other gate in this module is worth more than
    dropping an unused argument.

    **Deviation from the frozen spec, recorded as matrix item P-6.** Section 3.4
    writes the condition one-sided, `imb_t > z_pull`, which fires only when the
    pool is being bought. Adverse selection does not care which token the
    informed trader is taking: an arbitrageur draining token0 picks the position
    off exactly as thoroughly as one draining token1, and the sign of `imb_t`
    only records the direction of the drain. Read literally, the rule defends one
    side of the book and leaves the other open.

    So this is `|imb_t| > z_pull`, and the deviation is written down rather than
    resolved in silence.

    Making it a function also settles a disagreement the two callers had. The
    policy tested `imb_t > z_pull` and the engine's streak logic tested
    `|imb_t| > z_pull`, so on one-way selling the policy would call the pool
    clean while the engine reset the clear streak that governs re-entry — an
    agent held out of the market by a condition its own policy said was not
    happening. Neither was wrong about the value; there were two rules. Now there
    is one, and it is the one both read.

    Invisible until now, because nothing ever produced a non-zero z-score.
    """
    return abs(obs.swap_imbalance_z) > obs.swap_imbalance_threshold


def toxicity(obs: Observation, params: Params, meta: PoolMeta) -> tuple[bool, dict[str, float]]:
    """Is the next flow likely to be informed?

    When a centralised venue leads the pool by more than the round-trip cost of
    arbitraging the difference, the next trade through the pool is an
    arbitrageur — the literal informed trader — and the expected LVR on it
    exceeds the expected fee. The right response is the same one a market maker
    makes: pull the quote. Here that means withdrawing the range.

    Two independent triggers, either sufficient:

      - the CEX-DEX gap exceeds `fee_tier + arb_cost` for `m` consecutive
        samples;
      - the signed swap-volume imbalance z-score exceeds `z_pull`, which catches
        one-sided flow without needing the off-chain feed at all.

    If the CEX feed is down, the spec's fallback applies instead: pull when
    realized LVR per hour has been running above realized fees per hour. That is
    strictly worse — it reacts after the damage rather than before it — so which
    rule fired is recorded and shown.
    """
    threshold_bps = meta.fee_bps + params.arb_cost_bps
    terms: dict[str, float] = {
        "toxicity_threshold_bps": threshold_bps,
        "swap_imbalance_z": obs.swap_imbalance_z,
        # Recorded alongside the z-score because the threshold now moves. A
        # journal that shows the reading without the bar it was judged against
        # cannot answer "why did this pull fire" a week later.
        "swap_imbalance_threshold": obs.swap_imbalance_threshold,
        "toxic_streak": float(obs.toxic_streak),
        "clear_streak": float(obs.clear_streak),
    }

    is_imbalanced = imbalance_toxic(obs, params)
    terms["imbalance_toxic"] = float(is_imbalanced)
    # The threshold the gap is being compared against, recorded so the journal
    # says what the rule actually applied rather than only what it concluded —
    # and so a driver can tell whether the *condition* held on this sample,
    # which is what advances the persistence streak.
    terms["gap_threshold_bps"] = threshold_bps

    if obs.cex_gap is None:
        # Fallback: on-chain only. Bleeding more to arbitrage than we earn in
        # fees is the observable consequence of toxic flow, after the fact.
        gap_toxic = obs.lvr_rate > obs.fee_rate and obs.toxic_streak + 1 >= params.m_toxic
        # NOT NaN. A gap is a magnitude and can never be negative, so -1 is an
        # unambiguous "not measured" — and unlike NaN it compares equal to
        # itself. `Decision` is frozen and hashable precisely so test T1 can
        # compare decision sequences bitwise; a NaN anywhere in `reasons` makes
        # every decision unequal to itself, so T1 could never pass on any
        # decision taken while the feed was down. `using_onchain_fallback`
        # carries the real signal.
        terms["cex_gap_bps"] = GAP_NOT_MEASURED
        terms["using_onchain_fallback"] = 1.0
        terms["lvr_rate"] = obs.lvr_rate
        terms["fee_rate"] = obs.fee_rate
    else:
        gap_bps = abs(obs.cex_gap) * 10_000.0
        gap_toxic = gap_bps > threshold_bps and obs.toxic_streak + 1 >= params.m_toxic
        terms["cex_gap_bps"] = gap_bps
        terms["using_onchain_fallback"] = 0.0

    terms["gap_toxic"] = float(gap_toxic)
    is_toxic = bool(gap_toxic or is_imbalanced)
    terms["toxic"] = float(is_toxic)
    return is_toxic, terms


# --- section 3.3: the recentre gates ---------------------------------------


def recenter_gates(
    obs: Observation,
    params: Params,
    meta: PoolMeta,
    target: tuple[Tick, Tick],
    width: int,
    toxic: bool,
) -> tuple[bool, dict[str, float]]:
    """R1 through R4. All four are always evaluated; none short-circuits.

    That costs nothing and buys the ability to say *why* the position sat still,
    which is most of what makes a tearsheet worth reading. The spec is explicit
    that this is the practical threshold form of an optimal-stopping problem,
    with (theta, tau_cool) approximating the free boundary — not the exact
    solution, and not presented as one.
    """
    lower, upper = target
    target_centre = (lower + upper) // 2
    current_centre = obs.position.center

    # R1 — has the range drifted far enough to be worth moving?
    drift = abs(target_centre - current_centre) if current_centre is not None else 0
    r1_threshold = params.theta * width
    r1 = drift >= r1_threshold

    # R2 — does the expected fee GAIN clear the cost of capturing it?
    #
    # Gain, not absolute fees. Spec section 3.3 asks for "E[fee gain over
    # remaining window]", which is what the target range would earn *minus what
    # the current one would earn if left alone*. Testing absolute fees instead
    # is a strictly weaker gate: it authorises a rebalance whenever the target
    # earns more than the cost, even when the position is already earning nearly
    # as much where it stands — spending gas, slippage and a 10 bps MEV haircut
    # to buy almost nothing.
    #
    # Trailing rates only, both of them. A forward estimate here would be
    # look-ahead wearing a hat.
    fees_at_target = obs.fee_rate_per_liquidity_target * obs.target_liquidity * obs.T_t
    fees_if_we_stay = obs.fee_rate_per_liquidity_current * obs.position.liquidity * obs.T_t
    expected_gain = fees_at_target - fees_if_we_stay

    # Assumption A4 charges the haircut on the *rebalanced notional* — what the
    # recentre actually swaps to restore target composition — not on the whole
    # position, which would overstate it several-fold.
    mev = obs.rebalance_notional_quote * params.mev_haircut_bps / 10_000.0
    cost = obs.gas_cost_quote + obs.slippage_quote + mev
    r2 = expected_gain - cost > 0

    # R3 — anti-churn: the cooldown and the daily budget.
    since_last = obs.t - obs.position.last_rebalance_ts
    cooled = since_last >= params.tau_cool_s
    # Today's count, not the lifetime one. The stored counter never reset, so
    # this gate used to freeze the agent permanently after eight moves — see
    # `core.position.rebalances_today`.
    spent_today = rebalances_today(obs.position, obs.t)
    under_budget = spent_today < params.max_rebalances_per_day
    r3 = cooled and under_budget

    # R4 — never rebalance into flow we already believe is informed.
    r4 = not toxic

    terms = {
        "R1_drift_ticks": float(drift),
        "R1_threshold_ticks": r1_threshold,
        "R1": float(r1),
        "R2_fees_at_target": fees_at_target,
        "R2_fees_if_we_stay": fees_if_we_stay,
        "R2_expected_gain": expected_gain,
        "R2_gas": obs.gas_cost_quote,
        "R2_slippage": obs.slippage_quote,
        "R2_mev_haircut": mev,
        "R2_net": expected_gain - cost,
        "R2": float(r2),
        "R3_seconds_since_rebalance": float(since_last),
        "R3_cooldown_s": float(params.tau_cool_s),
        "R3_rebalances_today": float(spent_today),
        "R3": float(r3),
        "R4": float(r4),
    }
    return bool(r1 and r2 and r3 and r4), terms


# --- the policy ------------------------------------------------------------


def decide(obs: Observation, params: Params, meta: PoolMeta) -> Decision:
    """The whole policy, as one pure function.

    Precedence is deliberate: toxicity outranks everything. A position that is
    losing to arbitrage faster than it earns fees should leave, and it should
    not be talked out of leaving by a cooldown or a gas calculation.
    """
    toxic, tox_terms = toxicity(obs, params, meta)
    lower, upper, centre, width, r, delta_star = target_range(obs, params, meta)

    if not obs.position.in_market:
        # Out of market: the only question is whether it is safe to come back.
        #
        # **And whether we can afford to.** Coming back costs gas, slippage and
        # the MEV haircut every time, and section 3.4 says nothing about how
        # often it may happen. On the 30-day chain tape it happened 2,585 times —
        # a pull-and-return every seventeen minutes for a month, no recentres at
        # all — and spent 5.2x the deployed capital on costs to earn 0.23 of
        # token1. See requirements-matrix P-12.
        #
        # The budget is deliberately asymmetric: it gates coming **back**, never
        # leaving. An agent that cannot afford to re-enter sits flat, which is
        # safe and free. An agent forbidden to *exit* because it had run out of
        # budget would be held inside exactly the flow the rule exists to escape,
        # and that is the one outcome worse than churning.
        ready = obs.clear_streak >= params.m_clear
        affordable, spent = reentry_affordable(obs, params)
        # A20. The width is set here and never re-examined, so this is the only
        # moment at which sigma and kappa being guesses can be caught.
        trustworthy, width_terms = width_inputs_trustworthy(obs, params)
        action = Action.HOLD
        target_l: Tick | None = None
        target_u: Tick | None = None
        if not toxic and ready and affordable and trustworthy:
            action = Action.MINT if obs.position.token_id is None else Action.REENTER
            target_l, target_u = lower, upper

        reasons = (
            ("in_market", 0.0),
            ("reentry_ready", float(ready)),
            ("reentry_affordable", float(affordable)),
            ("reentries_today", float(spent)),
            ("m_clear", float(params.m_clear)),
            ("width_inputs_trustworthy", float(trustworthy)),
            *sorted(width_terms.items()),
            *sorted(tox_terms.items()),
        )
        return Decision(
            action=action,
            target_lower=target_l,
            target_upper=target_u,
            center_tick=centre,
            half_width_ticks=width,
            r=r,
            delta_star=delta_star,
            reasons=reasons,
        )

    if toxic:
        # Toxicity still outranks every other consideration — but "leave" is an
        # action with a price, and A17 makes it clear the price. A pull that
        # cannot pay for itself is not caution, it is a round trip billed to the
        # position: 653 of them on the 30-day tape, costing twice the fees the
        # agent earned. The gate opens immediately when the pool is genuinely
        # bleeding, which is the case the precedence above exists to serve.
        worth_it, pull_terms = pull_pays_for_itself(obs, params)
        if worth_it:
            return Decision(
                action=Action.PULL,
                target_lower=None,
                target_upper=None,
                center_tick=centre,
                half_width_ticks=width,
                r=r,
                delta_star=delta_star,
                reasons=(
                    ("in_market", 1.0),
                    ("pull_pays", 1.0),
                    *sorted(pull_terms.items()),
                    *sorted(tox_terms.items()),
                ),
            )
        # Toxic, but not worth paying to escape. Hold rather than recentre: the
        # gates below would price a move against flow already believed informed,
        # and R4 refuses that anyway.
        return Decision(
            action=Action.HOLD,
            target_lower=None,
            target_upper=None,
            center_tick=centre,
            half_width_ticks=width,
            r=r,
            delta_star=delta_star,
            reasons=(
                ("in_market", 1.0),
                ("pull_pays", 0.0),
                *sorted(pull_terms.items()),
                *sorted(tox_terms.items()),
            ),
        )

    should_move, gate_terms = recenter_gates(obs, params, meta, (lower, upper), width, toxic)

    return Decision(
        action=Action.RECENTER if should_move else Action.HOLD,
        target_lower=lower if should_move else None,
        target_upper=upper if should_move else None,
        center_tick=centre,
        half_width_ticks=width,
        r=r,
        delta_star=delta_star,
        reasons=(("in_market", 1.0), *sorted(gate_terms.items()), *sorted(tox_terms.items())),
    )


def passive_policy(obs: Observation, params: Params, meta: PoolMeta) -> Decision:
    """The benchmark: mint once at the initial width, then never move.

    This is the primary comparator for NetFeeAPR (spec section 4.1) and it is
    also test T4's instrument — running it through the same engine and comparing
    against a direct chain-state computation is what proves the engine is
    self-consistent rather than merely plausible.
    """
    lower, upper, centre, width, r, delta_star = target_range(obs, params, meta)
    # A20 applies to the benchmark too, and it has to: `passive_policy` calls the
    # same `target_range`, so it was opening at the same prior-sized width. On the
    # 30-day tape that cut the baseline's fees from 0.01753 to 0.00697. A
    # comparison is only worth making if both sides are sized by the same rule,
    # and "the baseline is not a different program" is the claim this benchmark
    # exists to support.
    trustworthy, width_terms = width_inputs_trustworthy(obs, params)
    mint = not obs.position.in_market and obs.position.token_id is None and trustworthy
    return Decision(
        action=Action.MINT if mint else Action.HOLD,
        target_lower=lower if mint else None,
        target_upper=upper if mint else None,
        center_tick=centre,
        half_width_ticks=width,
        r=r,
        delta_star=delta_star,
        reasons=(("passive", 1.0), *sorted(width_terms.items())),
    )
