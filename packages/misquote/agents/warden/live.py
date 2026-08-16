"""The Warden's live decision loop.

Polls a `ChainSource`, steps the shared engine, and hands each decision to an
executor. This file is the live half of the pair that test L1 compares: it keeps
its own loop, its own position bookkeeping, and its own idea of when to sample,
so the equality L1 asserts is between two implementations rather than one
implementation called twice.

Nothing here signs anything. The executor is an interface, and the step-13
implementation is what will hold a key. That separation is what lets the whole
loop be tested against recorded history with no possibility of a transaction.

The decision clock is the head block's timestamp, never a wall clock. The
layering test forbids `time.time()` below this layer, and this is the reason:
live and replay must feed the engine the same kind of number, or L1 compares two
different experiments and passes for the wrong reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from misquote.chain.source import ChainSource
from misquote.core.liquidity import get_liquidity_for_amounts
from misquote.core.position import apply_decision
from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import Action, Decision, Params, PoolMeta, PositionState
from misquote.replay.engine import Engine, MarketState


@runtime_checkable
class Executor(Protocol):
    """Performs a decision against the world. The only thing that can act.

    `runtime_checkable`, matching `ChainSource`, so a test can assert that an
    implementation still satisfies it. Without that the live agent discovers a
    drifted signature at the first decision it tries to act on, which is the
    worst possible moment.

    Returns the NFPM token id where one exists, and nothing else. Working out
    the resulting `PositionState` is `core.position.apply_decision`'s job — when
    the executor did it, the live and replay drivers computed it separately and
    drifted, which is what test L1 caught.
    """

    def mint(self, lower: int, upper: int, liquidity: int, ts: int) -> int | None: ...

    def rebalance(
        self, current: PositionState, lower: int, upper: int, liquidity: int, ts: int
    ) -> int | None: ...

    def pull(self, current: PositionState, ts: int) -> None: ...


@dataclass(slots=True)
class SimulatedExecutor:
    """Applies decisions to a position that exists only in memory.

    Used by L1 and by the dry-run mode. Deliberately *not* a stub that records
    calls and returns nothing: it maintains a real position, because the engine's
    next decision depends on it, and a hollow executor would make the loop
    diverge from the live one in exactly the way L1 exists to catch.
    """

    moves: list[tuple[str, int]] = field(default_factory=list)

    def mint(self, lower: int, upper: int, liquidity: int, ts: int) -> int | None:
        self.moves.append(("mint", ts))
        return None

    def rebalance(
        self, current: PositionState, lower: int, upper: int, liquidity: int, ts: int
    ) -> int | None:
        self.moves.append(("rebalance", ts))
        return current.token_id

    def pull(self, current: PositionState, ts: int) -> None:
        self.moves.append(("pull", ts))


class WardenLive:
    """The live loop, in a form that can be stepped synchronously.

    Step 14 wraps this in asyncio with a kill-file check and a replace-on-full
    action queue. The decision logic is here so it can be tested against
    recorded history first — writing the loop and the transaction path at the
    same time means debugging both at once.
    """

    __slots__ = (
        "meta",
        "params",
        "engine",
        "source",
        "executor",
        "capital_quote",
        "decisions",
        "timestamps",
    )

    def __init__(
        self,
        meta: PoolMeta,
        source: ChainSource,
        executor: Executor,
        *,
        params: Params | None = None,
        capital_quote: float = 1000.0,
    ) -> None:
        self.meta = meta
        self.params = params or Params()
        self.engine = Engine(meta, self.params)
        self.source = source
        self.executor = executor
        self.capital_quote = capital_quote
        self.decisions: list[Decision] = []
        self.timestamps: list[int] = []

    def decide(self, t: int) -> Decision | None:
        """Observe, ingest, decide. **Executes nothing and applies nothing.**

        Split out of `step` so the async loop can put the transaction on a worker
        thread while the policy keeps sampling. `step` still composes the two, so
        every synchronous caller — including test L1 — is unaffected.

        Returns None when the pool has not been read yet: `sqrt_price == 0` means
        the source has nothing to describe, and deciding on that would be
        deciding on a price of zero.
        """
        events = self.source.events_since(0, t)
        sqrt_price, tick = self.source.slot0()
        if sqrt_price == 0:
            return None

        market = MarketState(
            t=t,
            sqrt_price_x96=sqrt_price,
            tick=tick,
            pool_liquidity=self.source.liquidity(),
            gas_cost_quote=self.source.gas_price_quote(),
            slippage_quote=0.0,
            cex_gap=None,
        )

        decision = self.engine.step(events, market)
        self.decisions.append(decision)
        self.timestamps.append(t)
        self._last_market = market
        return decision

    def perform(self, decision: Decision, market: MarketState | None = None) -> None:
        """Act on a decision, then record the position it produced.

        **In that order, and only on success.** If the executor raises, the
        engine is never told, so the agent's idea of its own position stays equal
        to the chain's. That property is provided by call order alone and is the
        whole reason `_execute` applies afterwards rather than before.

        `market` defaults to the one `decide` last built. Sizing against the
        freshest observation is right: the queue may have held this decision for
        a while, and the slippage bound is only meaningful against the price the
        transaction will actually meet.
        """
        if market is None:
            market = self._last_market
        if market is None:
            raise AssumptionViolated("perform() before any decide(): there is no market to size against")
        self._execute(decision, market)

    def step(self, t: int) -> Decision | None:
        """One decision at time `t`, acted on immediately.

        Unchanged in behaviour: `decide` then `perform`, synchronously, before
        returning. Test L1 compares this path against the replay driver byte for
        byte, and the replay driver applies each decision before making the next
        one — so anything that deferred execution here would change the
        observation feeding the next decision and break the comparison.
        """
        decision = self.decide(t)
        if decision is not None:
            self.perform(decision)
        return decision

    def run_until(self, end_ts: int, *, start_ts: int | None = None) -> list[Decision]:
        """Sample on the policy's cadence until the tape or the clock runs out."""
        step = self.params.sample_interval_s
        t = start_ts if start_ts is not None else self.source.head().ts
        while t <= end_ts:
            self.step(t)
            t += step
        return self.decisions

    # --- applying a decision ----------------------------------------------

    def _execute(self, decision: Decision, market: MarketState) -> None:
        position = self.engine.position

        if decision.action is Action.HOLD:
            return
        if decision.action is Action.PULL:
            self.executor.pull(position, market.t)
            self.engine.set_position(apply_decision(position, Action.PULL, market.t))
            return

        liquidity = self._size(decision, market)
        if position.in_market:
            token_id = self.executor.rebalance(
                position, decision.target_lower, decision.target_upper, liquidity, market.t
            )
        else:
            token_id = self.executor.mint(
                decision.target_lower, decision.target_upper, liquidity, market.t
            )
        self.engine.set_position(
            apply_decision(
                position,
                decision.action,
                market.t,
                lower=decision.target_lower,
                upper=decision.target_upper,
                liquidity=liquidity,
                token_id=token_id,
            )
        )

    def _size(self, decision: Decision, market: MarketState) -> int:
        sa = get_sqrt_ratio_at_tick(decision.target_lower)
        sb = get_sqrt_ratio_at_tick(decision.target_upper)
        amount1 = int(self.capital_quote * 10**self.meta.dec1)
        amount0 = int(self.capital_quote * 10**self.meta.dec0)
        wanted = get_liquidity_for_amounts(market.sqrt_price_x96, sa, sb, amount0, amount1)
        cap = int(market.pool_liquidity * self.params.eps_liquidity_share)
        return max(1, min(wanted, cap))
