"""Enqueueing a replay, and refusing before anyone waits for one.

A quote is 4.6 hours on the 30-day tape. Everything worth asserting here follows
from that: the pre-flight runs *before* a job id is minted, the refusal is a 409
and not a job that resolves into one later, and the two terminal states that are
not errors stay distinguishable from the one that is.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="the `api` extra is not installed — `uv sync --extra api`")

from fastapi.testclient import TestClient  # noqa: E402

from misquote.api import service as api  # noqa: E402
from misquote.chain.addresses import known_pools_on  # noqa: E402
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
    from misquote.ops.quote_job import INTERACTIVE_WINDOWS
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
    assert cost["estimated_seconds"] == round(cost["events"] / EVENTS_PER_SECOND)


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
    note = _queued_note(1_787_657_569, None)
    assert "does not report enough to estimate" in note
    assert "None" not in note


def test_an_unattended_queue_is_reported_before_any_duration() -> None:
    """A job behind no worker is not slow, it is unattended.

    From outside the two are identical — `queued` either way — and the estimate
    would make the unattended case read as a wait that ends.
    """
    from misquote.api.quote import _queued_note

    assert "nothing has claimed a job" in _queued_note(None, 397)
    assert "397" not in _queued_note(None, 397)
