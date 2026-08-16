"""The live tail, and the one mistake that would make it a backfill.

The backfill and the tail are the same read against the same endpoints, and only
one of them works without a paid key. Measured against the target pool in
2,000-block windows: four requests in eleven seconds exhausts all three free
endpoints with `-32005`, while one request per sixty seconds ran six for six with
no rotations at all.

So the tail exists to stay near the head *without ever being refused*, and the
failure that would destroy it is subtle: start with no cursor, decide that means
"start at the beginning", and quietly issue a two-day backfill at a rate designed
for one request a minute. The first test below is the one that matters.
"""

from __future__ import annotations

import pytest

from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import Event, PoolMeta
from misquote.indexer import store
from misquote.indexer.follow import DEFAULT_POLL_SECONDS, Tail, follow

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


def event(block: int, log_index: int = 0) -> Event:
    return Event(
        block=block,
        log_index=log_index,
        ts=1_700_000_000 + block,
        kind="swap",
        tx=f"0x{block:063x}{log_index:01x}",
        amount0=-(10**20),
        amount1=10**20,
        sqrt_price_x96=get_sqrt_ratio_at_tick(-64180),
        liquidity=10**24,
        tick=-64180,
    )


class FakeReader:
    """Counts every range it is asked for, so a burst is visible in the test."""

    def __init__(self, head: int = 10_000, *, fail: bool = False) -> None:
        self._head = head
        self.fail = fail
        self.ranges: list[tuple[int, int]] = []

    def safe_head(self) -> int:
        return self._head

    def events(self, pool, start, end):
        self.ranges.append((start, end))
        if self.fail:
            raise RuntimeError("-32005 limit exceeded")
        return [event(b) for b in range(start, min(end, start + 2) + 1)]

    def advance(self, blocks: int) -> None:
        self._head += blocks

    @property
    def widest(self) -> int:
        return max((end - start + 1 for start, end in self.ranges), default=0)


@pytest.fixture
def conn():
    connection = store.connect(":memory:")
    store.register_pool(connection, META)
    yield connection
    connection.close()


# --- the one that matters ---------------------------------------------------


def test_an_empty_database_primes_at_the_head_rather_than_at_genesis(conn) -> None:
    """A tail must not silently become a backfill.

    With no cursor, "start at the beginning" would mean walking 116 million
    blocks at one request a minute — 220 years — while looking like it was
    working. It starts at the head instead, and records that it did.
    """
    reader = FakeReader(head=116_000_000)
    tail = Tail(conn, reader, POOL)
    assert tail.cursor() is None

    result = tail.poll_once()
    assert result["primed"] == 1
    assert tail.cursor() == 116_000_000
    assert reader.ranges == [], "a priming poll must not fetch any logs"


def test_it_never_asks_for_more_than_one_chunk_however_far_behind(conn) -> None:
    """Catching up happens across polls, not in one burst — the burst is the
    thing that gets refused."""
    reader = FakeReader(head=10_000)
    tail = Tail(conn, reader, POOL, chunk=500)
    tail.poll_once()  # prime at 10,000

    reader.advance(50_000)  # gone for a while
    for _ in range(3):
        tail.poll_once()

    assert reader.widest <= 500, f"asked for {reader.widest} blocks in one request"
    assert tail.behind() > 0, "it should still be catching up, one chunk at a time"


# --- the cursor -------------------------------------------------------------


def test_the_cursor_advances_with_the_rows(conn) -> None:
    """Same transaction, so a crash between them cannot leave a gap nothing
    downstream can detect."""
    reader = FakeReader(head=1_000)
    tail = Tail(conn, reader, POOL, chunk=100)
    tail.poll_once()  # prime at 1,000

    reader.advance(50)
    tail.poll_once()

    assert tail.cursor() == 1_050
    assert tail.seen > 0
    assert store.cursor_for(conn, POOL) == 1_050


def test_a_refused_poll_leaves_the_cursor_where_it_was(conn) -> None:
    """Advancing past blocks nobody read is how a tape acquires a silent hole."""
    reader = FakeReader(head=1_000)
    tail = Tail(conn, reader, POOL, chunk=100)
    tail.poll_once()

    reader.fail = True
    reader.advance(100)
    tail.poll_once()

    assert tail.cursor() == 1_000, "cursor moved past a range that was never read"
    assert tail.refused == 1
    assert tail.polls == 0, "a refused poll is not a poll"


def test_it_resumes_from_the_cursor_rather_than_re_priming(conn) -> None:
    """Stop it and start it again a day later; it picks up where it stopped."""
    reader = FakeReader(head=1_000)
    Tail(conn, reader, POOL, chunk=100).poll_once()  # primes at 1,000

    reader.advance(200)
    resumed = Tail(conn, reader, POOL, chunk=100)
    assert resumed.cursor() == 1_000

    result = resumed.poll_once()
    assert result["from"] == 1_001, "re-primed instead of resuming"
    assert resumed.cursor() == 1_100


