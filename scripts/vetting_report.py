"""Republish the pool badges on disk as the artifact the site reads.

    uv run python scripts/vetting_report.py
    uv run python scripts/vetting_report.py --chain 97

`Readme.md` §1 promises that "every pool a listed agent touches gets a
due-diligence badge". `misquote.vetting` generates them — nine chain reads per
pool, each check existing because something in this project actually went wrong
— and writes them to `vetting/badges/<pool>.json`. Nothing carried them any
further, so the finished half of that promise sat on disk where no reader could
see it.

**This reads no chain.** `make vet` does the reading; this republishes what that
left behind. That separation is why the emitter can sit inside `make artifacts`
without an RPC, and it is why every pool here carries the age of its own reading
rather than a freshness verdict: the badge was true when it was taken, and how
long ago that was is a fact the reader is entitled to weigh for themselves.

## Degrading without lying

Two absences, kept distinct, because collapsing them is the failure this project
is named after:

- **No badges at all** — `surveyed: false` and the reason, never `{"pools": 0}`
  presented as a measurement. Zero pools checked and zero pools failing are not
  the same sentence.
- **A pool this repo lists, with no badge on disk** — disclosed by name with a
  reason, never omitted. An absent row and a clean row look identical once
  rendered, which is exactly why `tearsheet.ledger` exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from misquote.chain.addresses import BSC_MAINNET, known_pools_on
from misquote.tearsheet import provenance

REPO = Path(__file__).resolve().parents[1]
BADGE_DIR = REPO / "vetting" / "badges"

# Worst-first, matching `vetting/read.py`'s own ordering so the two agree about
# which verdict is the more serious.
SEVERITY = {"PASS": 0, "WARN": 1, "UNKNOWN": 2, "FAIL": 3}


def shown(path: Path) -> str:
    """A path as a reader would cite it: repo-relative where it can be.

    `--badges` may point anywhere, so an unconditional `relative_to(REPO)`
    raises on any directory outside the checkout. Same idiom as
    `scripts/showcase.py`.
    """
    return (path.relative_to(REPO) if path.is_relative_to(REPO) else path).as_posix()


def listed_pools(chain_id: int) -> list[tuple[str, str]]:
    """Every pool this repository claims to care about, on one chain.

    The point of listing them here is that a pool with no badge can be *named*
    as unbadged rather than quietly missing from the page.

    It used to say it "mirrors `vetting/read.py::_known_pools`" and write the
    list out again, which is a mirror only for as long as somebody keeps
    polishing it. Both call `known_pools_on` now, and neither is a subset of
    `KNOWN_POOLS` chosen by hand — `TARGET_POOL_WIDE` was missing from every
    such subset in the repository at once.

    In `known_pools_on`'s order, not sorted by address. Sorting was harmless
    while the mainnet list was two pools that happened to sort flagship-first;
    adding `0x1401ff94…` put the second venue at the top of a page that leads
    with the pool this project actually trades. `known_pools_on` is already
    deterministic, so the sort was buying nothing.
    """
    seen: dict[str, str] = {}
    for ref in known_pools_on(chain_id):
        seen.setdefault(ref.address.lower(), ref.label or ref.address)
    return list(seen.items())


def badges_on_disk(directory: Path) -> dict[str, dict[str, Any]]:
    """Badges keyed by lowercase address, each stamped with when it was read."""
    found: dict[str, dict[str, Any]] = {}
    if not directory.exists():
        return found

    now = datetime.now(UTC)
    for path in sorted(directory.glob("*.json")):
        try:
            badge = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            # A half-written badge is not a badge. Skipping it means the pool
            # reports as unbadged, which is true and is the safer error.
            continue

        read_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        badge["path"] = shown(path)
        badge["read_at"] = read_at.isoformat(timespec="seconds")
        badge["age_hours"] = round((now - read_at).total_seconds() / 3600, 1)
        badge["proof"] = proof_for(badge)
        found[str(badge.get("pool", "")).lower()] = badge
    return found


def proof_for(badge: dict[str, Any]) -> dict[str, Any]:
    """Which of this badge's findings are executable, and which ran.

    Two separable things, and keeping them separate is the point. **Coverage**
    needs no chain and no toolchain — it is computed from the badge on disk — so
    it ships on every build and the six unprovable checks always carry their
    reason. **Proofs** need foundry, anvil and a fork url, so a build without
    them reports `ran: false` rather than omitting the section, which would read
    as nothing to prove.
    """
    from misquote.vetting import proof as vp

    payload: dict[str, Any] = {"coverage": vp.coverage(badge), "ran": False, "proofs": []}

    record = vp.RUN_DIR / f"proof-{str(badge.get('pool', '')).lower()}.json"
    if not record.is_file():
        payload["reason"] = "no proof has been executed — `make vet-prove` writes one"
        return payload
    try:
        ran = json.loads(record.read_text())
    except (OSError, json.JSONDecodeError) as error:
        payload["reason"] = f"{record.name} could not be read: {error}"
        return payload

    payload["ran"] = True
    payload["proofs"] = ran.get("proofs", [])
    payload["record"] = shown(record)
    return payload


def survey(chain_id: int, directory: Path) -> dict[str, Any]:
    on_disk = badges_on_disk(directory)

    if not on_disk:
        return {
            "surveyed": False,
            "reason": ("no pool has been badged — run `make vet`, which needs a reachable BSC RPC"),
            "chain_id": chain_id,
            "badge_dir": shown(directory),
            "pools": [],
            "summary": {"pools": 0, "badged": 0},
        }

    pools: list[dict[str, Any]] = []
    for address, label in listed_pools(chain_id):
        badge = on_disk.pop(address, None)
        if badge is None:
            pools.append(
                {
                    "pool": address,
                    "label": label,
                    "badged": False,
                    "reason": "this pool is listed in chain/addresses.py and has no badge",
                }
            )
        else:
            pools.append({"badged": True, **badge})

    # A badge for a pool the repo no longer lists is still evidence; dropping it
    # would be the omission this module exists to prevent.
    for leftover in on_disk.values():
        pools.append({"badged": True, "listed": False, **leftover})

    badged = [p for p in pools if p["badged"]]
    checks = [c for p in badged for c in p.get("checks", [])]
    verdicts: dict[str, int] = {}
    for pool in badged:
        verdicts[pool["verdict"]] = verdicts.get(pool["verdict"], 0) + 1

    return {
        "surveyed": True,
        "chain_id": chain_id,
        "badge_dir": shown(directory),
        "pools": pools,
        "summary": {
            "pools": len(pools),
            "badged": len(badged),
            "unbadged": len(pools) - len(badged),
            "cleared": sum(1 for p in badged if p.get("safe_to_provide")),
            "blocked": sum(1 for p in badged if not p.get("safe_to_provide")),
            "checks": len(checks),
            "unknown_checks": sum(1 for c in checks if c.get("status") == "UNKNOWN"),
            "failed_checks": sum(1 for c in checks if c.get("status") == "FAIL"),
            "verdicts": verdicts,
            "worst": max(
                (p["verdict"] for p in badged),
                key=lambda v: SEVERITY.get(v, 0),
                default="UNKNOWN",
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", type=int, default=BSC_MAINNET)
    parser.add_argument("--badges", default=str(BADGE_DIR))
    parser.add_argument(
        "--out", default=str(REPO / "apps" / "web" / "public" / "artifacts" / "vetting.json")
    )
    args = parser.parse_args(argv)

    payload = survey(args.chain, Path(args.badges))
    payload["build"] = provenance.build_stamp(
        f"python scripts/vetting_report.py --chain {args.chain}",
        source="chain-read badges on disk",
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    if not payload["surveyed"]:
        print(f"  not surveyed — {payload['reason']}")
    else:
        s = payload["summary"]
        print(f"  pools          {s['badged']} badged, {s['unbadged']} not")
        print(
            f"  checks         {s['checks']}, {s['unknown_checks']} unknown, {s['failed_checks']} failed"
        )
        print(f"  worst verdict  {s['worst']}")
    print(f"  -> {out.relative_to(REPO) if out.is_relative_to(REPO) else out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
