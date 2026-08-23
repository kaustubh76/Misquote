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
