"""Layer 3: applying decisions to a simulated position.

The engine decides; this executes. In replay that means moving a hypothetical
position and charging a cost model; live it means signing transactions. Both call
the same `Engine.step()` with the same arguments, which is what test L1 proves.

The decision clock is driven off the *tape*, not off a wall clock. There is no
`time.time()` anywhere below layer 3 and the layering test forbids adding one, so
a replay and a live run feed the engine the same *kind* of number — a block
timestamp. That is what makes L1's byte-identical comparison meaningful rather
than coincidental.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from misquote.core.liquidity import get_liquidity_for_amounts
from misquote.core.position import apply_decision
from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import Action, Decision, Event, Params, Policy, PoolMeta
from misquote.replay.engine import Engine, MarketState


@dataclass(frozen=True, slots=True)
class CostModel:
    """What a rebalance costs. Every field is published in the assumption sheet.

    Deliberately conservative: gas and slippage are charged in full on every
    move, and assumption A4's MEV haircut is applied to the rebalanced notional
    on top. A replay that undercharges its own strategy produces exactly the kind
    of number this product exists to argue against.
    """

    gas_quote: float = 0.5  # trailing median gas x price, in token1
    slippage_bps: float = 5.0  # on the rebalanced notional
    mev_haircut_bps: float = 10.0  # assumption A4


@dataclass(slots=True)
class ReplayResult:
    """One run's outcome, with enough detail to argue with."""

    decisions: list[Decision] = field(default_factory=list)
    timestamps: list[int] = field(default_factory=list)
    rebalances: int = 0
    pulls: int = 0
    mints: int = 0
    total_fees: float = 0.0
    total_lvr: float = 0.0
    total_costs: float = 0.0
    samples: int = 0
    in_range_samples: int = 0
    first_ts: int | None = None
    last_ts: int | None = None

    @property
    def net_quote(self) -> float:
        """Fees, less adverse selection, less what it cost to stay there."""
        return self.total_fees - self.total_lvr - self.total_costs

    @property
    def in_range_fraction(self) -> float:
        return self.in_range_samples / self.samples if self.samples else 0.0

    @property
    def hours(self) -> float:
        if self.first_ts is None or self.last_ts is None:
            return 0.0
        return max(0.0, (self.last_ts - self.first_ts) / 3600.0)


