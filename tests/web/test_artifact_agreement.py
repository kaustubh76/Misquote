"""A quantity published twice must be published the same both times.

`go_no_go.check_artifact_freshness` asks whether an artifact still describes the
engine that exists, and `test_artifact_projections` asks whether an artifact
still matches the constants it projects. Both compare an artifact to the code.
Nothing compared one artifact to another, and that is the gap a partial
regeneration falls straight through.

It did. `make showcase` rewrites the three LP cards and nothing else — Router's
card comes from `make router-card`, the advantage report from `make advantage` —
so a run of the first alone left the site saying both of these at once:

    /advantage, first task    agent loses to DIY by 64.29pp     built 23 Aug
    /agent/warden             agent beats DIY by 17.21pp        built 28 Aug

Eighty-one points apart, about one agent, on one site. `tearsheet/generate.py`
already names this class — "a ninety-point contradiction between two of this
project's own outputs, in the project whose entire argument is that its numbers
agree". Every published check passed: the numbers were each internally
consistent, each correctly derived, and each from a different run.

## What is compared, and what is not

`advantage.json` carries an `agent` block per task holding the replay it scored
— `fees`, `costs`, `in_range`, `mints` — and those values are *copied* from the
same run the card publishes. So they compare exactly, with no tolerance, and a
tolerance here would be a licence for the drift this exists to catch.

`delta_pp` is deliberately **not** compared. Both artifacts carry it and neither
copies it: the report recomputes the figure on its own capital basis, so the two
disagree by 0.02pp for Warden and 1.10pp for Sentinel even when everything is in
order. Asserting on it would need a threshold, and a threshold chosen to admit
1.10 is a threshold that admits most of what matters.

`advantage_short.json` is excluded for a different reason: it is a deliberately
short *synthetic* tape, so its replay is not the chain replay the cards publish
and the two are not supposed to match.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO / "apps" / "web" / "public" / "artifacts"

#: The agents that publish a card of their own.
AGENTS = ("warden", "grid", "sentinel", "router")

#: `with_agent` reads "Warden — Avellaneda–Stoikov recentring", and Router's
#: reads "Router - move only when…" with a plain hyphen. Both separators are
#: matched rather than normalised in the emitter, because the wording is prose
#: the report renders and this test is the one that has to bend.
NAMED = re.compile(r"\s*([A-Za-z]+)\s*[—–-]\s")

#: `advantage.json`'s per-task `agent` block, against the card's `replay` block.
#: Only the fields both sides carry; the report scores more than the card shows.
COPIED = {
    "fees": "fees_quote",
    "lvr_upper_bound": "lvr_quote_upper_bound",
    "costs": "costs_quote",
    "in_range": "in_range_fraction",
    "mints": "mints",
    "pulls": "pulls",
    "recentres": "rebalances",
}


def _load(name: str) -> dict | None:
    path = ARTIFACTS / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


@pytest.fixture(scope="module")
def report() -> dict:
    payload = _load("advantage.json")
    if not payload or not payload.get("tasks"):
        pytest.skip("no advantage report; run `make advantage`")
    return payload


def _agent_of(task: dict) -> str | None:
    """The card this task scored, or None where a task names no agent.

    One task is the venue choice — "pick the pool whose flow is not one-way" —
    and it has no card to disagree with. Skipped, not failed.
    """
    match = NAMED.match(str(task.get("with_agent") or ""))
    name = match.group(1).lower() if match else None
    return name if name in AGENTS else None


def test_every_advantage_task_agrees_with_the_agents_own_card(report: dict) -> None:
    """The replay the report scored is the replay the card publishes."""
    disagreements: list[str] = []
    compared = 0

    for task in report["tasks"]:
        name = _agent_of(task)
        if name is None:
            continue
        card = _load(f"{name}.json")
        if not card:
            continue

        replay = card.get("replay") or {}
        scored = task.get("agent") or {}
        compared += 1

        for key, field in COPIED.items():
            if key not in scored or field not in replay:
                continue
            if scored[key] != replay[field]:
                disagreements.append(
                    f"{name}: advantage.json scored {key}={scored[key]!r} "
                    f"but {name}.json publishes {field}={replay[field]!r} "
                    f"(report built at {report['build']['git_sha']}, "
                    f"card at {card['build']['git_sha']})"
                )

    assert compared, "no task was matched to a card — see the join test below"
    assert not disagreements, (
        "these artifacts were generated from different runs and the site "
        "publishes both:\n  " + "\n  ".join(disagreements) + "\n\nRegenerate the set in one pass: "
        "`make showcase && make router-card && make advantage`."
    )


def test_the_join_still_finds_the_agents(report: dict) -> None:
    """The check above is a join, and a join that matches nothing passes.

    `with_agent` is prose the report renders, so the day it is reworded this
    would go quietly green with every comparison skipped. That is the failure
    mode of every join and it is worth its own line: the emitter ships a task
    for each agent that has one, and finding fewer than two means the parse
    stopped working rather than the tasks going away.
    """
    named = [t for t in report["tasks"] if _agent_of(t) is not None]

    assert len(named) >= 2, (
        "fewer than two advantage tasks resolve to an agent card — "
        f"`with_agent` now reads {[t.get('with_agent') for t in report['tasks']]}, "
        "which this test's `NAMED` pattern no longer parses"
    )
