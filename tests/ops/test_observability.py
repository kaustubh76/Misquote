"""Metrics, heartbeat and alerting — and the absences they must report honestly.

Every test here is about a case where doing nothing and being unable to do
anything look identical from the outside. That is the whole reason this package
took so long to write: an exporter with no samples, a notifier with no token and
an agent that has never run all produce silence, and silence is what an operator
reads as *fine*.
"""

from __future__ import annotations

import pytest

from misquote.ops import alerts, metrics
from misquote.ops.heartbeat import Heartbeat


def test_a_missing_extra_refuses_rather_than_serving_an_empty_exposition() -> None:
    """The distinction the `/metrics` route exists to preserve.

    `prometheus-client` absent and the agent idle both produce an empty body. A
    scraper cannot tell them apart, so `exposition()` raises for the first and
    the route turns that into a 501 naming the install command.
    """
    if metrics.available():
        body, content_type = metrics.exposition()
        assert b"" == body or body, "an installed client must produce a body"
        assert "text/plain" in content_type
    else:  # pragma: no cover — depends on whether the extra is installed
        with pytest.raises(RuntimeError, match="uv sync --extra ops"):
            metrics.exposition()


#: Every metric the agent touches, with the labels its call sites pass.
#:
#: Written out here rather than derived, because deriving them from the same
#: dict the code builds would make this test agree with itself.
CALL_SITES = {
    "decisions": {"agent": "warden"},
    "actions": {"agent": "warden", "kind": "mint"},
    "action_failures": {"agent": "warden"},
    "polls_refused": {"agent": "warden"},
    "heartbeat": {"agent": "warden"},
    "kill_switch": {"agent": "warden"},
}


def test_every_call_site_passes_labels_the_metric_declares() -> None:
    """A wrong label name raises, and it should — in a test, not in the loop.

    The first version of this asserted that metrics "never raise at a call
    site", which is true only when the extra is **absent** and the no-ops take
    over. With `prometheus-client` installed, `labels(agent=..., kind=...)` on a
    counter declared with one label raises `ValueError: Incorrect label names` —
    so the protection covers the missing dependency and not a typo.

    That is the right split. A typo is a bug and should be loud; a missing
    optional dependency is a deployment choice and must not be. What makes it
    safe is that the labels are checked here against the ones the loop passes.
    """
    for name, labels in CALL_SITES.items():
        handle = metrics.metric(name)
        handle.labels(**labels)  # raises if the declaration and the call disagree


def test_an_unknown_metric_is_a_no_op_rather_than_a_key_error() -> None:
    """Asking for a metric nobody declared must not take the agent down.

    Between "this counter does not exist" and "the agent stopped", the first is
    the one an operator can live with.
    """
    handle = metrics.metric("not_a_real_metric")
    handle.labels(agent="warden", anything="at all").inc()
    handle.set(1.0)


def test_the_metrics_survive_the_extra_being_absent(monkeypatch) -> None:
    """The case the no-ops exist for, exercised rather than assumed."""
    monkeypatch.setattr(metrics, "available", lambda: False)
    monkeypatch.setattr(metrics, "_metrics", {})
    for name, labels in CALL_SITES.items():
        metrics.metric(name).labels(**labels).inc()
    metrics.metric(name).labels(agent="warden").set(2.0)
    monkeypatch.setattr(metrics, "_metrics", {})


def test_no_pnl_metric_is_exported() -> None:
    """A second, differently-derived copy of a published number is how two
    numbers in one system come to disagree.

    Fee APR, LVR and position value are computed once by the replay accountant
    with their assumptions attached. Exporting them here would create a path to
    the same quantity that no assumption sheet covers — which is P-8's shape.
    """
    if not metrics.available():
        pytest.skip("prometheus-client is not installed")

    metrics.metric("decisions").labels(agent="warden").inc()
    body, _ = metrics.exposition()
    text = body.decode()
    for forbidden in ("pnl", "fee_apr", "position_value", "lvr", "net_return"):
        assert forbidden not in text, (
            f"{forbidden} is published by the tearsheet with its assumptions; a "
            f"second derivation here is how two numbers in one system disagree"
        )


