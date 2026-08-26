"""Equations (1) and (2) against numbers worked out by hand, then the gates.

The frozen spec's definition of done for this layer is that the equations are
reproduced against hand-computed fixtures. Comparing the implementation to a
rearrangement of itself would prove nothing, so the expected values below are
arithmetic done independently from the spec's printed form.
"""

from __future__ import annotations

import math

import pytest

from misquote.core.policy import (
    LN_TICK_BASE,
    center_tick,
    decide,
    half_width_logprice,
    half_width_ticks,
    passive_policy,
    recenter_gates,
    reservation_logprice,
    target_range,
    toxicity,
)
from misquote.core.types import Action, Observation, Params, PoolMeta, PositionState

META = PoolMeta(
    address="0x36696169C63e42cd08ce11f5deeBbCeBae652050",
    chain_id=56,
    token0="0x55d398326f99059fF775485246999027B3197955",
    token1="0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    dec0=18,
    dec1=18,
    fee_pips=500,
    tick_spacing=10,
    fee_protocol=3400,
)
PARAMS = Params()


def make_position(**overrides: object) -> PositionState:
    base = {
        "lower": -64400,
        "upper": -64000,
        "liquidity": 10**22,
        "token_id": 1,
        "minted_ts": 1_000_000,
        "last_rebalance_ts": 1_000_000,
        "rebalances_today": 0,
    }
    base.update(overrides)
    return PositionState(**base)  # type: ignore[arg-type]


def make_obs(**overrides: object) -> Observation:
    base = {
        "t": 1_000_000 + 3 * 3600,
        "tick": -64183,
        "y": -64183 * LN_TICK_BASE,
        "sqrt_price_x96": 3200722388915492693232066486,
        "pool_liquidity": 1_275_390_104_039_763_402_054_142,
        "q": 0.0,
        "sigma": 0.02,
        "kappa": 50.0,
        "kappa_r2": 0.81,
        "kappa_is_fallback": False,
        "sigma_confidence": 0.95,
        "T_t": 24.0,
        "gas_cost_quote": 0.5,
        "slippage_quote": 0.2,
        "fee_rate_per_liquidity_target": 1e-20,
        "fee_rate_per_liquidity_current": 0.0,
        "target_liquidity": 10**22,
        "position_value_quote": 200.0,
        "rebalance_notional_quote": 200.0,
        "cex_gap": 0.0,
        "swap_imbalance_z": 0.0,
        "swap_imbalance_threshold": 2.5,
        "lvr_rate": 0.0,
        "fee_rate": 1.0,
        "toxic_streak": 0,
        "clear_streak": 99,
        "position": make_position(),
    }
    base.update(overrides)
    return Observation(**base)  # type: ignore[arg-type]


# --- equation (1) ----------------------------------------------------------


def test_equation_1_against_a_hand_computed_value() -> None:
    """r = y - q*gamma*sigma^2*(T-t), with every term chosen to be checkable.

    y = -1, q = 0.5, gamma = 0.8, sigma = 0.1, T-t = 10
    skew = 0.5 * 0.8 * 0.01 * 10 = 0.04
    r    = -1 - 0.04 = -1.04
    """
    assert reservation_logprice(-1.0, 0.5, 0.8, 0.1, 10.0) == pytest.approx(-1.04, abs=1e-15)


def test_a_flat_position_is_not_skewed() -> None:
    assert reservation_logprice(-6.4183, 0.0, 0.8, 0.5, 24.0) == pytest.approx(-6.4183)


def test_excess_token0_pushes_the_range_down() -> None:
    """The direction is the entire economic content of equation (1).

    Holding too much token0 means the position should be a keener seller, so the
    range moves below the market. Getting this sign backwards would make the
    agent accumulate its own imbalance.
    """
    y = -6.4183
    long0 = reservation_logprice(y, +0.5, 0.8, 0.2, 24.0)
    flat = reservation_logprice(y, 0.0, 0.8, 0.2, 24.0)
    short0 = reservation_logprice(y, -0.5, 0.8, 0.2, 24.0)
    assert long0 < flat < short0


