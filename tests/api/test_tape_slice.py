"""The committed tape must be a true subset of the one it was cut from.

`data/deploy/tape.db` is the only database that ships. Every claim the deployed
API makes about coverage, and every refusal it issues about a window being too
short, is read out of this file — so the file being *smaller* than the source is
fine and the file being *wrong* about what it holds is not.

## The failure this guards

`schema.sql` explains `covered` at length: a quiet block range and a range nobody
fetched both hold zero swaps, and no query over `swap` can distinguish them. A
slice is precisely the operation that manufactures the bad shape — keep the
events from a window, keep the coverage row from the whole backfill, and the
result is a database asserting it read five million blocks while holding two
hundred thousand blocks' worth of events. Nothing errors. It quotes.

So both directions are asserted. `test_no_event_lies_outside_the_declared_coverage`
catches a claim wider than the data; `test_no_coverage_run_exceeds_the_source`
catches a slice inventing history the original never recorded.

## The size bound

Not tidiness. `scripts/slice_tape.py` computes its cut block against the
attached source, and an unqualified table name there resolves to the *empty
destination* instead — which makes the cut 0, copies all 245MB, and still passes
both invariants above, because copying everything is trivially consistent. That
is not a hypothetical: it wrote a 119.6MB "slice" once. The bound is the only
assertion that would have caught it.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from misquote.api.preflight import assess
from misquote.chain.addresses import known_pools_on
from misquote.indexer.store import connect

REPO = Path(__file__).resolve().parents[2]
SLICE = REPO / "data" / "deploy" / "tape.db"
SOURCE = REPO / "data" / "misquote.db"

#: Comfortably above the 31MB the ten-day window produces, and far below the
#: 119.6MB an uncut copy produces. A slice that legitimately grows past this has
#: had its window widened, which is a decision worth making deliberately.
MAX_BYTES = 60_000_000

CHAIN_ID = 56


@pytest.fixture(scope="module")
def sliced() -> sqlite3.Connection:
    if not SLICE.exists():
        pytest.skip(f"no slice at {SLICE} — `make tape-slice`")
    # `immutable=1`, not merely `mode=ro`. A read-only connection to a
    # WAL-mode database still needs the shared-memory index, and SQLite creates
    # `-shm` beside the file to get it — so `mode=ro` alone left two untracked
    # sidecars next to a committed database every time the suite ran.
    # `immutable` promises the file will not change underneath us, which is true
    # of a committed artifact, and skips the WAL machinery entirely.
    conn = sqlite3.connect(f"file:{SLICE}?immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.mark.parametrize("table", ["swap", "mint", "burn"])
def test_no_event_lies_outside_the_declared_coverage(
    sliced: sqlite3.Connection, table: str
) -> None:
    loose = sliced.execute(
        f"SELECT COUNT(*) FROM {table} e WHERE NOT EXISTS ("
        " SELECT 1 FROM covered c WHERE c.pool = e.pool"
        " AND e.block BETWEEN c.from_block AND c.to_block)"
    ).fetchone()[0]
    assert loose == 0, f"{loose} {table} row(s) sit outside every coverage run this slice declares"


def test_no_coverage_run_exceeds_the_source(sliced: sqlite3.Connection) -> None:
    if not SOURCE.exists():
        pytest.skip("the 245MB source tape is not in this checkout")

    sliced.execute("ATTACH ? AS src", (str(SOURCE.resolve()),))
    try:
        invented = sliced.execute(
            "SELECT COUNT(*) FROM covered c WHERE NOT EXISTS ("
            " SELECT 1 FROM src.covered s WHERE s.pool = c.pool"
            " AND c.from_block >= s.from_block AND c.to_block <= s.to_block)"
        ).fetchone()[0]
    finally:
        sliced.execute("DETACH src")
    assert invented == 0, "the slice claims coverage the source never recorded"


def test_the_slice_is_small_enough_to_have_been_cut(sliced: sqlite3.Connection) -> None:
    size = SLICE.stat().st_size
    assert size <= MAX_BYTES, (
        f"{size / 1e6:.1f}MB — larger than a windowed slice should be. The likely cause is "
        "`_cut_block` resolving a table against the destination instead of `src.`, which "
        "silently copies the whole tape."
    )


def test_every_verified_pool_is_present(sliced: sqlite3.Connection) -> None:
    """A pool the site quotes but the slice omits would refuse in production only."""
    held = {row["address"] for row in sliced.execute("SELECT address FROM pool")}
    missing = [
        ref.address.lower() for ref in known_pools_on(CHAIN_ID) if ref.address.lower() not in held
    ]
    assert not missing, f"the deployed tape holds no rows for {missing}"


def test_the_engines_own_predicate_says_the_slice_can_quote(tmp_path: Path) -> None:
    """The slice is only worth deploying if `preflight` agrees it is quotable.

    `assess` is the engine's sufficiency rule, not a restatement of it — it
    imports `MIN_SAMPLES` and `MIN_WINDOW_HOURS` from `replay.ranges`. If the
    window here ever drops below what the engine needs, this fails rather than
    the deployment quietly refusing every quote a reader asks for.
    """
    if not SLICE.exists():
        pytest.skip(f"no slice at {SLICE} — `make tape-slice`")

    # Copied first. `store.connect` opens read-write and applies the schema, and
    # a WAL-mode database opened that way leaves `-wal` and `-shm` beside it —
    # two untracked files next to a committed one, created by running the test
    # suite. `assess` needs the row factory `connect` installs, so the fix is to
    # give it a scratch copy rather than a read-only handle.
    scratch = tmp_path / "tape.db"
    scratch.write_bytes(SLICE.read_bytes())

    conn = connect(scratch)
    try:
        verdicts = {ref.label: assess(conn, ref) for ref in known_pools_on(CHAIN_ID)}
    finally:
        conn.close()

    refused = {label: v["why_not"] for label, v in verdicts.items() if not v["quotable"]}
    assert not refused, f"the deployed tape cannot quote: {refused}"


def test_reading_the_tape_does_not_modify_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answering a question about the tape must not change the tape.

    `store.connect` creates the file if absent and runs `schema.sql` over it,
    which begins `PRAGMA journal_mode = WAL`. The API opened the tape that way,
    so a single `GET /tape` rewrote the database header of this committed file
    and left `-wal` and `-shm` beside it — `git status` dirty from having served
    a read.

    Hashed rather than compared by mtime, because the change was one byte.
    """
    if not SLICE.exists():
        pytest.skip(f"no slice at {SLICE} — `make tape-slice`")

    from misquote.api import tape as tape_routes

    monkeypatch.setenv("DB_PATH", str(SLICE))
    before = hashlib.sha256(SLICE.read_bytes()).hexdigest()

    answered = tape_routes.tape(chain_id=CHAIN_ID)
    assert answered["pools"], "the read returned nothing, so it proves nothing about writing"

    assert hashlib.sha256(SLICE.read_bytes()).hexdigest() == before
    for sidecar in (f"{SLICE}-wal", f"{SLICE}-shm"):
        assert not Path(sidecar).exists(), f"reading the tape created {sidecar}"
