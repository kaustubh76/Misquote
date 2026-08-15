"""The live chain source, and the two clocks it has to keep apart.

Until this existed the only `ChainSource` was the tape, so the "live" agent had
never read a live chain. The hard part is not correctness but *rate*: free BSC
endpoints refuse roughly four `eth_getLogs` in eleven seconds, and spec section 8
asks the policy to sample every five.

So the decision clock and the poll clock are separate, and these tests pin the
consequences — most importantly that the source never invents what it has not
read.
"""

from __future__ import annotations

import pytest

from misquote.chain.live_source import REBALANCE_GAS_UNITS, LiveChainSource
from misquote.chain.source import ChainHead, ChainSource
from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import Event, PoolMeta

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


class FakeClock:
    """A monotonic clock the test drives, so nothing here sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def event(block: int, tick: int, ts: int) -> Event:
    return Event(
        block=block,
        log_index=0,
        ts=ts,
        kind="swap",
        tx=f"0x{block:064x}",
        amount0=-(10**20),
        amount1=10**20,
        sqrt_price_x96=get_sqrt_ratio_at_tick(tick),
        liquidity=10**24,
        tick=tick,
    )


class FakeReader:
    """A `BscReader` shaped stub that counts what was asked of it."""

    def __init__(self, *, head: int = 1000, fail_logs: bool = False) -> None:
        self._head = head
        self.fail_logs = fail_logs
        self.log_calls: list[tuple[int, int]] = []
        self.head_calls = 0
        self.w3 = _FakeW3()

    def safe_head(self) -> int:
        self.head_calls += 1
        return self._head

    def block_timestamp(self, number: int) -> int:
        return 1_700_000_000 + number

    def events(self, pool, start, end):
        self.log_calls.append((start, end))
        if self.fail_logs:
            raise RuntimeError("-32005 limit exceeded")
        return [event(end, -64180, 1_700_000_000 + end)]

    def advance_head(self, blocks: int) -> None:
        self._head += blocks


class _FakeW3:
    class _Eth:
        gas_price = 3_000_000_000  # 3 gwei, BSC's floor for years

        def contract(self, address, abi):
            return _FakeContract()

    eth = _Eth()

    @staticmethod
    def to_checksum_address(value):
        return value


class _FakeContract:
    class _Fn:
        def __init__(self, value):
            self._value = value

        def call(self):
            return self._value

    class functions:  # noqa: N801 — mirrors web3's own shape
        @staticmethod
        def slot0():
            return _FakeContract._Fn((get_sqrt_ratio_at_tick(-64180), -64180, 0, 0, 0, 3400, True))

        @staticmethod
        def liquidity():
            return _FakeContract._Fn(10**24)


def source(reader, clock, **kw):
    live = LiveChainSource(META, reader, poll_seconds=60.0, **kw)
    # The module reads `time.monotonic` directly; patching it per-instance would
    # be a lie about how it runs. Tests drive it through monkeypatch instead.
    return live


# --- the protocol -----------------------------------------------------------


def test_it_satisfies_the_same_protocol_the_tape_source_does() -> None:
    """If this grew a method the tape lacks, test L1's comparison between the
    live and replay paths would stop meaning anything."""
    live = LiveChainSource(META, FakeReader())
    assert isinstance(live, ChainSource)


def test_priming_reads_the_pool_so_a_quiet_start_is_not_a_dead_one() -> None:
    """`WardenLive.step` returns None while sqrtPrice is zero, so without this a
    fresh agent sits idle for as long as the pool is quiet and looks broken."""
    reader = FakeReader(head=5000)
    live = LiveChainSource(META, reader)
    assert live.slot0() == (0, 0)

    live.prime()
    sqrt_price, tick = live.slot0()
    assert tick == -64180
    assert sqrt_price == get_sqrt_ratio_at_tick(-64180)
    assert live.liquidity() == 10**24
    assert live.cursor == 5000, "a tail must start at the head, not at genesis"


# --- the two clocks ---------------------------------------------------------


def test_it_does_not_ask_the_chain_more_often_than_the_poll_interval(monkeypatch) -> None:
    """The measurement this exists for: ~4 getLogs in 11s exhausts every free
    endpoint. At the spec's 5s cadence that is twelve a minute."""
    clock = FakeClock()
    monkeypatch.setattr("misquote.chain.live_source.time.monotonic", clock)

    reader = FakeReader(head=5000)
    live = LiveChainSource(META, reader, poll_seconds=60.0)
    live.prime()
    before = len(reader.log_calls)

    # Twelve decision ticks at the spec's 5s cadence — one minute of policy.
    for _ in range(12):
        clock.advance(5.0)
        reader.advance_head(10)
        live.events_since(0, 0)

    assert len(reader.log_calls) - before <= 1, (
        f"{len(reader.log_calls) - before} getLogs in one minute — this is the "
        "rate that gets refused"
    )


