"""The chain seam: one interface, three ways of satisfying it.

The live agent and the replay engine differ in exactly one thing — where the
market data comes from. Everything above this line is shared, and that is what
lets test L1 assert the two produce byte-identical decisions rather than merely
similar ones.

Three implementations:

- `RpcChainSource` reads a real node (step 13).
- `TapeChainSource` serves a recorded tape as though it were a chain, which is
  what L1 uses to run the *live* driver over history.
- `ForkChainSource` points at an anvil fork (step 10).

The interface is deliberately narrow. It answers "what is true now" and "what
happened since", and nothing else — no "what will happen", no seeking, no
lookahead. A source that could answer more would put the live path's guarantees
below the replay path's, and then L1 would be comparing two different things.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from misquote.core.errors import LookAheadError
from misquote.core.types import Event


@dataclass(frozen=True, slots=True)
class ChainHead:
    """Where the chain is, as far as we are willing to trust it.

    `ts` is the head block's timestamp, and it is the decision clock. Not
    `time.time()` — the layering test forbids a wall clock below the driver
    layer, and the reason is precisely this: live and replay must feed the
    engine the same *kind* of number or L1's comparison means nothing.
    """

    block: int
    ts: int


@runtime_checkable
class ChainSource(Protocol):
    """What a driver may ask the chain."""

    def head(self) -> ChainHead: ...

    def events_since(self, ts: int, until_ts: int) -> Sequence[Event]:
        """Events in `(ts, until_ts]`, in chain order."""
        ...

    def slot0(self) -> tuple[int, int]:
        """`(sqrtPriceX96, tick)` as of the last observed event."""
        ...

    def liquidity(self) -> int: ...

    def gas_price_quote(self) -> float:
        """Cost of one rebalance in token1, at current gas."""
        ...

    def close(self) -> None: ...


class TapeChainSource:
    """A recorded tape, served as though it were a live chain.

    This is what makes L1 possible. The live driver polls a chain; give it a
    source backed by history and it replays that history through the live code
    path, so the two decision sequences can be compared directly. If the live
    driver ever grows a shortcut the replay driver lacks, the comparison breaks.

    The frontier discipline is the tape's, unchanged: `events_since` cannot
    return anything past `until_ts`, and the clock cannot run backwards.
    """

    __slots__ = ("_tape", "_ts", "_sqrt_price", "_tick", "_liquidity", "_gas_quote", "_block")

    def __init__(self, tape, *, gas_quote: float = 0.5) -> None:
        self._tape = tape
        self._ts = tape.first_ts or 0
        self._sqrt_price = 0
        self._tick = 0
        self._liquidity = 0
        self._gas_quote = gas_quote
        self._block = 0

    def advance(self, ts: int) -> None:
        """Move the simulated head. The driver's own clock drives this."""
        if ts < self._ts:
            raise LookAheadError(f"chain head moved backwards: {self._ts} -> {ts}")
        self._ts = ts

    def head(self) -> ChainHead:
        return ChainHead(block=self._block, ts=self._ts)

    def events_since(self, ts: int, until_ts: int) -> Sequence[Event]:
        events = self._tape.advance_to(until_ts)
        if events:
            last = events[-1]
            self._sqrt_price = last.sqrt_price_x96
            self._tick = last.tick
            self._liquidity = last.liquidity
            self._block = last.block
        return events

    def slot0(self) -> tuple[int, int]:
        return self._sqrt_price, self._tick

    def liquidity(self) -> int:
        return self._liquidity

    def gas_price_quote(self) -> float:
        return self._gas_quote

    def close(self) -> None:
        self._tape.close()

    @property
    def first_ts(self) -> int | None:
        return self._tape.first_ts

    @property
    def last_ts(self) -> int | None:
        return self._tape.last_ts
