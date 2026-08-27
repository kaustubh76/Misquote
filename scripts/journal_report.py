"""What the live agents actually did, as a file the static export can read.

`AgentJournal` fetches `/journal/{agent}` and, when nothing answers, renders
**nothing at all** — `if (!journal || journal.total_rows === 0) return null`. On
the exported site that is the ordinary case: `MISQUOTE_API_BASE` is often unset,
and when it is set it points at a free-tier service that sleeps. So the one
section showing what a live agent decided, minute by minute, is missing from
`/agent/warden` and `/agent/router` exactly when a reader arrives cold.

`/status` reports the burn-in gate against that journal. The gate is on the
site; the evidence behind it was not.

## Why a projection rather than the file

`data/journal/warden.jsonl` is 181 rows and only 175 of them are decisions. The
other six are lifecycle: `{event: "run_start", head_block, poll_seconds,
sample_interval_s, chain_id, pool}`. Those are dropped here, for two reasons.

The first is that they are not decisions and this artifact is about decisions —
`total_rows` keeps the count so "the file also holds six lifecycle rows" still
has its number.

The second is mechanical and would otherwise have cost a red suite:
`tests/web/test_artifact_contract.py::test_no_artifact_number_is_hardcoded_in_the_ui`
builds a forbidden-literal set out of **every value in every published
artifact** and then greps every non-test `.ts`/`.tsx` for them. `poll_seconds`
is `90.0`. `Button.tsx` holds `hover:opacity-90` in a bare
`Record<ButtonTone, string>` — a string constant, not a `className` attribute,
so `strip_styling` does not remove it. Publishing the lifecycle rows would have
failed that guard on a Tailwind opacity step, and the fix would have looked like
adding `90` to the undistinctive list, which is the one thing that test's own
docstring argues against.

## Reuse

`_rows` and `_summary` come from `misquote.api.journal` and are not
reimplemented. `_summary`'s comment records why it is a field-by-field read
rather than `dataclasses.asdict`: `gate_blocks` is a `Counter`, and `asdict`
rebuilt it as `Counter({("R1", 115): 1})` — the endpoint served "R1 was blocked
once" for a gate that blocked 115 times. Two implementations of one summary is
precisely what that comment exists to prevent, and this file would be the second
one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from misquote.api.journal import _rows, _summary
from misquote.tearsheet import provenance
from misquote.tearsheet.generate import read_journal

REPO = Path(__file__).resolve().parents[1]
JOURNAL_DIR = REPO / "data" / "journal"
OUT = REPO / "apps" / "web" / "public" / "artifacts" / "journal.json"


def agent_journal(path: Path) -> dict[str, Any]:
    """One agent's file, as the artifact carries it: the summary and nothing else.

    ## Why not the decisions

    The first version of this carried all 344 of them across the two agents,
    trimmed to ten fields each, and the result was a **340KB** artifact fetched
    by a page that already fetches `registry.json` at 126KB. `LISTING_LIMIT` in
    `registry_report.py` records the same lesson from the other emitter: 400
    listings was 226KB "for a page that fetches it client-side, and enough DOM
    to time out a jsdom render".

    It also broke `test_no_artifact_number_is_hardcoded_in_the_ui`, and the way
    it broke is worth keeping. That guard builds a forbidden-literal set out of
    every value in every artifact and greps the whole front end for them — so
    publishing 344 rows of tick indices and floats forbade `-1` across every
    `.ts` and `.tsx` in the app. `-1` is `indexOf`'s miss, `slice`'s last
    element and a dozen other things; the artifact would have been dictating
    what unrelated components may write.

    The summary is 292 bytes and fixes the defect this file exists for:
    `AgentJournal` renders a summary, not a stepper, and it renders **nothing**
    when no API answers. A stepper over the rows is a separate feature that can
    bound its own payload when it is built — this is not the artifact to
    speculatively oversize for it.
    """
    _, total, unparsed = _rows(path, tail=0)
    return {
        "total_rows": total,
        "unparsed_rows": unparsed,
        "summary": _summary(read_journal(path)),
    }


def build(directory: Path = JOURNAL_DIR) -> dict[str, Any]:
    """Every journal on disk. An agent with no file is absent, not empty.

    The distinction is the API's, and it is worth keeping: `/journal/grid`
    refuses with "Either this agent has never run, or the name is not one of
    ours. Both are absences and neither is an empty journal." An entry here with
    `decisions: []` would contradict that from the other direction.
    """
    agents: dict[str, Any] = {}
    if directory.exists():
        for path in sorted(directory.glob("*.jsonl")):
            agents[path.stem] = agent_journal(path)

    return {
        "agents": agents,
        "note": (
            "What the live agents did, summarised. An agent absent from this "
            "object has never run — which is an absence rather than an empty "
            "journal, and the two are different claims. The decisions "
            "themselves are not carried: 344 rows is 340KB of artifact for a "
            "page that renders their summary."
        ),
        "build": provenance.build_stamp("python scripts/journal_report.py", source="journal"),
    }


def main() -> int:
    payload = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    for name, entry in payload["agents"].items():
        summary = entry["summary"]
        print(
            f"  {name:8} {entry['total_rows']:>4} rows · "
            f"{summary.get('decisions', 0)} decisions · {summary.get('holds', 0)} holds"
        )
    if not payload["agents"]:
        print("  no journal on disk — `make warden` and `make router` write them")
    print(f"  -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