@pytest.mark.parametrize("sigma", [0.01, 0.1, 0.5])
def test_skew_grows_with_volatility_and_horizon(sigma: float) -> None:
    y, q, gamma = -6.4183, 0.4, 0.8
    short_horizon = abs(reservation_logprice(y, q, gamma, sigma, 1.0) - y)
    long_horizon = abs(reservation_logprice(y, q, gamma, sigma, 24.0) - y)
    assert long_horizon > short_horizon


# --- equation (2) ----------------------------------------------------------


def test_equation_2_against_a_hand_computed_value() -> None:
    """delta* = 1/2 * [ gamma*sigma^2*(T-t) + (2/gamma)*ln(1 + gamma/kappa) ]

    gamma = 0.8, sigma = 0.1, T-t = 10, kappa = 50

    inventory term = 0.8 * 0.1^2 * 10                = 0.08
    fill term      = (2/0.8) * ln(1 + 0.8/50)        = 2.5 * ln(1.016)
    ln(1.016)      = 0.015873349156290149...         (Mercator series, 30 digits)
    fill term      = 0.039683372890725373...
    bracket        = 0.119683372890725373...
    delta*         = 0.059841686445362686...

    The literal is carried to more digits than a float can hold on purpose. It
    was derived with `decimal` at 40 significant figures, independently of
    `math.log`, so this compares the implementation against arithmetic rather
    than against a rearrangement of itself.
    """
    expected = 0.5 * (0.08 + 2.5 * math.log(1.016))
    assert half_width_logprice(0.8, 0.1, 10.0, 50.0) == pytest.approx(expected, rel=1e-15)
    assert half_width_logprice(0.8, 0.1, 10.0, 50.0) == pytest.approx(
        0.05984168644536268655645351, abs=1e-15
    )


def test_the_half_is_applied_exactly_once() -> None:
    """Matrix item D-3, as an executable assertion.

    The function this was re-derived from returns a *total* spread, so a literal
    port would halve a value that already contains the half. The check is that
    our result equals half of the bracket, not a quarter of it.
    """
    gamma, sigma, t_rem, kappa = 0.8, 0.1, 10.0, 50.0
    bracket = gamma * sigma**2 * t_rem + (2.0 / gamma) * math.log(1 + gamma / kappa)
    got = half_width_logprice(gamma, sigma, t_rem, kappa)

    assert got == pytest.approx(bracket / 2.0, rel=1e-15)
    assert got != pytest.approx(bracket / 4.0, rel=1e-6)
    assert got != pytest.approx(bracket, rel=1e-6)


def test_more_volatility_widens_the_range() -> None:
    narrow = half_width_logprice(0.8, 0.01, 24.0, 50.0)
    wide = half_width_logprice(0.8, 0.50, 24.0, 50.0)
    assert wide > narrow


def test_richer_fee_flow_tightens_the_range() -> None:
    """Large kappa means fills concentrate near the mid, so sit in them."""
    thin = half_width_logprice(0.8, 0.1, 24.0, 5.0)
    rich = half_width_logprice(0.8, 0.1, 24.0, 500.0)
    assert rich < thin


def test_degenerate_parameters_are_refused_not_silently_absorbed() -> None:
    for gamma in (0.0, -1.0):
        with pytest.raises(ValueError, match="gamma"):
            half_width_logprice(gamma, 0.1, 10.0, 50.0)
    for kappa in (0.0, -1.0):
        with pytest.raises(ValueError, match="kappa"):
            half_width_logprice(0.8, 0.1, 10.0, kappa)


# --- ticks -----------------------------------------------------------------


def test_center_tick_lands_on_the_spacing_grid() -> None:
    r = -64183 * LN_TICK_BASE
    got = center_tick(r, 10)
    assert got % 10 == 0
    assert abs(got - (-64183)) <= 10


def test_half_width_is_floored_at_w_min() -> None:
    """Spec section 3.2's anti-dust floor: 4 tick spacings, so 40 at 0.05%."""
    tiny = half_width_ticks(1e-9, 10, 4)
    assert tiny == 40


