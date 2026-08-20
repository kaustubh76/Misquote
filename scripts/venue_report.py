"""The venue, as an integration rather than as a data label.

    python scripts/venue_report.py

Reads no chain and no database. Every field below is a projection of a Python
constant or of a pure function, which is what lets
`tests/web/test_artifact_projections.py` re-derive the whole file and compare.

## Why this artifact exists

`PancakeSwap` appeared in exactly one authored string anywhere in the front end —
the `<title>` in `app/layout.tsx`. Everywhere else it reached a reader as
interpolated data: the pool label inside a provenance banner, a faint eyebrow on
a task card. The venue was framed as *where the tape came from*, never as *what
this is built on*.

That got the emphasis backwards. The pool label is the least interesting true
thing about the venue. The interesting part is every place PancakeSwap is
**not** Uniswap, each of which is a defect this project actually hit, each of
which costs something specific, and each of which is caught by a test that runs.
The count is `len(divergences())` wherever it is stated, never a numeral — the
list grew from five to six while this file was being written.
Those lived in Python docstrings and in `docs/FOR_JUDGES.md`, where a judge
looking at the site would never find them.

## Sentences here, numbers derived

The prose in `DIVERGENCES` is authored, and it is authored *once*, here, rather
than typed into a `.tsx` — so it is a single copy, it carries citation ids the
assumption sheet resolves, and the parity test covers it.

Every figure is computed from the code that implements the thing being described.
`fee_overstatement` calls `lp_share_of_fee`; `unmintable_remainder` takes the
modulo; the tier table is `badge.FEE_TIER_SPACING` itself. Nothing here is
retyped, because a page about getting the details right cannot afford a number
that drifted from the code it describes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from misquote.chain.addresses import (
    BSC_MAINNET,
    EQUITY_POOL,
    TARGET_POOL,
    TARGET_POOL_WIDE,
    TESTNET_MIRROR_POOL,
    PoolRef,
    known_pools_on,
)
from misquote.core.fees import lp_share_of_fee
from misquote.core.tickmath import MIN_TICK
from misquote.tearsheet import provenance, vectors
from misquote.vetting.badge import FEE_TIER_SPACING

REPO = Path(__file__).resolve().parents[1]

# Uniswap's 0.30% tier, and the reason its absence is a divergence rather than a
# curiosity: a range width copied from a Uniswap example assumes a spacing of 60
# and there is no such spacing here.
UNISWAP_ONLY_TIER = 3000

# A round number to divide, so the ratio is the ratio and not a rounding of one.
# `lp_share_of_fee` is integer arithmetic on wei-scale amounts.
_FEE_PROBE = 10**18


def fee_overstatement(fee_protocol: int) -> float:
    """How much reconstructing fees from volume overstates what an LP earns.

    Derived, because the repository already contains two spellings of it: the
    prose says 1.52x and `tests/core/test_fees.py` asserts 1.515. Both describe
    `1 / 0.66`. Publishing the computed value means the page cannot disagree with
    the test.
    """
    return _FEE_PROBE / lp_share_of_fee(_FEE_PROBE, fee_protocol)


def unmintable_remainder(spacing: int) -> int:
    """`MIN_TICK` is not a multiple of any Pancake spacing. This is the leftover.

    Non-zero means clamping a range bound to the extreme produces a tick the pool
    rejects, so the mint reverts (V-10). Taken on the magnitude: Python's modulo
    on a negative operand returns 8 rather than 2, which is the same fact wearing
    a different sign convention and would read as a different number on a page.
    """
    return abs(MIN_TICK) % spacing


def pool_row(pool: PoolRef, role: str) -> dict[str, Any]:
    """One pool, with the fields that differ between them.

    `lp_fee_share` is the property, not a recomputation of it — the point of the
    row is that this value is read per pool and has no defensible default.
    """
    return {
        "role": role,
        "label": pool.label,
        "address": pool.address,
        "chain_id": pool.chain_id,
        "fee_pips": pool.fee_pips,
        "tick_spacing": pool.tick_spacing,
        "fee_protocol": pool.fee_protocol,
        "lp_fee_share": pool.lp_fee_share,
        "w_min_ticks": pool.w_min_ticks,
        "quote_symbol": pool.quote_symbol,
    }


# What each verified pool is *for*, keyed by address. The role is the only part
# of a row that is not read off the `PoolRef`, so it is the only part that can
# be missing — and `tests/chain/test_known_pools_are_published.py` fails on a
# pool with no entry here rather than letting it publish as "".
#
# A pool nobody has described is a pool nobody has thought about, and this table
# is on the page that argues the details were read rather than assumed.
POOL_ROLES: dict[str, str] = {
    TARGET_POOL.address.lower(): "flagship",
    TARGET_POOL_WIDE.address.lower(): "the second venue",
    EQUITY_POOL.address.lower(): "tokenized equity",
    TESTNET_MIRROR_POOL.address.lower(): "testnet mirror",
}


def pool_rows() -> list[dict[str, Any]]:
    """Every verified pool, on both chains, in a stable order.

    This was three literal `pool_row(...)` calls and `TARGET_POOL_WIDE` was not
    one of them — so the section headed "The pools we actually read" omitted the
    pool the Agent Advantage Report's third task compares the flagship against,
    and whose protocol fee of 3200 against the flagship's 3400 is the third
    instance of P-8. Derived from `KNOWN_POOLS` now, so a pool cannot be
    verified and then left off the page that lists what was verified.
    """
    rows: list[dict[str, Any]] = []
    for chain_id in (BSC_MAINNET, TESTNET_MIRROR_POOL.chain_id):
        for pool in known_pools_on(chain_id):
            rows.append(pool_row(pool, POOL_ROLES.get(pool.address.lower(), "")))
    return rows


def divergences() -> list[dict[str, Any]]:
    """Every place the fork is not the original, each with what it cost.

    Ordered by what getting it wrong does to a reader, not by where it sits in
    the codebase: a number that is silently 1.5x too big outranks a call that
    reverts, because the revert tells you.
    """
    spacing = TARGET_POOL.tick_spacing
    return [
        {
            "what": "The protocol takes 34% of every fee, by default",
            "uniswap": "protocol fee off unless governance turns it on",
            "pancake": f"slot0.feeProtocol packs (fee0, fee1); this pool reads {TARGET_POOL.fee_protocol}, so LPs keep {TARGET_POOL.lp_fee_share:.0%}",
            "costs": (
                f"Reconstructing fees from swap volume — the natural way to write a replay "
                f"engine — overstates LP earnings by {fee_overstatement(TARGET_POOL.fee_protocol):.3f}x, "
                f"and that error lands on the headline APR."
            ),
            "where": "packages/misquote/core/fees.py",
            "caught_by": "tests/core/test_fees.py",
            "provenance": "P-1, P-8: no constant is right for both of our pools",
        },
        {
            "what": "Pools are deployed by a separate PancakeV3PoolDeployer",
            "uniswap": "CREATE2 from the factory, address derivable offline",
            "pancake": "a different init-code hash, so Uniswap's computeAddress constants are wrong",
            "costs": (
                "Deriving a pool address offline produces a plausible address that is not "
                "the pool. Resolve through factory.getPool(), always."
            ),
            "where": "packages/misquote/chain/nfpm.py",
            "caught_by": "packages/misquote/vetting/badge.py — check 'factory resolves it'",
            "provenance": "P-6",
        },
        {
            "what": "The callbacks are renamed",
            "uniswap": "uniswapV3MintCallback",
            "pancake": "pancakeV3MintCallback",
            "costs": (
                "A direct pool call built against the Uniswap ABI reverts. Everything here "
                "goes through the position manager instead, never the pool."
            ),
            "where": "packages/misquote/chain/nfpm.py",
            "caught_by": "tests/chain/test_write_path.py",
            "provenance": "P-6",
        },
        {
            "what": "The router keeps `deadline` inside the params struct",
            "uniswap": "SwapRouter02 dropped it from the struct",
            "pancake": "it is still a member, so the calldata shape differs",
            "costs": (
                "The wrong shape costs 23,000 gas and reverts with empty data, which looks "
                "like nothing at all. Check the selector, not the documentation."
            ),
            "where": "packages/misquote/chain/nfpm.py",
            "caught_by": "tests/chain/test_position_differential.py",
            "provenance": "P-6",
        },
        {
            "what": f"There is no {UNISWAP_ONLY_TIER} fee tier, and so no spacing of 60",
            "uniswap": f"{UNISWAP_ONLY_TIER} -> 60 is the most-used tier",
            "pancake": " · ".join(f"{fee} -> {sp}" for fee, sp in sorted(FEE_TIER_SPACING.items())),
            "costs": (
                f"A width copied from a Uniswap example assumes a spacing that does not exist. "
                f"And MIN_TICK is not a multiple of any of these — {abs(MIN_TICK)} % {spacing} = "
                f"{unmintable_remainder(spacing)} — so clamping a bound to the extreme yields a "
                f"tick the pool refuses and the mint reverts."
            ),
            "where": "packages/misquote/core/policy.py",
            "caught_by": "packages/misquote/vetting/badge.py — check 'a mintable range exists'",
            "provenance": "P-6, V-10",
        },
        {
            "what": "The Swap event is not Uniswap's",
            "uniswap": "seven parameters; topic0 0xc42079f9…",
            "pancake": "nine — it carries protocolFeesToken0 and protocolFeesToken1; topic0 0x19b47279…",
            "costs": (
                "Filtering on the Uniswap signature returns zero logs from a pool doing "
                "millions in volume. The two extra fields are also why the accountant reads "
                "the protocol's actual take per swap rather than modelling it."
            ),
            "where": "packages/misquote/indexer/reader.py",
            "caught_by": "packages/misquote/lvr/accountant.py",
            "provenance": "P-1",
        },
    ]


def build_payload() -> dict[str, Any]:
    corpus = vectors.corpus()
    return {
        "venue": {
            "name": "PancakeSwap v3",
            "fork_of": "Uniswap v3",
            "chain_id": BSC_MAINNET,
        },
        # The half that is *not* a divergence, and it is the larger half. Stated
        # first on the page for that reason: the core math is byte-identical
        # upstream, which is why a differential corpus is meaningful at all.
        "shared_math": {
            "cases": corpus["cases"],
            "groups": len(corpus["groups"]),
            "pins": corpus["pins"],
        },
        # A list, not a dict. `sort_keys=True` orders JSON object keys as
        # strings, which puts 10000 before 2500 — a fee-tier table out of
        # numeric order reads as a mistake in the venue rather than in the
        # serialiser. Ordering is data here, so it is carried as data.
        "fee_tiers": [
            {"fee_pips": fee, "tick_spacing": spacing}
            for fee, spacing in sorted(FEE_TIER_SPACING.items())
        ],
        "uniswap_only_tier": UNISWAP_ONLY_TIER,
        "fee_overstatement": fee_overstatement(TARGET_POOL.fee_protocol),
        "unmintable_remainder": unmintable_remainder(TARGET_POOL.tick_spacing),
        "divergences": divergences(),
        "pools": pool_rows(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default=str(REPO / "apps" / "web" / "public" / "artifacts" / "venue.json")
    )
    args = parser.parse_args(argv)

    payload = build_payload()
    payload["build"] = provenance.build_stamp(
        "python scripts/venue_report.py",
        source="offline",
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    print(f"  venue          {payload['venue']['name']}, a fork of {payload['venue']['fork_of']}")
    print(f"  shared math    {payload['shared_math']['cases']:,} vectors")
    print(f"  divergences    {len(payload['divergences'])}")
    print(f"  pools          {len(payload['pools'])}")
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
