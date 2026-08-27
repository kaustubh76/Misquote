"""The artifacts, over HTTP, without adding a single number to them.

    uv run uvicorn misquote.api.service:app --port 8000
    uv run uvicorn misquote.api.service:app --host 0.0.0.0 --port $PORT   # Render

## What this is for, stated honestly

`next.config.ts` is `output: "export"`, so `apps/web/public/artifacts/*.json` is
copied verbatim into the static site and already served over HTTP by whatever
hosts it. **This API does not make the data reachable — it was already
reachable.** Claiming otherwise would be the kind of overstatement the rest of
this repository exists to catch.

Two things it does add, and they are the only two:

1. **A census with provenance.** A static host answers "give me
   `warden.json`" and nothing else. It cannot answer "which of these were
   produced by the same commit", or "which record no commit at all" — and on
   this project that second question has a real answer that mattered: six
   artifacts published replay results with no `git_sha` for weeks, which is why
   `go_no_go.py`'s freshness gate sat UNVERIFIED. `/artifacts` answers it.

2. **Refusals that name a remedy.** A static host returns its own 404 page for a
   file nobody has generated. That is indistinguishable from a typo in the URL,
   and it tells a reader nothing about how to fix it. Here, a missing artifact
   comes back with the command that writes it.

## What it deliberately does not do

No computation, no aggregation, no derived fields. Every figure in a response
body is bytes an emitter wrote. The moment this file starts computing a summary,
it becomes a second implementation of something `tearsheet/` already does, and
the two will disagree — which is this project's name.

It does not sign, and it holds no key. It does now reach a chain — for a
wallet's positions and for an agent card the survey never sampled — and it does
accept one write verb: `POST /quote`, which creates a job and computes nothing
itself. What has not changed is the artifact surface: those routes serve bytes
an emitter wrote, and `tests/api/test_app.py` asserts that nothing under
`/artifacts` accepts a write verb.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from misquote.api import journal as journal_routes
from misquote.api import pools as pools_routes
from misquote.api import quote as quote_routes
from misquote.api import registry as registry_routes
from misquote.api import sessions as sessions_routes
from misquote.api import tape as tape_routes
from misquote.api import vetting as vetting_routes
from misquote.api import wallet as wallet_routes
from misquote.api.errors import refuse

REPO = Path(__file__).resolve().parents[3]

#: Overridable so a host can point at a bundled copy without a checkout layout.
ARTIFACTS = Path(
    os.environ.get("MISQUOTE_ARTIFACTS", REPO / "apps" / "web" / "public" / "artifacts")
)

#: What writes each artifact, for the refusal to quote when one is absent.
#: Keyed by stem so a new artifact without an entry still resolves to something
#: true rather than to a confident wrong command.
REMEDIES: dict[str, str] = {
    "index": "make showcase-demo",
    "warden": "make showcase-demo",
    "grid": "make showcase-demo",
    "sentinel": "make showcase-demo",
    # `make router-card`, not `make showcase-demo`. The allocation card is
    # written by `scripts/router_showcase.py`, which `showcase.py` does not
    # call — so this line answered a reader's "how do I generate this?" with a
    # command that would run, succeed, and not produce the file.
    "router": "make router-card",
    "advantage": "make advantage",
    "advantage_short": "make advantage-short",
    "assumptions": "make assumptions",
    "build": "make artifacts",
    "status": "make status",
    "registry": "make registry",
    "vetting": "make vet && make vetting",
    "vectors": "make vectors-report",
    "venue": "make venue",
    "addresses": "make addresses",
    "api": "make api-config",
}


def artifact_names() -> list[str]:
    """Every artifact on disk, by stem, sorted.

    Read per call rather than cached at import. An emitter can write a new file
    while this process is up, and a cached list would answer a question about
    the directory as it was when the container started — which is exactly the
    staleness this module's census exists to report on.
    """
    if not ARTIFACTS.is_dir():
        return []
    return sorted(p.stem for p in ARTIFACTS.glob("*.json"))


def _path_for(name: str) -> Path:
    """Resolve a stem to a file, refusing anything that is not one of ours.

    Membership in the directory listing, never string sanitising. `name` arrives
    from the URL, and `ARTIFACTS / name` with a crafted value walks out of the
    directory — the classic traversal. Checking against `artifact_names()` means
    the only reachable paths are files this function just enumerated, so there
    is no expression a caller can supply that reaches a seventeenth file.
    """
    if name not in artifact_names():
        raise refuse(
            404,
            error=f"no artifact named {name!r}",
            remedy=REMEDIES.get(name, "see `make help` for the emitters"),
            available=artifact_names(),
            # Absent and not-yet-generated are different sentences, and a
            # bare 404 collapses them.
            note=(
                "This is a file nobody has generated, or a name that does not exist. "
                "Both are absences and neither is an empty result."
            ),
        )
    return ARTIFACTS / f"{name}.json"


def _load(name: str) -> Any:
    path = _path_for(name)
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        # A half-written artifact is not an artifact. 503 rather than 500: an
        # emitter is very likely mid-write, and the correct advice is to retry —
        # which is a different instruction from "this is broken".
        raise refuse(
            503,
            error=f"{name}.json is on disk and could not be read: {error}",
            remedy=f"retry; if it persists, {REMEDIES.get(name, 'see `make help`')}",
            note="An emitter may be writing it. This is a transient state, not a failure.",
        ) from error


def _stamp(blob: Any) -> dict[str, Any]:
    """The provenance an artifact records about itself, or the fact it records none.

    `build.git_sha` for most; the top level for `build.json`, which *is* the
    stamp. Absence is reported as a field rather than omitted, because a caller
    that sees no key cannot tell "unstamped" from "this endpoint forgot".
    """
    if not isinstance(blob, dict):
        return {"records_commit": False}

    build = blob.get("build") if isinstance(blob.get("build"), dict) else {}
    sha = build.get("git_sha") or blob.get("git_sha")
    if not isinstance(sha, str) or not sha:
        return {"records_commit": False}

    return {
        "records_commit": True,
        "git_sha": sha,
        # Carried, never smoothed over. A dirty tree is what makes a sha a lie:
        # the commit is real and the code that produced these numbers is not in
        # it. `apps/web/src/app/vectors/view.tsx` renders the same flag for the
        # same reason.
        #
        # That path is a correction. This comment named a build-stamp component
        # that was planned and never written, which is the exact defect
        # `tests/web/test_comment_references.py` exists to catch — and the
        # component is not named here even to describe the mistake, because the
        # guard suffix-matches and cannot tell a citation from a post-mortem.
        "git_dirty": bool(build.get("git_dirty") or blob.get("git_dirty")),
        "generated_at": build.get("generated_at") or blob.get("generated_at"),
        "command": build.get("command") or blob.get("command"),
        "source": build.get("source") or blob.get("source"),
    }


def census() -> dict[str, Any]:
    """Every artifact, what commit it records, and how much the set agrees.

    The one question a static host cannot answer. `unstamped` is the field with
    history behind it: six artifacts published replay results carrying no commit
    at all, which is why the readiness gate reported UNVERIFIED rather than
    passing, and nothing surfaced it to a reader for weeks.

    `commits` is a list, not a boolean. Artifacts legitimately differ — a run
    that did not touch a file leaves its stamp alone — so "they disagree" is not
    a fault, and reducing it to `consistent: false` would state one.
    """
    entries = []
    for name in artifact_names():
        path = ARTIFACTS / f"{name}.json"
        try:
            blob = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            entries.append({"name": name, "readable": False, "records_commit": False})
            continue
        entries.append(
            {"name": name, "readable": True, "bytes": path.stat().st_size, **_stamp(blob)}
        )

    stamped = [e for e in entries if e.get("records_commit")]
    return {
        "artifacts": entries,
        "total": len(entries),
        "stamped": len(stamped),
        "unstamped": [e["name"] for e in entries if not e.get("records_commit")],
        "commits": sorted({e["git_sha"] for e in stamped}),
        "dirty": sorted(e["name"] for e in stamped if e.get("git_dirty")),
    }


app = FastAPI(
    title="Misquote artifacts",
    version="1",
    description=(
        "Read-only access to the artifacts the emitters write. Adds no figure to "
        "them: every number in a response body is bytes an emitter produced."
    ),
)

# The same JSON is already public on the static site, so there is nothing here
# to protect by origin. Restricting it would only stop a browser reading data it
# can already fetch from the other host.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # POST because `/quote` creates a job, and OPTIONS because a browser sends a
    # preflight before any POST carrying a content-type. Omitting OPTIONS is the
    # subtle half: the POST route existed and worked from curl, and the page
    # failed with a bare "TypeError: Failed to fetch" — no status, no body, and
    # nothing in the service log, because the request the browser actually made
    # first was the one that was refused.
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness, and explicitly not a statement about the data.

    A health check that went red when an artifact was missing would take the
    service down for a condition the service is built to report. So this answers
    "is the process up", and `artifacts_present` is reported beside it as
    information rather than as the verdict.
    """
    names = artifact_names()
    return {
        "ok": True,
        "artifacts_present": len(names),
        "artifacts_dir": str(ARTIFACTS),
        "note": "ok reflects the process, not the freshness or completeness of the artifacts",
    }


