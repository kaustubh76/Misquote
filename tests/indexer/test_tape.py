"""The tape's guarantees: idempotence, ordering, and no silent truncation.

The whole indexer exists to make one sentence true — *re-running a backfill is a
no-op* — because that is what turns crash recovery into "run it again" and lets
a judge rebuild the tape from scratch and get the same file.

These run offline against a temporary database. The decoder's agreement with
real chain data is checked separately under the `chainfork` marker.
"""

from __future__ import annotations

import dataclasses
import sqlite3

import pytest

from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import Event, PoolMeta
from misquote.indexer import store
from misquote.indexer.reader import (
    TOPIC_BURN,
    TOPIC_MINT,
    TOPIC_SWAP,
    is_range_too_large,
    is_transient,
)

POOL = "0x36696169c63e42cd08ce11f5deebbcebae652050"

META = PoolMeta(
    address=POOL,
    chain_id=56,
    token0="0x55d398326f99059ff775485246999027b3197955",
    token1="0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
    dec0=18,
    dec1=18,
    fee_pips=500,
    tick_spacing=10,
    fee_protocol=3400,
)


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    c = store.connect(tmp_path / "tape.db")
    store.register_pool(c, META)
    return c


def swap(block: int, log_index: int = 0, tick: int = -64183, ts: int | None = None) -> Event:
    return Event(
        block=block,
        log_index=log_index,
        ts=ts if ts is not None else 1_700_000_000 + block,
        kind="swap",
        tx=f"0x{block:062x}{log_index:02x}",
        amount0=10**18,
        amount1=-(10**18),
        sqrt_price_x96=get_sqrt_ratio_at_tick(tick),
        liquidity=1_275_390_104_039_763_402_054_142,
        tick=tick,
        protocol_fee0=170_000_000_000_000,
        protocol_fee1=0,
    )


# --- the property everything else rests on ---------------------------------


def test_reingesting_the_same_events_inserts_nothing(conn) -> None:
    """`INSERT OR IGNORE` on the chain's own identity for a log.

    Without this, a crash mid-backfill needs a reconciliation step — and a
    reconciliation step is one more thing that can be subtly wrong.
    """
    events = [swap(100 + i) for i in range(20)]

    assert store.write_events(conn, POOL, events, advance_cursor_to=119) == 20
    assert store.write_events(conn, POOL, events, advance_cursor_to=119) == 0
    assert store.write_events(conn, POOL, events[:10], advance_cursor_to=119) == 0

    assert store.tape_summary(conn, POOL)["swaps"] == 20


def test_an_overlapping_refetch_adds_only_what_is_new(conn) -> None:
    """Chunk boundaries overlap after a resume; only the new rows should land."""
    store.write_events(conn, POOL, [swap(b) for b in range(100, 120)], advance_cursor_to=119)
    added = store.write_events(
        conn, POOL, [swap(b) for b in range(110, 130)], advance_cursor_to=129
    )
    assert added == 10
    assert store.tape_summary(conn, POOL)["swaps"] == 30


def test_two_logs_in_one_block_are_distinct_rows(conn) -> None:
    """A busy pool puts several swaps in one block; `log_index` separates them."""
    assert store.write_events(conn, POOL, [swap(500, 0), swap(500, 1), swap(500, 2)]) == 3


# --- uint256 survives the round trip ---------------------------------------


def test_large_values_are_not_truncated_by_sqlite(conn) -> None:
    """SQLite's INTEGER is signed 64-bit and would silently truncate these.

    `sqrtPriceX96` and `liquidity` routinely exceed it, and the failure mode is
    not an error — it is a smaller, entirely plausible number.
    """
    huge = Event(
        block=1,
        log_index=0,
        ts=1_700_000_000,
        kind="swap",
        tx="0x" + "ab" * 32,
        amount0=-(2**200),
        amount1=2**200,
        sqrt_price_x96=(1 << 160) - 1,  # the largest a uint160 can hold
        liquidity=(1 << 128) - 1,
        tick=-64183,
        protocol_fee0=(1 << 128) - 1,
        protocol_fee1=0,
    )
    store.write_events(conn, POOL, [huge])

    got = next(iter(store.read_swaps(conn, POOL)))
    assert got.sqrt_price_x96 == (1 << 160) - 1
    assert got.liquidity == (1 << 128) - 1
    assert got.amount0 == -(2**200)
    assert got.protocol_fee0 == (1 << 128) - 1
    assert 2**63 < got.sqrt_price_x96, "the value genuinely exceeds a signed 64-bit int"


def test_negative_amounts_survive_the_round_trip(conn) -> None:
    """Swap amounts are signed from the pool's perspective; one side is always
    negative, and losing that sign inverts the direction of every trade."""
    store.write_events(conn, POOL, [swap(1)])
    got = next(iter(store.read_swaps(conn, POOL)))
    assert got.amount0 > 0 > got.amount1


# --- ordering and the cursor -----------------------------------------------


