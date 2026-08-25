"""What a personal quote would cost to produce, and whether it is possible.

`replay/ranges.py::quote()` measures 4.6 hours for four agents on the 30-day
tape and is process-global non-reentrant, so it lives behind a job queue and a
worker process rather than behind a request. `POST /quote` enqueues; the worker
in `ops/worker.py` runs it; `GET /quote/job/{id}` and its `/stream` report it.

The pre-flight comes first and refuses first. A refusal that arrives in a
hundred milliseconds and names the missing tape beats a spinner that resolves
into the same refusal twenty minutes later — so `POST /quote` recomputes the
engine's own sufficiency predicate *before* enqueueing anything, and returns 409
rather than a job id when the answer is already no.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from misquote.api import rpc
from misquote.api.errors import refuse
from misquote.api.locations import db_path
from misquote.api.preflight import assess
from misquote.api.wallet import _valid
from misquote.chain.addresses import known_pools_on, pool_by_address
from misquote.chain.positions import PositionReader
from misquote.indexer.store import connect_readonly
from misquote.ops import jobs

DEFAULT_CHAIN_ID = 56


def _conn() -> Any:
    path = db_path()
    if not path.exists():
        raise refuse(
            503,
            error=f"no tape at {path}",
            remedy="make indexer POOL=0x...",
            note="Nothing has indexed anything yet, so no quote is possible for any pool.",
        )
    return connect_readonly(path)


def quote_preflight(chain_id: int = DEFAULT_CHAIN_ID) -> dict[str, Any]:
    """Per verified pool: could the tape support a quote, and if not, why not."""
    pools = known_pools_on(chain_id)
    conn = _conn()
    try:
        assessed = [assess(conn, ref) for ref in pools]
    finally:
        conn.close()

    return {
        "chain_id": chain_id,
        "pools": assessed,
        "quotable": [a["pool"] for a in assessed if a["quotable"]],
        "note": (
            "Quotable means the tape could support a replay, not that one has run. "
            "A quote is a 4.6-hour job on the 30-day tape and is not served from a "
            "request; this is the check that runs before one is queued."
        ),
    }


def quote_eligibility(address: str, chain_id: int = DEFAULT_CHAIN_ID) -> dict[str, Any]:
    """One wallet: what it holds, and which of it could be quoted.

    Three states per position, and they are deliberately not collapsed into two.
    A position in a pool we never verified is unquotable for a reason no amount
    of indexing time fixes; a position in a verified pool whose tape is too thin
    is unquotable *today*. Reporting both as "no" would tell a reader to wait
    for something that is never coming.
    """
    if not _valid(address):
        raise refuse(
            400,
            error=f"{address!r} is not a 20-byte hex address",
            remedy="pass a 0x-prefixed 40-hex-digit address",
            note=(
                "Refused before the chain read: an unreachable address and an empty "
                "wallet return the same thing from an RPC, and a typo must not come "
                "back as 'you hold nothing'."
            ),
        )

    pools = known_pools_on(chain_id)
    w3 = rpc.connect(chain_id)
    found = PositionReader(w3, chain_id).read(address, pools)

    conn = _conn()
    try:
        by_pool = {ref.address.lower(): assess(conn, ref) for ref in pools}
    finally:
        conn.close()

    holdings = []
    for pool, positions in found.in_known_pools.items():
        check = by_pool.get(pool, {})
        try:
            label = pool_by_address(pool).label
        except ValueError:  # pragma: no cover — it came from known_pools_on
            label = ""
        holdings.append(
            {
                "pool": pool,
                "label": label,
                "positions": len(positions),
                "open_positions": sum(1 for p in positions if p.is_open),
                "quotable": check.get("quotable", False),
                "why_not": check.get("why_not", []),
                "plan": check.get("plan"),
            }
        )

    return {
        "owner": found.owner,
        "chain_id": chain_id,
        "read_at_block": found.read_at_block,
        "held": len(found.held),
        # Named separately from "not quotable". Indexing will never make these
        # quotable; a thin tape will.
        "in_unverified_pools": found.unknown_pool_count,
        "holdings": holdings,
        "note": (
            "A position in a pool this repository has not verified cannot be replayed "
            "at all — its fee tier and protocol cut decide what its swaps mean. A "
            "position in a verified pool with too little tape cannot be replayed yet. "
            "Those are different absences and are reported separately."
        ),
    }


def submit_quote(payload: dict[str, Any]) -> dict[str, Any]:
    """Enqueue a replay, or refuse before anyone waits.

    The pre-flight runs synchronously and its verdict is the response: a 409
    here costs a hundred milliseconds, and the alternative is a job id that
    resolves twenty minutes later into the same sentence.
    """
    address = str(payload.get("pool") or "")
    try:
        ref = pool_by_address(address)
    except ValueError as error:
        raise refuse(
            404,
            error=str(error),
            remedy="quote a pool this repository has verified",
            available=[p.address for p in known_pools_on(DEFAULT_CHAIN_ID)],
            note=(
                "A pool's fee tier and protocol cut decide what its swaps mean, so an "
                "unchecked address would produce a complete, plausible, wrongly-"
                "denominated quote."
            ),
        ) from error

    conn = _conn()
    try:
        check = assess(conn, ref)
    finally:
        conn.close()

    if not check["quotable"]:
        raise refuse(
            409,
            error="the tape cannot support a quote for this pool",
            remedy=check["remedy"] or f"make indexer POOL={ref.address}",
            note=" · ".join(check["why_not"]),
        )

    store = jobs.connect()
    try:
        job_id = jobs.submit(
            store,
            "quote",
            {
                "pool": ref.address,
                "capital_quote": payload.get("capital_quote"),
                "windows": payload.get("windows"),
            },
        )
        last_seen = jobs.worker_last_seen(store)
    finally:
        store.close()

    return {
        "job_id": job_id,
        "status": "queued",
        "poll": f"/quote/job/{job_id}",
        "stream": f"/quote/job/{job_id}/stream",
        "preflight": check["plan"],
        # Whether anything is draining the queue, reported at submit time.
        #
        # Without this the failure is silent and indistinguishable from a slow
        # replay: the POST succeeds, the job sits `queued`, and the page shows
        # "queued" forever. On a deployment where the worker was never
        # provisioned it would show that indefinitely, and nothing in the
        # response would hint why.
        "worker_last_seen": last_seen,
        "note": (
            "Queued, not computed. A full run is hours of arithmetic, not seconds."
            if last_seen
            else "Queued — but nothing has claimed a job on this instance, so it may "
            "sit here. Start a worker with `make api-worker`."
        ),
    }


def quote_job_status(job_id: str) -> dict[str, Any]:
    """Where a job got to, including the two terminal states that are not errors."""
    store = jobs.connect()
    try:
        row = jobs.get(store, job_id)
        if row is None:
            raise refuse(
                404,
                error=f"no job {job_id!r}",
                remedy="POST /quote to enqueue one",
                note="Job ids are not guessable; this is an absence, not a permission error.",
            )
        log = jobs.events(store, job_id)
    finally:
        store.close()

    return {
        "job_id": job_id,
        "kind": row["kind"],
        "status": row["status"],
        "progress": {"done": row["done"], "total": row["total"], "phase": row["phase"]},
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "refusal": json.loads(row["refusal_json"]) if row["refusal_json"] else None,
        "events": len(log),
        "note": _STATE_NOTES.get(str(row["status"]), ""),
    }


#: What each terminal state means, in the response rather than in documentation.
#:
#: `refused` and `failed` are one word apart and mean opposite things about
#: whether retrying is sensible, so the body says which.
_STATE_NOTES = {
    "queued": "waiting for a worker to claim it",
    "running": "a worker is replaying; progress is a record, see the stream",
    "done": "the replay finished and produced a range",
    "refused": "the replay finished and the evidence could not support a quote. Retrying "
    "will refuse again for the same reason.",
    "failed": "something broke. This is a fault, not an answer, and is worth retrying.",
    "cancelled": "withdrawn from the queue before it started",
    "orphaned": "the worker holding it stopped reporting. The attempt did not finish and "
    "nothing is working on it.",
}


async def quote_job_stream(job_id: str, request: Request) -> StreamingResponse:
    """Server-sent events, replayed from the log rather than tailed from memory.

    `Last-Event-ID` is honoured, so a dropped connection costs nothing: the
    events are rows and the client asks for the ones past the last it saw. A
    stream that could only forward what happened next would make a one-hour job
    unwatchable from a laptop that slept.
    """
    after = int(request.headers.get("last-event-id") or 0)

    async def events() -> Any:
        store = jobs.connect()
        cursor = after
        try:
            while True:
                if await request.is_disconnected():
                    return

                for event in jobs.events(store, job_id, after=cursor):
                    cursor = event["seq"]
                    yield f"id: {event['seq']}\nevent: {event['kind']}\ndata: {json.dumps(event['payload'])}\n\n"
                    if event["kind"] in jobs.FINISHED:
                        return

                row = jobs.get(store, job_id)
                if row is None:
                    yield 'event: failed\ndata: {"error": "no such job"}\n\n'
                    return

                # A comment frame, because Render's proxy closes an idle
                # connection and a job can legitimately be quiet for minutes.
                yield ": keepalive\n\n"
                await asyncio.sleep(POLL_S)
        finally:
            store.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Without this, a buffering proxy holds every frame until the
            # response ends — which for a one-hour job is the whole point missed.
            "X-Accel-Buffering": "no",
        },
    )


#: How often the stream looks for new events. Rows, not a subscription: SQLite
#: has no push, and a two-second poll on a job measured in minutes is cheap.
POLL_S = 2.0
