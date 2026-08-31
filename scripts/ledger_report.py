"""Refresh `index.json`'s not-built ledger, and nothing else.

    uv run python scripts/ledger_report.py
    make ledger

## Why this exists

`index.json["not_built"]` is a **pure projection** of
`tearsheet/ledger.py::NOT_BUILT` — no tape, no replay, no chain read. It was
written by two emitters that each do an hour of other work first:
`showcase.py` replays three agents over a 252,923-event tape, and
`router_showcase.py` replays a rate tape twice.

So editing one sentence of a ledger entry required a full replay to publish, and
`tests/web/test_artifact_projections.py` — correctly — fails until it is
published. That is a coupling with a predictable consequence: the cheapest way to
make the suite green after a ledger edit is to not edit the ledger.

This does the last line of those two emitters on its own. It writes **only**
`not_built`, so it cannot overwrite a replayed number with a stale one — the
failure mode a "just regenerate the index" script would otherwise have.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from misquote.tearsheet import ledger

REPO = Path(__file__).resolve().parents[1]
INDEX = REPO / "apps" / "web" / "public" / "artifacts" / "index.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default=str(INDEX))
    args = parser.parse_args(argv)

    path = Path(args.index)
    if not path.is_file():
        print(f"  {path} not found — run `make showcase-auto` first")
        return 1

    index = json.loads(path.read_text())
    before = [entry.get("name") for entry in index.get("not_built", [])]
    entries = ledger.to_dicts()
    index["not_built"] = entries
    path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")

    after = [entry["name"] for entry in entries]
    print(f"  ledger  {len(entries)} entries -> {path}")
    for name in after:
        mark = " " if name in before else "+"
        print(f"    {mark} {name}")
    for name in before:
        if name not in after:
            print(f"    - {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
