"""Whether PancakeSwap's core math really is Uniswap's, checked rather than assumed.

    uv run python scripts/verify_fork_parity.py            # fetch, compare, record
    uv run python scripts/verify_fork_parity.py --check    # compare, write nothing

## The claim this exists to hold up

Everything the differential corpus proves is proved against **Uniswap's**
Solidity. `vetting/forge/src/Exposer.sol` imports `@uniswap/v3-core`, the vectors
record `source: "Uniswap v3 Solidity, redeployed to a local anvil"`, and
`/vectors` publishes 19,546 answers replayed at exact integer equality.

None of that is a statement about PancakeSwap. It becomes one only through a
bridge — *the fork did not change these libraries* — and that bridge was carried
by two comments:

    ops/forge_deps.txt      "PancakeSwap v3 uses Uniswap v3's core math
                             unchanged, so upstream Uniswap is the faithful
                             reference."
    scripts/venue_report.py "the core math is byte-identical upstream, which is
                             why a differential corpus is meaningful at all."

Both are true. Neither was checked, and it is the single largest load-bearing
assertion on the venue track: if PancakeSwap had touched one line of
`SqrtPriceMath`, 19,546 green cases would say nothing about the pool this
project quotes, and nothing anywhere would have noticed. A project whose whole
argument is that every number traces to a reading cannot rest its biggest
comparison on a sentence.

## What it compares, and what it deliberately ignores

Every library `Exposer.sol` imports, fetched from PancakeSwap's own repository
at the pinned commit below and compared against the Uniswap copy already on disk
under `vetting/forge/lib` — the *same files the vectors were generated from*,
which is what makes this a bridge rather than a second opinion.

The comparison is on a **token stream**, not on bytes. Comments are stripped and
whitespace is collapsed, because three things differ between the two copies and
none of them is arithmetic:

  - the SPDX line (BUSL-1.1 and MIT upstream, GPL-2.0-or-later at PancakeSwap),
  - prettier's line wrapping, which reflowed several ternaries,
  - `@uniswap/v3-core/` -> `@pancakeswap/v3-core/` in one import path.

Anything else is a real divergence and fails the run. An identical token stream
under a 0.7.6 compiler is the same program: the compiler does not read comments
and does not care where the newlines are.

## An absent reference is not a pass

`vetting/forge/lib` is gitignored and populated by `make setup`. With no Uniswap
copy on disk there is nothing to compare against, and the outcome recorded for
that is `UNAVAILABLE` — never `PASS`. A check that reports its own inability to
run as a negative result is the failure mode this repository has already shipped
three times.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from misquote.tearsheet import provenance

REPO = Path(__file__).resolve().parents[1]
LIB = REPO / "vetting" / "forge" / "lib"
OUT = REPO / "vetting" / "runs" / "fork-parity.json"

#: PancakeSwap's monorepo, pinned. A moving ref would make this record
#: unreproducible in exactly the way `ops/forge_deps.txt` pins against.
PANCAKE_REPO = "pancakeswap/pancake-v3-contracts"
PANCAKE_COMMIT = "986847948755cba528324d41be19480731c36c2a"
PANCAKE_PINNED = "2026-05-14"

#: Every library `vetting/forge/src/Exposer.sol` imports, as (local, remote).
#:
#: Derived from the Exposer's import list rather than chosen: the set that
#: matters is exactly the set the vectors exercise, and a library compared here
#: that no vector touches would be reassurance about code this project does not
#: run.
LIBRARIES: tuple[tuple[str, str, str], ...] = (
    (
        "TickMath",
        "v3-core/contracts/libraries/TickMath.sol",
        "projects/v3-core/contracts/libraries/TickMath.sol",
    ),
    (
        "SqrtPriceMath",
        "v3-core/contracts/libraries/SqrtPriceMath.sol",
        "projects/v3-core/contracts/libraries/SqrtPriceMath.sol",
    ),
    (
        "FullMath",
        "v3-core/contracts/libraries/FullMath.sol",
        "projects/v3-core/contracts/libraries/FullMath.sol",
    ),
    (
        "FixedPoint128",
        "v3-core/contracts/libraries/FixedPoint128.sol",
        "projects/v3-core/contracts/libraries/FixedPoint128.sol",
    ),
    (
        "Tick",
        "v3-core/contracts/libraries/Tick.sol",
        "projects/v3-core/contracts/libraries/Tick.sol",
    ),
    (
        "LiquidityAmounts",
        "v3-periphery/contracts/libraries/LiquidityAmounts.sol",
        "projects/v3-periphery/contracts/libraries/LiquidityAmounts.sol",
    ),
)

#: The import path rewrite, which is the one token difference that is expected.
#:
#: Named rather than tolerated by a fuzzy comparison: this is the only edit
#: PancakeSwap makes to these files, so it is normalised away explicitly and
#: anything else still fails. A comparison loose enough to swallow it by accident
#: would be loose enough to swallow a changed constant.
_VENDOR = re.compile(r"@pancakeswap/")

_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_TOKEN = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*|0x[0-9a-fA-F]+|\d+|[^\s]")


def normalise(source: str) -> list[str]:
    """Solidity source as the tokens a compiler would see.

    Comments out, whitespace collapsed, vendor prefix folded. What survives is
    every identifier, literal, and operator in order — so a changed magic number,
    a flipped comparison or a dropped `unchecked` all still register, and a
    reflowed ternary does not.
    """
    text = _BLOCK_COMMENT.sub("", _LINE_COMMENT.sub("", source))
    return _TOKEN.findall(_VENDOR.sub("@uniswap/", text))


def raw_url(path: str) -> str:
    return f"https://raw.githubusercontent.com/{PANCAKE_REPO}/{PANCAKE_COMMIT}/{path}"


def fetch(path: str, *, timeout: float = 30.0) -> str:
    with urllib.request.urlopen(raw_url(path), timeout=timeout) as response:  # noqa: S310
        return response.read().decode()


def first_divergence(left: list[str], right: list[str]) -> str:
    """Where the two token streams part, in words a reader can act on.

    A boolean saying "they differ" would send someone to diff 1,666 tokens by
    hand. This is the position and both neighbourhoods, which is enough to see
    whether it is a renamed constant or a changed one.
    """
    for index, (a, b) in enumerate(zip(left, right, strict=False)):
        if a != b:
            window = slice(max(0, index - 6), index + 6)
            return (
                f"token {index}: uniswap ...{' '.join(left[window])}... "
                f"vs pancakeswap ...{' '.join(right[window])}..."
            )
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    return f"identical for {len(shorter)} tokens, then {len(longer) - len(shorter)} more"


def compare_one(name: str, local: str, remote: str) -> dict[str, Any]:
    """One library, both copies, and the verdict on the pair."""
    path = LIB / local
    if not path.is_file():
        return {
            "library": name,
            "status": "UNAVAILABLE",
            "detail": f"no reference at {path.relative_to(REPO)} — run `make setup`",
            "uniswap": str(path.relative_to(REPO)),
            "pancakeswap": raw_url(remote),
        }

    try:
        theirs = fetch(remote)
    except (urllib.error.URLError, TimeoutError) as error:
        return {
            "library": name,
            "status": "UNAVAILABLE",
            "detail": f"could not read PancakeSwap's copy: {error}",
            "uniswap": str(path.relative_to(REPO)),
            "pancakeswap": raw_url(remote),
        }

    ours = normalise(path.read_text())
    them = normalise(theirs)
    same = ours == them
    return {
        "library": name,
        "status": "PASS" if same else "FAIL",
        "detail": (
            f"{len(ours):,} tokens, identical"
            if same
            else f"diverges — {first_divergence(ours, them)}"
        ),
        "tokens": len(ours),
        "uniswap": str(path.relative_to(REPO)),
        "pancakeswap": raw_url(remote),
    }


def build_payload() -> dict[str, Any]:
    checks = [compare_one(*row) for row in LIBRARIES]
    # Three outcomes, ordered by which one a reader must not miss. An
    # unavailable reference and a genuine divergence are different claims and
    # collapsing them into `ok: false` would lose the one that matters.
    if any(c["status"] == "FAIL" for c in checks):
        outcome = "FAIL"
    elif any(c["status"] == "UNAVAILABLE" for c in checks):
        outcome = "UNAVAILABLE"
    else:
        outcome = "PASS"

    return {
        "outcome": outcome,
        "fork_of": "Uniswap v3",
        "venue": "PancakeSwap v3",
        "pancakeswap": {
            "repo": PANCAKE_REPO,
            "commit": PANCAKE_COMMIT,
            "pinned": PANCAKE_PINNED,
        },
        "libraries": len(checks),
        "identical": sum(1 for c in checks if c["status"] == "PASS"),
        "checks": checks,
        "summary_line": (
            f"{sum(1 for c in checks if c['status'] == 'PASS')} of {len(checks)} libraries "
            f"token-identical to PancakeSwap's own copies at {PANCAKE_COMMIT[:12]}"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare only, write nothing")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    payload = build_payload()
    payload["build"] = provenance.build_stamp(
        "python scripts/verify_fork_parity.py", source="upstream"
    )

    for check in payload["checks"]:
        print(f"  {check['status']:<12} {check['library']:<18} {check['detail']}")
    print(f"  {payload['outcome']}: {payload['summary_line']}")

    if not args.check:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"  -> {out}")

    return 0 if payload["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