@app.get("/")
def index() -> dict[str, Any]:
    return {
        "service": "Misquote artifacts",
        "reads": str(ARTIFACTS),
        "routes": {
            "/health": "liveness",
            "/artifacts": "every artifact with the commit it records",
            "/artifacts/{name}": "one artifact, verbatim",
            "/agents": "the generated agent index",
            "/agents/{slug}": "one agent card, verbatim",
            "/tape": "what the indexed tape holds, per verified pool",
            "/tape/{address}": "one pool's coverage, longest contiguous run, and holes",
            "/journal": "which agents have written a decision journal",
            "/journal/{agent}": "one agent's decisions, as appended",
            "/vetting": "which pools carry a due-diligence badge, and which do not",
            "/vetting/{address}": "one pool's recorded badge",
            "/pools": "which pool, at what width, as P25-P75 bands over the tape",
            "/pools/{address}": "one pool's width ladder and demand, refusal included",
            "/registry/agents": "search the surveyed agents, with the coverage that search had",
            "/registry/agents/{agent_id}": "one agent, from the survey or from chain",
            "/wallet/{address}/positions": "a wallet's v3 positions, and which we could replay",
            "/quote/preflight": "whether each pool's tape could support a quote",
            "/quote/eligibility/{address}": "what one wallet holds, and which of it is quotable",
            "/sessions/capability": "what activation would consist of, and why it is not possible",
            "/sessions/{owner}": "the grants an address holds, once there is a module to ask",
            "POST /quote": "enqueue a replay, or refuse before anyone waits",
            "/quote/job/{job_id}": "where a queued replay got to",
            "/quote/job/{job_id}/stream": "the same, as server-sent events",
        },
        "note": (
            "The artifact routes serve what the emitters wrote and add nothing to it. "
            "The tape and journal routes answer live questions a static host cannot: "
            "what the database holds right now, and what the agents actually did. "
            "Neither computes a metric — the tape reports coverage, the journal "
            "reports rows, and the one summary is `read_journal`'s own return value."
        ),
    }


