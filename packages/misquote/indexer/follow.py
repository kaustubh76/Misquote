"""Follow a pool forward from the cursor, at a rate free endpoints tolerate.

    uv run python -m misquote.indexer.follow --seconds 3600
    uv run python -m misquote.indexer.follow --chain 97 --seconds 0   # until killed
    make indexer-follow

The backfill and this are the same read against the same endpoints, and only one
of them works without a paid key. The difference is entirely rate, and it is
worth stating with the measurement rather than as an intuition.

## The measurement

Against the target pool, in 2,000-block windows:

| Cadence | Result |
|---|---|
| ~4 requests in 11 seconds | `-32005 limit exceeded`, all three endpoints exhausted |
| 1 request every 60 seconds | **6 of 6 succeeded, zero endpoint rotations** |

So the endpoints do not object to the *range*; they object to the *rate*. That
single fact separates two things this project had been treating as one blocked
item:

- **A 30-day backfill is 2,880 requests as fast as they will be served.** At the
  rate that actually works, that is two days of wall clock, and any interruption
  restarts the clock rather than the cursor. It needs a keyed endpoint, and that
  remains blocked.
- **A live tail is one request per fifteen minutes of chain.** BSC produces 2,000
  blocks in about fifteen minutes at 0.45 s/block, so polling once a minute is
  fifteen times faster than the chain moves and still an order of magnitude
  inside the quota. That works today, on the free endpoints, with no key.

The consequence is worth being precise about, because it is easy to oversell: we
cannot obtain thirty days of *history* without a key, but we can accumulate real
chain data *going forward* starting now. A tape built this way is real, it is
short, and it gets longer at exactly the speed of real time. Nothing here turns
a two-hour tape into a thirty-day claim.

## Resumability

Identical to the backfill's, because it is the same store: the cursor advances in
the same transaction as the rows, so a crash between them cannot leave a gap that
nothing downstream can detect. Stop this and restart it a day later and it
resumes from the cursor — and if that gap exceeds what one poll can cover, it
walks forward in chunks at the safe rate rather than asking for the lot.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from misquote.chain.addresses import pool_for
from misquote.core.types import PoolMeta
from misquote.indexer import store
from misquote.indexer.backfill import DEFAULT_CHUNK
from misquote.indexer.reader import BscReader, RangeTooLarge, connect_all

# One poll a minute. Chosen from the measurement above, not from taste: it is
# fifteen times faster than the chain produces a chunk and roughly fifteen times
# slower than the rate that gets refused.
DEFAULT_POLL_SECONDS = 60.0

# The operator's stop signal, shared with the agent loop. A tail that ignored it
# would keep hammering an endpoint after someone had said stop.
DEFAULT_KILL_FILE = "ops/KILL"

# The endpoints are a **shared** resource, and not only with other copies of this
# process. An anvil fork proxies every state read to the same public nodes, so
# running the chain-fork test suite can exhaust the quota and leave a tail
# refused for as long as it takes to refill. Backing off is what lets it recover
# instead of spending its whole budget being told no.
BACKOFF_FACTOR = 2.0
MAX_POLL_SECONDS = 15 * 60.0


class Tail:
    """One pool, followed forward. Stateless between polls except for the cursor.

    Deliberately not a subclass or a wrapper of the backfill: the backfill's job
    is to close a known gap as fast as it is allowed, and this one's is to stay
    close to the head without ever being refused. Sharing an implementation would
    mean one of the two rates was wrong.
    """

    __slots__ = ("conn", "reader", "pool", "chunk", "polls", "refused", "inserted", "seen")

    def __init__(self, conn, reader: BscReader, pool: str, *, chunk: int = DEFAULT_CHUNK) -> None:
        self.conn = conn
        self.reader = reader
        self.pool = pool
        self.chunk = chunk
        self.polls = 0
        self.refused = 0
        self.inserted = 0
        self.seen = 0

    def cursor(self) -> int | None:
        return store.cursor_for(self.conn, self.pool)

    def poll_once(self) -> dict[str, int]:
        """Fetch at most one chunk forward. Never more, however far behind we are.

        Catching up on a long absence happens across successive polls rather than
        in one burst, because a burst is the thing that gets refused. The cost is
        that a tail restarted after a week takes a while to arrive; the benefit is
        that it arrives at all.
        """
        head = self.reader.safe_head()
        start = self.cursor()
        if start is None:
            # Nothing recorded yet: begin at the head rather than at genesis.
            # A tail is not a backfill and must not silently become one.
            store.write_events(self.conn, self.pool, [], advance_cursor_to=head, now_ts=_now())
            return {"from": head, "to": head, "events": 0, "inserted": 0, "primed": 1}

        start += 1
        if start > head:
            return {"from": start, "to": head, "events": 0, "inserted": 0, "primed": 0}

        end = min(start + self.chunk - 1, head)
        try:
            events = self.reader.events(self.pool, start, end)
        except RangeTooLarge:
            self.refused += 1
            self.chunk = max(50, self.chunk // 2)
            return {"from": start, "to": end, "events": 0, "inserted": 0, "primed": 0}
        except Exception:  # noqa: BLE001 — a refused poll is not a crash
            self.refused += 1
            return {"from": start, "to": end, "events": 0, "inserted": 0, "primed": 0}

        inserted = store.write_events(
            self.conn, self.pool, events, advance_cursor_to=end, now_ts=_now()
        )
        self.polls += 1
        self.seen += len(events)
        self.inserted += inserted
        return {
            "from": start,
            "to": end,
            "events": len(events),
            "inserted": inserted,
            "primed": 0,
        }

    def behind(self) -> int:
        """Blocks between the cursor and the settled head."""
        cursor = self.cursor()
        return max(0, self.reader.safe_head() - cursor) if cursor is not None else 0


def _now() -> int:
    return int(time.time())


def follow(
    conn,
    reader: BscReader,
    pool: str,
    *,
    seconds: float = 3600.0,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    chunk: int = DEFAULT_CHUNK,
    kill_file: str | Path = DEFAULT_KILL_FILE,
    progress: bool = True,
) -> dict[str, int]:
    """Poll until the deadline, the kill file, or a keyboard interrupt."""
    tail = Tail(conn, reader, pool, chunk=chunk)
    kill = Path(kill_file)
    started = time.monotonic()
    deadline = started + seconds if seconds > 0 else None
    interval = poll_seconds
    consecutive_refusals = 0

    while True:
        if kill.exists():
            if progress:
                print(f"  stopped: {kill} present")
            break
        if deadline is not None and time.monotonic() >= deadline:
            break

        before_refused = tail.refused
        result = tail.poll_once()
        refused = tail.refused > before_refused
        elapsed = time.monotonic() - started

        if refused:
            # **Say so.** This used to print only on success, so a tail refused
            # on every poll produced an empty log — indistinguishable from a
            # quiet pool, and identical to a tail that was working perfectly on
            # a pool nobody was trading. A run that cannot tell you it is failing
            # is worse than one that stops.
            consecutive_refusals += 1
            interval = min(interval * BACKOFF_FACTOR, MAX_POLL_SECONDS)
            if progress:
                print(
                    f"  t+{elapsed:6.0f}s  REFUSED ({consecutive_refusals} in a row) "
                    f"[{result['from']:,}..{result['to']:,}]  "
                    f"backing off to {interval:.0f}s"
                )
        else:
            if consecutive_refusals and progress:
                print(f"  t+{elapsed:6.0f}s  recovered after {consecutive_refusals} refusals")
            consecutive_refusals = 0
            interval = poll_seconds
            if progress and (result["events"] or result["primed"]):
                label = "primed at" if result["primed"] else f"{result['events']:3d} events in"
                print(
                    f"  t+{elapsed:6.0f}s  {label} "
                    f"[{result['from']:,}..{result['to']:,}]  "
                    f"+{result['inserted']} rows  {tail.behind():,} blocks behind"
                )

        if deadline is not None and time.monotonic() + interval > deadline:
            break
        time.sleep(interval)

    return {
        "polls": tail.polls,
        "refused": tail.refused,
        "events": tail.seen,
        "inserted": tail.inserted,
        "behind": tail.behind(),
        "consecutive_refusals": consecutive_refusals,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chain", type=int, default=56, choices=(56, 97))
    ap.add_argument("--db", default="data/misquote.db")
    ap.add_argument("--seconds", type=float, default=3600.0, help="0 follows until killed")
    ap.add_argument("--poll", type=float, default=DEFAULT_POLL_SECONDS)
    ap.add_argument("--chunk", type=int, default=DEFAULT_CHUNK)
    args = ap.parse_args(argv)

    pool = pool_for(args.chain)
    endpoints = connect_all(args.chain)
    if not endpoints:
        print(f"no reachable RPC for chain {args.chain}")
        return 1
    reader = BscReader(endpoints, pace_seconds=0.2)

    meta = PoolMeta(
        address=pool.address,
        chain_id=pool.chain_id,
        token0=pool.token0,
        token1=pool.token1,
        dec0=pool.dec0,
        dec1=pool.dec1,
        fee_pips=pool.fee_pips,
        tick_spacing=pool.tick_spacing,
        fee_protocol=pool.fee_protocol,
    )
    conn = store.connect(args.db)
    store.register_pool(conn, meta)

    print(f"  pool  {pool.label}")
    print(f"        {pool.address}")
    print(f"  db    {args.db}")
    print(f"  rate  one poll every {args.poll:.0f}s, at most {args.chunk:,} blocks each")
    print("        measured: 1 req/60s sustains; ~4 req/11s is refused by every endpoint")
    print(f"  stop  touch {DEFAULT_KILL_FILE}\n")

    try:
        result = follow(
            conn,
            reader,
            pool.address,
            seconds=args.seconds,
            poll_seconds=args.poll,
            chunk=args.chunk,
        )
    except KeyboardInterrupt:
        print("\n  interrupted; the cursor is durable, so re-running resumes")
        return 0
    finally:
        conn.close()

    print(
        f"\n  {result['polls']} polls, {result['refused']} refused, "
        f"{result['events']:,} events, {result['inserted']:,} rows written"
    )
    print(f"  {result['behind']:,} blocks behind the settled head")
    if result["refused"] and not result["polls"]:
        print("\n  every poll was refused, so nothing was written.")
        print("  The endpoints are shared: an anvil fork proxies every state read to")
        print("  the same public nodes, so running the chain-fork suite can exhaust")
        print("  the quota. Wait for it to refill, slow --poll down, or set a keyed")
        print("  BSC_RPC_URL.")
        return 1
    if result["consecutive_refusals"]:
        print(f"  ending on {result['consecutive_refusals']} consecutive refusals")
    return 0


if __name__ == "__main__":
    sys.exit(main())
