"""One job at a time, in a process of its own.

    uv run python -m misquote.ops.worker          # drain forever
    uv run python -m misquote.ops.worker --once   # take one job and stop

## Why a separate process, and not a thread in the API

Three independent reasons, each sufficient on its own.

**`ranges.quote()` is process-global non-reentrant.** It keeps per-run state in a
module-level dict so forked workers inherit it, and raises if entered twice in
one process. Two concurrent quotes inside uvicorn is not a slow response, it is
a `RuntimeError`.

**Forking from a threaded process is the unsafe case.** `ops/parallel.py` uses
`multiprocessing.get_context("fork")`, and its own docstring notes its callers
are single-threaded batch scripts. An ASGI server is not one. This worker is,
which is what makes `fork_map` safe to use inside it.

**The job system must not require the API extra.** `fastapi` and `uvicorn` are
an optional dependency group. A queue that could only be drained by a web
process would make running a quote depend on installing a web framework.

One job at a time per worker, deliberately. Concurrency comes from running more
workers, each single-threaded, each claiming under `BEGIN IMMEDIATE` — which is
what stops two of them starting the same 4.6-hour replay.
"""

from __future__ import annotations

import argparse
import os
import socket
import sqlite3
import time
import traceback
from typing import Any

from misquote.ops import jobs, quote_job

#: How long to wait before asking for work again when the queue is empty.
IDLE_SLEEP_S = 2.0

#: What each job kind runs. Keyed rather than dispatched on an `if`, so adding a
#: kind is a table entry and an unknown kind is a refusal rather than a silent
#: no-op that leaves the row `running` forever.
HANDLERS: dict[str, Any] = {"quote": quote_job.run}


def run_one(conn: sqlite3.Connection, job: dict[str, Any]) -> str:
    """Run a claimed job to a terminal state. Returns that state.

    Every exit path finishes the job. A handler that raises must not leave the
    row saying `running` — that is indistinguishable from a worker still
    working, and the orphan sweep would not touch it for five minutes.
    """
    import json

    handler = HANDLERS.get(job["kind"])
    if handler is None:
        jobs.finish(
            conn,
            job["id"],
            "failed",
            refusal={
                "error": f"no handler for job kind {job['kind']!r}",
                "remedy": f"one of {sorted(HANDLERS)}",
            },
        )
        return "failed"

    try:
        handler(conn, job["id"], json.loads(job["params_json"]))
    except Exception as error:  # noqa: BLE001 — the worker must survive one bad job
        jobs.finish(
            conn,
            job["id"],
            "failed",
            refusal={
                "error": f"{type(error).__name__}: {error}",
                # The traceback goes in the record rather than only to stderr:
                # the worker may be on a host whose logs nobody can reach, and a
                # failure a caller cannot diagnose is barely better than a hang.
                "traceback": traceback.format_exc(limit=8),
                "remedy": "resubmit, or check the worker log",
            },
        )
        return "failed"

    row = jobs.get(conn, job["id"])
    return str(row["status"]) if row else "failed"


def drain(
    conn: sqlite3.Connection, *, once: bool = False, idle_sleep_s: float = IDLE_SLEEP_S
) -> int:
    """Claim and run jobs until the queue is empty (`once`) or forever.

    Returns how many jobs were run, which is what makes the loop testable
    without a clock: `once=True` drains what is queued and returns.
    """
    pid = os.getpid()
    host = socket.gethostname()
    ran = 0

    while True:
        # Before the claim, so an idle worker is still visible. `worker_last_seen`
        # used to infer a worker from the jobs it had touched, which cannot fire
        # on a fresh deploy: a worker against an empty queue has touched nothing
        # and reads exactly like no worker at all. That is the first state
        # anyone hiring meets, and it was the one the queue could not describe.
        jobs.announce(conn, pid=pid, host=host)

        job = jobs.claim(conn, pid=pid)
        if job is None:
            if once:
                return ran
            time.sleep(idle_sleep_s)
            continue

        status = run_one(conn, job)
        ran += 1
        print(f"job {job['id'][:8]} {job['kind']} -> {status}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="drain the queue and exit")
    args = parser.parse_args(argv)

    conn = jobs.connect()
    try:
        # On boot, before claiming anything. A row left `running` by a killed
        # worker is neither running nor failed, and saying either would be a
        # lie; it is marked `orphaned` with an event explaining what happened.
        # Nothing is re-run: restarting a 4.6-hour replay because a process died
        # is a decision, and it is the caller's.
        orphans = jobs.sweep_orphans(conn)
        if orphans:
            print(f"marked {len(orphans)} orphaned job(s) from a previous worker", flush=True)

        drain(conn, once=args.once)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