# Registered here rather than with `include_router`, and the difference is not
# stylistic. Under FastAPI 0.141 an included router lands in `app.routes` as a
# single opaque `_IncludedRouter` with no `.path` and no `.endpoint`, so its
# handlers are invisible to `test_every_handler_is_actually_routed` — which is
# the *only* thing keeping them visible to `tests/test_no_dead_definitions.py`,
# because a route decorator is not a reference any AST scan can see. Mounting by
# router would have quietly removed four public functions from both guards at
# once. `add_api_route` flattens them into real `APIRoute` objects, and the
# wiring stays assertable.
for _path, _handler in (
    ("/tape", tape_routes.tape),
    ("/tape/{address}", tape_routes.tape_for_pool),
    ("/journal", journal_routes.journals),
    ("/journal/{agent}", journal_routes.journal),
    ("/vetting", vetting_routes.vetting),
    ("/vetting/{address}", vetting_routes.badge),
    ("/pools", pools_routes.pools),
    ("/pools/{address}", pools_routes.pool),
    ("/registry/agents", registry_routes.registry_agents),
    ("/registry/agents/{agent_id}", registry_routes.registry_agent),
    ("/wallet/{address}/positions", wallet_routes.wallet_positions),
    ("/quote/preflight", quote_routes.quote_preflight),
    ("/quote/eligibility/{address}", quote_routes.quote_eligibility),
    ("/sessions/capability", sessions_routes.sessions_capability),
    ("/sessions/{owner}", sessions_routes.sessions_for),
    ("/quote/job/{job_id}", quote_routes.quote_job_status),
    ("/quote/job/{job_id}/stream", quote_routes.quote_job_stream),
):
    app.add_api_route(_path, _handler, methods=["GET"])

