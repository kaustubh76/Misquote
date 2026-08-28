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

What is guarded here is the artifact contract, not any particular view: a run
that publishes a `delta_pp` must record the tape it came from. An emitter that
stops writing `source` would make the two runs indistinguishable in the files
themselves, which is where the distinction has to survive — a reader comparing
`advantage.json` against a card has nothing else to go on.

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
# Router included: it is a card, it carries a `source`, and the whole point
# of this file is that a card built from real flow and a card built from a
# random walk must never be indistinguishable. Router reads a different tape
# from the other three, which makes its disclosure more load-bearing rather
# than less.
CARDS = ("warden.json", "grid.json", "sentinel.json", "router.json")


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

    quote = blob.get("quote")
    if isinstance(quote, dict) and quote.get("sufficient") is False:
        # Same reason: a refusing card compares nothing, and the refusal is
        # what it is disclosing.
        return

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

    # A card that is *refusing* has no span to state, and that is the disclosure
    # rather than a gap in it. Router publishes this shape when there is no rate
    # tape — `make artifacts` must complete on a clean checkout, so the card
    # withholds instead of the build aborting. Its note names the command that
    # would fill it.
    quote = blob.get("quote")
    if isinstance(quote, dict) and quote.get("sufficient") is False:
        assert quote.get("note"), f"{name} withholds its quote and does not say why"
        return

    hours = blob.get("replay", {}).get("hours")

    assert isinstance(hours, (int, float)), (
        f"{name} records no replay.hours, so the banner has no span to state beside its source."
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


def test_a_synthetic_report_contains_no_chain_task() -> None:
    """A report cannot be part constructed and part real without saying so.

    `advantage.py`'s Route task reads the Venus rate tape from `--db`, which
    defaults to the real database whatever `--synthetic` says. So
    `make advantage-short` — the report whose whole purpose is *"the same three
    tasks on too little history, which every one of them refuses to quote"* —
    was about to gain a fourth task, from real chain data, that quotes fine.
    The demonstration would have disproved itself.

    `to_payload` already downgrades the report-level flag to `"mixed"` when the
    tasks disagree, so the artifact would not have *lied*; it would have quietly
    stopped being the thing it exists to be. This asserts the class rather than
    the instance: whatever a report's own source says, no task may claim a
    stronger one.
    """
    for name in REPORTS:
        blob = _load(name)
        report_source = blob.get("source")
        if report_source != "synthetic":
            continue
        offenders = [
            t.get("task", "<unnamed>") for t in blob.get("tasks", []) if t.get("source") == "chain"
        ]
        assert not offenders, (
            f"{name} declares source={report_source!r} and carries chain-sourced "
            f"task(s): {offenders}. A constructed report that reaches for a real "
            f"tape is no longer the thing it was generated to demonstrate."
        )


def test_a_chain_report_carries_the_yield_task_when_a_rate_tape_exists() -> None:
    """The category cannot go missing quietly.

    `advantage.json` shipped with three tasks and `source: chain` while a Venus
    rate tape sat on disk, because `task_route` caught an ImportError and
    returned `None` — the same value it returns for "there is no tape". The
    report was one category short and nothing said so.

    The main track's stated requirement is all four categories at equal depth,
    so a chain report that silently drops one is the failure this project is
    named after, applied to its own deliverable.
    """
    blob = _load("advantage.json")
    if blob.get("source") != "chain":
        pytest.skip("the published report is not chain-sourced")

    import sqlite3

    db = REPO / "data" / "misquote.db"
    if not db.exists():
        pytest.skip("no database to check for a rate tape")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        markets = conn.execute("SELECT count(DISTINCT market) FROM accrue").fetchone()[0]
    except sqlite3.OperationalError:
        pytest.skip("no accrue table")
    finally:
        conn.close()

    if markets < 2:
        pytest.skip(f"only {markets} market(s) on the rate tape — the task is legitimately absent")

    names = [t.get("task", "") for t in blob.get("tasks", [])]
    assert any(n.startswith("Route") for n in names), (
        f"{markets} Venus markets have a rate tape and the chain report carries no "
        f"Route task. Its tasks are {names}. A category that disappears without a "
        f"stated reason is exactly what this report exists to argue against."
    )


# ── the half that was narrowed away, restored ────────────────────────────────


def _views() -> dict[str, str]:
    web = REPO / "apps" / "web" / "src"
    return {p.name: p.read_text() for p in web.rglob("*.tsx") if not p.name.endswith(".test.tsx")}


def test_every_view_that_publishes_a_delta_also_shows_its_tape() -> None:
    """The failure this file is named for, guarded where it actually happened.

    This module's docstring opens with the defect:

        /advantage        Protect — Sentinel   -38.17pp   source: chain
        /agent/sentinel   Sentinel             +0.72pp    source: synthetic

    and its original fix was a view: "`SourceBanner` now leads every card, and
    each side carries the other's figure and a link to it." That component was
    later deleted, and this file was rewritten to guard the *artifact contract*
    instead — honestly, and with the narrowing stated. But the artifact was
    never the half that broke. `source` went on being written and stopped being
    shown, `AGENT_FIELDS` recorded it as unrendered, and nothing failed.

    `tearsheet/provenance.py::build_stamp` does not treat this as optional:
    "chain" and "synthetic" "are two different claims, and the UI is required to
    say which one it is showing."

    So: a component that renders a `delta_pp` must also render the tape it came
    from. Matched on `TapeSource` rather than on the word, because the word is
    "chain" or "synthetic" and both appear in prose all over this codebase —
    the same leaf-name weakness `test_artifact_contract.py` documents in both
    directions.
    """
    views = _views()
    #: Components that put a `delta_pp` in front of a reader.
    #:
    #: Named rather than detected: `delta_pp` reaches these through half a dozen
    #: local aliases (`adv.delta_pp`, `task.delta_pp`, a `deltaPp` prop), and a
    #: grep loose enough to catch all of them catches the type declarations too.
    publishing = ("AgentCard.tsx", "RouterCard.tsx", "AgentDetail.tsx", "RouterDetail.tsx")

    missing = [name for name in publishing if name in views and "TapeSource" not in views[name]]

    assert not missing, (
        "these render a delta and do not say which tape it came from — the "
        f"defect this file is named for, one component at a time: {missing}"
    )


def test_the_advantage_page_says_which_tape_each_of_its_two_reports_ran_over() -> None:
    """`/advantage` renders two reports and one of them is synthetic.

    `advantage_short.json` is emitted by `make advantage-short` from a
    deliberately truncated synthetic tape, so every task comes back withheld —
    which is the point of the panel. The page labelled it "Deliberately short
    tape", and short is not the same claim as synthetic: a short *chain* tape is
    real history that ran out, a short *synthetic* one is a random walk cut off.

    So the page showed a chain report and a synthetic report side by side and
    distinguished them by length.
    """
    view = (REPO / "apps" / "web" / "src" / "app" / "advantage" / "view.tsx").read_text()

    assert view.count("TapeSource") >= 3, (
        "/advantage renders two reports; each needs its own tape disclosed "
        "(one import plus one use per report)"
    )
