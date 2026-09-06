#!/usr/bin/env python3
"""Publish where the live API is, as an artifact rather than as a build flag.

The web app is `output: "export"` — built once, served anywhere — and the API
origin differs between a laptop, a preview and Render. `NEXT_PUBLIC_*` bakes at
build time, so pointing the export at a different backend would mean rebuilding
it, which defeats the property the export exists for.

So the base URL is read at runtime, from a file. Putting that file *inside*
`apps/web/public/artifacts/` rather than beside it is what makes it cheap:

- `src/test/harness.tsx` throws on any fetch whose URL is not root-absolute
  under `/artifacts/`, and this path already is, so the test harness needs no
  exception carved into it;
- `api/service.py` serves it at `/artifacts/api` like every other artifact,
  so the API can tell a client where the API is;
- the provenance census counts it, and `build_stamp()` gives it the same
  commit trail as everything else the site reads.

`base` is deliberately allowed to be null. A site with no backend configured is
the normal case — the whole export works without one — and `null` says "there is
no live API here" where an empty string would read as "the API is at the site
root", which is a different and wrong claim.

## Why null cannot silently replace a base that is already there

`make artifacts` runs this target unconditionally, nothing in the build loads
`.env`, and `MISQUOTE_API_BASE` is not in `.env.example` — so any rebuild that
did not happen to have the variable inline wrote `base: null` over a working
one, and every live feature on the site went dark with no error and no diff
anybody reads. Commit `840b3dd` is that happening: the base was restored the
next day by someone noticing the site, not by a check.

So an empty base now **keeps** the base already on disk and says so, loudly.
Blanking it deliberately is `--allow-null`, which is one flag and a decision
rather than an omission. This is not a validity check — null is valid, and a
fresh clone with no `api.json` still publishes it without complaint. It is only
a refusal to *lose* a value that nothing else in the build remembers.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from misquote.tearsheet.provenance import build_stamp

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "apps" / "web" / "public" / "artifacts"


def config(base: str | None) -> dict[str, Any]:
    """What the client needs to decide whether to try the API at all."""
    cleaned = (base or "").strip().rstrip("/")
    return {
        "base": cleaned or None,
        # What a browser client actually calls, which is not the same as what
        # the service serves. `api/service.py`'s index route is the full list;
        # this is the discovery map, so a route nothing can reach from a page
        # does not belong in it.
        #
        # `/wallet/{address}/positions` used to be here and is not, and the
        # reason is worth recording rather than silently dropping: it is a real
        # route and the site never calls it, because `/quote/eligibility`
        # already folds the chain read and the tape check into one answer.
        # Asking for positions separately would be a second round trip
        # returning strictly less.
        #
        # The quote path is three entries because it is three requests with
        # three different failure modes — the POST can be refused before a job
        # exists, the poll is the fallback when a stream is buffered, and the
        # stream is the one that replays from `Last-Event-ID`.
        "routes": {
            "tape": "/tape",
            "journal": "/journal/{agent}",
            "vetting": "/vetting/{address}",
            # An unquotable pool answers 200 with its refusal rather than a 4xx:
            # a pool with too little tape has no ranking, and that is a result
            # rather than a failure. A client must read the body either way.
            "pools": "/pools",
            "pool": "/pools/{address}",
            "registry": "/registry/agents",
            "eligibility": "/quote/eligibility/{address}",
            "quote": "POST /quote",
            "job": "/quote/job/{job_id}",
            "stream": "/quote/job/{job_id}/stream",
            "capability": "/sessions/capability",
        },
        "note": (
            "base is null when no live API is configured, which is the ordinary "
            "state: every page on this site renders from the artifacts alone. A "
            "client that finds null must not fall back to the site origin — there "
            "is no API there, and requesting one would 404 against the export."
        ),
        "build": build_stamp(command="make artifacts", source="environment"),
    }


def existing_base(path: Path) -> str | None:
    """The base already published at `path`, if there is a readable one.

    A missing, empty or malformed file is not an error here — it is the fresh
    clone, and it has no value to lose.
    """
    try:
        published = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    base = published.get("base") if isinstance(published, dict) else None
    return base if isinstance(base, str) and base else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # The literal, not a constant holding it. `tests/test_env_template.py` finds
    # environment reads by walking the AST for string literals, so a name routed
    # through `ENV_VAR = "MISQUOTE_API_BASE"` is invisible to it — and that guard
    # is precisely what keeps `.env.example` from drifting out of step with what
    # the program actually reads. Indirection here would have bought nothing and
    # cost the check.
    parser.add_argument("--base", default=os.environ.get("MISQUOTE_API_BASE", ""))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--allow-null",
        action="store_true",
        help="blank a base that is already published (dark-site the live features)",
    )
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "api.json"

    base = args.base
    kept = None
    if not config(base)["base"] and not args.allow_null:
        kept = existing_base(path)
        if kept:
            base = kept

    path.write_text(json.dumps(config(base), indent=2, sort_keys=True) + "\n")

    if kept:
        print(f"  MISQUOTE_API_BASE is unset; kept the published base -> {kept}")
        print("  (pass --allow-null to blank it, which dark-sites every live feature)")
    else:
        print(f"  api base -> {config(base)['base'] or 'no live API configured'}")
    print(f"\n  -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
