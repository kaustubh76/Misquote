"""The API must serve the artifacts and add nothing to them.

Its whole claim is that every figure in a response body is bytes an emitter
wrote. That is a property worth a test rather than a docstring: the moment this
service computes a summary it becomes a second implementation of something
`tearsheet/` already does, and the two will disagree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# `fastapi` lives in the optional `api` extra, so a checkout installed without
# it has no API to test — and must say so rather than fail to collect. Without
# this, `make test` on a clean clone dies at import with a ModuleNotFoundError
# that looks like a broken suite instead of an absent extra.
#
# Installed here, so these run; a skip that always skips is worse than no test,
# and `test_the_extra_is_installed_in_this_checkout` is what keeps the skip from
# becoming permanent unnoticed. It lives in `tests/api/test_api_extra.py` rather
# than below this line, because a test written below an `importorskip` is
# skipped by the very condition it exists to detect. This comment named it as
# "below" for as long as it named a test that did not exist anywhere.
pytest.importorskip("fastapi", reason="the `api` extra is not installed — `uv sync --extra api`")

from fastapi.testclient import TestClient  # noqa: E402

from misquote.api import journal as journal_routes  # noqa: E402
from misquote.api import pools as pools_routes
from misquote.api import quote as quote_routes  # noqa: E402
from misquote.api import registry as registry_routes  # noqa: E402
from misquote.api import service as api  # noqa: E402
from misquote.api import sessions as sessions_routes  # noqa: E402
from misquote.api import tape as tape_routes  # noqa: E402
from misquote.api import vetting as vetting_routes  # noqa: E402
from misquote.api import wallet as wallet_routes  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


@pytest.fixture
def names() -> list[str]:
    found = api.artifact_names()
    if not found:
        pytest.skip("no artifacts on disk; run `make artifacts`")
    return found


def test_every_artifact_is_served_byte_for_byte(client: TestClient, names: list[str]) -> None:
    """The claim, asserted as equality rather than as a shape.

    Not "the response has the expected keys" — that passes on a service that
    rounds a float or drops a field it did not recognise. The parsed body must
    equal the parsed file, for every artifact, including the 179KB one.
    """
    for name in names:
        on_disk = json.loads((api.ARTIFACTS / f"{name}.json").read_text())
        served = client.get(f"/artifacts/{name}")
        assert served.status_code == 200, name
        assert served.json() == on_disk, f"{name} was altered in transit"


def test_the_body_is_not_wrapped(client: TestClient, names: list[str]) -> None:
    """Unwrapped, so this surface and the static site return the same shape.

    Nesting under a `data` key would make every consumer read one shape here and
    another from the export for the same file.
    """
    name = "venue" if "venue" in names else names[0]
    body = client.get(f"/artifacts/{name}").json()
    assert set(body) != {"data"}
    assert body == json.loads((api.ARTIFACTS / f"{name}.json").read_text())


def test_provenance_travels_in_headers_not_the_body(client: TestClient, names: list[str]) -> None:
    name = names[0]
    response = client.get(f"/artifacts/{name}")
    assert "X-Misquote-Commit" in response.headers
    assert response.json() == json.loads((api.ARTIFACTS / f"{name}.json").read_text())


def test_the_census_reports_unstamped_artifacts_rather_than_hiding_them(
    client: TestClient, names: list[str]
) -> None:
    """The one question a static host cannot answer.

    Six artifacts published replay results with no `git_sha` for weeks, which is
    why the readiness gate sat UNVERIFIED. A census that silently counted only
    the stamped ones would have reported the same clean number the whole time.
    """
    body = client.get("/artifacts").json()

    assert body["total"] == len(names)
    assert body["stamped"] + len(body["unstamped"]) == body["total"]
    assert set(body["unstamped"]).isdisjoint(
        {e["name"] for e in body["artifacts"] if e.get("records_commit")}
    )

    for entry in body["artifacts"]:
        assert "records_commit" in entry, (
            f"{entry['name']} does not say whether it records a commit"
        )


def test_a_missing_artifact_refuses_with_the_command_that_writes_it(client: TestClient) -> None:
    """A bare 404 is indistinguishable from a typo in the URL."""
    response = client.get("/artifacts/nothing_has_ever_written_this")
    assert response.status_code == 404

    detail = response.json()["detail"]
    assert "available" in detail and detail["available"]
    assert "remedy" in detail
    assert "absence" in detail["note"]


def test_a_known_artifact_that_is_absent_names_its_own_emitter(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`REMEDIES` is keyed by stem, so the advice is specific rather than generic."""
    monkeypatch.setattr(api, "ARTIFACTS", tmp_path)
    response = client.get("/artifacts/advantage")

    assert response.status_code == 404
    assert response.json()["detail"]["remedy"] == "make advantage"


