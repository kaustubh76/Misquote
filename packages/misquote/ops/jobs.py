"""A job store, because a quote is not something a request can wait for.

`replay/ranges.py::quote()` records its own cost in its docstring: 60 replays of
~125,700 events each, **4.6 hours** for the four agents the showcase runs. It is
also process-global non-reentrant — it keeps per-run state in a module-level
dict so forked workers inherit it, and raises rather than letting a second call
corrupt the first. Neither fact is negotiable from the API side, so the API does
not call it. It enqueues.

## Why a file and not a dict

An in-process dict loses every job when the service restarts, which on Render's
free plan is *after every idle period*. It also cannot be read by the worker,
which is a different process on purpose (see `ops/worker.py`). SQLite gives both,
and gives the claim atomically: `BEGIN IMMEDIATE` around the claim is what stops
two workers running the same 4.6-hour replay.

## Terminal states are not interchangeable

`done`, `refused`, `failed`, `cancelled` and `orphaned` are five different
sentences and the store keeps them apart.

`refused` is the one that matters. A replay that finishes and reports that the
tape cannot support a quote has *succeeded*; `MIN_WINDOW_HOURS` and the
observation floor exist to produce exactly that answer. Filing it as `failed`
would tell a caller to retry something that will refuse again for the same good
reason, and would make the product's central honesty look like a bug.

`orphaned` is the second. A worker killed mid-replay leaves a row saying
`running` forever, and the two available lies are "still going" and "failed".
Neither is true: the attempt did not finish and nothing is working on it. The
sweep marks it and appends an event saying so, and does **not** silently re-run —
a 4.6-hour job restarted without anyone asking is not a recovery.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]

SCHEMA_PATH = Path(__file__).with_name("jobs_schema.sql")

#: Terminal states. A job in one of these is never claimed again.
FINISHED = frozenset({"done", "refused", "failed", "cancelled", "orphaned"})

#: How long a `running` job may go without a heartbeat before the sweep calls it
#: orphaned. Generous, because a single replay window can take minutes and a
#: loaded machine can stretch that; the cost of waiting is a stale row, and the
#: cost of being wrong is declaring a live job dead.
STALE_AFTER_S = 300


def db_path() -> Path:
    """Where the store lives. Read per call so tests can redirect it."""
    return Path(os.environ.get("MISQUOTE_JOBS_DB", REPO / "data" / "jobs.db"))


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open the store, creating it if absent."""
    target = Path(path) if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, isolation_level=None)  # explicit transactions
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


def _now() -> int:
    return int(time.time())


def submit(conn: sqlite3.Connection, kind: str, params: dict[str, Any]) -> str:
    """Enqueue a job and return its id."""
    job_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO job (id, kind, params_json, status, created_ts) VALUES (?, ?, ?, 'queued', ?)",
        (job_id, kind, json.dumps(params, sort_keys=True), _now()),
    )
    append(conn, job_id, "queued", {"kind": kind})
    return job_id


def append(conn: sqlite3.Connection, job_id: str, kind: str, payload: dict[str, Any]) -> int:
    """Append one event and return its sequence number.

    The sequence is per job and derived inside the same statement, so two
    writers cannot mint the same `seq` — it is the id an SSE client reconnects
    with, and a duplicate would silently drop an event on replay.
    """
    cur = conn.execute(
        """INSERT INTO job_event (job_id, seq, ts, kind, payload_json)
           VALUES (?, (SELECT coalesce(max(seq), 0) + 1 FROM job_event WHERE job_id = ?), ?, ?, ?)
           RETURNING seq""",
        (job_id, job_id, _now(), kind, json.dumps(payload, sort_keys=True)),
    )
    return int(cur.fetchone()[0])