def test_half_width_beyond_the_floor_snaps_to_spacing() -> None:
    """Exact equality, not `approx(..., abs=10)`.

    The previous version of this test allowed a tolerance of exactly one tick
    spacing — the largest possible disagreement on a 10-tick grid — which made
    the assertion vacuous. It computed the *spec's* answer (round to nearest,
    590 -> 600), the implementation floored (590), and the tolerance swallowed
    the difference. It was the only test standing between the codebase and the
    floor-versus-round defect, and it let it through.

    A tolerance equal to the grid quantum can never fail on a grid-rounding
    assertion. Grid arithmetic is exact, so the test should be too.
    """
    delta_star = 0.0598416928
    expected = round(delta_star / LN_TICK_BASE / 10) * 10
    assert half_width_ticks(delta_star, 10, 4) == expected == 600


def test_the_target_range_is_symmetric_around_the_centre() -> None:
    lower, upper, centre, width, _, _ = target_range(make_obs(), PARAMS, META)
    assert upper - centre == centre - lower == width
    assert lower % META.tick_spacing == 0
    assert upper % META.tick_spacing == 0


# --- section 3.4, toxicity -------------------------------------------------


def test_a_quiet_market_is_not_toxic() -> None:
    toxic, terms = toxicity(make_obs(), PARAMS, META)
    assert not toxic
    assert terms["toxicity_threshold_bps"] == pytest.approx(5.0 + 5.0)


def test_a_gap_wider_than_the_arbitrage_cost_pulls_the_quote() -> None:
    """The fee tier is 5 bps and arb cost is 5 bps, so 10 bps is the line.
    A 30 bps gap means the next trade through the pool is an arbitrageur."""
    obs = make_obs(cex_gap=0.0030, toxic_streak=PARAMS.m_toxic - 1)
    toxic, terms = toxicity(obs, PARAMS, META)
    assert toxic
    assert terms["cex_gap_bps"] == pytest.approx(30.0)


def test_a_wide_gap_still_needs_to_persist() -> None:
    """One sample is noise; `m` consecutive samples is a signal."""
    obs = make_obs(cex_gap=0.0030, toxic_streak=0)
    toxic, _ = toxicity(obs, PARAMS, META)
    assert not toxic


def test_a_gap_inside_the_arbitrage_cost_is_ignored_however_long_it_lasts() -> None:
    obs = make_obs(cex_gap=0.0005, toxic_streak=100)
    toxic, _ = toxicity(obs, PARAMS, META)
    assert not toxic


def test_one_sided_flow_pulls_without_any_off_chain_feed() -> None:
    obs = make_obs(cex_gap=None, swap_imbalance_z=3.0)
    toxic, terms = toxicity(obs, PARAMS, META)
    assert toxic
    assert terms["imbalance_toxic"] == 1.0


def test_the_fallback_rule_fires_when_the_feed_is_down() -> None:
    """Spec section 3.4's on-chain fallback: bleeding to arbitrage faster than
    we earn. It reacts after the damage rather than before it, so the decision
    records that the fallback was in use."""
    obs = make_obs(cex_gap=None, lvr_rate=5.0, fee_rate=1.0, toxic_streak=PARAMS.m_toxic - 1)
    toxic, terms = toxicity(obs, PARAMS, META)
    assert toxic
    assert terms["using_onchain_fallback"] == 1.0


def test_the_fallback_stays_quiet_while_fees_beat_lvr() -> None:
    obs = make_obs(cex_gap=None, lvr_rate=0.5, fee_rate=2.0, toxic_streak=100)
    toxic, _ = toxicity(obs, PARAMS, META)
    assert not toxic


# --- section 3.3, the gates ------------------------------------------------


def _gates(**overrides: object) -> tuple[bool, dict[str, float]]:
    obs = make_obs(**overrides)
    lower, upper, _, width, _, _ = target_range(obs, PARAMS, META)
    return recenter_gates(obs, PARAMS, META, (lower, upper), width, toxic=False)


def test_all_four_gates_are_reported_on_every_decision() -> None:
    """A tearsheet that can only say 'it did not rebalance' is much less useful
    than one that can say which gate held it back."""
    _, terms = _gates()
    for gate in ("R1", "R2", "R3", "R4"):
        assert gate in terms