class ReplayDriver:
    """Steps the engine across a tape and applies what it decides.

    The position is hypothetical, so its liquidity is capped at a fraction of the
    pool's (assumption A1): a replayed position large enough to have moved the
    price it is being replayed against is not a backtest, it is fiction.
    """

    __slots__ = (
        "engine",
        "meta",
        "params",
        "costs",
        "capital_quote",
        "eps",
        "_result",
    )

    def __init__(
        self,
        meta: PoolMeta,
        *,
        params: Params | None = None,
        costs: CostModel | None = None,
        capital_quote: float = 1000.0,
        policy: Policy | None = None,
    ) -> None:
        self.meta = meta
        self.params = params or Params()
        # Which agent to replay. Defaults to Warden, so every existing caller is
        # unchanged, and passing one is the only supported way to run another —
        # replacing the engine module's `decide` global, which is what the
        # showcase used to do, cannot run two agents concurrently and leaves the
        # wrong policy installed if anything in between raises.
        self.engine = Engine(meta, self.params, policy=policy)
        self.costs = costs or CostModel()
        self.capital_quote = capital_quote
        self.eps = self.params.eps_liquidity_share
        self._result = ReplayResult()

    def run(self, tape, *, sample_seconds: int | None = None) -> ReplayResult:
        """Walk the tape at the policy's sampling cadence.

        `sample_seconds` defaults to spec section 8's Δs. Sampling on a fixed
        grid rather than per-event is what makes the toxicity rule's "m
        consecutive samples" mean a duration rather than a trade count.
        """
        step = sample_seconds or self.params.sample_interval_s
        if tape.first_ts is None:
            return self._result

        market: MarketState | None = None
        t = tape.first_ts
        end = tape.last_ts

        while t <= end:
            events = tape.advance_to(t)
            market = self._market_at(t, events, market)
            if market is None:
                t += step
                continue

            decision = self.engine.step(events, market)
            self._apply(decision, market)
            t += step

        self._finalise()
        return self._result

    # --- what the driver knows that the engine does not --------------------

    def _market_at(
        self, t: int, events: Sequence[Event], previous: MarketState | None
    ) -> MarketState | None:
        """Pool state at `t`, from the last event at or before it.

        Reading it from the tape rather than from a snapshot table is what makes
        replay reproducible from a single file. If nothing has traded yet there
        is no state to observe and no decision to make.
        """
        if events:
            last = events[-1]
            return MarketState(
                t=t,
                sqrt_price_x96=last.sqrt_price_x96,
                tick=last.tick,
                pool_liquidity=last.liquidity,
                gas_cost_quote=self.costs.gas_quote,
                slippage_quote=0.0,
                cex_gap=None,
            )
        if previous is None:
            return None
        return MarketState(
            t=t,
            sqrt_price_x96=previous.sqrt_price_x96,
            tick=previous.tick,
            pool_liquidity=previous.pool_liquidity,
            gas_cost_quote=self.costs.gas_quote,
            slippage_quote=0.0,
            cex_gap=None,
        )

    def _apply(self, decision: Decision, market: MarketState) -> None:
        result = self._result
        result.decisions.append(decision)
        result.timestamps.append(market.t)
        result.samples += 1
        if result.first_ts is None:
            result.first_ts = market.t
        result.last_ts = market.t

        position = self.engine.position
        if position.in_market and position.contains(market.tick):
            result.in_range_samples += 1

        if decision.action is Action.HOLD:
            return

        if decision.action is Action.PULL:
            self._settle(market)
            self.engine.set_position(apply_decision(position, Action.PULL, market.t))
            result.pulls += 1
            return

        # MINT or REBALANCE: settle what the old position earned, then open the
        # new one and charge for the privilege.
        if position.in_market:
            self._settle(market)
            result.rebalances += 1
        else:
            result.mints += 1

        liquidity = self._size(decision, market)
        self.engine.set_position(
            apply_decision(
                position,
                decision.action,
                market.t,
                lower=decision.target_lower,
                upper=decision.target_upper,
                liquidity=liquidity,
            )
        )
        result.total_costs += self._move_cost()

    def _size(self, decision: Decision, market: MarketState) -> int:
        """Liquidity for `capital_quote`, capped at A1's share of the pool."""
        sa = get_sqrt_ratio_at_tick(decision.target_lower)
        sb = get_sqrt_ratio_at_tick(decision.target_upper)

        # Split the capital the way the curve will hold it at this price.
        amount1 = int(self.capital_quote * 10**self.meta.dec1)
        amount0 = int(self.capital_quote * 10**self.meta.dec0)
        wanted = get_liquidity_for_amounts(market.sqrt_price_x96, sa, sb, amount0, amount1)

        # Assumption A1. A replayed position big enough to have moved the price
        # it is replayed against would be fiction, not a backtest.
        cap = int(market.pool_liquidity * self.eps)
        return max(1, min(wanted, cap))

    def _settle(self, market: MarketState) -> None:
        """Bank what the closing position earned and cost."""
        accountant = self.engine.lvr
        if accountant is None:
            return
        self._result.total_fees += accountant.total_fees
        self._result.total_lvr += accountant.total_lvr

    def _move_cost(self) -> float:
        notional = self.capital_quote
        slippage = notional * self.costs.slippage_bps / 10_000.0
        mev = notional * self.costs.mev_haircut_bps / 10_000.0
        return self.costs.gas_quote + slippage + mev

    def _finalise(self) -> None:
        accountant = self.engine.lvr
        if accountant is not None:
            self._result.total_fees += accountant.total_fees
            self._result.total_lvr += accountant.total_lvr


def passive_result(meta: PoolMeta, tape, lower: int, upper: int, liquidity: int) -> ReplayResult:
    """A position that is minted once and never touched.

    The comparator equation (4) is defined against, and the subject of test T4:
    with the policy replaced by "always HOLD", the replay must agree with a
    direct computation from chain state.
    """
    result = ReplayResult()
    from misquote.lvr.accountant import LvrAccountant

    accountant: LvrAccountant | None = None
    for event in tape.advance_to(tape.last_ts or 0):
        if accountant is None:
            accountant = LvrAccountant(
                lower, upper, liquidity, meta, sqrt_price_x96=event.sqrt_price_x96
            )
            result.first_ts = event.ts
            continue
        accountant.absorb(event)
        result.last_ts = event.ts
        result.samples += 1
        if lower <= event.tick < upper:
            result.in_range_samples += 1

    if accountant is not None:
        result.total_fees = accountant.total_fees
        result.total_lvr = accountant.total_lvr
    result.mints = 1
    return result
