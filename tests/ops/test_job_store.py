"""The job store, and the five different sentences its terminal states carry.

Almost everything here is about not collapsing distinctions: `refused` is not
`failed`, `orphaned` is neither, and a claim that two workers can both win is
not a race that shows up as slowness — it is two four-hour replays and one of
them overwriting the other.
"""

from __future__ import annotations

import json

import pytest

from misquote.ops import jobs


@pytest.fixture
def conn():
    connection = jobs.connect()
    yield connection
    connection.close()


def test_the_store_lands_where_the_fixture_put_it() -> None:
    """`conftest` redirects MISQUOTE_JOBS_DB into tmp_path.

    Asserted rather than assumed: without the redirect the first test here
    writes `data/jobs.db` into the repository, and every later run inherits
    whatever the last one queued — including, once `POST /quote` exists, a real
    4.6-hour replay sitting in `queued`.
    """
    assert "jobs.db" in jobs.db_path().name
    assert "data" not in jobs.db_path().parts[-2:-1] or "tmp" in str(jobs.db_path())


def test_a_submitted_job_starts_queued_and_is_logged(conn) -> None:
    job_id = jobs.submit(conn, "quote", {"pool": "0xabc"})

    row = jobs.get(conn, job_id)
    assert row["status"] == "queued"
    assert json.loads(row["params_json"]) == {"pool": "0xabc"}
    assert [e["kind"] for e in jobs.events(conn, job_id)] == ["queued"]


def test_only_one_worker_can_claim_a_job(conn) -> None:
    """The race that costs two 4.6-hour replays rather than a stack trace."""
    jobs.submit(conn, "quote", {"pool": "0xabc"})

    first = jobs.claim(conn, pid=1)
    second = jobs.claim(conn, pid=2)

    assert first is not None
    assert second is None, "a second worker claimed a job already running"
    assert jobs.get(conn, first["id"])["worker_pid"] == 1


def test_claims_take_the_oldest_job_first(conn) -> None:
    first = jobs.submit(conn, "quote", {"n": 1})
    jobs.submit(conn, "quote", {"n": 2})

    assert jobs.claim(conn, pid=1)["id"] == first


def test_refused_is_a_terminal_state_of_its_own(conn) -> None:
    """A replay that reports the evidence is too thin has succeeded.

    Filing it as `failed` would tell a caller to retry something that will
    refuse again for the same good reason, and would make the product's central
    honesty look like a bug.
    """
    job_id = jobs.submit(conn, "quote", {})
    jobs.claim(conn, pid=1)
    jobs.finish(conn, job_id, "refused", refusal={"note": "4 usable replays, need 20"})

    row = jobs.get(conn, job_id)
    assert row["status"] == "refused"
    assert row["result_json"] is None
    assert "need 20" in row["refusal_json"]
    assert row["status"] in jobs.FINISHED


def test_a_state_that_is_not_terminal_is_refused_at_the_boundary(conn) -> None:
    job_id = jobs.submit(conn, "quote", {})
    with pytest.raises(ValueError, match="terminal"):
        jobs.finish(conn, job_id, "running")


def test_progress_beats_the_heart(conn) -> None:
    """The heartbeat is what tells a killed worker from a slow one."""
    job_id = jobs.submit(conn, "quote", {})
    jobs.claim(conn, pid=1)
    conn.execute("UPDATE job SET heartbeat_ts = 0 WHERE id = ?", (job_id,))

    jobs.progress(conn, job_id, 3, 20, phase="replaying")

    row = jobs.get(conn, job_id)
    assert (row["done"], row["total"], row["phase"]) == (3, 20, "replaying")
    assert row["heartbeat_ts"] > 0


def test_a_worker_that_died_leaves_an_orphan_not_a_ghost(conn) -> None:
    """Neither "still going" nor "failed" is true, so there is a third word."""
    job_id = jobs.submit(conn, "quote", {})
    jobs.claim(conn, pid=1)
    conn.execute("UPDATE job SET heartbeat_ts = 0 WHERE id = ?", (job_id,))

    assert jobs.sweep_orphans(conn) == [job_id]

    row = jobs.get(conn, job_id)
    assert row["status"] == "orphaned"

    last = jobs.events(conn, job_id)[-1]
    assert last["kind"] == "orphaned"
    assert last["payload"]["remedy"] == "resubmit"


def test_the_sweep_leaves_a_job_that_is_still_beating(conn) -> None:
    """A slow replay is not a dead one, and the sweep must not take it."""
    job_id = jobs.submit(conn, "quote", {})
    jobs.claim(conn, pid=1)
    jobs.progress(conn, job_id, 1, 20)

    assert jobs.sweep_orphans(conn) == []
    assert jobs.get(conn, job_id)["status"] == "running"


def test_the_sweep_does_not_requeue(conn) -> None:
    """Restarting a 4.6-hour replay because a process died is a decision."""
    job_id = jobs.submit(conn, "quote", {})
    jobs.claim(conn, pid=1)
    conn.execute("UPDATE job SET heartbeat_ts = 0 WHERE id = ?", (job_id,))
    jobs.sweep_orphans(conn)

    assert jobs.claim(conn, pid=2) is None, "the sweep put an orphan back on the queue"


def test_events_replay_from_a_sequence_number(conn) -> None:
    """What an SSE client reconnects with, so a drop costs nothing."""
    job_id = jobs.submit(conn, "quote", {})
    jobs.claim(conn, pid=1)
    jobs.progress(conn, job_id, 1, 3)
    jobs.progress(conn, job_id, 2, 3)

    everything = jobs.events(conn, job_id)
    # queued, running, and one per progress call — the lifecycle is in the log,
    # not only the progress, which is what lets a client that connects late
    # reconstruct what happened rather than just where it got to.
    assert [e["kind"] for e in everything] == ["queued", "running", "progress", "progress"]
    assert [e["seq"] for e in everything] == [1, 2, 3, 4]
    assert jobs.events(conn, job_id, after=2) == everything[2:]


def test_a_queued_job_can_be_withdrawn(conn) -> None:
    job_id = jobs.submit(conn, "quote", {})

    assert jobs.cancel(conn, job_id) is True
    assert jobs.get(conn, job_id)["status"] == "cancelled"
    assert jobs.claim(conn, pid=1) is None


def test_a_running_job_cannot_be_cancelled(conn) -> None:
    """Stopping a replay mid-window leaves a partial nobody can interpret.

    The honest surface is that a job can be withdrawn from the queue, not that
    arithmetic can be interrupted.
    """
    job_id = jobs.submit(conn, "quote", {})
    jobs.claim(conn, pid=1)

    assert jobs.cancel(conn, job_id) is False
    assert jobs.get(conn, job_id)["status"] == "running"


def test_the_listing_narrows_without_losing_the_rest(conn) -> None:
    jobs.submit(conn, "quote", {})
    other = jobs.submit(conn, "crawl", {})
    jobs.claim(conn, pid=1)

    assert [j["id"] for j in jobs.listing(conn, kind="crawl")] == [other]
    assert len(jobs.listing(conn)) == 2
    assert len(jobs.listing(conn, status="queued")) == 1