def test_r1_blocks_a_range_that_has_barely_moved() -> None:
    obs = make_obs()
    lower, upper, centre, width, _, _ = target_range(obs, PARAMS, META)
    obs = make_obs(position=make_position(lower=centre - width, upper=centre + width))
    passed, terms = recenter_gates(obs, PARAMS, META, (lower, upper), width, toxic=False)
    assert terms["R1"] == 0.0
    assert not passed


def test_r2_blocks_a_rebalance_that_costs_more_than_it_earns() -> None:
    _, terms = _gates(fee_rate_per_liquidity_target=0.0, gas_cost_quote=5.0)
    assert terms["R2"] == 0.0
    assert terms["R2_net"] < 0


def test_r2_charges_the_published_mev_haircut() -> None:
    """Assumption A4: 10 bps of rebalanced notional, on a $200 position."""
    _, terms = _gates(rebalance_notional_quote=200.0)
    assert terms["R2_mev_haircut"] == pytest.approx(0.20)


def test_r3_blocks_inside_the_cooldown() -> None:
    obs_time = 1_000_000 + 600  # ten minutes after the last rebalance
    _, terms = _gates(t=obs_time)
    assert terms["R3"] == 0.0


def test_r3_blocks_once_the_daily_budget_is_spent() -> None:
    _, terms = _gates(position=make_position(rebalances_today=PARAMS.max_rebalances_per_day))
    assert terms["R3"] == 0.0


def test_r4_blocks_while_flow_is_toxic() -> None:
    obs = make_obs()
    lower, upper, _, width, _, _ = target_range(obs, PARAMS, META)
    passed, terms = recenter_gates(obs, PARAMS, META, (lower, upper), width, toxic=True)
    assert terms["R4"] == 0.0
    assert not passed


# --- decide ----------------------------------------------------------------


def test_a_drifted_range_with_every_gate_open_recenters() -> None:
    obs = make_obs(
        position=make_position(lower=-70000, upper=-69600),
        fee_rate_per_liquidity_target=1e-15,
    )
    decision = decide(obs, PARAMS, META)
    assert decision.action is Action.RECENTER
    assert decision.target_lower is not None and decision.target_upper is not None
    assert decision.target_upper > decision.target_lower


def test_toxicity_outranks_every_other_consideration() -> None:
    """A position losing to arbitrage should leave, and should not be talked out
    of leaving by a cooldown or a gas calculation."""
    obs = make_obs(
        cex_gap=0.01,
        toxic_streak=PARAMS.m_toxic,
        t=1_000_000 + 5,  # deep inside the cooldown
        position=make_position(rebalances_today=PARAMS.max_rebalances_per_day),
    )
    decision = decide(obs, PARAMS, META)
    assert decision.action is Action.PULL
    assert decision.target_lower is None


def test_a_pulled_position_waits_for_the_signal_to_clear() -> None:
    out = make_position(lower=None, upper=None, liquidity=0)
    assert decide(make_obs(position=out, clear_streak=0), PARAMS, META).action is Action.HOLD
    assert decide(make_obs(position=out, clear_streak=99), PARAMS, META).action is Action.REENTER


def test_a_position_that_never_existed_mints_rather_than_reenters() -> None:
    fresh = make_position(lower=None, upper=None, liquidity=0, token_id=None)
    assert decide(make_obs(position=fresh), PARAMS, META).action is Action.MINT


def test_a_pulled_position_does_not_reenter_into_continuing_toxicity() -> None:
    out = make_position(lower=None, upper=None, liquidity=0)
    obs = make_obs(position=out, clear_streak=99, cex_gap=0.01, toxic_streak=PARAMS.m_toxic)
    assert decide(obs, PARAMS, META).action is Action.HOLD


def test_the_decision_is_hashable_and_compares_by_value() -> None:
    """What makes test T1's bitwise comparison cheap to express."""
    a = decide(make_obs(), PARAMS, META)
    b = decide(make_obs(), PARAMS, META)
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1


def test_the_same_observation_always_decides_the_same_way() -> None:
    obs = make_obs()
    assert len({decide(obs, PARAMS, META) for _ in range(20)}) == 1


