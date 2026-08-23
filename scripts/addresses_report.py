"""Republish whatever `make vet-addresses` left on disk, as the site's artifact.

    python scripts/addresses_report.py --chain 56

Reads no chain. `scripts/verify_addresses.py` does the reading and writes a
record per chain into `vetting/addresses/`; this turns those records into
`apps/web/public/artifacts/addresses.json`. Exactly the split `make vet` and
`make vetting` already use, and for the same reason: `make artifacts` has to be
runnable with no network, and an emitter that quietly reaches for one is an
emitter that produces different output depending on who ran it.

`/vetting` renders this beside the pool badges. The two are the same shape —
named checks, verdicts, chain provenance — because they are the same kind of
question asked about two different subjects. Pools are what the agent provides
liquidity to; these are the contracts the signer is aimed at.

## Nothing recorded is a sentence, not an empty list

Public BSC endpoints are unreliable, and `verify_addresses.py` reaches for a
list of them rather than a configured key — so "no reading was taken" is a
routine state here, not an exceptional one. It is published as
`surveyed: false` with a reason. Zero checks failing and zero checks run render
identically to a reader unless something says which happened.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from misquote.chain.addresses import BSC_MAINNET
from misquote.tearsheet import provenance

REPO = Path(__file__).resolve().parents[1]
RECORD_DIR = REPO / "vetting" / "addresses"

NOTHING_RECORDED = (
    "no address verification has been recorded — run `make vet-addresses`, which "
    "reads the chain and needs a reachable BSC RPC"
)


def read_record(directory: Path, chain_id: int, prefix: str = "") -> dict[str, Any]:
    """One recorded survey, with how old it is.

    The age is published; no freshness *verdict* is invented from it. How stale
    is too stale depends on what the reader is about to do with it, and a page
    that decided that for them would be asserting a policy nobody wrote down.

    `prefix` selects which survey. This read `{chain_id}.json` and nothing else,
    so `venus-56.json` and `erc8183-56.json` — written by `make venus-verify`
    and `make erc8183-verify`, and **cited as the evidence** for two mainnet
    escrow addresses and for the whole Yield category — were never republished
    and carried no age anywhere. Evidence a reader cannot see is not evidence.
    """
    path = directory / f"{prefix}{chain_id}.json"
    if not path.is_file():
        return {"surveyed": False, "reason": NOTHING_RECORDED, "chain_id": chain_id, "checks": []}

    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return {
            "surveyed": False,
            "reason": f"{path.relative_to(REPO)} could not be read: {error}",
            "chain_id": chain_id,
            "checks": [],
        }

    read_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    record["read_at"] = read_at.isoformat(timespec="seconds")
    record["age_hours"] = round((datetime.now(UTC) - read_at).total_seconds() / 3600, 1)
    record["record"] = str(path.relative_to(REPO))
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", type=int, default=BSC_MAINNET)
    parser.add_argument("--records", default=str(RECORD_DIR))
    parser.add_argument(
        "--out", default=str(REPO / "apps" / "web" / "public" / "artifacts" / "addresses.json")
    )
    args = parser.parse_args(argv)

    payload = read_record(Path(args.records), args.chain)
    # The other two recorded surveys, published beside the PancakeSwap one and
    # aged the same way. `verify_venus.py` gates the whole Yield category and
    # `verify_erc8183.py` justifies two mainnet escrow addresses; both wrote
    # their readings to this directory and nothing ever read them back, so the
    # evidence strings in `registry/erc8183.py` pointed at files the site did
    # not publish.
    payload["venus"] = read_record(Path(args.records), args.chain, prefix="venus-")
    payload["erc8183"] = {
        str(chain): read_record(Path(args.records), chain, prefix="erc8183-") for chain in (56, 97)
    }
    payload["build"] = provenance.build_stamp(
        f"python scripts/addresses_report.py --chain {args.chain}",
        source="chain reads recorded on disk",
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    if not payload.get("surveyed"):
        print(f"  not surveyed — {payload['reason']}")
    else:
        summary = payload.get("summary", {})
        print(f"  verdict        {payload.get('verdict')}")
        print(
            f"  checks         {summary.get('checked', 0)}, "
            f"{summary.get('failed', 0)} failed, {summary.get('unknown', 0)} unknown"
        )
        print(f"  read           {payload['age_hours']}h ago")
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
