"""The agents' decision journals, as they were appended.

`data/journal/<agent>.jsonl` is append-only and is the tearsheet's only input.
`tearsheet/generate.py::read_journal` already summarises it — how often each
R-gate held the agent back, how many decisions there were. This does not
summarise. It serves the rows.

That distinction is the reason this route is allowed to exist at all. A summary
here would be a second implementation of `read_journal`, and the two would
disagree; the rows are the record, and the record is what a reader cannot
currently get. The `summary` field below is `read_journal`'s own return value,
called rather than reproduced.

Rows come back newest-last, the order they were written, because a decision
journal read out of order is a different document.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from fastapi import Query

from misquote.api.errors import refuse
from misquote.api.locations import journal_dir
from misquote.tearsheet.generate import read_journal

#: What runs each agent, for the refusal to quote when a journal is absent.
#: Keyed by agent so the advice is specific; a name that is not ours resolves to
#: something true rather than to a confident wrong command.
WRITTEN_BY: dict[str, str] = {
    # `make warden ENV=testnet` until 2026-09-06, and it was wrong in the way a
    # published command can only be wrong once somebody runs it: `ENV` was
    # declared in the Makefile and referenced by nothing, while the target
    # passes `--chain $(CHAIN)`, which defaults to **56**. So the remedy this
    # API hands every reader of an empty journal said testnet and ran mainnet.
    "warden": "make warden CHAIN=56",
    "router": "make router",
}

#: Rows returned when the caller names no limit.
#:
#: The note here read "the warden journal is ~180 lines today and will not stay
#: that size once the loop runs for a day". The day has since happened — a 24h
#: mainnet burn-in leaves tens of thousands of rows — so this is a tail over a
#: large file rather than most of a small one, which is what it was written for.
DEFAULT_TAIL = 200


def agent_names() -> list[str]:
    """Every agent that has actually written a journal, by stem, sorted.

    Read from disk per call rather than from a list of the four agents we ship:
    an agent that has never run has no journal, and reporting it as available
    would be advertising an empty file as a record.
    """
    directory = journal_dir()
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.jsonl"))


def _rows(path: Path, tail: int) -> tuple[list[dict[str, Any]], int, int]:
    """Parsed rows, how many there were, and how many did not parse.

    A malformed line is counted and skipped rather than raising. The writer
    appends while this reads, so the last line can legitimately be half-written
    — and a 500 on a torn final line would make a healthy agent look broken.
    Reported as `unparsed` so the count is never silently zero.
    """
    rows: list[dict[str, Any]] = []
    unparsed = 0
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                unparsed += 1
    return rows[-tail:] if tail > 0 else rows, len(rows), unparsed


def _summary(summary: Any) -> dict[str, Any]:
    """`JournalSummary` as plain JSON types, read field by field.

    Not `dataclasses.asdict`, and the reason is a bug this would otherwise have
    shipped. `asdict` recurses into every value and rebuilds each container as
    `type(obj)(generated_pairs)` — and `JournalSummary.gate_blocks` is a
    `Counter`, so `Counter({"R1": 115})` came back as
    `Counter({("R1", 115): 1})`: the pairs counted as elements. The endpoint
    served "R1 was blocked once" for a gate that blocked 115 times, in the
    plausible shape of a real answer.

    A shallow read cannot do that. `JournalSummary`'s fields are ints, optional
    ints and the one counter, so there is nothing here that needs recursing
    into — and `dict()` on the counter is exact rather than reconstructive.
    """
    out: dict[str, Any] = {}
    for field in dataclasses.fields(summary):
        if field.metadata.get("publish") is False:
            continue
        value = getattr(summary, field.name)
        out[field.name] = dict(value) if isinstance(value, dict) else value

    # The three that are properties rather than fields, and are the reason this
    # walk was not enough on its own.
    #
    # The duration was never in this artifact. `AgentJournal.tsx` computed it
    # from `first_ts` and `last_ts` — the two ends of an append-only file — and
    # so rendered "covers 555h" for a 24-hour run, beside a sentence calling it
    # "the same file the readiness gate measures". The gate said 19.7h. Carrying
    # the number means there is one answer to copy rather than two to derive.
    out["hours"] = round(summary.hours, 2)
    out["span_hours"] = round(summary.span_hours, 2)
    out["runs"] = summary.runs
    return out


def journals() -> dict[str, Any]:
    """Which agents have written a journal, and how long each is."""
    directory = journal_dir()
    names = agent_names()
    return {
        "directory": str(directory),
        "agents": names,
        "note": (
            "An agent absent from this list has not run. That is an absence, not an "
            "empty journal — `make warden` and `make router` are what write them."
        ),
    }


def journal(agent: str, tail: int = Query(DEFAULT_TAIL, ge=0, le=10_000)) -> dict[str, Any]:
    """One agent's decisions, newest last, with the tearsheet's own summary."""
    names = agent_names()
    if agent not in names:
        raise refuse(
            404,
            error=f"no journal for {agent!r}",
            # Keyed by agent, and generic for a name that is not one of ours.
            # The first version of this line answered every unknown name with
            # `make router`, so a typo was told to run a command that would
            # succeed and still not produce the file it asked for — the same
            # defect as `REMEDIES["router"]`, one commit after fixing it.
            remedy=WRITTEN_BY.get(agent, "make warden CHAIN=56, or make router"),
            available=names,
            note=(
                "Either this agent has never run, or the name is not one of ours. "
                "Both are absences and neither is an empty journal."
            ),
        )

    path = journal_dir() / f"{agent}.jsonl"
    rows, total, unparsed = _rows(path, tail)
    return {
        "agent": agent,
        "file": str(path),
        "total_rows": total,
        "unparsed_rows": unparsed,
        "returned": len(rows),
        "tail": tail,
        # `read_journal`'s own output, not a second count of the same file.
        "summary": _summary(read_journal(path)),
        "rows": rows,
    }