def claim(conn: sqlite3.Connection, *, pid: int) -> dict[str, Any] | None:
    """Take the oldest queued job, atomically, or return None.

    `BEGIN IMMEDIATE` takes the write lock before the SELECT, so two workers
    cannot both read the same row as queued and both claim it. Without it the
    failure is not a crash — it is two processes running the same 4.6-hour
    replay and one of them overwriting the other's result.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT * FROM job WHERE status = 'queued' ORDER BY created_ts LIMIT 1"
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None

        now = _now()
        conn.execute(
            "UPDATE job SET status = 'running', started_ts = ?, heartbeat_ts = ?, worker_pid = ? "
            "WHERE id = ?",
            (now, now, pid, row["id"]),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    append(conn, row["id"], "running", {"pid": pid})
    return dict(row) | {"status": "running", "worker_pid": pid}


def progress(conn: sqlite3.Connection, job_id: str, done: int, total: int, phase: str = "") -> None:
    """Record how far along a job is, and beat its heart while doing so."""
    conn.execute(
        "UPDATE job SET done = ?, total = ?, phase = ?, heartbeat_ts = ? WHERE id = ?",
        (done, total, phase or None, _now(), job_id),
    )
    append(conn, job_id, "progress", {"done": done, "total": total, "phase": phase})


def finish(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    refusal: dict[str, Any] | None = None,
) -> None:
    """Move a job to a terminal state, with the payload that state implies."""
    if status not in FINISHED:
        raise ValueError(f"{status!r} is not a terminal state; one of {sorted(FINISHED)}")

    conn.execute(
        "UPDATE job SET status = ?, finished_ts = ?, result_json = ?, refusal_json = ? WHERE id = ?",
        (
            status,
            _now(),
            json.dumps(result, sort_keys=True) if result is not None else None,
            json.dumps(refusal, sort_keys=True) if refusal is not None else None,
            job_id,
        ),
    )
    append(conn, job_id, status, refusal or result or {})


def sweep_orphans(conn: sqlite3.Connection, *, stale_after_s: int = STALE_AFTER_S) -> list[str]:
    """Mark `running` jobs whose worker stopped beating, and say so in their log.

    Called on worker boot. Does not re-run anything: a 4.6-hour replay restarted
    because a process died is a decision, not a recovery, and it is the caller's
    to make.
    """
    cutoff = _now() - stale_after_s
    rows = conn.execute(
        "SELECT id FROM job WHERE status = 'running' AND coalesce(heartbeat_ts, 0) < ?",
        (cutoff,),
    ).fetchall()

    orphaned = [row["id"] for row in rows]
    for job_id in orphaned:
        conn.execute(
            "UPDATE job SET status = 'orphaned', finished_ts = ? WHERE id = ?", (_now(), job_id)
        )
        append(
            conn,
            job_id,
            "orphaned",
            {
                "note": (
                    "the worker holding this job stopped reporting. The attempt did not "
                    "finish and nothing is working on it."
                ),
                "remedy": "resubmit",
            },
        )
    return orphaned


def get(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def events(conn: sqlite3.Connection, job_id: str, *, after: int = 0) -> list[dict[str, Any]]:
    """Every event past `after`, oldest first. `after` is a `Last-Event-ID`."""
    rows = conn.execute(
        "SELECT seq, ts, kind, payload_json FROM job_event WHERE job_id = ? AND seq > ? "
        "ORDER BY seq",
        (job_id, after),
    ).fetchall()
    return [
        {
            "seq": int(r["seq"]),
            "ts": int(r["ts"]),
            "kind": r["kind"],
            "payload": json.loads(r["payload_json"]),
        }
        for r in rows
    ]


def listing(conn: sqlite3.Connection, *, kind: str = "", status: str = "") -> list[dict[str, Any]]:
    """Jobs, newest first, optionally narrowed."""
    clauses, args = [], []
    if kind:
        clauses.append("kind = ?")
        args.append(kind)
    if status:
        clauses.append("status = ?")
        args.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(f"SELECT * FROM job {where} ORDER BY created_ts DESC LIMIT 200", args)
    return [dict(r) for r in rows]


def cancel(conn: sqlite3.Connection, job_id: str) -> bool:
    """Cancel a job that has not started. Returns whether anything changed.

    Only `queued`. A running replay is in a forked worker and stopping it
    mid-window would leave a partial result nobody could interpret; the honest
    surface is that you can withdraw a job from the queue, not that you can
    interrupt arithmetic.
    """
    cur = conn.execute(
        "UPDATE job SET status = 'cancelled', finished_ts = ? WHERE id = ? AND status = 'queued'",
        (_now(), job_id),
    )
    if cur.rowcount:
        append(conn, job_id, "cancelled", {"note": "withdrawn from the queue before it started"})
    return bool(cur.rowcount)