def test_reason_lookup_is_explicit_about_a_missing_key() -> None:
    decision = decide(make_obs(), PARAMS, META)
    assert decision.reason("R1") in (0.0, 1.0)
    with pytest.raises(KeyError):
        decision.reason("R9")


# --- the passive benchmark -------------------------------------------------


def test_the_passive_policy_mints_once_and_then_never_moves() -> None:
    fresh = make_position(lower=None, upper=None, liquidity=0, token_id=None)
    assert passive_policy(make_obs(position=fresh), PARAMS, META).action is Action.MINT

    drifted = make_position(lower=-70000, upper=-69600)
    assert passive_policy(make_obs(position=drifted), PARAMS, META).action is Action.HOLD


def test_the_passive_policy_ignores_toxicity_by_design() -> None:
    """It is a benchmark, not a strategy. Letting it react would stop it being
    the thing the active policy is measured against."""
    obs = make_obs(cex_gap=0.05, toxic_streak=99)
    assert passive_policy(obs, PARAMS, META).action is Action.HOLD


# --- the pull-and-return cycle, and what bounds it --------------------------
#
# The 30-day chain tape ran Warden into **2,585 mints and 2,584 pulls, and zero
# recentres** — a pull-and-return every seventeen minutes for a month. It spent
# 5,170 of token1 on costs against a deployed 1,000 to earn 0.234, and quoted
# -6,851% annualised. Section 3.4 caps rebalances and says nothing whatever
# about how often a position may leave and come back.
#
# Two things were wrong underneath, and only real data was busy enough to show
# either. See requirements-matrix P-12.


def test_a_return_after_a_pull_counts_against_todays_budget() -> None:
    """`apply_decision` reset the counter on every re-entry.

    The PULL branch deliberately carries the count forward, with a comment that
    an agent "cannot reset its own daily limit by pulling and re-minting". The
    re-mint then set it to zero, because the test was `current.in_market` and a
    flat position is not in market. The comment described a defence the code did
    not provide.
    """
    from misquote.core.position import CLOSED, apply_decision

    opened = apply_decision(CLOSED, Action.MINT, 1_000_000, lower=-64400, upper=-64000)
    assert opened.rebalances_today == 0, "a first mint is not a rebalance"
    assert opened.reentries_today == 0, "nor is it a re-entry — there was nothing to return to"

    pulled = apply_decision(opened, Action.PULL, 1_000_100)
    assert pulled.rebalances_today == 0
    assert pulled.reentries_today == 0

    back = apply_decision(pulled, Action.MINT, 1_000_200, lower=-64400, upper=-64000)
    assert back.reentries_today == 1, "the return reset the budget it should spend"
    assert back.rebalances_today == 0, (
        "a return from a pull is not a recentre and must not spend that budget — "
        "charging both to one counter is what left Warden out of the market 94% "
        "of the 30-day tape (P-20)"
    )

    out_again = apply_decision(back, Action.PULL, 1_000_300)
    once_more = apply_decision(out_again, Action.MINT, 1_000_400, lower=-64400, upper=-64000)
    assert once_more.reentries_today == 2
    assert once_more.rebalances_today == 0

    # The property the single counter existed to protect, kept under the split:
    # neither budget can be reset by leaving and coming back.
    moved = apply_decision(once_more, Action.RECENTER, 1_000_500, lower=-64500, upper=-64100)
    assert moved.rebalances_today == 1
    assert moved.reentries_today == 2, "the re-entry count survives a recentre"


def test_a_first_mint_still_starts_the_count_at_zero() -> None:
    """The rule this file already documents, which the fix must not break:
    there was nothing to rebalance, so opening is not a rebalance."""
    from misquote.core.position import CLOSED, apply_decision

    assert apply_decision(CLOSED, Action.MINT, 1_000_000, lower=-1, upper=1).rebalances_today == 0


def test_the_count_still_rolls_over_at_the_day_boundary() -> None:
    """A per-day cap that never resets is a lifetime cap. That was a real defect
    once and the fix must not reintroduce it."""
    from misquote.core.position import CLOSED, SECONDS_PER_DAY, apply_decision

    opened = apply_decision(CLOSED, Action.MINT, 1_000_000, lower=-1, upper=1)
    spent = apply_decision(opened, Action.RECENTER, 1_000_100, lower=-2, upper=2)
    assert spent.rebalances_today == 1

    tomorrow = apply_decision(
        spent, Action.RECENTER, 1_000_100 + SECONDS_PER_DAY, lower=-3, upper=3
    )
    assert tomorrow.rebalances_today == 1, "yesterday's spending followed it into today"


