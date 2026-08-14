"""The shared decision step. Executes nothing, and cannot.

This is layer 2 of three, and the reason the live agent and the replay engine are
provably the same policy rather than two implementations that resemble each
other. `Engine.step()` ingests events, updates estimators, assembles an
`Observation`, and returns a `Decision`. Applying that decision — minting,
burning, or simulating — belongs to the driver.

There is no `if replay:` anywhere in this file, and there cannot be one: the
engine has no way to tell which driver is calling it. That is what test L1
checks, by running the live driver against a tape and asserting its decision
sequence is byte-identical to the replay driver's.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from misquote.core.liquidity import get_amounts_for_liquidity
from misquote.core.policy import decide, inventory_imbalance
from misquote.core.tickmath import Q96, get_sqrt_ratio_at_tick
from misquote.core.types import (
    Decision,
    Event,
    Observation,
    Params,
    PoolMeta,
    PositionState,
)
from misquote.estimators.kappa import KappaEstimator
from misquote.estimators.sigma import SigmaEstimator
from misquote.lvr.accountant import LvrAccountant

# The on-chain toxicity fallback compares trailing realized LVR against trailing
# realized fees. Both are zero the instant a position is minted, and after a
# single swap the comparison is a verdict drawn from a sample of one — which,
# because LVR is an upper bound (assumption A10) and fees accrue in slivers,
# almost always reads as toxic. The agent would then pull, wait out m_clear,
# re-mint, and pull again: a loop that looks like risk management and is
# actually noise.
#
# So the rates are reported as zero — no verdict — until enough swaps have been
# observed to have one. This is the same sample-size discipline the tearsheet
# applies before it will call a result. Published as assumption A12.
MIN_SWAPS_FOR_TOXICITY_VERDICT = 30


@dataclass(frozen=True, slots=True)
class MarketState:
    """What the driver knows about the pool right now.

    Supplied by the driver rather than read by the engine, because reading it is
    exactly the capability that differs between live and replay — and the whole
    architecture depends on that difference living in one place.
    """

    t: int
    sqrt_price_x96: int
    tick: int
    pool_liquidity: int
    gas_cost_quote: float
    slippage_quote: float
    cex_gap: float | None = None


class Engine:
    """Estimators plus the policy, with no capability to act.

    Owns the trailing estimators because they are stateful and must see every
    event exactly once, in order. The look-ahead guard lives in their `ingest`,
    unconditionally, in both drivers — spec test T3 implemented in code rather
    than asserted in review.
    """

    __slots__ = (
        "meta",
        "params",
        "sigma",
        "kappa",
        "_lvr",
        "_position",
        "_toxic_streak",
        "_clear_streak",
        "_last_decision",
        "_fee_rate_current",
        "_fee_rate_target",
        "decisions",
    )

    def __init__(self, meta: PoolMeta, params: Params | None = None) -> None:
        self.meta = meta
        self.params = params or Params()
        self.sigma = SigmaEstimator()
        self.kappa = KappaEstimator()
        self._lvr: LvrAccountant | None = None
        self._position = PositionState(
            lower=None,
            upper=None,
            liquidity=0,
            token_id=None,
            minted_ts=0,
            last_rebalance_ts=0,
            rebalances_today=0,
        )
        self._toxic_streak = 0
        self._clear_streak = 0
        self._last_decision: Decision | None = None
        self._fee_rate_current = 0.0
        self._fee_rate_target = 0.0
        self.decisions = 0

    # --- state the driver owns and hands back ------------------------------

    def set_position(self, position: PositionState) -> None:
        """The driver applied a decision; this is the result."""
        self._position = position
        if position.in_market and position.liquidity > 0:
            self._lvr = LvrAccountant(
                position.lower,
                position.upper,
                position.liquidity,
                self.meta,
                l_pool_includes_self=False,
            )
        else:
            self._lvr = None

    @property
    def position(self) -> PositionState:
        return self._position

    @property
    def lvr(self) -> LvrAccountant | None:
        return self._lvr

    # --- the step ----------------------------------------------------------

    def step(self, events: Sequence[Event], market: MarketState) -> Decision:
        """Ingest, estimate, observe, decide. Nothing else.

        Events must be everything in `(previous t, market.t]` and nothing else.
        The estimators enforce that: an event after the decision time raises
        `LookAheadError` and one out of chain order raises `OutOfOrderError`,
        always, with no flag to switch either off.
        """
        self.sigma.set_decision_time(market.t)
        self.kappa.set_decision_time(market.t)

        for event in events:
            self.sigma.ingest(event)
            self.kappa.ingest(event)
            if self._lvr is not None:
                self._lvr.absorb(event)

        observation = self._observe(market)
        decision = decide(observation, self.params, self.meta)

        # Streaks are maintained here rather than by the driver so both drivers
        # cannot drift apart on the one piece of state whose semantics are
        # subtle. The gap arm alone advances `toxic_streak`: section 3.4 wants
        # the gap condition to persist for m samples while the imbalance arm
        # fires instantly, so counting the overall verdict would let a single
        # imbalance spike satisfy the other rule's persistence requirement.
        gap_held = _gap_condition_held(decision)
        self._toxic_streak = self._toxic_streak + 1 if gap_held else 0
        self._clear_streak = 0 if decision.reason("toxic") > 0.0 else self._clear_streak + 1

        self._last_decision = decision
        self.decisions += 1
        return decision

    # --- assembling the Observation ---------------------------------------

    def _observe(self, market: MarketState) -> Observation:
        position = self._position
        q, value_quote, notional = self._inventory(market, position)

        window = self.params.window_hours
        elapsed_hours = (
            max(1e-9, (market.t - position.minted_ts) / 3600.0) if position.in_market else window
        )
        have_verdict = (
            self._lvr is not None and self._lvr.swaps_seen >= MIN_SWAPS_FOR_TOXICITY_VERDICT
        )
        lvr_rate = (self._lvr.total_lvr / elapsed_hours) if have_verdict else 0.0
        fee_rate = (self._lvr.total_fees / elapsed_hours) if have_verdict else 0.0

        return Observation(
            t=market.t,
            tick=market.tick,
            y=_log_price(market.sqrt_price_x96),
            sqrt_price_x96=market.sqrt_price_x96,
            pool_liquidity=market.pool_liquidity,
            q=q,
            sigma=self.sigma.value(),
            kappa=self.kappa.value(),
            kappa_r2=self.kappa.fit().r_squared,
            kappa_is_fallback=self.kappa.fit().is_fallback,
            # Spec section 2 calls this "remaining contract window (rolling)"
            # and section 7 says W = 24h rolling. Constant, not decaying: a
            # decaying horizon collapses the range to w_min at each window
            # boundary and then jumps it back, churning gas for nothing.
            T_t=window,
            gas_cost_quote=market.gas_cost_quote,
            slippage_quote=market.slippage_quote,
            fee_rate_per_liquidity_target=self._fee_rate_target,
            fee_rate_per_liquidity_current=self._fee_rate_current,
            target_liquidity=position.liquidity or 0,
            position_value_quote=value_quote,
            rebalance_notional_quote=notional,
            cex_gap=market.cex_gap,
            swap_imbalance_z=0.0,
            lvr_rate=lvr_rate,
            fee_rate=fee_rate,
            toxic_streak=self._toxic_streak,
            clear_streak=self._clear_streak,
            position=position,
        )

    def _inventory(
        self, market: MarketState, position: PositionState
    ) -> tuple[float, float, float]:
        """`q`, position value, and what a recentre would actually swap."""
        if not position.in_market or position.liquidity <= 0:
            return 0.0, 0.0, 0.0

        sa = get_sqrt_ratio_at_tick(position.lower)
        sb = get_sqrt_ratio_at_tick(position.upper)
        amount0, amount1 = get_amounts_for_liquidity(
            market.sqrt_price_x96, sa, sb, position.liquidity
        )
        price = ((market.sqrt_price_x96 / Q96) ** 2) * 10.0 ** (self.meta.dec0 - self.meta.dec1)
        value0 = (amount0 / 10.0**self.meta.dec0) * price
        value1 = amount1 / 10.0**self.meta.dec1

        q = inventory_imbalance(value0, value1)
        total = value0 + value1
        # Assumption A4's base: a recentre swaps only enough to restore the
        # target composition, which is half the imbalance, not the whole
        # position.
        notional = abs(value0 - value1) / 2.0
        return q, total, notional

    def set_fee_rates(self, current: float, target: float) -> None:
        """Trailing fee-rate-per-unit-liquidity for the current and target ranges.

        Two of them because R2 asks for a *gain*: what the target range would
        earn against what staying put would earn. One rate cannot express a
        difference.
        """
        self._fee_rate_current = current
        self._fee_rate_target = target


def _gap_condition_held(decision: Decision) -> bool:
    """Did the gap *condition* hold this sample, regardless of the streak?

    `gap_toxic` is the rule's verdict, which already requires m consecutive
    samples — so reading only that could never let the streak reach m. What
    advances the streak is the underlying condition: the CEX gap exceeding the
    arbitrage cost, or, when the feed is down, LVR outrunning fees.
    """
    if decision.reason("using_onchain_fallback") > 0.0:
        return decision.reason("lvr_rate") > decision.reason("fee_rate")
    return decision.reason("cex_gap_bps") > decision.reason("gap_threshold_bps")


def _log_price(sqrt_price_x96: int) -> float:
    """Raw pool log-price, which is what `center_tick` divides by ln(1.0001).

    Deliberately *not* decimal-adjusted. The tick scale is defined on the raw
    pool price, so adjusting here would shift every centre by
    `(dec1 - dec0)*ln(10)/ln(1.0001)` — 276,310 ticks on a pool with a 12-decimal
    asymmetry, which is outside the representable range entirely.
    """
    import math

    return 2.0 * math.log(sqrt_price_x96 / Q96)
