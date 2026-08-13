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

from misquote.core.errors import AssumptionViolated
from misquote.core.tickmath import MAX_TICK, MIN_TICK, nearest_usable_tick
from misquote.core.types import Action, Decision, Observation, Params, PoolMeta, Tick

# One tick is a factor of 1.0001 in price, so this converts log-price to ticks.
LN_TICK_BASE = math.log(1.0001)

# Sentinel for "the CEX feed was down, so no gap was measured". A gap is an
# absolute magnitude and is never negative, so this cannot collide with a real
# reading. Deliberately not NaN — see `toxicity`.
GAP_NOT_MEASURED = -1.0


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


def half_width_ticks(delta_star: float, tick_spacing: int, w_min_mult: int) -> int:
    """Half-width in log-price -> half-width in ticks, floored against dust.

    Spec section 3.2: `w_t = max(w_min, round_to_spacing(δ*/ln(1.0001)))`. It
    rounds, and it used to floor here — which made every range systematically
    narrower than specified, by an average of 4.4 ticks and up to a full
    spacing. Narrower means more time out of range, so the bias was toward more
    rebalancing and more gas, silently.

    `w_min = w_min_mult * tick_spacing`. That floor is not a rounding detail: a
    range narrower than it earns fees on a position too small to matter while
    still paying a full rebalance in gas every time price drifts.
    """
    w_min = w_min_mult * tick_spacing
    return max(w_min, _round_to_spacing(delta_star / LN_TICK_BASE, tick_spacing))


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
    delta_star = half_width_logprice(params.gamma, obs.sigma, obs.T_t, obs.kappa)

    centre = center_tick(r, meta.tick_spacing)
    width = half_width_ticks(delta_star, meta.tick_spacing, params.w_min_mult)

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
        "toxic_streak": float(obs.toxic_streak),
        "clear_streak": float(obs.clear_streak),
    }

    imbalance_toxic = obs.swap_imbalance_z > params.z_pull
    terms["imbalance_toxic"] = float(imbalance_toxic)

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
    is_toxic = bool(gap_toxic or imbalance_toxic)
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
    under_budget = obs.position.rebalances_today < params.max_rebalances_per_day
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
        "R3_rebalances_today": float(obs.position.rebalances_today),
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
        ready = obs.clear_streak >= params.m_clear
        action = Action.HOLD
        target_l: Tick | None = None
        target_u: Tick | None = None
        if not toxic and ready:
            action = Action.MINT if obs.position.token_id is None else Action.REENTER
            target_l, target_u = lower, upper

        reasons = (
            ("in_market", 0.0),
            ("reentry_ready", float(ready)),
            ("m_clear", float(params.m_clear)),
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
        return Decision(
            action=Action.PULL,
            target_lower=None,
            target_upper=None,
            center_tick=centre,
            half_width_ticks=width,
            r=r,
            delta_star=delta_star,
            reasons=(("in_market", 1.0), *sorted(tox_terms.items())),
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
    mint = not obs.position.in_market and obs.position.token_id is None
    return Decision(
        action=Action.MINT if mint else Action.HOLD,
        target_lower=lower if mint else None,
        target_upper=upper if mint else None,
        center_tick=centre,
        half_width_ticks=width,
        r=r,
        delta_star=delta_star,
        reasons=(("passive", 1.0),),
    )