@pytest.mark.parametrize(
    "attempt",
    [
        "../pyproject",
        "..%2F..%2Fpyproject",
        "....//pyproject",
        "%2e%2e%2fpyproject",
        "/etc/passwd",
        "warden/../../../pyproject",
    ],
)
def test_no_path_walks_out_of_the_artifacts_directory(client: TestClient, attempt: str) -> None:
    """Membership in the listing, never string sanitising.

    `ARTIFACTS / name` with a crafted value leaves the directory. Checking
    against `artifact_names()` means the only reachable paths are files that
    function just enumerated, so there is no expression that reaches a
    sixteenth file — including the encodings a sanitiser typically misses.
    """
    response = client.get(f"/artifacts/{attempt}")
    assert response.status_code in (404, 307), attempt
    if response.status_code == 404 and isinstance(response.json().get("detail"), dict):
        assert "pyproject" not in json.dumps(response.json())


def test_health_stays_up_when_there_are_no_artifacts(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Health is about the process, not the data.

    A check that went red on a missing artifact would take the service down for
    exactly the condition the service exists to report — and a host would then
    restart it in a loop while `/artifacts` was ready to explain the problem.
    """
    monkeypatch.setattr(api, "ARTIFACTS", tmp_path)
    body = client.get("/health").json()

    assert body["ok"] is True
    assert body["artifacts_present"] == 0


def test_the_agent_index_keeps_what_was_not_built(client: TestClient, names: list[str]) -> None:
    """`not_built` is a published absence, and filtering it would silence it."""
    if "index" not in names:
        pytest.skip("no index artifact")

    body = client.get("/agents").json()
    on_disk = json.loads((api.ARTIFACTS / "index.json").read_text())

    assert body["agents"] == on_disk["agents"]
    assert body["not_built"] == on_disk.get("not_built", [])
    assert "records_commit" in body["provenance"]


def test_an_agent_the_index_does_not_list_is_refused(client: TestClient, names: list[str]) -> None:
    """The site and this API must refuse the same set.

    `generateStaticParams` builds exactly the slugs `index.json` lists. A slug
    that 404s on the site and answers here is two products disagreeing about
    which agents exist.
    """
    if "index" not in names:
        pytest.skip("no index artifact")

    response = client.get("/agents/not-an-agent")
    assert response.status_code == 404
    assert "available" in response.json()["detail"]

    for slug in [a["slug"] for a in client.get("/agents").json()["agents"]]:
        assert client.get(f"/agents/{slug}").status_code == 200, slug


def test_a_half_written_artifact_is_transient_rather_than_broken(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """503, not 500. An emitter mid-write is a retry, not a fault."""
    monkeypatch.setattr(api, "ARTIFACTS", tmp_path)
    (tmp_path / "venue.json").write_text('{"divergences": [')

    response = client.get("/artifacts/venue")
    assert response.status_code == 503
    assert "writing it" in response.json()["detail"]["note"]


def test_a_browser_can_reach_the_one_write_route(client: TestClient) -> None:
    """The preflight, which is the request that actually fails first.

    CORS was `allow_methods=["GET"]` for as long as the service was read-only,
    and widening it was deferred until a POST route existed. When one did, the
    POST worked from curl and the page failed with a bare
    `TypeError: Failed to fetch` — no status, no body, nothing in the service
    log — because a browser sends `OPTIONS` before any POST carrying a
    content-type, and that was the request being refused.

    Asserted through the middleware rather than by reading the config, so the
    thing checked is what a browser would actually receive.
    """
    response = client.options(
        "/quote",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert "POST" in response.headers.get("access-control-allow-methods", "")


def test_no_artifact_route_accepts_a_write_verb(client: TestClient, names: list[str]) -> None:
    """The read-only guarantee, restated where it still holds.

    `POST /quote` exists now, so the service as a whole is no longer GET-only
    and the docstring that said so has been rewritten. What has not changed is
    the part worth guarding: the artifact routes read files an emitter wrote and
    must never grow a way to write one. Asserted here rather than left implied
    by the older test's name.
    """
    for method in (client.post, client.put, client.delete, client.patch):
        assert method("/artifacts").status_code == 405
        assert method(f"/artifacts/{names[0]}").status_code == 405
        assert method("/agents").status_code == 405


def test_the_service_is_read_only(client: TestClient, names: list[str]) -> None:
    """No verb but GET. This reads files and must never grow a way to write one."""
    for method in (client.post, client.put, client.delete, client.patch):
        assert method(f"/artifacts/{names[0]}").status_code == 405


def test_every_handler_is_actually_routed() -> None:
    """The decorator did its job, asserted rather than assumed.

    Two things make this worth its own test.

    **`tests/test_no_dead_definitions.py` cannot see a decorator.** It scans for
    identifiers that something loads, calls, imports or accesses, and a FastAPI
    handler is referenced by none of those — `@app.get("/health")` wires it and
    the name then appears nowhere. It flagged `health` for exactly that reason.
    The instruction it prints is "delete it, wire it up, or add it to ALLOWED
    with the reason", and of those three only one is true here: it *is* wired.
    An ALLOWED entry would record the opposite — that the name is deliberately
    unreferenced — so the reference belongs here, in an assertion that the
    wiring exists.

    **The other five pass that guard by coincidence.** `index`, `artifacts`,
    `artifact`, `agents` and `agent` are ordinary words this codebase uses in
    dozens of places, so the scan finds them whether or not they are routed. A
    handler that lost its decorator would keep passing. This does not.

    **And the list has to be the whole list.** A tuple of names checked one by
    one only proves the named ones are wired; handler number eleven, absent from
    it, would be routed, unasserted here, and invisible to the dead-definition
    scan — exactly the state this test exists to make impossible. So the tuple
    is also asserted to be complete, against every route whose handler this
    package defines. FastAPI's own `/docs`, `/redoc` and `/openapi.json` are
    excluded by that rule rather than by name, so a future version adding a
    seventh built-in does not fail us.
    """
    routed = {
        route.path: route.endpoint
        for route in api.app.routes
        if hasattr(route, "endpoint") and hasattr(route, "path")
    }

    expected = (
        ("/health", api.health),
        # Outside the `add_api_route` block in `service.py` because it returns a
        # `Response` with Prometheus's own content type rather than JSON, which
        # is exactly the case this tuple exists to catch.
        ("/metrics", api.prometheus_metrics),
        ("/", api.index),
        ("/artifacts", api.artifacts),
        ("/artifacts/{name}", api.artifact),
        ("/agents", api.agents),
        ("/agents/{slug}", api.agent),
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
        ("/quote", quote_routes.submit_quote),
        ("/quote/job/{job_id}", quote_routes.quote_job_status),
        ("/quote/job/{job_id}/stream", quote_routes.quote_job_stream),
    )

    for path, handler in expected:
        assert routed.get(path) is handler, f"{path} is not wired to {handler.__name__}"

    ours = {
        path
        for path, handler in routed.items()
        if getattr(handler, "__module__", "").startswith("misquote.api")
    }
    assert ours == {path for path, _ in expected}, (
        "a route this package defines is not in the tuple above. Add it — that "
        "tuple is the only reference tests/test_no_dead_definitions.py can see, "
        f"so a handler missing from it is a public function nothing appears to "
        f"use: {sorted(ours ^ {p for p, _ in expected})}"
    )


def test_included_routers_would_not_have_been_caught() -> None:
    """Why the new routes are added with `add_api_route`, not `include_router`.

    Under FastAPI 0.141 an included router lands in `app.routes` as one opaque
    `_IncludedRouter` with neither `.path` nor `.endpoint`, so the comprehension
    above skips it entirely and every handler inside it is silently unasserted —
    and, because a decorator is not a reference, silently invisible to the
    dead-definition scan as well. Mounting four handlers by router would have
    removed them from both guards in one line, and nothing would have gone red.

    This pins the shape rather than the version: if a future FastAPI starts
    flattening included routers, this fails and the comment above it is the
    thing to delete.
    """
    from fastapi import APIRouter, FastAPI

    probe = APIRouter()

    @probe.get("/probe")
    def _probe() -> dict[str, str]:
        return {}

    app = FastAPI()
    app.include_router(probe)

    reachable = [r for r in app.routes if getattr(r, "path", None) == "/probe"]
    assert not reachable, (
        "included routers now flatten into app.routes; add_api_route is no longer "
        "required and the comment in service.py explaining it is stale"
    )


def test_the_command_render_runs_reaches_the_app_it_names() -> None:
    """`render.yaml` -> `scripts/serve.sh` -> `misquote.api.service:app`.

    Three files and two string references, none of which any import resolves. A
    rename in the module breaks a deploy and nothing local notices, which is the
    whole reason to assert the spelling rather than trust it.

    The chain grew a link when the worker moved in beside uvicorn: the blueprint
    used to invoke uvicorn directly, and now it invokes a script that does. This
    test failed at exactly that change, which is the behaviour wanted — the
    assertion followed the command rather than being deleted for being
    inconvenient.
    """
    import importlib
    import os

    module = importlib.import_module("misquote.api.service")
    assert hasattr(module, "app"), "the start command points at misquote.api.service:app"

    blueprint = (REPO / "render.yaml").read_text()
    script_path = REPO / "scripts" / "serve.sh"
    assert "scripts/serve.sh" in blueprint, "the blueprint no longer runs the launcher"
    assert script_path.is_file(), "render.yaml runs a script that is not in the repository"
    assert os.access(script_path, os.X_OK), "scripts/serve.sh is not executable"

    script = script_path.read_text()
    assert "misquote.api.service:app" in script
    # Render assigns the port and routes to it; a hardcoded one is unreachable,
    # and binding localhost inside a container serves nobody outside it.
    assert "--host 0.0.0.0" in script
    assert "PORT" in script

    # The half that makes a hire finish. Without this the API still answers,
    # jobs still queue, and every one of them sits unclaimed forever.
    assert "misquote.ops.worker" in script, "the launcher no longer starts a worker"
    # `exec`, so Render's SIGTERM reaches uvicorn rather than a shell that would
    # have to forward it.
    assert "exec uvicorn" in script


def test_the_index_advertises_every_route_this_service_registers() -> None:
    """A route nobody can find is a route nobody has.

    `/pools` and `/pools/{address}` were registered here, unit-tested, and served
    — and named in neither of this service's two self-descriptions: `index()`'s
    routes map, nor `api.json`, which is what `/tape` renders for a reader
    looking for the API surface. `api/tape.py` exists because of the milder
    version of this: a route that *was* advertised and had no caller. This was
    worse, and nothing failed.

    The whole list, both directions. Advertising a route that does not exist is
    the same defect wearing the other face, and a hand-kept map drifts from a
    hand-kept registration by default rather than by accident.
    """
    registered = {
        route.path
        for route in api.app.routes
        if hasattr(route, "path")
        and hasattr(route, "endpoint")
        # This package's own handlers only: FastAPI's `/docs`, `/redoc` and
        # `/openapi.json` are excluded by where they come from rather than by
        # name, so a future built-in does not fail us.
        and getattr(route.endpoint, "__module__", "").startswith("misquote.")
    }
    # The POST is advertised with its verb, since that is what a caller types.
    advertised = {path.removeprefix("POST ") for path in api.index()["routes"]}
    # The index does not list itself. A reader holding this response has already
    # found it, and an entry for "/" would describe the thing they are reading.
    registered.discard("/")

    unadvertised = registered - advertised
    assert not unadvertised, (
        "these routes are served and named in no self-description, so nothing "
        f"pointing a reader at this API can mention them: {sorted(unadvertised)}"
    )

    phantom = advertised - registered
    assert not phantom, (
        f"the index advertises routes this service does not serve: {sorted(phantom)}"
    )


def test_the_published_api_config_advertises_the_same_routes() -> None:
    """`api.json` is the map a *page* reads, and it drifted from the service.

    `index()` answers a caller who already found the API. `api.json` is how the
    site tells a reader it exists at all — `/tape` renders that map — so a route
    missing here is missing from the only surface most readers will see.

    Subset rather than equality: the config deliberately publishes fewer entries
    than the service serves, because `/artifacts/{name}` and friends are the
    static surface every page already reads from disk. What it must not do is
    advertise something that is not there.
    """
    import importlib.util  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    source = Path(__file__).resolve().parents[2] / "scripts" / "emit_api_config.py"
    spec = importlib.util.spec_from_file_location("misquote_emit_api_config", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    registered = {
        route.path
        for route in api.app.routes
        if hasattr(route, "path") and hasattr(route, "endpoint")
    }
    published = {path.removeprefix("POST ") for path in module.config(base="")["routes"].values()}

    phantom = published - registered
    assert not phantom, (
        f"api.json points readers at routes this service does not serve: {sorted(phantom)}"
    )
    for path in ("/pools", "/pools/{address}"):
        assert path in published, (
            f"{path} is served and unadvertised — the failure `api/tape.py`'s own "
            "docstring describes, one step further along"
        )