def test_re_entry_is_refused_once_the_daily_budget_is_gone() -> None:
    """Nothing bounded the return, so a flickering toxicity signal bought a
    fresh position every time it cleared."""
    flat = make_position(
        lower=None,
        upper=None,
        liquidity=0,
        token_id=None,
        reentries_today=PARAMS.max_reentries_per_day,
    )
    obs = make_obs(position=flat, clear_streak=PARAMS.m_clear + 5, swap_imbalance_z=0.0)

    decision = decide(obs, PARAMS, META)
    assert decision.action is Action.HOLD
    assert dict(decision.reasons)["reentry_affordable"] == 0.0


def test_re_entry_is_allowed_while_the_budget_lasts() -> None:
    """The other half — a gate that can never open is not a gate."""
    flat = make_position(lower=None, upper=None, liquidity=0, token_id=None, reentries_today=0)
    obs = make_obs(position=flat, clear_streak=PARAMS.m_clear + 5, swap_imbalance_z=0.0)

    decision = decide(obs, PARAMS, META)
    assert decision.action in (Action.MINT, Action.REENTER)
    assert dict(decision.reasons)["reentry_affordable"] == 1.0


def test_leaving_is_never_refused_for_want_of_budget() -> None:
    """The asymmetry is the whole point, and it is the half that protects money.

    An agent held inside toxic flow because it had run out of budget is worse
    off than one that churns: churn costs gas, and being unable to leave costs
    the position. Exit stays unconditional however much has been spent today.

    The fixture now carries a danger with a *size* — a 2% CEX gap against a
    position worth 200 — because A17 asks whether the exit pays for itself and
    that question needs a magnitude to answer. The property under test is
    unchanged and is specifically about the budget: both counters are run far
    past their caps and neither is consulted on the way out.
    """
    held = make_position(
        rebalances_today=PARAMS.max_rebalances_per_day * 10,
        reentries_today=PARAMS.max_reentries_per_day * 10,
    )
    obs = make_obs(
        position=held,
        swap_imbalance_z=PARAMS.z_pull + 1.0,
        cex_gap=0.02,
        toxic_streak=PARAMS.m_toxic,
    )

    assert decide(obs, PARAMS, META).action is Action.PULL


def test_a_pull_that_cannot_pay_for_itself_is_not_made() -> None:
    """A17. The gate R2 always applied to moving, applied to leaving.

    Nothing priced the exit, so the toxicity arm could cycle the position at
    whatever rate the daily budget allowed. On the 30-day chain tape it made 653
    pull-and-return round trips costing 9.6% of deployed capital against 4.8% of
    fees earned — the round trips, not the strategy, were the loss.

    Here the imbalance arm fires on a pool that is earning fees and has no
    measured adverse selection at all. There is nothing to escape, and paying a
    round trip to escape it is the behaviour being removed.
    """
    held = make_position()
    obs = make_obs(
        position=held,
        swap_imbalance_z=PARAMS.z_pull + 1.0,
        cex_gap=0.0,
        lvr_rate=0.0,
        fee_rate=1.0,
    )

    decision = decide(obs, PARAMS, META)
    reasons = dict(decision.reasons)

    assert decision.action is Action.HOLD
    assert reasons["toxic"] == 1.0, "the signal still fired; only the response changed"
    assert reasons["pull_pays"] == 0.0
    assert reasons["pull_round_trip_cost"] > reasons["pull_saving"]


