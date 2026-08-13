"""The Warden's policy: Avellaneda-Stoikov, mapped term by term onto v3 ranges.

The isomorphism the whole agent rests on: a concentrated-liquidity position on
[P_l, P_u] *is* a pair of limit orders. As price rises through the range the
position continuously sells the risk asset — an ask ladder; as it falls, it
continuously buys. So the market-making solution maps across directly:

    reservation price r    ->  range centre, inventory-skewed
    optimal half-spread    ->  range half-width
    inventory penalty      ->  the recentre trigger
    adverse selection      ->  LVR, since arbitrage flow is the informed flow
    quote pull on toxicity ->  range withdrawal

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

from misquote.core.tickmath import MAX_TICK, MIN_TICK, nearest_usable_tick
from misquote.core.types import Action, Decision, Observation, Params, PoolMeta, Tick

# One tick is a factor of 1.0001 in price, so this converts log-price to ticks.
LN_TICK_BASE = math.log(1.0001)


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


def center_tick(r: float, tick_spacing: int) -> Tick:
    """Log-price -> the usable tick nearest it."""
    raw = int(round(r / LN_TICK_BASE))
    return nearest_usable_tick(max(MIN_TICK, min(MAX_TICK, raw)), tick_spacing)


def half_width_ticks(delta_star: float, tick_spacing: int, w_min_mult: int) -> int:
    """Half-width in log-price -> half-width in ticks, floored against dust.

    `w_min = w_min_mult * tick_spacing` (spec section 3.2). The floor is not a
    rounding detail: a range narrower than this earns fees on a position too
    small to matter while still paying a full rebalance in gas every time price
    drifts, so the policy must never propose one.
    """
    w_min = w_min_mult * tick_spacing
    raw = int(round(delta_star / LN_TICK_BASE))
    snapped = (raw // tick_spacing) * tick_spacing
    return max(w_min, snapped)


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

    lower = max(MIN_TICK, centre - width)
    upper = min(MAX_TICK, centre + width)
    return lower, upper, centre, width, r, delta_star


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
        terms["cex_gap_bps"] = float("nan")
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

    # R2 — does the expected fee gain clear the cost of capturing it?
    # Trailing fee rate only. A forward estimate here would be look-ahead
    # wearing a hat.
    expected_fees = obs.fee_rate_per_liquidity * obs.position.liquidity * obs.T_t
    mev = obs.position_value_quote * params.mev_haircut_bps / 10_000.0
    cost = obs.gas_cost_quote + obs.slippage_quote + mev
    r2 = expected_fees - cost > 0

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
        "R2_expected_fees": expected_fees,
        "R2_gas": obs.gas_cost_quote,
        "R2_slippage": obs.slippage_quote,
        "R2_mev_haircut": mev,
        "R2_net": expected_fees - cost,
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