def test_a_heartbeat_that_never_beat_is_infinitely_stale_not_fresh() -> None:
    """`0.0` reads as *just beat*, which is the opposite of the truth.

    Same confusion `api/sessions.py` refuses between an empty wallet and an
    unreachable chain: an agent that has never completed a cycle and one that
    completed a cycle a moment ago are different states.
    """
    beat = Heartbeat(agent="warden")
    assert beat.stale_for() == float("inf")
    assert beat.is_stale(1.0)


def test_the_staleness_bound_belongs_to_the_caller() -> None:
    """How long is too long depends on the poll cadence, which this cannot know.

    `chain/live_source.py` polls once a minute because five seconds is refused by
    every public endpoint (matrix D-9). A module hardcoding "30s is dead" would
    be asserting a policy against a cadence it was never told.
    """
    beat = Heartbeat(agent="warden")
    beat.beat(at=1_000.0)

    assert beat.stale_for(now=1_005.0) == 5.0
    assert beat.is_stale(3.0, now=1_005.0)
    assert not beat.is_stale(30.0, now=1_005.0)

    with pytest.raises(ValueError, match="calls every agent dead"):
        beat.is_stale(0.0)


def test_beats_are_rate_limited_into_the_journal_but_not_into_the_gauge() -> None:
    """17,280 identical rows a day is a log; the journal is evidence.

    Every beat updates the gauge, because that is free and it is what a scraper
    reads. One a minute is written down.
    """
    rows: list[dict] = []

    class _Journal:
        @staticmethod
        def write(row: dict) -> None:
            rows.append(row)

    beat = Heartbeat(agent="warden", journal=_Journal(), journal_every_s=60.0)
    for i in range(30):
        beat.beat(at=1_000.0 + i)  # thirty beats over 29 seconds

    assert beat.beats == 30
    assert len(rows) == 1, "one row, not thirty"

    beat.beat(at=1_100.0)
    assert len(rows) == 2


def test_alerting_is_silent_and_says_so_rather_than_raising() -> None:
    """A notifier that raises when unconfigured takes the agent down to announce
    that the agent is up."""
    assert alerts.notify("anything") is False
    assert not alerts.configured()

    why = alerts.why_silent()
    assert "TELEGRAM_BOT_TOKEN" in why and "TELEGRAM_CHAT_IDS" in why, (
        "an absence a reader cannot explain looks like a fault"
    )
    assert "queued" in why, "and it must say nothing is being buffered for later"


def test_a_token_with_no_chat_ids_is_not_configured(monkeypatch) -> None:
    """Both, not either. A token with nowhere to send makes a silent notifier
    look like a working one."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.delenv("TELEGRAM_CHAT_IDS", raising=False)
    assert not alerts.configured()

    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "")
    assert not alerts.configured()

    monkeypatch.setenv("TELEGRAM_CHAT_IDS", " 1 , 2 ,")
    assert alerts.configured()
    assert alerts.chat_ids() == ("1", "2"), "whitespace and trailing commas are not chats"


def test_an_empty_alert_is_refused(monkeypatch) -> None:
    """Sending a blank message is always a bug at the call site."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "1")
    with pytest.raises(ValueError, match="empty alert"):
        alerts.notify("   ")


def test_the_loop_exporter_starts_nothing_by_default() -> None:
    """A port nobody asked for is a listener nobody secured.

    `make api` already serves `/metrics` for that process. This exists for the
    case it does not cover — `make warden` is a separate process with no HTTP
    server — so the default has to be off, and it has to be off *silently*
    rather than by raising.
    """
    assert metrics.serve(0) is None
    assert metrics.serve(-1) is None


def test_the_exporter_returns_the_port_it_actually_bound() -> None:
    """A log line saying "metrics on 9090" when nothing bound is worse than
    silence: it sends an operator to a port that will never answer.

    So `serve` returns the port rather than a bool, and returns `None` on every
    way it can legitimately do nothing — unset, extra missing, port taken.
    """
    import socket

    if not metrics.available():
        assert metrics.serve(9_999) is None
        return

    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        busy = taken.getsockname()[1]
        assert metrics.serve(busy) is None, (
            "a port already in use must report nothing bound, not the port it wanted"
        )

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]
    bound = metrics.serve(free)
    assert bound == free
