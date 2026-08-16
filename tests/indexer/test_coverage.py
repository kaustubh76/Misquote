"""What was read, as distinct from what was found.

`check_tape` measured the tape as `(max(ts) - min(ts)) / 86400` and passed the
readiness gate at 25 days. That measures the distance between the two ends of the
tape and says nothing at all about the middle, so a database holding one day at
each end of a twenty-six day span reported "spanning 26.0 days" and went green.
Every interrupted backfill produces exactly that shape, and so does the tail:
it primes by putting the cursor at the head with nothing underneath it.

No query over `swap` can find that hole, because a five-thousand-block window
with no swaps in it and a window nobody ever fetched are the same empty list.
The distinction has to be recorded when the read happens or it is gone.
"""

from __future__ import annotations

import pytest

from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import Event, PoolMeta
from misquote.indexer import store

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


def event(block: int, ts: int | None = None) -> Event:
    return Event(
        block=block,
        log_index=0,
        ts=ts if ts is not None else 1_700_000_000 + block,
        kind="swap",
        tx=f"0x{block:064x}",
        amount0=-(10**20),
        amount1=10**20,
        sqrt_price_x96=get_sqrt_ratio_at_tick(-64180),
        liquidity=10**24,
        tick=-64180,
    )


@pytest.fixture
def conn():
    connection = store.connect(":memory:")
    store.register_pool(connection, META)
    yield connection
    connection.close()


def read(conn, lo: int, hi: int, events=()) -> None:
    """One chunk fetched, whatever it happened to contain."""
    store.write_events(conn, POOL, list(events), advance_cursor_to=hi, covered=(lo, hi), now_ts=0)


# --- the one that matters ---------------------------------------------------


def test_a_quiet_range_and_an_unread_range_stop_looking_alike(conn) -> None:
    """The distinction the swap table cannot express, and the whole reason this
    exists. Both ranges hold zero swaps; only one of them was looked at."""
    read(conn, 1_000, 1_999)  # fetched, genuinely nothing traded
    # 2,000..2,999 never fetched at all

    assert store.gaps(conn, POOL, 1_000, 2_999) == [(2_000, 2_999)]


def test_the_hole_that_passed_the_readiness_gate_is_now_visible(conn) -> None:
    """A day at each end of a twenty-six day span. `max(ts) - min(ts)` calls that
    twenty-six days of history; the longest run of blocks actually read is one."""
    day = 86_400
    read(conn, 1_000, 1_999, [event(1_000, ts=0), event(1_999, ts=day)])
    read(conn, 100_000, 100_999, [event(100_000, ts=25 * day), event(100_999, ts=26 * day)])

    summary = store.tape_summary(conn, POOL)
    old_measure = (summary["last_ts"] - summary["first_ts"]) / day
    assert old_measure == 26.0, "the gate's measure; kept here as the contrast"

    longest = store.covered_span(conn, POOL)
    assert longest == (1_000, 1_999) or longest == (100_000, 100_999)
    assert store.gaps(conn, POOL, 1_000, 100_999) == [(2_000, 99_999)]


def test_an_unrecorded_database_reports_unknown_rather_than_complete(conn) -> None:
    """Databases written before this existed hold real events and no record of
    what was fetched to find them. The badge's rule applies: unknown does not
    become pass."""
    store.write_events(conn, POOL, [event(1_500)], advance_cursor_to=1_999, now_ts=0)

    assert store.coverage(conn, POOL) == []
    assert store.covered_span(conn, POOL) is None
    assert store.gaps(conn, POOL, 1_000, 1_999) == [(1_000, 1_999)]


# --- merging ----------------------------------------------------------------


def test_adjacent_chunks_are_one_run_not_two(conn) -> None:
    """Otherwise every chunk boundary reads as a one-block hole and the gaps
    report is noise nobody can act on."""
    read(conn, 1_000, 1_999)
    read(conn, 2_000, 2_999)

    assert store.coverage(conn, POOL) == [(1_000, 2_999)]
    assert store.gaps(conn, POOL, 1_000, 2_999) == []


def test_overlapping_chunks_merge(conn) -> None:
    read(conn, 1_000, 1_999)
    read(conn, 1_500, 2_499)

    assert store.coverage(conn, POOL) == [(1_000, 2_499)]


def test_a_gap_filled_later_closes(conn) -> None:
    """Re-running a backfill over the hole is meant to fix it, and the record has
    to agree that it did."""
    read(conn, 1_000, 1_999)
    read(conn, 3_000, 3_999)
    assert store.gaps(conn, POOL, 1_000, 3_999) == [(2_000, 2_999)]

    read(conn, 2_000, 2_999)
    assert store.gaps(conn, POOL, 1_000, 3_999) == []
    assert store.coverage(conn, POOL) == [(1_000, 3_999)]


def test_re_reading_the_same_range_changes_nothing(conn) -> None:
    read(conn, 1_000, 1_999)
    read(conn, 1_000, 1_999)

    assert store.coverage(conn, POOL) == [(1_000, 1_999)]


def test_gaps_are_clipped_to_the_window_asked_about(conn) -> None:
    read(conn, 1_000, 1_999)

    assert store.gaps(conn, POOL, 500, 2_500) == [(500, 999), (2_000, 2_500)]
    assert store.gaps(conn, POOL, 1_200, 1_400) == []


# --- the tail must not certify what it never read ---------------------------


def test_priming_records_no_coverage(conn) -> None:
    """The tail's first poll moves the cursor to the head without reading a
    block. That call is the act that *creates* the hole; recording coverage for
    it would have the tail certify a tape it has never looked at."""
    from misquote.indexer.follow import Tail

    class Reader:
        def safe_head(self) -> int:
            return 116_000_000

        def events(self, *_a):  # pragma: no cover — priming must not call this
            raise AssertionError("a priming poll fetched logs")

    tail = Tail(conn, Reader(), POOL)
    assert tail.poll_once()["primed"] == 1

    assert store.cursor_for(conn, POOL) == 116_000_000
    assert store.coverage(conn, POOL) == [], "the tail certified blocks it never read"


def test_a_real_poll_does_record_it(conn) -> None:
    """The other half, so the test above cannot pass by coverage never working."""
    from misquote.indexer.follow import Tail

    class Reader:
        def __init__(self) -> None:
            self.head = 116_000_000

        def safe_head(self) -> int:
            return self.head

        def events(self, _pool, start, end):
            return [event(start)]

    reader = Reader()
    tail = Tail(conn, reader, POOL, chunk=1_000)
    tail.poll_once()
    reader.head += 1_000
    tail.poll_once()

    assert store.coverage(conn, POOL) == [(116_000_001, 116_001_000)]


# --- reorg ------------------------------------------------------------------


def test_a_rewind_retreats_coverage_with_the_rows(conn) -> None:
    """Rewinding deletes rows. Coverage that stayed put would claim we hold
    blocks the same call just removed — a hole reported as covered by the one
    mechanism built to find holes."""
    read(conn, 1_000, 1_999, [event(1_500)])
    store.rewind(conn, POOL, 1_400)

    assert store.coverage(conn, POOL) == [(1_000, 1_400)]


def test_a_rewind_past_a_whole_run_drops_it(conn) -> None:
    read(conn, 1_000, 1_999)
    read(conn, 3_000, 3_999)
    store.rewind(conn, POOL, 2_500)

    assert store.coverage(conn, POOL) == [(1_000, 1_999)]