def test_a_leading_gap_is_judged_on_its_own_magnitude_not_on_trailing_damage() -> None:
    """The CEX-gap arm leads, so trailing realized LVR is the wrong yardstick.

    A gap of `g` against a position worth `V` is arbitraged for about `V*g`, and
    that is knowable before any of it has happened. Judging the leading arm by
    damage already done would refuse the pull exactly when the signal is doing
    its job — which is what the first version of A17's gate did, and what
    `test_toxicity_outranks_every_other_consideration` caught.
    """
    obs = make_obs(
        position=make_position(),
        cex_gap=0.02,
        toxic_streak=PARAMS.m_toxic,
        lvr_rate=0.0,
        fee_rate=1.0,
    )

    decision = decide(obs, PARAMS, META)
    reasons = dict(decision.reasons)

    assert decision.action is Action.PULL
    assert reasons["pull_saving_from_gap"] > reasons["pull_saving_from_bleed"]
    assert reasons["pull_saving_from_bleed"] == 0.0, "nothing has been lost yet"


# --- A20: the width is sized once, so it must not be sized on a guess -------


def test_a_position_is_not_opened_while_sigma_is_still_the_prior() -> None:
    """The one decision nothing re-examines must not be made on a constant.

    `estimators.sigma.shrink` returns the prior outright before any returns
    exist, and A7 records that prior as roughly 190% annualised against BNB's
    typical 50-70%. On the 30-day chain tape the agent opened at +/-14.45% on a
    pool that moved 11.6% for the month, held it for the month because no gate
    revisits a width, and earned 6.7x less in fees than a fixed 200-tick ladder.
    """
    flat = make_position(lower=None, upper=None, liquidity=0, token_id=None)
    obs = make_obs(position=flat, clear_streak=PARAMS.m_clear + 5, sigma_confidence=0.0)

    decision = decide(obs, PARAMS, META)
    reasons = dict(decision.reasons)

    assert decision.action is Action.HOLD
    assert reasons["width_inputs_trustworthy"] == 0.0
    assert reasons["sigma_confident"] == 0.0
    assert decision.target_lower is None, "refusing to open must not publish a range"


def test_a_position_opens_once_sigma_is_mostly_measurement() -> None:
    """The other half — a gate that never opens is not a gate, it is an outage."""
    flat = make_position(lower=None, upper=None, liquidity=0, token_id=None)
    obs = make_obs(
        position=flat,
        clear_streak=PARAMS.m_clear + 5,
        sigma_confidence=PARAMS.min_sigma_confidence,
    )

    decision = decide(obs, PARAMS, META)

    assert decision.action in (Action.MINT, Action.REENTER)
    assert dict(decision.reasons)["width_inputs_trustworthy"] == 1.0


def test_the_benchmark_is_sized_by_the_same_rule_as_the_agent() -> None:
    """`passive_policy` calls the same `target_range`, so it opened at the same
    prior-sized width — which cut the baseline's own fees from 0.01753 to 0.00697
    on the chain tape.

    A comparison is only worth making if both sides are sized by one rule. "The
    baseline is not a different program" is the claim this benchmark exists to
    support, and it has to survive a change to how widths are chosen.
    """
    flat = make_position(lower=None, upper=None, liquidity=0, token_id=None)

    early = passive_policy(make_obs(position=flat, sigma_confidence=0.0), PARAMS, META)
    assert early.action is Action.HOLD, "the baseline must wait too"

    later = passive_policy(
        make_obs(position=flat, sigma_confidence=PARAMS.min_sigma_confidence), PARAMS, META
    )
    assert later.action is Action.MINT


def test_a_fallback_kappa_does_not_block_the_open() -> None:
    """The first version of this gate had kappa backwards, and it matters enough
    to pin.

    A fallback kappa is the published fit, 3,600.91, at which equation (2) returns
    about 3 ticks — under the A18 floor, so the floor sets the width and the
    result is the *safe* case. The +/-14.45% range came from kappa around 7, which
    is `is_fallback=False`: a real fit, clearing r-squared 0.5, wrong by 500x.
    Blocking on the flag refuses the safe case and admits the dangerous one, and
    A19's ceiling is what actually bounds kappa.
    """
    flat = make_position(lower=None, upper=None, liquidity=0, token_id=None)
    obs = make_obs(
        position=flat,
        clear_streak=PARAMS.m_clear + 5,
        sigma_confidence=PARAMS.min_sigma_confidence,
        kappa_is_fallback=True,
    )

    assert decide(obs, PARAMS, META).action in (Action.MINT, Action.REENTER)
