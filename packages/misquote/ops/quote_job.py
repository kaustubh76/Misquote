"""The work a quote job does: one replay run, reported as it goes.

Separated from `worker.py` so the loop that claims jobs knows nothing about
replays, and from `api/` so running a quote does not require FastAPI to be
installed. The layering is not decoration — `ops` is a driver layer and may
import `replay`; `replay` is pure and may import neither.

## The two seams this uses, and why they exist

`ranges.quote()` takes `on_progress(done, total)` and `map_fn`. Both are there
because `tests/test_layering.py` bans the pure `replay` layer from importing
`multiprocessing`, `time` or anything else that constitutes a capability — so
the pure layer decides *what* runs and this decides *where* and *who is told*.
Passing `ops.parallel.fork_map` changes no arithmetic: the replays are
independent by construction and `imap` preserves submission order, which is what
keeps `returns` and `net_positive` identical to the serial run.

## Refusal is the expected outcome, not the error path

`quote_from_results` sets `sufficient=False` and writes its own sentence into
`note` when the windows are too short or too few. That is the engine doing its
job, and it arrives here as a `refused` job carrying that sentence **verbatim**.
Rewording it would put a second voice on the one answer the product exists to
give honestly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from misquote.chain.addresses import PoolRef, pool_by_address
from misquote.core.types import DEFAULT_CAPITAL_QUOTE, Event, PoolMeta
from misquote.indexer import store
from misquote.ops import jobs
from misquote.ops.parallel import fork_map
from misquote.replay.ranges import Quote, quote
from misquote.replay.tape import MemoryTape

#: Windows to run for an interactive quote, against the engine's default of 20.
#:
#: This is the only number here that is a *choice* rather than the engine's, and
#: it is disclosed rather than absorbed: fewer windows means fewer observations,
#: a wider spread, and a refusal where a full run might have quoted. The
#: direction of the error is toward refusing, which is the safe direction.
#: Published as **A15** on `docs/ASSUMPTIONS.md`, which is where a reader
#: arrives from the `interactive_budget` flag on the result.
INTERACTIVE_WINDOWS = 8

#: The engine's own default, for telling a reduced run apart from a full one.
DEFAULT_WINDOWS = 20

def replay_jobs() -> int:
    """How many processes to fork for the window x perturbation replays.

    ## `os.cpu_count()` is the wrong number inside a container

    It reports the **host's** cores, not the share this container may use. On the
    free instance this deploys to that is the difference between 1 and something
    like 16, and each fork is a full interpreter that copies the event list —
    Python's refcounting writes to every object it touches, so copy-on-write
    does not save you. Sixteen of those in a 512MB box does not run slowly, it
    gets the container killed.

    That is what was happening: a replay would reach "loading the tape" and then
    the job would *vanish*, because the container restarted and took the
    ephemeral `jobs.db` with it. It happened on the 60,853-swap pool and just as
    reliably on the 85-swap one, which is what ruled out data volume and pointed
    here.

    So the cgroup quota is read first, since that is the only number that
    describes this container. `MISQUOTE_REPLAY_JOBS` overrides everything, for a
    host where the quota is unreadable or a caller who knows better.
    """
    override = os.environ.get("MISQUOTE_REPLAY_JOBS")
    if override:
        return max(1, int(override))

    # cgroup v2: "$QUOTA $PERIOD", or "max $PERIOD" when uncapped.
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            return max(1, int(float(quota) / float(period)))
    except (OSError, ValueError):
        pass

    # Affinity beats `cpu_count` where it is honoured, and is a no-op elsewhere.
    try:
        available = len(os.sched_getaffinity(0))
    except AttributeError:  # not Linux
        available = os.cpu_count() or 2

    return max(1, available - 1)


#: Processes to spread the window x perturbation replays across.
JOBS = replay_jobs()


def meta_for(ref: PoolRef) -> PoolMeta:
    """The replay's view of a pool, built from the verified record.

    Restated from `PoolRef` rather than carried on it, the way `showcase.py`
    does: `PoolRef` is what this repository checked on chain, `PoolMeta` is what
    the pure engine consumes, and the two are deliberately different types so a
    pool nobody verified cannot be handed to a replay.
    """
    return PoolMeta(
        address=ref.address,
        chain_id=ref.chain_id,
        token0=ref.token0,
        token1=ref.token1,
        dec0=ref.dec0,
        dec1=ref.dec1,
        fee_pips=ref.fee_pips,
        tick_spacing=ref.tick_spacing,
        fee_protocol=ref.fee_protocol,
    )


def tape_db_path(params: dict[str, Any]) -> str:
    """Which tape this replay reads: the job's, then `DB_PATH`, then the default.

    A function rather than an expression inline, so the service and the worker
    cannot drift apart again — and so a test can assert against *this* rather
    than against a copy of it, which is the same mistake one level up.

    `run` hardcoded `data/misquote.db` while every other reader of the tape
    honours `DB_PATH`: `api/locations.py::db_path`, `go_no_go.py`, the agents.
    On the deployment that is not a preference. The service reads the committed
    slice at `data/deploy/tape.db` and answers `/tape` with 60,853 swaps for the
    target pool; the replay opened a 245MB gitignored file absent from the
    checkout, found nothing, and refused with *"the tape holds no swaps for
    0x3669…"*.

    Every word of that refusal was true about the file it opened and wrong about
    the pool — two halves of one system disagreeing about where the truth lives,
    reported to a caller as an absence. In the path that answers a hire.
    """
    return str(
        params.get("db_path")
        or os.environ.get("DB_PATH")
        or jobs.REPO / "data" / "misquote.db"
    )


def load_events(db_path: Any, address: str) -> list[Event]:
    """Every swap for one pool, in time order."""
    conn = store.connect(db_path)
    try:
        return list(store.read_swaps(conn, address))
    finally:
        conn.close()


def run(conn: Any, job_id: str, params: dict[str, Any]) -> None:
    """Replay one pool and file the outcome under the state it earned."""
    ref = pool_by_address(str(params["pool"]))
    # `DEFAULT_CAPITAL_QUOTE`, not `0.0`. This coerced an absent field to zero,
    # and `ranges.quote` then divided every replay by it and reported 0.0 — so a
    # hire that named only a pool, which is what the site's own button sends,
    # answered `0.00% to 0.00%` and called it sufficient. The engine refuses that
    # now; this is the other half, because a job with no stated size should quote
    # the same unit the published cards do rather than fail. See P-32.
    capital = float(params.get("capital_quote") or DEFAULT_CAPITAL_QUOTE)
    windows = int(params.get("windows") or INTERACTIVE_WINDOWS)
    tape_db = tape_db_path(params)

    jobs.progress(conn, job_id, 0, 0, phase="loading the tape")
    events = load_events(tape_db, ref.address)

    if not events:
        jobs.finish(
            conn,
            job_id,
            "refused",
            refusal={
                "error": f"the tape holds no swaps for {ref.address}",
                "note": "An unindexed pool is an absence, not an empty result.",
                "remedy": f"make indexer POOL={ref.address}",
            },
        )
        return

    def factory(start: int | None, end: int | None) -> MemoryTape:
        # A *fresh* tape per window, and a slice rather than a bound cursor.
        # `quote()`'s docstring is explicit that a tape cannot be rewound —
        # rewinding is how a replay quietly restarts its clock — so reusing one
        # raises rather than silently producing a wrong answer. Same shape as
        # `scripts/showcase.py::run_agent`.
        if start is None or end is None:
            return MemoryTape(events)
        return MemoryTape([e for e in events if start <= e.ts <= end])

    def on_progress(done: int, total: int) -> None:
        jobs.progress(conn, job_id, done, total, phase="replaying")

    result: Quote = quote(
        meta_for(ref),
        factory,
        capital_quote=capital,
        windows=windows,
        map_fn=fork_map(JOBS),
        on_progress=on_progress,
    )

    if not result.sufficient:
        # The engine's own sentence, copied and not rewritten.
        jobs.finish(
            conn,
            job_id,
            "refused",
            refusal={
                "error": "the evidence cannot support a quote",
                "note": result.note,
                "windows": result.windows,
                "samples": result.samples,
                "remedy": f"make indexer POOL={ref.address}",
            },
        )
        return

    jobs.finish(
        conn,
        job_id,
        "done",
        result={
            "pool": ref.address,
            "p25": result.p25,
            "p50": result.p50,
            "p75": result.p75,
            "samples": result.samples,
            "windows": result.windows,
            "perturbations": result.perturbations,
            "hours_per_window": result.hours_per_window,
            "net_positive": result.net_positive,
            "distinct_returns": result.distinct_returns,
            "annualised": result.annualised,
            "basis": result.basis,
            "note": result.note,
            "windows_requested": windows,
            # Flagged on the result rather than left for a reader to infer from
            # the window count. An interactive run is a *different* measurement
            # from the published card and must not be compared with it silently.
            "interactive_budget": windows < DEFAULT_WINDOWS,
        },
    )
