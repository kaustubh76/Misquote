"""Every published advantage says which tape it came from.

The site answers one question in two places. `advantage.json` is the track's
judged deliverable — each task done both ways, agent against DIY — and each
agent card answers the same question for its own policy. They are separate
replays over separate tape, and they are allowed to disagree.

What they are not allowed to do is disagree silently. On the tree this file was
written against:

    /advantage        Protect — Sentinel   −38.17pp   source: chain
    /agent/sentinel   Sentinel             +0.72pp    source: synthetic

A sign flip, one click apart, both pages confident and neither mentioning the
other. `scripts/showcase.py` calls mistaking one tape for the other "the failure
this whole project is named after"; this is that failure committed to the
project's own site.

The views are fixed — `SourceBanner` now leads every card, and each side carries
the other's figure and a link to it. What is guarded here is the precondition
those views depend on: a page can only disclose a source if the artifact records
one. An emitter that stops writing `source`, or starts publishing a `delta_pp`
without one, would take the disclosure off the page without failing anything —
`readArtifact` returns `undefined` rather than throwing, and the banner would
simply render its other branch.

Nothing here asserts the two runs agree. Requiring that would forbid the thing
the report exists to do.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO / "apps" / "web" / "public" / "artifacts"

# The report and the cards. Named rather than globbed: a new artifact that
# publishes a delta should have to be added here deliberately, with whoever adds
# it deciding what its span is.
REPORTS = ("advantage.json", "advantage_short.json")
CARDS = ("warden.json", "grid.json", "sentinel.json")


def _load(name: str) -> dict:
    path = ARTIFACTS / name
    if not path.exists():
        pytest.skip(f"{name} has not been generated")
    return json.loads(path.read_text())


def _deltas(blob: dict) -> list[tuple[str, dict]]:
    """Every block in an artifact that publishes a `delta_pp`, with its label.

    Two shapes carry one: a card's `advantage`, and each row of a report's
    `tasks`. Anything else growing a `delta_pp` is a third shape nobody has
    thought about the source of, and the test below will say so.
    """
    found: list[tuple[str, dict]] = []

    advantage = blob.get("advantage")
    if isinstance(advantage, dict) and "delta_pp" in advantage:
        found.append((blob.get("agent", "advantage"), advantage))

    for task in blob.get("tasks", []):
        if isinstance(task, dict) and "delta_pp" in task:
            found.append((task.get("task", "<unnamed task>"), task))

    return found


@pytest.mark.parametrize("name", REPORTS + CARDS)
def test_every_published_advantage_records_its_tape(name: str) -> None:
    blob = _load(name)
    blocks = _deltas(blob)

    assert blocks, (
        f"{name} publishes no delta_pp anywhere this test knows to look. Either "
        "it stopped comparing, or it grew a third shape for the comparison and "
        "_deltas() needs to learn it — the second case would drop this file out "
        "of the guard while looking like it passes."
    )

    # Per block first, then the artifact's own. `advantage.json` records a
    # source on every task because its tasks can be replayed separately and two
    # of them were; `advantage_short.json` predates that field and carries only
    # the report-level one. Either is a real answer to "which tape"; neither is
    # optional.
    for label, block in blocks:
        source = block.get("source") or blob.get("source")
        assert isinstance(source, str) and source.strip(), (
            f"{name} publishes a delta_pp for {label!r} with no source at any "
            "level. The page renders `source !== 'chain'` as a synthetic-tape "
            "warning, so a missing source does not fail — it silently claims "
            "the number came from a generated tape, or, if the emitter ever "
            "writes 'chain' by default, that it came from history."
        )


@pytest.mark.parametrize("name", CARDS)
def test_every_card_records_how_much_tape_it_read(name: str) -> None:
    """A source without a span is half a disclosure.

    "Synthetic" and "62.2 hours" are one qualification. A reader who is told the
    first and not the second knows the history is generated but not that the
    verdict rests on two and a half days of it — and the card states a P25–P75
    band and a "bands do not overlap" separation on that basis.
    """
    blob = _load(name)
    hours = blob.get("replay", {}).get("hours")

    assert isinstance(hours, (int, float)), (
        f"{name} records no replay.hours, so the banner has no span to state "
        "beside its source."
    )
    assert hours > 0, (
        f"{name} publishes a replay of {hours} hours. A band computed over no "
        "tape is not a refusal — it is a claim with nothing behind it, and the "
        "card would render it exactly like one that has."
    )


def test_the_disagreement_is_visible_rather_than_averaged() -> None:
    """Where the same agent is judged twice, both answers survive.

    This is the fact the pages exist to show, asserted as a fact rather than as
    a requirement: the report and the cards may differ by any amount, but each
    figure has to remain attributable to a named tape. A future emitter that
    "reconciled" them by copying one into the other — or by dropping the loser
    — would pass every other test in this directory.
    """
    report = _load("advantage.json")
    tasks = {task.get("with_agent", ""): task for task in report.get("tasks", [])}

    judged_twice: list[str] = []
    for name in CARDS:
        card = _load(name)
        agent = card.get("agent")
        if not isinstance(agent, str) or "advantage" not in card:
            continue

        # The same join `apps/web/src/lib/counterpart.ts` uses: the card's bare
        # name against the start of the report's sentence, ending at the dash.
        # Kept deliberately simple here — this asserts the relation exists, and
        # `counterpart.test.ts` is what pins the matching rule.
        for column, task in tasks.items():
            if not column.lower().startswith(agent.lower()):
                continue
            judged_twice.append(agent)

            card_source = card.get("source")
            task_source = task.get("source") or report.get("source")
            assert card_source and task_source, (
                f"{agent} is judged in both {name} and advantage.json, and one "
                "of the two does not say which tape it read."
            )
            break

    assert judged_twice, (
        "no agent is judged in both the report and its own card, so the "
        "cross-reference on those pages resolves to nothing. Either the report "
        "stopped naming agents in `with_agent`, or the cards stopped carrying "
        "`agent` — both would empty the banner without failing a page test."
    )
