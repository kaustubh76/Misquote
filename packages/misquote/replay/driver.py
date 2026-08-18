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

from misquote.core.liquidity import get_amounts_for_liquidity, liquidity_for_capital
from misquote.core.position import apply_decision
from misquote.core.tickmath import Q96, get_sqrt_ratio_at_tick
from misquote.core.types import (
    DEFAULT_CAPITAL_QUOTE,
    DEFAULT_GAS_QUOTE,
    Action,
    Decision,
    Event,
    Params,
    Policy,
    PoolMeta,
)
from misquote.replay.engine import Engine, MarketState


@dataclass(frozen=True, slots=True)
class CostModel:
    """What a rebalance costs. Every field is published in the assumption sheet.

    Deliberately conservative: gas and slippage are charged in full on every
    move, and assumption A4's MEV haircut is applied to the rebalanced notional
    on top. A replay that undercharges its own strategy produces exactly the kind
    of number this product exists to argue against.
    """

    # One recentre — burn, collect, mint — at BSC's prevailing gas price, in
    # token1. `chain/live_source.py` computes exactly this from the chain as
    # `REBALANCE_GAS_UNITS * eth_gasPrice / 1e18`; measured 17 Aug 2026 at
    # 0.05 gwei, that is 600,000 x 5e7 / 1e18 = 3.0e-5 BNB, about two cents.
    #
    # This field held **0.5** — the same quantity the live source measures, in
    # the same units, **16,667x too large**, with a comment claiming it was a
    # trailing median. Nothing measured it. On the 30-day tape Grid paid 26.0 in
    # costs against 0.164 of fees, and the quote it produced was a statement
    # about this constant rather than about the strategy. See P-13.
    gas_quote: float = DEFAULT_GAS_QUOTE

    # Both bps figures are charged on the **rebalanced notional** — what a
    # recentre actually swaps — not on the whole position. See `_move_cost`.
    slippage_bps: float = 5.0
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
    # Times A1's 1% ceiling bound the position. A1 says a quote that breaches
    # epsilon is *refused rather than rendered*; the cap was applied silently
    # and the quote published anyway. See P-14.
    a1_capped: int = 0
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
        "_held",
    )

    def __init__(
        self,
        meta: PoolMeta,
        *,
        params: Params | None = None,
        costs: CostModel | None = None,
        capital_quote: float = DEFAULT_CAPITAL_QUOTE,
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
        # What a pull left in hand, so a re-entry is priced as the swap it is.
        self._held: tuple[int, int] | None = None

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
            # What the burn returned. A v3 position pays out **both** tokens, so
            # the agent stands there holding a mixture — not a single asset. The
            # next entry therefore has to swap only the difference between what
            # it holds and what the new range wants, and pricing it as a fresh
            # entry charges for a swap that does not happen. See P-18.
            self._held = get_amounts_for_liquidity(
                market.sqrt_price_x96,
                get_sqrt_ratio_at_tick(position.lower),
                get_sqrt_ratio_at_tick(position.upper),
                position.liquidity,
            )
            self.engine.set_position(apply_decision(position, Action.PULL, market.t))
            result.pulls += 1
            # A withdrawal costs gas: `decreaseLiquidity` plus `collect`. This
            # branch used to return before anything was charged, so leaving was
            # free — an undercharge that fell on the agent and never on the
            # never-withdraw baseline. It was immaterial while a *return* cost
            # half the capital and swamped it; now that a return is priced as the
            # small swap it is (P-18), gas is most of what a pull-and-return
            # cycle costs, and free withdrawals would be the largest remaining
            # thumb on the scale. No slippage or MEV: a burn swaps nothing.
            result.total_costs += self.costs.gas_quote
            return

        # MINT or REBALANCE: settle what the old position earned, then open the
        # new one and charge for the privilege.
        recentring = position.in_market
        if recentring:
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
        result.total_costs += self._move_cost(
            recentring=recentring, market=market, decision=decision, liquidity=liquidity
        )
        self._held = None

    def _size(self, decision: Decision, market: MarketState) -> int:
        """Liquidity worth `capital_quote`, via the one implementation.

        This and `WardenLive._size` held the same arithmetic twice; correcting
        one diverged the drivers and L1 said so. See `core.liquidity`.
        """
        liquidity, capped = liquidity_for_capital(
            market.sqrt_price_x96,
            get_sqrt_ratio_at_tick(decision.target_lower),
            get_sqrt_ratio_at_tick(decision.target_upper),
            capital_quote=self.capital_quote,
            dec1=self.meta.dec1,
            pool_liquidity=market.pool_liquidity,
            eps=self.eps,
        )
        if capped:
            self._result.a1_capped += 1
        return liquidity

    def _settle(self, market: MarketState) -> None:
        """Bank what the closing position earned and cost."""
        accountant = self.engine.lvr
        if accountant is None:
            return
        self._result.total_fees += accountant.total_fees
        self._result.total_lvr += accountant.total_lvr

    def _move_cost(
        self,
        *,
        recentring: bool,
        market: MarketState,
        decision: Decision,
        liquidity: int,
    ) -> float:
        """A4's cost of one move: gas, plus slippage and MEV on what is *swapped*.

        This charged both bps figures against `self.capital_quote` — the entire
        position, on every move — while `Engine._inventory` computed A4's actual
        base and handed it to the policy as `rebalance_notional_quote`. So R2
        decided whether a move paid for itself using one number and this ledger
        charged for it using another (P-13).

        Three cases, and conflating any two of them is wrong in a different
        direction:

        **Recentring.** Swap only enough to restore the target composition —
        A4's imbalance base, near zero on a well-centred position.

        **Opening from nothing.** Convert about half the capital into the other
        token. A flat position has `value0 == value1 == 0`, so A4's formula reads
        zero here and would make every mint slippage-free.

        **Returning after a pull.** The one this used to get worst. Burning a v3
        position pays out *both* tokens, so the agent already holds a mixture:
        the swap is the difference between what it holds and what the new range
        wants, which is small when price has not moved far. Charging it as an
        opening — half the capital — made 249 round trips cost 19.4% of capital
        over thirty days and was the whole of Warden's and Sentinel's reported
        loss. See P-18.
        """
        if recentring:
            observation = self.engine.last_observation
            notional = (
                observation.rebalance_notional_quote
                if observation is not None
                else self.capital_quote
            )
        elif self._held is not None:
            # Returning: what we hold, against what the target range needs.
            sqrt_price = market.sqrt_price_x96
            want0, want1 = get_amounts_for_liquidity(
                sqrt_price,
                get_sqrt_ratio_at_tick(decision.target_lower),
                get_sqrt_ratio_at_tick(decision.target_upper),
                liquidity,
            )
            have0, have1 = self._held
            price_raw = (sqrt_price / Q96) ** 2
            # Half the mismatch, in token1, matching A4's "restore the target
            # composition" base — one side is bought and the other sold.
            gap = abs((want0 - have0) * price_raw - (want1 - have1)) / 2.0
            notional = gap / 10.0**self.meta.dec1
        else:
            # Entering from a single asset: half of it has to become the other.
            notional = self.capital_quote / 2.0
        slippage = notional * self.costs.slippage_bps / 10_000.0
        mev = notional * self.costs.mev_haircut_bps / 10_000.0
        return self.costs.gas_quote + slippage + mev

    def _finalise(self) -> None:
        accountant = self.engine.lvr
        if accountant is not None:
            self._result.total_fees += accountant.total_fees
            self._result.total_lvr += accountant.total_lvr


# `passive_result` lived here and is gone. It built a `ReplayResult` for a
# never-touched position, and nothing called it — not the showcase, not the
# advantage report, not a single test. `tearsheet/advantage.py` cited it as
# built machinery, which is how it survived.
#
# It is deleted rather than kept because it counted a *published* metric by a
# different rule than the live path: `in_range_samples` per **swap event**,
# where `ReplayDriver._apply` counts per **decision sample** on the fixed dS
# grid. One is trade-weighted, the other time-weighted, and on a pool whose
# trading is bursty they are not close. Dead code is tolerable; dead code that
# answers a live question differently is a trap with a fuse in it.
#
# The passive baseline that *is* used runs through `ReplayDriver` with
# `policy=passive_policy`, which is the whole point — same engine, same costs,
# same accountant, so "the baseline is not a different program" is structural
# rather than promised.
