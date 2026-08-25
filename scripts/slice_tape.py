"""A tape small enough to deploy, that still refuses for the right reasons.

    uv run python scripts/slice_tape.py                  # write data/deploy/tape.db
    uv run python scripts/slice_tape.py --check          # verify an existing one
    uv run python scripts/slice_tape.py --window-days 30 # a wider slice

`data/misquote.db` is 245MB and gitignored, and Render deploys from a checkout.
So the API's tape routes and its whole quote path — `/tape`, `/quote/preflight`,
`/quote/eligibility` — come up 503 on any host that is not this laptop, which is
how a service ends up shipping with a third of its routes permanently refusing.

This writes the smallest database those routes can answer honestly from.

## What is left out, and why each omission is safe

**The Venus tables.** `accrue` and its indexes are 131MB of the 245 — over half
the file — and no swap quote reads them. `replay/ranges.py` never opens them;
they exist for the rate tape the Router agent replays, which is published as an
artifact and needs no live database.

**Everything older than the window.** A uniform `--window-days` applied to every
verified pool, rather than a per-pool rule, because a per-pool rule is a table of
exceptions that nobody re-derives when a pool is added.

## The invariant that makes a slice honest

`schema.sql` explains why `covered` exists: a quiet block range and a range
nobody fetched both hold zero swaps, and no query over `swap` can tell them
apart. A tape holding one day at each end of a twenty-six-day span "reported
spanning 26 days and passed the readiness gate".

A slice is exactly the operation that manufactures that shape. Copy the events
inside a window but the `covered` row from the whole backfill, and the result is
a database asserting it read five million blocks while holding the events from
the last two hundred thousand — indistinguishable, to every consumer, from a
tape whose middle silently failed to index. It would not error. It would quote.

So `covered` is intersected with the kept window, and `--check` asserts the
result two ways: no event lies outside the coverage this file declares, and no
coverage this file declares lies outside what the source recorded. The first
catches a claim wider than the data; the second catches a slice inventing
history the original never had.

Downsampling — every tenth swap, say — would land at a fraction of the size and
is not available for the same reason. There is no coverage row that describes
"nine of every ten blocks in this range were skipped", so the resulting file
could only lie.

## Why a cursor is copied unchanged

`cursor` is a resume high-water mark, not a completeness claim — schema.sql says
so at length. It stays at the source's value because it remains true: reading
did stop there. `covered` is the field that describes what is held, and it is
the one that moves.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

from misquote.chain.addresses import known_pools_on
from misquote.indexer.store import connect

REPO = Path(__file__).resolve().parents[1]

DEFAULT_SOURCE = REPO / "data" / "misquote.db"

#: Committed, and read by `render.yaml` through `DB_PATH`. Under `data/deploy/`
#: rather than beside the source because `.gitignore` excludes `data/*.db` — a
#: pattern that matches direct children only, so this path is tracked without
#: carving a negation into the ignore file for something that must never catch
#: the real 245MB tape by accident.
DEFAULT_OUT = REPO / "data" / "deploy" / "tape.db"

#: Ten days, and the floor it clears is not the obvious one. A quote needs
#: `MIN_SAMPLES` windows of `MIN_WINDOW_HOURS` each — 20 × 24h — which a much
#: shorter tape satisfies, since the windows overlap. The binding constant is
#: `MIN_HOURS_TO_ANNUALISE`, 7 days: below it a quote states the period it
#: covers instead of an annual rate, and the annual rate is the figure every
#: other page on the site shows. Ten leaves three days of margin rather than
#: sitting on the threshold.
DEFAULT_WINDOW_DAYS = 10

SECONDS_PER_DAY = 86_400

#: Copied whole for the kept pools. `pool_state` is in the list although the
#: source holds none: a periodic snapshot that starts being recorded later
#: should reach the slice without anyone remembering to add it here.
EVENT_TABLES = ("swap", "mint", "burn", "pool_state")

CHAIN_ID = 56


def _cut_block(src: sqlite3.Connection, pool: str, window_days: int) -> int:
    """The first block of the kept window, or 0 to keep everything.

    Cut on a block number rather than on a timestamp, because `covered` is
    denominated in blocks and the two must describe the same boundary. A
    timestamp cut would leave the coverage row and the events it vouches for
    disagreeing by however many blocks share the boundary second.

    Every table here is `src.`-qualified. Unqualified, they resolve to the
    destination — which is empty when this is called, so `MAX(ts)` is NULL, the
    cut is 0, and the "slice" is a byte-for-byte copy of a 245MB tape that still
    passes the coverage check, because copying everything is trivially
    consistent. It wrote 119.6MB once before this comment existed.
    """
    end = src.execute("SELECT MAX(ts) FROM src.swap WHERE pool = ?", (pool,)).fetchone()[0]
    if end is None:
        return 0
    cut_ts = int(end) - window_days * SECONDS_PER_DAY
    row = src.execute("SELECT MIN(number) FROM src.block WHERE ts >= ?", (cut_ts,)).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def build(source: Path, out: Path, window_days: int) -> dict[str, Any]:
    """Write the slice. Returns what it wrote, for the caller to print."""
    if not source.exists():
        raise SystemExit(f"no tape at {source} — run `make indexer POOL=0x...` first")

    for stale in (out, Path(f"{out}-wal"), Path(f"{out}-shm")):
        stale.unlink(missing_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)

    # `connect` applies `indexer/schema.sql`, so the slice cannot drift from the
    # shape the indexer writes. Restating the DDL here would be a second copy of
    # a schema whose comments are load-bearing.
    dst = connect(out)
    dst.execute("ATTACH ? AS src", (str(source.resolve()),))

    kept: list[dict[str, Any]] = []
    try:
        with dst:
            for ref in known_pools_on(CHAIN_ID):
                pool = ref.address.lower()
                cut = _cut_block(dst, pool, window_days)

                dst.execute(
                    "INSERT OR IGNORE INTO pool SELECT * FROM src.pool WHERE address = ?", (pool,)
                )
                for table in EVENT_TABLES:
                    dst.execute(
                        f"INSERT OR IGNORE INTO {table} SELECT * FROM src.{table} "
                        "WHERE pool = ? AND block >= ?",
                        (pool, cut),
                    )
                dst.execute(
                    "INSERT OR IGNORE INTO cursor SELECT * FROM src.cursor WHERE pool = ?", (pool,)
                )
                # The intersection this module exists to get right. `max(from_block, cut)`
                # narrows a run that straddles the boundary; `to_block >= cut` drops one
                # that ends before it entirely.
                dst.execute(
                    "INSERT OR IGNORE INTO covered "
                    "SELECT pool, MAX(from_block, ?), to_block FROM src.covered "
                    "WHERE pool = ? AND to_block >= ?",
                    (cut, pool, cut),
                )
                swaps = dst.execute("SELECT COUNT(*) FROM swap WHERE pool = ?", (pool,)).fetchone()[
                    0
                ]
                kept.append({"pool": pool, "label": ref.label, "swaps": swaps, "from_block": cut})

            # Only the blocks the kept events name. The source's `block` table
            # spans every pool's history and is meaningless without them.
            dst.execute(
                "INSERT OR IGNORE INTO block SELECT * FROM src.block WHERE number IN ("
                " SELECT block FROM swap UNION SELECT block FROM mint"
                " UNION SELECT block FROM burn UNION SELECT block FROM pool_state)"
            )

        dst.execute("DETACH src")
        # TRUNCATE rather than PASSIVE: a checkpointed-but-present `-wal` file
        # beside a committed database is a second file whose absence on a fresh
        # clone changes nothing, which makes it exactly the sort of thing that
        # is committed once and confusing forever.
        dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        # Out of WAL mode before it is committed. `schema.sql` selects WAL
        # because the Warden reads the tape while the indexer writes it, and
        # neither of those is true of a file that ships read-only — what is true
        # is that a WAL database is three files, and the two the reader does not
        # think about get created beside it by anything that opens it, including
        # the test suite. One file, and `store.connect` puts a deployed copy
        # back into WAL on its own when a host actually wants it.
        dst.execute("PRAGMA journal_mode = DELETE")
        dst.execute("VACUUM")
        dst.commit()
    finally:
        dst.close()

    Path(f"{out}-wal").unlink(missing_ok=True)
    Path(f"{out}-shm").unlink(missing_ok=True)
    return {"out": str(out), "bytes": out.stat().st_size, "window_days": window_days, "pools": kept}


def check(source: Path, out: Path) -> list[str]:
    """Both halves of the invariant. Returns the complaints, empty when clean."""
    if not out.exists():
        return [f"no slice at {out} — run `make tape-slice`"]

    problems: list[str] = []
    dst = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        for table in ("swap", "mint", "burn"):
            loose = dst.execute(
                f"SELECT COUNT(*) FROM {table} e WHERE NOT EXISTS ("
                " SELECT 1 FROM covered c WHERE c.pool = e.pool"
                " AND e.block BETWEEN c.from_block AND c.to_block)"
            ).fetchone()[0]
            if loose:
                problems.append(
                    f"{loose} {table} row(s) lie outside the coverage this slice declares"
                )

        if source.exists():
            dst.execute("ATTACH ? AS src", (str(source.resolve()),))
            invented = dst.execute(
                "SELECT COUNT(*) FROM covered c WHERE NOT EXISTS ("
                " SELECT 1 FROM src.covered s WHERE s.pool = c.pool"
                " AND c.from_block >= s.from_block AND c.to_block <= s.to_block)"
            ).fetchone()[0]
            if invented:
                problems.append(f"{invented} coverage run(s) claim more than the source recorded")
            dst.execute("DETACH src")
    finally:
        dst.close()
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument(
        "--check", action="store_true", help="verify an existing slice, write nothing"
    )
    args = parser.parse_args(argv)

    if not args.check:
        written = build(args.source, args.out, args.window_days)
        print(
            f"{written['out']}  {written['bytes'] / 1e6:.1f} MB  (last {written['window_days']} days)"
        )
        for row in written["pools"]:
            print(
                f"  {row['pool']}  {row['label']:<24} {row['swaps']:>7} swaps  from block {row['from_block']}"
            )

    problems = check(args.source, args.out)
    for problem in problems:
        print(f"REFUSED: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("coverage invariant holds: every event is inside a run the source recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
