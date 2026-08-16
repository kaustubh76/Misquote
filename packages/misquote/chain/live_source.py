"""A real pool, served through the `ChainSource` protocol.

The protocol's other implementation, `TapeChainSource` in `chain/source.py`,
serves recorded history — that is what makes test L1 possible, and for a long
time it was the only one. The "live" agent therefore had no way to read a live
chain: the loop, the action queue, the journal and the kill file all existed
with nothing underneath them, which is why every journal in this repo has zero
rows and every card reports its provenance journal empty.

This is the half that reads a node.

## The constraint is rate, not correctness

Reading a pool is easy. Reading it *often enough* is the whole problem, and it is
worth stating with the measurement rather than as a caveat.

Free BSC endpoints do not cap the block range so much as the request rate. A
probe against the target pool asking for 2,000-block windows — a fifteen-minute
slice of chain, nothing like a backfill — succeeded four times and then failed
with `-32005 limit exceeded` **eleven seconds in**, having rotated through all
three endpoints. Range size was never the issue: `eth_getLogs` is simply
expensive and the quota is small.

Spec section 8 sets the sampling interval at **Δs = 5 seconds**. A source that
called `eth_getLogs` on every sample would issue twelve per minute and die in the
first minute of any run. So this class separates two clocks that the tape source
never had to distinguish:

- **the decision clock**, which ticks at Δs and drives the policy;
- **the poll clock**, which is how often we are allowed to ask the chain anything.

Between polls, `events_since` returns nothing and `head()` returns the last head
actually observed. That is not a simulation of freshness — it is the honest
statement that we have not looked. The engine handles an empty event batch
correctly, and `set_decision_time` permits time to stand still; what it forbids
is time moving backwards, and this never does.

**The deviation this forces is recorded, not hidden.** Sampling the *chain* every
`poll_seconds` rather than every 5 seconds means section 3.4's "m consecutive
samples" spans `m x poll_seconds` of wall time instead of `m x 5`. With the
defaults that is three minutes rather than fifteen seconds. The toxicity rule
therefore reacts more slowly here than the frozen spec describes, and the reason
is an endpoint quota rather than a design choice. Published as matrix item D-9.

## What it will not do

It will not invent a timestamp between polls, will not extrapolate a price, and
will not report a head it has not read. A source that filled the gaps would make
the agent look responsive while feeding it fiction, and a replay of that journal
would be a replay of the fiction.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from web3 import Web3

from misquote.chain.source import ChainHead
from misquote.core.types import Event, PoolMeta
from misquote.indexer.reader import BscReader

# One recentre is a burn, a collect and a mint through the NonfungiblePositionManager.
# Measured on the BSC fork in `tests/chain/test_position_lifecycle.py`, rounded up:
# a mint alone runs a little over 400k, and the burn/collect legs add the rest.
# It is an estimate and it is used only to price gas, never to set a gas limit —
# a wrong limit would revert a transaction, a wrong estimate only misprices R2.
REBALANCE_GAS_UNITS = 600_000

# How often we are willing to ask the chain for logs. Chosen from the measurement
# in the module docstring, not from taste: four requests in eleven seconds
# exhausted every free endpoint we have, and BSC produces 2,000 blocks in about
# fifteen minutes, so one poll a minute is both survivable and far faster than
# the chain moves.
DEFAULT_POLL_SECONDS = 60.0

SLOT0_ABI = [
    {
        "name": "slot0",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {"type": "uint160"},
            {"type": "int24"},
            {"type": "uint16"},
            {"type": "uint16"},
            {"type": "uint16"},
            {"type": "uint32"},
            {"type": "bool"},
        ],
    },
    {
        "name": "liquidity",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint128"}],
    },
]


class LiveChainSource:
    """The `ChainSource` a running agent reads, backed by a real pool.

    Deliberately the same interface `TapeChainSource` implements, so the live
    loop is the same code path test L1 compares against the replay driver. If
    this class grew a method the tape source lacks, that comparison would stop
    meaning anything.
    """

    __slots__ = (
        "meta",
        "reader",
        "poll_seconds",
        "_pool",
        "_cursor",
        "_head",
        "_sqrt_price",
        "_tick",
        "_liquidity",
        "_gas_quote",
        "_last_poll",
        "_last_head_poll",
        "polls",
        "poll_failures",
        "events_seen",
    )

    def __init__(
        self,
        meta: PoolMeta,
        reader: BscReader,
        *,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        start_block: int | None = None,
        clock=time.monotonic,
    ) -> None:
        del clock  # the poll clock is monotonic by construction; see `_due`
        self.meta = meta
        self.reader = reader
        self.poll_seconds = poll_seconds
        self._pool = Web3.to_checksum_address(meta.address)
        self._cursor = start_block
        self._head: ChainHead | None = None
        self._sqrt_price = 0
        self._tick = 0
        self._liquidity = 0
        self._gas_quote = 0.0
        self._last_poll = 0.0
        self._last_head_poll = 0.0
        self.polls = 0
        self.poll_failures = 0
        self.events_seen = 0

    # --- startup -----------------------------------------------------------

    def prime(self) -> None:
        """Read the pool's current state once, before any event has arrived.

        Without this the source reports `sqrtPriceX96 == 0` until the first swap
        lands in a polled window, and `WardenLive.step` correctly refuses to
        decide on that — so a fresh agent would sit idle for as long as the pool
        was quiet, looking broken rather than patient. Two `eth_call`s.
        """
        contract = self.reader.w3.eth.contract(address=self._pool, abi=SLOT0_ABI)
        slot0 = contract.functions.slot0().call()
        self._sqrt_price = int(slot0[0])
        self._tick = int(slot0[1])
        self._liquidity = int(contract.functions.liquidity().call())

        head_block = self.reader.safe_head()
        self._head = ChainHead(block=head_block, ts=self.reader.block_timestamp(head_block))
        if self._cursor is None:
            self._cursor = head_block
        self._refresh_gas()

    # --- the protocol ------------------------------------------------------

    def head(self) -> ChainHead:
        """Where the chain was when we last looked.

        Refreshed on the poll clock, and **not** interpolated in between. A head
        whose timestamp advanced without anyone reading a block would be a wall
        clock wearing a chain's clothes, and the layering test forbids that below
        the driver for exactly this reason: live and replay must feed the engine
        the same kind of number.
        """
        if self._head is None:
            self.prime()
        if self._due(self._last_head_poll):
            try:
                block = self.reader.safe_head()
                if self._head is None or block > self._head.block:
                    self._head = ChainHead(block=block, ts=self.reader.block_timestamp(block))
            except Exception:  # noqa: BLE001 — a read failure is not a reason to stop
                self.poll_failures += 1
            self._last_head_poll = time.monotonic()
        return self._head

    def events_since(self, ts: int, until_ts: int) -> Sequence[Event]:
        """New events, or nothing at all if it is not yet time to ask.

        `ts` is ignored, as it is by the tape source: the cursor is the frontier,
        and it advances only when a poll succeeds. Returning an empty batch is
        the truthful answer to "what has happened since we last looked" when the
        answer is "we have not looked".
        """
        del ts, until_ts
        if self._head is None:
            self.prime()
        if not self._due(self._last_poll):
            return ()

        # Refresh the head *here* rather than relying on the caller to have asked
        # for it first. `WardenLoop` happens to call `head()` before every step,
        # so this worked by coincidence; a caller that did not would have polled
        # forever against the block observed at prime and returned nothing while
        # reporting no failures. Both clocks are still gated independently, so
        # this adds no requests beyond the ones `head()` was already allowed.
        self.head()

        self._last_poll = time.monotonic()
        target = self._head.block if self._head else 0
        if self._cursor is None or target <= self._cursor:
            return ()

        try:
            events = self.reader.events(self._pool, self._cursor + 1, target)
        except Exception:  # noqa: BLE001 — a refused poll is a quiet poll, not a crash
            self.poll_failures += 1
            return ()

        self.polls += 1
        self._cursor = target
        if events:
            last = events[-1]
            self._sqrt_price = last.sqrt_price_x96
            self._tick = last.tick
            self._liquidity = last.liquidity
            self.events_seen += len(events)
        return events

    def slot0(self) -> tuple[int, int]:
        return self._sqrt_price, self._tick

    def liquidity(self) -> int:
        return self._liquidity

    def gas_price_quote(self) -> float:
        """What one recentre costs, in token1.

        Only meaningful when token1 is the chain's native wrapper — on the target
        pool it is WBNB, so gas priced in BNB is already in token1 and no
        conversion is involved. On a pool whose token1 is something else this
        would need the BNB/token1 price, and rather than invent one it returns
        the last figure it could justify.
        """
        if self._due(self._last_poll, factor=10.0):
            self._refresh_gas()
        return self._gas_quote

    def close(self) -> None:
        """Nothing to release. Present because the protocol has it."""

    # --- internals ---------------------------------------------------------

    def _due(self, last: float, *, factor: float = 1.0) -> bool:
        return (time.monotonic() - last) >= self.poll_seconds * factor

    def _refresh_gas(self) -> None:
        try:
            wei = int(self.reader.w3.eth.gas_price)
        except Exception:  # noqa: BLE001
            self.poll_failures += 1
            return
        self._gas_quote = REBALANCE_GAS_UNITS * wei / 1e18

    @property
    def cursor(self) -> int | None:
        return self._cursor

    def status(self) -> dict:
        """What the source has actually done, for the journal.

        A run whose polls all failed and a run that found a quiet pool look
        identical from the decisions alone. These counters are what tells them
        apart afterwards.
        """
        return {
            "polls": self.polls,
            "poll_failures": self.poll_failures,
            "events_seen": self.events_seen,
            "cursor": self._cursor,
            "head_block": self._head.block if self._head else None,
            "head_ts": self._head.ts if self._head else None,
            "poll_seconds": self.poll_seconds,
        }