# The one write verb on this service, and a POST rather than a GET because it
# creates something: a queued job with an id. `tests/api/test_app.py` asserts
# separately that nothing under `/artifacts` accepts a write verb — that is
# where the read-only guarantee still holds, and it is worth restating there
# now that it is no longer true of the service as a whole.
app.add_api_route("/quote", quote_routes.submit_quote, methods=["POST"], status_code=202)


@app.get("/artifacts")
def artifacts() -> dict[str, Any]:
    return census()


@app.get("/artifacts/{name}")
def artifact(name: str) -> JSONResponse:
    """One artifact, byte-for-byte what the emitter wrote.

    Returned unwrapped. Nesting it under a `data` key would mean every consumer
    reads a different shape here from the one the static site serves for the
    same file, and the two surfaces would drift apart for no gain. Provenance
    goes in a header instead, where it cannot alter the body.
    """
    blob = _load(name)
    stamp = _stamp(blob)
    return JSONResponse(
        content=blob,
        headers={
            "X-Misquote-Commit": stamp.get("git_sha") or "none recorded",
            "X-Misquote-Dirty": "true" if stamp.get("git_dirty") else "false",
        },
    )


@app.get("/agents")
def agents() -> dict[str, Any]:
    """The agent index, and the fourth category it deliberately does not build.

    `not_built` is passed through rather than filtered. It is the list of things
    this marketplace does not have, published on purpose, and an API that
    returned only `agents` would quietly turn a stated absence into a silence.
    """
    blob = _load("index")
    return {
        "agents": blob.get("agents", []),
        "not_built": blob.get("not_built", []),
        "source": blob.get("source"),
        "pool": blob.get("pool"),
        "counterfactual": blob.get("counterfactual"),
        "badge": blob.get("badge"),
        "provenance": _stamp(blob),
    }


@app.get("/agents/{slug}")
def agent(slug: str) -> JSONResponse:
    """One agent's card.

    Resolved through the index rather than by treating the slug as a filename.
    `generateStaticParams` builds exactly the routes `index.json` lists, and the
    site and this API should refuse the same set — otherwise a slug 404s in one
    place and answers in the other.
    """
    known = [a.get("slug") for a in _load("index").get("agents", [])]
    if slug not in known:
        raise refuse(
            404,
            error=f"the index lists no agent {slug!r}",
            remedy=REMEDIES["index"],
            available=[s for s in known if s],
        )
    return artifact(slug)
