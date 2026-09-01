"""Enqueueing a replay, and refusing before anyone waits for one.

A quote is 4.6 hours on the 30-day tape. Everything worth asserting here follows
from that: the pre-flight runs *before* a job id is minted, the refusal is a 409
and not a job that resolves into one later, and the two terminal states that are
not errors stay distinguishable from the one that is.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="the `api` extra is not installed — `uv sync --extra api`")

from fastapi.testclient import TestClient  # noqa: E402

from misquote.api import service as api  # noqa: E402
from misquote.chain.addresses import (
    TARGET_POOL,  # noqa: E402
    known_pools_on,  # noqa: E402
)
from misquote.indexer.store import connect as connect_tape  # noqa: E402
from misquote.ops import jobs  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


@pytest.fixture
def pool() -> str:
    return known_pools_on(56)[0].address


def test_a_pool_we_never_verified_is_refused_before_anything_is_queued(
    client: TestClient,
) -> None:
    connect_tape(jobs.db_path().parent / "misquote.db").close()

    response = client.post("/quote", json={"pool": "0x000000000000000000000000000000000000dead"})
    assert response.status_code == 404
    assert "wrongly-" in response.json()["detail"]["note"]

    store = jobs.connect()
    try:
        assert jobs.listing(store) == [], "a refused request still queued a job"
    finally:
        store.close()


def test_a_tape_too_thin_to_quote_refuses_at_409(client: TestClient, pool: str) -> None:
    """The whole reason the pre-flight is synchronous.

    An empty tape cannot support a window, and the honest answer costs a
    hundred milliseconds. The alternative is a job id that resolves twenty
    minutes later into exactly this sentence.
    """
    connect_tape(jobs.db_path().parent / "misquote.db").close()

    response = client.post("/quote", json={"pool": pool})
    assert response.status_code == 409

    detail = response.json()["detail"]
    assert "make indexer" in detail["remedy"]
    assert "floor" in detail["note"] or "no swaps" in detail["note"]

    store = jobs.connect()
    try:
        assert jobs.listing(store) == [], "a 409 still queued a job"
    finally:
        store.close()


def test_no_tape_at_all_is_a_retry_rather_than_a_refusal(client: TestClient, pool: str) -> None:
    """503 and not 409: nothing was assessed, so nothing was refused."""
    response = client.post("/quote", json={"pool": pool})
    assert response.status_code == 503
    assert "make indexer" in response.json()["detail"]["remedy"]


def test_an_unknown_job_is_an_absence_not_a_permission_error(client: TestClient) -> None:
    response = client.get("/quote/job/nosuchjob")
    assert response.status_code == 404
    assert "not guessable" in response.json()["detail"]["note"]


def test_status_says_whether_retrying_is_sensible(client: TestClient) -> None:
    """`refused` and `failed` are one word apart and mean opposite things.

    The body carries which, because a caller looking at a status string alone
    cannot tell an answer from a fault.
    """
    store = jobs.connect()
    try:
        refused = jobs.submit(store, "quote", {"pool": "0x0"})
        jobs.claim(store, pid=1)
        jobs.finish(store, refused, "refused", refusal={"note": "4 usable replays, need 20"})

        failed = jobs.submit(store, "quote", {"pool": "0x0"})
        jobs.claim(store, pid=1)
        jobs.finish(store, failed, "failed", refusal={"error": "boom"})
    finally:
        store.close()

    refused_body = client.get(f"/quote/job/{refused}").json()
    assert refused_body["status"] == "refused"
    assert "refuse again" in refused_body["note"]
    assert refused_body["result"] is None
    assert refused_body["refusal"]["note"] == "4 usable replays, need 20"

    failed_body = client.get(f"/quote/job/{failed}").json()
    assert "worth retrying" in failed_body["note"]


def test_progress_is_reported_while_it_runs(client: TestClient) -> None:
    store = jobs.connect()
    try:
        job_id = jobs.submit(store, "quote", {"pool": "0x0"})
        jobs.claim(store, pid=1)
        jobs.progress(store, job_id, 3, 24, phase="replaying")
    finally:
        store.close()

    body = client.get(f"/quote/job/{job_id}").json()
    assert body["progress"] == {"done": 3, "total": 24, "phase": "replaying"}
    assert body["status"] == "running"


def test_the_stream_replays_the_log_and_closes_on_a_terminal_event(client: TestClient) -> None:
    """SSE from rows, not from memory.

    A client that connects after the job finished still gets the whole history,
    which is what makes a one-hour job watchable from a laptop that slept.
    """
    store = jobs.connect()
    try:
        job_id = jobs.submit(store, "quote", {"pool": "0x0"})
        jobs.claim(store, pid=1)
        jobs.progress(store, job_id, 1, 2)
        jobs.finish(store, job_id, "refused", refusal={"note": "too thin"})
    finally:
        store.close()

    with client.stream("GET", f"/quote/job/{job_id}/stream") as response:
        assert response.status_code == 200
        assert response.headers["x-accel-buffering"] == "no"
        body = "".join(response.iter_text())

    assert "event: queued" in body
    assert "event: progress" in body
    assert "event: refused" in body
    assert "id: 1" in body, "events must carry a Last-Event-ID"


def test_the_stream_honours_last_event_id(client: TestClient) -> None:
    """A dropped connection costs nothing; the client asks for what it missed."""
    store = jobs.connect()
    try:
        job_id = jobs.submit(store, "quote", {"pool": "0x0"})
        jobs.claim(store, pid=1)
        jobs.finish(store, job_id, "done", result={"p50": 1.0})
    finally:
        store.close()

    with client.stream(
        "GET", f"/quote/job/{job_id}/stream", headers={"Last-Event-ID": "2"}
    ) as response:
        body = "".join(response.iter_text())

    assert "event: queued" not in body, "already-seen events were resent"
    assert "event: done" in body


def test_submitting_says_whether_anything_will_run_it(client: TestClient, pool: str) -> None:
    """The silent failure this exists to prevent.

    With nothing draining the queue, `POST /quote` succeeds, returns a job id,
    and the row sits `queued` forever — which looks exactly like a slow replay
    and is not one. On a deployment where the worker was never provisioned it
    would look that way indefinitely, and nothing in the response would hint
    why. `render.yaml` ships with the worker commented out, so this is the
    ordinary state there, not an edge case.
    """
    from misquote.ops import jobs as job_store

    store = job_store.connect()
    try:
        assert job_store.worker_last_seen(store) is None, "a fresh queue has seen no worker"
    finally:
        store.close()


def test_a_claimed_job_is_evidence_that_a_worker_exists(client: TestClient) -> None:
    """Evidence, not proof: there is no worker registry, only jobs they touch."""
    from misquote.ops import jobs as job_store

    store = job_store.connect()
    try:
        job_store.submit(store, "quote", {"pool": "0x0"})
        job_store.claim(store, pid=1)
        assert job_store.worker_last_seen(store) is not None
    finally:
        store.close()


def test_the_quoted_duration_counts_the_replays_a_job_actually_runs() -> None:
    """The estimate must use A15's window count, not the engine's.

    Two window counts exist and both are right for their own question. The
    sufficiency plan uses the engine's 20, because the floor it tests is whether
    a *full* run could be quoted at all. A job runs
    `quote_job.INTERACTIVE_WINDOWS`, which is 8.

    Written first against the plan's, this promised 60 replays for work that is
    24 — a caller told to expect two and a half times the arithmetic they will
    get. A watched job is what caught it, reporting `7/24 replaying` against a
    response quoting a plan of sixty, so the assertion is against the constant
    the worker imports rather than against a number typed here.
    """
    from misquote.api.quote import replay_cost
    from misquote.core.types import Params
    from misquote.ops.quote_job import INTERACTIVE_WINDOWS, JOBS
    from misquote.replay.ranges import EVENTS_PER_SECOND, perturbations

    check = {
        "plan": {"windows": 20, "widest_window_hours": 120.0},
        "tape": {"swaps": 60_853, "hours": 240.0},
    }
    cost = replay_cost(check)

    expected_replays = INTERACTIVE_WINDOWS * len(perturbations(Params()))
    assert cost["replays"] == expected_replays
    assert cost["replays"] != check["plan"]["windows"] * len(perturbations(Params())), (
        "the estimate is counting the sufficiency plan's windows again"
    )

    # Half the tape per window, times the replays, at the engine's own rate.
    assert cost["events"] == int(expected_replays * 60_853 * 0.5)

    # Divided by the processes that will do it, which this had no term for.
    # `EVENTS_PER_SECOND` is one machine's figure recorded with no note of the
    # fan-out it was measured across, so the estimate silently assumed both the
    # cores and how many of them. On an instance running one process instead of
    # seven a caller was quoted 397 seconds for a job still going forty minutes
    # later — and understating a wait is the direction that costs the person
    # deciding whether to sit through it.
    assert cost["processes"] == JOBS
    assert cost["estimated_seconds"] == round(cost["events"] / (EVENTS_PER_SECOND * JOBS))
    assert cost["measured_here"] is False, "no run has been observed in this test"


def test_the_estimate_prefers_what_this_host_actually_achieved() -> None:
    """A constant describes somebody's laptop; a finished replay describes here.

    The fallback is only honest until the machine has evidence about itself. Once
    a job records its own throughput, quoting the constant instead would be
    choosing the less informed of two numbers in the field least able to defend
    itself.
    """
    from misquote.api.quote import replay_cost
    from misquote.ops.quote_job import JOBS

    check = {
        "plan": {"windows": 20, "widest_window_hours": 120.0},
        "tape": {"swaps": 60_853, "hours": 240.0},
    }
    slow = replay_cost(check, rate_per_process=100.0)
    fast = replay_cost(check, rate_per_process=10_000.0)

    assert slow["measured_here"] is True
    assert slow["estimated_seconds"] > fast["estimated_seconds"]
    assert slow["estimated_seconds"] == round(slow["events"] / (100.0 * JOBS))


def test_no_duration_is_quoted_when_the_tape_cannot_support_one() -> None:
    """Absent, never guessed.

    A duration is the field a caller is most likely to believe and the least
    able to check. A pool with no swaps, no span or no window gets `None` and a
    sentence saying so, rather than a confident zero.
    """
    from misquote.api.quote import _queued_note, replay_cost

    for tape, plan in (
        ({"swaps": 0, "hours": 240.0}, {"widest_window_hours": 120.0}),
        ({"swaps": 500, "hours": 0.0}, {"widest_window_hours": 120.0}),
        ({"swaps": 500, "hours": 240.0}, {"widest_window_hours": 0.0}),
        ({}, {}),
    ):
        cost = replay_cost({"tape": tape, "plan": plan})
        assert cost["estimated_seconds"] is None, (tape, plan)
        assert cost["events"] is None

    # And the sentence degrades with it rather than rendering "None seconds".
    note = _queued_note(1, None)
    assert "does not report enough to estimate" in note
    assert "None" not in note


def test_an_unattended_queue_is_reported_before_any_duration() -> None:
    """A job behind no worker is not slow, it is unattended.

    From outside the two are identical — `queued` either way — and the estimate
    would make the unattended case read as a wait that ends.
    """
    from misquote.api.quote import _queued_note

    assert "no worker has beaten" in _queued_note(0, 397)
    assert "397" not in _queued_note(0, 397)

    # And a live worker gets the duration rather than the warning.
    assert "397s" in _queued_note(1, 397) or "minutes" in _queued_note(1, 397)


def test_a_booted_worker_is_visible_before_it_claims_anything(tmp_path) -> None:
    """The state a fresh deploy is in, which the queue could not describe.

    `worker_last_seen` inferred a worker from the jobs it had touched and said
    so honestly — "evidence, not proof". On a new instance that inference cannot
    fire: a worker against an empty queue has touched nothing and reads exactly
    like no worker at all.

    That is the first thing anyone hiring meets, and it is the difference
    between "your job is next" and "your job is unattended". Found by watching a
    live deploy leave a job `queued` for three minutes with no way to tell which
    of the two it was.
    """

    os.environ["MISQUOTE_JOBS_DB"] = str(tmp_path / "jobs.db")
    from misquote.ops import jobs

    conn = jobs.connect()
    try:
        assert jobs.worker_last_seen(conn) is None
        assert jobs.workers_alive(conn) == 0

        jobs.announce(conn, pid=4242, host="render-abc")

        assert jobs.workers_alive(conn) == 1
        assert jobs.worker_last_seen(conn) is not None

        # Keyed by pid: a restarted worker replaces its own row rather than
        # leaving a ghost that keeps reporting a process that has gone.
        jobs.announce(conn, pid=4242, host="render-abc")
        assert jobs.workers_alive(conn) == 1

        jobs.announce(conn, pid=99, host="render-abc")
        assert jobs.workers_alive(conn) == 2
    finally:
        conn.close()


def test_a_worker_that_stopped_beating_is_not_counted_as_draining(tmp_path) -> None:
    """`worker_last_seen` stays true forever; a heartbeat expires.

    The note keys on the heartbeat for exactly this reason — on a long-lived
    instance whose worker died, "something drained this once" is true and
    useless, and would tell a caller to wait for a process that is gone.
    """
    import time

    os.environ["MISQUOTE_JOBS_DB"] = str(tmp_path / "jobs.db")
    from misquote.ops import jobs

    conn = jobs.connect()
    try:
        jobs.announce(conn, pid=7, host="h")
        assert jobs.workers_alive(conn) == 1

        stale = int(time.time()) - jobs.STALE_AFTER_S - 60
        conn.execute("UPDATE worker SET heartbeat_ts = ?", (stale,))

        assert jobs.workers_alive(conn) == 0, "a stale heartbeat still counts as alive"
        assert jobs.worker_last_seen(conn) is not None, "the trace should survive"
    finally:
        conn.close()


def test_the_worker_announces_itself_by_draining(tmp_path) -> None:
    """Not that `announce` works — that the worker calls it.

    The first version of these tests exercised `jobs.announce` directly and
    passed while the worker's call to it was removed. A guard on a helper nobody
    is proven to invoke is a guard on nothing, so this drives the real loop:
    `drain(once=True)` against an empty queue claims nothing, and a worker must
    still be visible afterwards.
    """

    os.environ["MISQUOTE_JOBS_DB"] = str(tmp_path / "jobs.db")
    from misquote.ops import jobs, worker

    conn = jobs.connect()
    try:
        assert jobs.workers_alive(conn) == 0

        ran = worker.drain(conn, once=True, idle_sleep_s=0.01)

        assert ran == 0, "nothing was queued, so nothing should have run"
        assert jobs.workers_alive(conn) == 1, (
            "the worker drained an empty queue and left no trace of itself — which "
            "is the state a fresh deploy is in, and reads as no worker at all"
        )
    finally:
        conn.close()


def test_the_hire_note_agrees_with_the_worker_count_it_reports(tmp_path) -> None:
    """A worker that stopped beating must not be quoted as draining.

    `worker_last_seen` stays true forever once anything has touched the queue,
    so keying the note on it tells a caller to wait for a process that has gone.
    This builds exactly that state — a heartbeat aged past the staleness floor,
    leaving `worker_last_seen` set and `workers_alive` at zero — and asserts the
    sentence follows the live count rather than the historical one.

    Runs against the tape a deploy actually carries, because the queued branch
    is only reached when the pre-flight says a quote is possible; an empty tape
    refuses at 409 and never gets here.
    """
    import time
    from pathlib import Path

    tape = Path(__file__).resolve().parents[2] / "data" / "deploy" / "tape.db"
    if not tape.is_file():
        pytest.skip("no deploy tape; run `make tape-slice`")

    os.environ["MISQUOTE_JOBS_DB"] = str(tmp_path / "jobs.db")
    os.environ["DB_PATH"] = str(tape)
    from misquote.api import quote as quote_routes

    conn = jobs.connect()
    try:
        jobs.announce(conn, pid=11, host="h")
        conn.execute(
            "UPDATE worker SET heartbeat_ts = ?", (int(time.time()) - jobs.STALE_AFTER_S - 60,)
        )
        assert jobs.worker_last_seen(conn) is not None
        assert jobs.workers_alive(conn) == 0
    finally:
        conn.close()

    body = quote_routes.submit_quote({"pool": TARGET_POOL.address})

    assert body["workers_alive"] == 0
    assert body["worker_last_seen"] is not None, "the historical trace should survive"
    assert "no worker has beaten" in body["note"], (
        "the note is keyed on worker_last_seen, which outlives the worker"
    )


def test_a_hire_answers_with_what_the_marketplace_already_has() -> None:
    """The 202 carries completed runs, not only a job id.

    A hire names a pool and `quote_job.run` replays the engine's *default*
    policy over it at eight windows. The cards publish something different and
    better — named agents at the engine's twenty, sixty observations apiece,
    already replayed and stamped with the commit that produced them.

    Returning only a job id made a marketplace with four agents look like one
    with none, which is the thing a judge hiring is there to evaluate.
    """
    from misquote.api.quote import published_runs

    runs = published_runs(TARGET_POOL.address)
    assert runs, "the flagship pool publishes agents and none were found"

    for run in runs:
        assert run["agent"], "a published run with no agent named"
        assert run["quote"], f"{run['agent']} publishes no quote"
        # The track record the rubric asks for: the window it was measured over,
        # how many observations, and how many finished in profit.
        assert run["windows"], f"{run['agent']} does not say how many windows"
        assert run["observations"], f"{run['agent']} does not say how many observations"
        assert run["net_positive"] is not None, f"{run['agent']} publishes no win count"
        assert run["net_positive"] <= run["observations"], "more wins than observations"
        # And the provenance, so a twenty-window published run is tellable from
        # an eight-window interactive one without being told which is which.
        assert (run["build"] or {}).get("git_sha"), f"{run['agent']} carries no commit"


def test_a_pool_with_no_published_run_says_so_rather_than_borrowing_one() -> None:
    """Empty is the ordinary answer, and it must not fall back to another pool.

    Three agents run on the flagship and none on the second venue. Matching on
    the label rather than the address would have made "WBNB/USDT 0.05%" and
    "WBNB/USDT 0.25%" one pool, and the second venue would have inherited the
    first's track record — which is this project's name.
    """
    from misquote.api.quote import published_runs
    from misquote.chain.addresses import TARGET_POOL_WIDE

    assert published_runs(TARGET_POOL_WIDE.address) == []
    assert published_runs("0x000000000000000000000000000000000000dead") == []


def test_the_note_points_at_the_published_runs_when_there_are_any() -> None:
    """A caller told only "queued" would not look for what is already there."""
    from misquote.api.quote import _queued_note

    assert "completed run(s)" in _queued_note(0, 397, 3)
    assert "completed run(s)" in _queued_note(1, 397, 3)
    # And says nothing when there is nothing to point at.
    assert "completed run(s)" not in _queued_note(1, 397, 0)


def test_the_hire_response_actually_carries_the_published_runs(tmp_path) -> None:
    """That `published_runs` works is not the claim — that the 202 carries it is.

    Asserted on the helper alone, this passed with `published = []` wired into
    the response: the marketplace would have gone back to answering a hire with
    a job id and nothing else, and every test still green. Second time this
    session that a guard sat on a function nobody was proven to call.
    """
    from pathlib import Path

    tape = Path(__file__).resolve().parents[2] / "data" / "deploy" / "tape.db"
    if not tape.is_file():
        pytest.skip("no deploy tape; run `make tape-slice`")

    os.environ["MISQUOTE_JOBS_DB"] = str(tmp_path / "jobs.db")
    os.environ["DB_PATH"] = str(tape)
    from misquote.api import quote as quote_routes

    body = quote_routes.submit_quote({"pool": TARGET_POOL.address})

    assert body["published"], "the hire returned a job id and nothing the marketplace has"
    assert {r["agent"] for r in body["published"]} == {
        r["agent"] for r in quote_routes.published_runs(TARGET_POOL.address)
    }
    assert "completed run(s)" in body["note"]
    # And the job is still queued: the published runs are an answer alongside
    # the fresh one, never a substitute that quietly skips the work asked for.
    assert body["status"] == "queued"
    assert body["job_id"]


def test_an_allocation_card_is_never_offered_as_a_published_run(tmp_path, monkeypatch) -> None:
    """Router's record is a different shape, and shape is what excludes it.

    `router.json` has no `quote_detail` and its `quote` is an object rather than
    a sentence. It misses the scan today only because its `pool` is null — an
    accident of the emitter, not a guarantee — so a card that is allocation-
    shaped *and* names the pool is the case that must still be skipped. The
    browser types `quote` as a string; handing it an object is the failure this
    guards.
    """
    import json as _json

    from misquote.api.quote import published_runs

    (tmp_path / "router.json").write_text(
        _json.dumps(
            {
                "kind": "allocation",
                "agent": "Router",
                "pool": f"WBNB/USDT · {TARGET_POOL.address}",
                "quote": {"basis": "net return on supplied capital"},
            }
        )
    )
    monkeypatch.setenv("MISQUOTE_ARTIFACTS", str(tmp_path))

    assert published_runs(TARGET_POOL.address) == [], (
        "an allocation card named the pool and was offered as an LP track record"
    )


def test_the_replay_reads_the_tape_the_service_reads(monkeypatch, tmp_path) -> None:
    """One `DB_PATH`, or the API and the worker answer about different files.

    `quote_job.run` hardcoded `data/misquote.db` while every other reader of the
    tape — `api/locations.py::db_path`, `go_no_go.py`, the agents — honours
    `DB_PATH`. On the deployment that is not a preference: the service answers
    `/tape` from the committed slice with 60,853 swaps for the target pool, and
    the replay opened a 245MB gitignored file absent from the checkout, found
    nothing, and refused with *"the tape holds no swaps for 0x3669…"*.

    Every word of that refusal was true about the file it opened and wrong about
    the pool. Asserted here as agreement between the two resolvers rather than
    against a literal path, so the next reader added to the system has to join
    them rather than pick its own default.
    """
    from misquote.api import locations
    from misquote.ops import quote_job

    tape = tmp_path / "slice.db"
    monkeypatch.setenv("DB_PATH", str(tape))

    assert locations.db_path() == tape

    # The function `run` calls, not a copy of its body — a test that reimplements
    # the expression it is checking passes whatever the code does.
    assert Path(quote_job.tape_db_path({})) == tape, (
        "the replay resolved a different tape than the service reads; that "
        "disagreement is reported to a caller as an absence, not as a "
        "misconfiguration"
    )


def test_an_explicit_db_path_in_the_params_still_wins(monkeypatch, tmp_path) -> None:
    """A job that names its tape means it. The environment is the fallback."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "from-env.db"))
    named = str(tmp_path / "from-params.db")

    from misquote.ops import quote_job

    assert quote_job.tape_db_path({"db_path": named}) == named