def test_between_polls_it_reports_nothing_rather_than_guessing(monkeypatch) -> None:
    clock = FakeClock()
    monkeypatch.setattr("misquote.chain.live_source.time.monotonic", clock)

    reader = FakeReader(head=5000)
    live = LiveChainSource(META, reader, poll_seconds=60.0)
    live.prime()

    # The first call polls: the agent has just started and wants data now, not
    # a minute from now. That is the contract, so establish it rather than
    # assume the interval applies before anything has been read.
    reader.advance_head(100)
    assert len(live.events_since(0, 0)) == 1

    # Now the interval governs. Three decision ticks inside one poll window must
    # all report nothing rather than re-serving or re-fetching.
    for _ in range(3):
        clock.advance(5.0)
        reader.advance_head(100)
        assert live.events_since(0, 0) == (), "returned events without asking the chain"

    clock.advance(120.0)
    assert len(live.events_since(0, 0)) == 1, "never polled even after the interval"


def test_the_head_timestamp_is_never_interpolated(monkeypatch) -> None:
    """A head whose timestamp advanced without anyone reading a block is a wall
    clock wearing a chain's clothes, and the layering test forbids one here."""
    clock = FakeClock()
    monkeypatch.setattr("misquote.chain.live_source.time.monotonic", clock)

    reader = FakeReader(head=5000)
    live = LiveChainSource(META, reader, poll_seconds=60.0)
    live.prime()
    first = live.head()

    clock.advance(30.0)
    reader.advance_head(70)
    assert live.head() == first, "the head moved without a read"

    clock.advance(40.0)
    moved = live.head()
    assert moved.block == 5070
    assert moved.ts > first.ts


def test_the_head_never_moves_backwards(monkeypatch) -> None:
    """`set_decision_time` raises on a backwards clock, which would end the run."""
    clock = FakeClock()
    monkeypatch.setattr("misquote.chain.live_source.time.monotonic", clock)

    reader = FakeReader(head=5000)
    live = LiveChainSource(META, reader, poll_seconds=1.0)
    live.prime()
    first = live.head()

    reader._head = 4000  # an endpoint behind the others, which does happen
    clock.advance(10.0)
    assert live.head().block >= first.block


# --- failure is quiet, not fatal -------------------------------------------


def test_a_refused_poll_is_counted_and_does_not_raise(monkeypatch) -> None:
    """`-32005` mid-run must not end an unattended agent, and must not silently
    advance the cursor past blocks nobody read."""
    clock = FakeClock()
    monkeypatch.setattr("misquote.chain.live_source.time.monotonic", clock)

    reader = FakeReader(head=5000, fail_logs=True)
    live = LiveChainSource(META, reader, poll_seconds=60.0)
    live.prime()
    cursor = live.cursor

    clock.advance(120.0)
    reader.advance_head(100)
    assert live.events_since(0, 0) == ()
    assert live.poll_failures >= 1
    assert live.cursor == cursor, "cursor advanced past a range that was never read"


def test_status_distinguishes_a_quiet_pool_from_a_broken_one() -> None:
    """From the decisions alone the two are identical, which is how a run of
    nothing gets published as a run of holds."""
    live = LiveChainSource(META, FakeReader(head=5000))
    live.prime()
    status = live.status()
    assert set(status) >= {"polls", "poll_failures", "events_seen", "cursor", "poll_seconds"}
    assert status["cursor"] == 5000


def test_gas_is_priced_from_chain_not_from_a_constant() -> None:
    live = LiveChainSource(META, FakeReader(head=5000))
    live.prime()
    expected = REBALANCE_GAS_UNITS * 3_000_000_000 / 1e18
    assert live.gas_price_quote() == pytest.approx(expected)
    assert 0.0 < live.gas_price_quote() < 0.1, "a recentre should not cost a whole BNB"


def test_head_returns_a_chain_head_not_a_tuple() -> None:
    live = LiveChainSource(META, FakeReader(head=5000))
    assert isinstance(live.head(), ChainHead)
