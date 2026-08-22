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

Nor does it write, sign, or reach a chain. It is `GET` only, over files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
    "router": "make showcase-demo",
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
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"no artifact named {name!r}",
                "remedy": REMEDIES.get(name, "see `make help` for the emitters"),
                "available": artifact_names(),
                # Absent and not-yet-generated are different sentences, and a
                # bare 404 collapses them.
                "note": (
                    "This is a file nobody has generated, or a name that does not exist. "
                    "Both are absences and neither is an empty result."
                ),
            },
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
        raise HTTPException(
            status_code=503,
            detail={
                "error": f"{name}.json is on disk and could not be read: {error}",
                "note": "An emitter may be writing it. This is a transient state, not a failure.",
            },
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
        # it. `BuildStamp.tsx` renders the same flag for the same reason.
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
        entries.append({"name": name, "readable": True, "bytes": path.stat().st_size, **_stamp(blob)})

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
    allow_methods=["GET"],
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
        },
        "note": (
            "This serves what the emitters wrote and computes nothing. The same files "
            "are published by the static site; what is here and not there is the "
            "provenance census at /artifacts."
        ),
    }


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
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"the index lists no agent {slug!r}",
                "available": [s for s in known if s],
                "remedy": REMEDIES["index"],
            },
        )
    return artifact(slug)
