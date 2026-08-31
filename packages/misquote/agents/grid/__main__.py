"""Run Grid against a live chain, without the ability to spend.

    uv run python -m misquote.agents.grid --seconds 600
    make grid

## Why this file did not exist

`Readme.md` §1 commits to four agents "at equal depth", and the replay engine has
run all four since Step 7 — `tests/agents/` puts three different policies through
one engine, one tape, one cost model. The *live* driver could only ever run one:
`WardenLive` constructed `Engine(meta, params)` with no policy argument, so the
seam `Engine` already exposed stopped at the replay boundary.

That made "four agents at equal depth" true of the replay and false of the
process list, which is the kind of gap a marketplace's own generality claim
should not have. Passing the policy through was a one-line change; this file and
its Sentinel sibling are what it buys.

Everything else is Warden's: the same source, the same journal, the same kill
file, the same three gates in front of broadcasting. Reused rather than copied,
because a second entrypoint with its own gates is a second place for one of them
to be missing.
"""

from __future__ import annotations

import sys

from misquote.agents.grid.policy import GridParams, decide_grid
from misquote.agents.warden.__main__ import run_agent


def main(argv: list[str] | None = None) -> int:
    params = GridParams()
    return run_agent(
        name="grid",
        policy=lambda obs, _p, meta: decide_grid(obs, params, meta),
        argv=argv,
        description=__doc__,
    )


if __name__ == "__main__":
    sys.exit(main())
