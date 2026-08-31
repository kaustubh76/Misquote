"""Prometheus metrics for the live agent loop, and what happens without them.

`pyproject.toml` has declared `prometheus-client` in an `ops` extra since the
project started; nothing imported it. `tests/test_layering.py` bans it from the
pure layers — a guard on code that was never written. The ledger called the
package "docstring only", pointing at `ops/__init__.py`, which stayed true of
that one file while a 700-line job queue grew beside it.

## Absent by default, and absent honestly

`prometheus_client` is an **optional** dependency, so this module must work when
it is not installed. It does that by keeping the metric objects behind a registry
that degrades to no-ops rather than by wrapping every call site in a try/except —
a counter that raises on increment would take the agent down for the sake of
observability, which is the wrong way round.

`available()` says which it is, so `/metrics` can return a refusal naming the
extra instead of an empty page that looks like a working exporter with nothing to
report. Those two are indistinguishable to a scraper, and only one of them is a
fact about the agent.

## What is measured, and what deliberately is not

Counters for decisions, actions and failures; a gauge for the agent's last
heartbeat. **No PnL, no fee APR, no position value.** Those come from the replay
accountant and the tearsheet, where they are computed once with their assumptions
attached — a second, differently-derived copy exported here is exactly how two
numbers in one system come to disagree, which is the defect this project is named
after and has already caught twice (P-8, the equity pool's protocol fee).
"""

from __future__ import annotations

import os
from typing import Any

#: Where the **agent loop** serves its own `/metrics`, when asked. `0` — the
#: default — starts nothing.
#:
#: `make api` already exposes `/metrics` for that process. This is for the case
#: the API does not cover: `make warden`, `make grid` and `make sentinel` are
#: separate processes with no HTTP server, so without this their counters exist
#: and nothing can read them.
#:
#: Read at import rather than at serve time on purpose. A port that could change
#: under a running agent would mean the scrape target moves without the scraper
#: being told, and "the exporter is on a different port now" reads exactly like
#: "the agent died".
DEFAULT_PORT = int(os.environ.get("PROMETHEUS_PORT", "0") or 0)

_registry: Any | None = None
_metrics: dict[str, Any] = {}


class _Noop:
    """Stands in for a metric when `prometheus-client` is not installed.

    Every method returns self so a chained `labels(...).inc()` works, and none
    of them raises. The alternative — letting the import error out at the call
    site — makes observability able to stop the agent.
    """

    def labels(self, *_args: Any, **_kwargs: Any) -> _Noop:
        return self

    def inc(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def observe(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def available() -> bool:
    """Is `prometheus-client` installed? Asked rather than assumed.

    `uv sync --extra ops` installs it. Without it every metric below is a no-op
    and `/metrics` refuses rather than serving an empty exposition, because an
    exporter with no metrics and an agent doing nothing look identical.
    """
    try:
        import prometheus_client  # noqa: F401
    except ImportError:
        return False
    return True


def _build() -> dict[str, Any]:
    global _registry
    if not available():
        return {
            name: _Noop()
            for name in (
                "decisions",
                "actions",
                "action_failures",
                "polls_refused",
                "heartbeat",
                "kill_switch",
            )
        }

    from prometheus_client import CollectorRegistry, Counter, Gauge

    _registry = CollectorRegistry()
    return {
        "decisions": Counter(
            "misquote_decisions_total", "Policy decisions made", ["agent"], registry=_registry
        ),
        "actions": Counter(
            "misquote_actions_total",
            "Actions the executor was handed",
            ["agent", "kind"],
            registry=_registry,
        ),
        "action_failures": Counter(
            "misquote_action_failures_total",
            "Actions that raised",
            ["agent"],
            registry=_registry,
        ),
        "polls_refused": Counter(
            "misquote_polls_refused_total",
            "Chain polls the endpoint refused",
            ["agent"],
            registry=_registry,
        ),
        # A gauge of *when*, not a boolean of *whether*. "Is it alive" is a
        # question about a clock, and a boolean written by the agent itself
        # cannot answer it: a process that has hung stops updating either one,
        # and only the timestamp shows how long ago that was.
        "heartbeat": Gauge(
            "misquote_heartbeat_timestamp_seconds",
            "Unix time of the agent's last completed cycle",
            ["agent"],
            registry=_registry,
        ),
        "kill_switch": Gauge(
            "misquote_kill_switch_engaged",
            "1 when the kill file is present",
            ["agent"],
            registry=_registry,
        ),
    }


def metric(name: str) -> Any:
    """One metric by name, built lazily on first use."""
    global _metrics
    if not _metrics:
        _metrics = _build()
    return _metrics.get(name, _Noop())


def serve(port: int | None = None) -> int | None:
    """Start the loop's own exporter, or return None having started nothing.

    Returns the port actually listening so a caller can print it — a log line
    saying "metrics on 9090" when nothing bound is worse than silence.

    **Never raises.** Three ways this legitimately does nothing: the port is
    unset (the default), the extra is not installed, or the port is taken. None
    of them is a reason to stop an agent from trading, which is the same rule
    `alerts.notify` follows.
    """
    chosen = DEFAULT_PORT if port is None else int(port)
    if chosen <= 0 or not available():
        return None
    if not _metrics:
        metric("decisions")  # force the build, and with it the registry

    try:
        from prometheus_client import start_http_server

        start_http_server(chosen, registry=_registry)
    except Exception:  # noqa: BLE001 — observability must not stop the agent
        return None

    # Confirm it answers, rather than trusting that `start_http_server` raised.
    #
    # It does not raise on a port already in use: it sets `allow_reuse_address`,
    # and on macOS that binds over a listening socket without complaint. So the
    # naive version returned a port number for an exporter that was not the one
    # answering there — which sends an operator to a URL that responds with
    # somebody else's data, the one failure mode worse than no exporter at all.
    if not _answers(chosen):
        return None
    return chosen


def _answers(port: int, *, timeout: float = 1.0) -> bool:
    """Does our exporter answer on this port? One request, then done."""
    import http.client

    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.request("GET", "/metrics")
        response = conn.getresponse()
        body = response.read(4096)
        conn.close()
    except Exception:  # noqa: BLE001
        return False
    # Our registry always carries at least one `misquote_` family, because
    # `serve` forces the build before starting. Anything else on this port is
    # not us.
    return response.status == 200 and b"misquote_" in body


def exposition() -> tuple[bytes, str]:
    """The `/metrics` body and its content type, or a refusal.

    Raises `RuntimeError` when the extra is absent, so a route can turn that into
    a 501 that names the install command. Returning an empty body would be the
    dishonest option: a scraper cannot tell it from a healthy agent that has done
    nothing.
    """
    if not available():
        raise RuntimeError(
            "prometheus-client is not installed; `uv sync --extra ops` adds it. "
            "An empty exposition would be indistinguishable from an agent that "
            "has made no decisions."
        )
    if not _metrics:
        metric("decisions")  # force the build, and with it the registry

    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return generate_latest(_registry), CONTENT_TYPE_LATEST


__all__ = ["DEFAULT_PORT", "available", "exposition", "metric", "serve"]
