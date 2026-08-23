"""The loop that claims jobs, and the promise that it always finishes one.

The failure this guards is not a crash. It is a row left saying `running` after
the thing running it has gone — because that is indistinguishable from a worker
still working, and the orphan sweep will not touch it for five minutes.
"""

from __future__ import annotations

import pytest

from misquote.ops import jobs, worker


@pytest.fixture
def conn():
    connection = jobs.connect()
    yield connection
    connection.close()


def test_drain_returns_when_the_queue_is_empty(conn) -> None:
    """`once` is what makes the loop testable without a clock."""
    assert worker.drain(conn, once=True) == 0


def test_it_runs_what_it_claims(conn) -> None:
    seen: list[str] = []
    worker.HANDLERS["probe"] = lambda c, job_id, params: (
        seen.append(params["n"]),
        jobs.finish(c, job_id, "done", result={"n": params["n"]}),
    )
    try:
        jobs.submit(conn, "probe", {"n": "a"})
        jobs.submit(conn, "probe", {"n": "b"})

        assert worker.drain(conn, once=True) == 2
        assert seen == ["a", "b"], "jobs ran out of submission order"
        assert [j["status"] for j in jobs.listing(conn)] == ["done", "done"]
    finally:
        del worker.HANDLERS["probe"]


def test_a_handler_that_raises_still_finishes_the_job(conn) -> None:
    """The row must never be left `running` by an exception.

    A `running` row with no worker behind it is the one state the sweep is slow
    to catch and a reader cannot interpret, so the failure path closes it
    immediately and records what happened.
    """

    def explode(c, job_id, params):
        raise ZeroDivisionError("the tape had no hours in it")

    worker.HANDLERS["probe"] = explode
    try:
        job_id = jobs.submit(conn, "probe", {})
        worker.drain(conn, once=True)

        row = jobs.get(conn, job_id)
        assert row["status"] == "failed"
        assert "ZeroDivisionError" in row["refusal_json"]
        # The traceback travels with the record: a worker may be on a host whose
        # logs nobody can reach, and a failure a caller cannot diagnose is
        # barely better than a hang.
        assert "traceback" in row["refusal_json"]
    finally:
        del worker.HANDLERS["probe"]


def test_an_unknown_kind_is_refused_rather_than_left_running(conn) -> None:
    job_id = jobs.submit(conn, "no-such-kind", {})
    worker.drain(conn, once=True)

    row = jobs.get(conn, job_id)
    assert row["status"] == "failed"
    assert "no handler" in row["refusal_json"]


def test_a_refusing_handler_is_not_recorded_as_a_failure(conn) -> None:
    """The distinction the whole store exists to keep."""
    worker.HANDLERS["probe"] = lambda c, job_id, params: jobs.finish(
        c, job_id, "refused", refusal={"note": "4 usable replays, need 20"}
    )
    try:
        job_id = jobs.submit(conn, "probe", {})
        worker.drain(conn, once=True)
        assert jobs.get(conn, job_id)["status"] == "refused"
    finally:
        del worker.HANDLERS["probe"]


def test_the_quote_handler_is_registered() -> None:
    """`test_no_dead_definitions` cannot see a dict value; this names it."""
    from misquote.ops import quote_job

    assert worker.HANDLERS["quote"] is quote_job.run