def test_nothing_new_is_not_an_error(conn) -> None:
    reader = FakeReader(head=1_000)
    tail = Tail(conn, reader, POOL, chunk=100)
    tail.poll_once()

    result = tail.poll_once()  # head has not moved
    assert result["events"] == 0
    assert tail.refused == 0
    assert reader.ranges == []


def test_writing_the_same_range_twice_inserts_nothing_new(conn) -> None:
    """Idempotence, which is what makes "if a run dies, run it again" true.

    Tested against `write_events` directly rather than by rewinding the cursor:
    `store.rewind` is reorg recovery and *deletes* the rows above its block, so
    re-inserting them afterwards is correct behaviour rather than a bug. Using it
    here would have made this test claim the opposite of what it checks.
    """
    events = [event(b) for b in (1_001, 1_002, 1_003)]
    first = store.write_events(conn, POOL, events, advance_cursor_to=1_050, now_ts=0)
    assert first == 3

    again = store.write_events(conn, POOL, events, advance_cursor_to=1_050, now_ts=0)
    assert again == 0, "re-fetching an already-ingested range inserted rows twice"


def test_a_reorg_rewind_really_does_drop_the_rows(conn) -> None:
    """The other half of the same story, so the previous test's exemption is not
    taken on trust: rewinding is destructive, and that is its whole job."""
    store.write_events(
        conn, POOL, [event(b) for b in (1_001, 1_002)], advance_cursor_to=1_002, now_ts=0
    )
    removed = store.rewind(conn, POOL, 1_000)
    assert removed == 2
    assert store.cursor_for(conn, POOL) == 1_000


# --- the loop ---------------------------------------------------------------


def test_the_kill_file_stops_it(conn, tmp_path) -> None:
    """A tail that ignored the operator's stop would keep hammering an endpoint
    after someone had said stop."""
    kill = tmp_path / "KILL"
    kill.write_text("stop")

    reader = FakeReader(head=1_000)
    result = follow(
        conn, reader, POOL, seconds=30.0, poll_seconds=0.01, kill_file=kill, progress=False
    )
    assert result["polls"] == 0
    assert reader.ranges == []


def test_a_zero_second_deadline_still_honours_the_kill_file(conn, tmp_path) -> None:
    """`--seconds 0` means 'until killed', and must not mean 'forever'."""
    kill = tmp_path / "KILL"
    kill.write_text("stop")
    result = follow(
        conn,
        reader := FakeReader(head=1_000),
        POOL,
        seconds=0.0,
        poll_seconds=0.01,
        kill_file=kill,
        progress=False,
    )
    assert result["polls"] == 0
    assert reader.ranges == []


def test_the_default_poll_rate_is_the_one_that_was_measured() -> None:
    """One request a minute sustained 6 of 6; roughly four in eleven seconds was
    refused by every endpoint. The default has to be the first of those."""
    assert DEFAULT_POLL_SECONDS >= 60.0


# --- a tail that cannot say it is failing -----------------------------------


def test_a_refused_tail_reports_it_rather_than_looking_quiet(conn, capsys) -> None:
    """The defect a real run found: an empty log meant nothing at all.

    `follow` used to print only when a poll returned events, so a tail refused on
    every request produced no output — identical to a tail working perfectly on a
    pool nobody was trading. It ran for thirty-five minutes, wrote a zero-byte
    log, and advanced not one block.
    """
    reader = FakeReader(head=10_000)
    Tail(conn, reader, POOL).poll_once()  # prime, so the next poll actually fetches
    reader.fail = True
    reader.advance(5_000)

    result = follow(
        conn, reader, POOL, seconds=0.2, poll_seconds=0.01, kill_file="/nonexistent", progress=True
    )
    printed = capsys.readouterr().out

    assert result["refused"] >= 1
    assert result["polls"] == 0
    assert "REFUSED" in printed, "a tail that is failing must say so"


def test_refusals_back_off_instead_of_hammering(conn) -> None:
    """The endpoints are shared, and the quota refills with time rather than with
    persistence. Retrying at full rate spends the whole budget being told no."""
    reader = FakeReader(head=10_000)
    Tail(conn, reader, POOL).poll_once()  # prime
    reader.fail = True
    reader.advance(5_000)

    result = follow(
        conn, reader, POOL, seconds=0.3, poll_seconds=0.01, kill_file="/nonexistent", progress=False
    )
    # With backoff the interval doubles each time, so a 0.3s window admits far
    # fewer attempts than 0.3 / 0.01 = 30.
    assert result["refused"] < 12, f"{result['refused']} attempts — it is not backing off"
    assert result["consecutive_refusals"] == result["refused"]