def test_swaps_come_back_in_chain_order(conn) -> None:
    """Replay determinism needs a total order, and `(block, log_index)` is it."""
    scrambled = [swap(3, 1), swap(1, 0), swap(2, 5), swap(1, 1), swap(2, 0)]
    store.write_events(conn, POOL, scrambled)

    keys = [e.key for e in store.read_swaps(conn, POOL)]
    assert keys == sorted(keys)
    assert keys == [(1, 0), (1, 1), (2, 0), (2, 5), (3, 1)]


def test_the_cursor_advances_with_the_rows_not_separately(conn) -> None:
    assert store.cursor_for(conn, POOL) is None
    store.write_events(conn, POOL, [swap(b) for b in range(10, 20)], advance_cursor_to=19)
    assert store.cursor_for(conn, POOL) == 19


def test_the_cursor_never_goes_backwards_on_a_reingest(conn) -> None:
    """An out-of-order chunk must not un-claim progress already made."""
    store.write_events(conn, POOL, [swap(b) for b in range(100, 110)], advance_cursor_to=109)
    store.write_events(conn, POOL, [swap(b) for b in range(50, 60)], advance_cursor_to=59)
    assert store.cursor_for(conn, POOL) == 109


def test_a_failed_write_leaves_no_partial_state(conn) -> None:
    """The batch and the cursor move together or not at all.

    Otherwise a crash between them yields a cursor claiming progress the tape
    cannot support — a gap nothing downstream could ever detect.
    """
    store.write_events(conn, POOL, [swap(b) for b in range(100, 110)], advance_cursor_to=109)

    # `tick` is bound to SQLite directly rather than stringified, so an
    # unadaptable value fails partway through the batch — after the first row
    # has been inserted and before the cursor moves.
    broken = [swap(200), dataclasses.replace(swap(201), tick=object())]  # type: ignore[arg-type]
    with pytest.raises(sqlite3.ProgrammingError):
        store.write_events(conn, POOL, broken, advance_cursor_to=209)

    assert store.cursor_for(conn, POOL) == 109
    assert store.tape_summary(conn, POOL)["swaps"] == 10


# --- reorgs ----------------------------------------------------------------


def test_rewinding_drops_the_unsettled_tail_and_the_cursor_with_it(conn) -> None:
    """BSC reorgs are shallow, so discarding and re-fetching the tail is cheaper
    and far less error-prone than working out which events changed."""
    store.write_events(conn, POOL, [swap(b) for b in range(100, 121)], advance_cursor_to=120)

    removed = store.rewind(conn, POOL, 110)
    assert removed == 10
    assert store.cursor_for(conn, POOL) == 110
    assert max(e.block for e in store.read_swaps(conn, POOL)) == 110


def test_rewinding_past_everything_is_harmless(conn) -> None:
    store.write_events(conn, POOL, [swap(b) for b in range(100, 110)], advance_cursor_to=109)
    assert store.rewind(conn, POOL, 999) == 0
    assert store.tape_summary(conn, POOL)["swaps"] == 10


# --- time-bounded reads, which the replay tape depends on ------------------


def test_reads_can_be_bounded_in_time(conn) -> None:
    """`SqliteTape`'s frontier bound is built on this: the query itself refuses
    to return anything after the decision time."""
    store.write_events(conn, POOL, [swap(b, ts=1000 + b) for b in range(0, 100)])

    windowed = list(store.read_swaps(conn, POOL, since_ts=1020, until_ts=1040))
    assert len(windowed) == 21
    assert all(1020 <= e.ts <= 1040 for e in windowed)


# --- the topics, and the retry classifier ----------------------------------


def test_the_swap_topic_is_pancakes_not_uniswaps() -> None:
    """PancakeSwap's Swap event carries two extra protocol-fee fields, so its
    topic differs. Filtering on Uniswap's returns zero logs from a pool doing
    millions in volume, and nothing about that looks like a failure."""
    uniswap_swap = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
    assert TOPIC_SWAP == "0x19b47279256b2a23a1665c810c8d55a1758940ee09377d4f8d26497a3577dc83"
    assert TOPIC_SWAP != uniswap_swap

    for topic in (TOPIC_SWAP, TOPIC_MINT, TOPIC_BURN):
        assert topic.startswith("0x") and len(topic) == 66, "an unprefixed topic matches nothing"
    assert len({TOPIC_SWAP, TOPIC_MINT, TOPIC_BURN}) == 3


@pytest.mark.parametrize(
    "message",
    ["429 Too Many Requests", "502 Bad Gateway", "connection reset", "read timed out"],
)
def test_transient_failures_are_retried(message: str) -> None:
    assert is_transient(Exception(message))


@pytest.mark.parametrize(
    "message",
    ["execution reverted", "invalid opcode", "insufficient funds for gas"],
)
def test_a_revert_is_never_retried(message: str) -> None:
    """Retrying a revert wastes the budget and teaches you to ignore it."""
    assert not is_transient(Exception(message))


def test_a_refused_range_is_recognised_so_the_chunk_can_shrink() -> None:
    """Endpoints say this in prose rather than in a status code, so the backfill
    narrows and retries instead of aborting a multi-hour run."""
    assert is_range_too_large(Exception("query returned more than 10000 results"))
    assert is_range_too_large(Exception("block range is too wide"))
    assert not is_range_too_large(Exception("execution reverted"))
