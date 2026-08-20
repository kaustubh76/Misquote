"""A pool this repository has verified cannot be left off the pages that list them.

`TARGET_POOL_WIDE` was verified, indexed with 14,016 real swaps over the same
30.2 days as the flagship, asserted by `test_addresses.py` to carry a
`fee_protocol` of 3200 against the flagship's 3400 — and it appeared on neither
`/venue` nor `/vetting`.

That is not a typo, it is a shape. Four places needed "the pools we care about
on this chain" and each grew its own subset of `KNOWN_POOLS` by hand:

    vetting/read.py::recorded_for      (*POOLS.values(), EQUITY_POOL)
    vetting/read.py::_known_pools      POOLS[chain] + EQUITY_POOL
    vetting_report.py::listed_pools    POOLS.get(chain) + [TARGET_POOL, EQUITY_POOL]
    venue_report.py                    three literal pool_row(...) calls

The wide pool was in none of them, so the section headed "The pools we actually
read" omitted the pool that decides half of the Agent Advantage Report's third
task, and the nine-check badge run was never pointed at it.

All four derive from `known_pools_on` now. This is the test that says so — not
by checking that they call it, but by checking the property that mattered: every
verified pool reaches every surface. It needs no network; both emitters are pure
projections of the constants.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from misquote.chain.addresses import (
    BSC_MAINNET,
    BSC_TESTNET,
    KNOWN_POOLS,
    POOLS,
    known_pools_on,
)
from misquote.vetting.read import recorded_for

REPO = Path(__file__).resolve().parents[2]


def _script(name: str):
    """Import a `scripts/` module without putting `scripts/` on `sys.path`.

    Same idiom as `tests/web/test_citations.py`, and for the same reason: the
    test must exercise the emitter itself rather than a re-implementation of it,
    or the two drift and the test certifies the drift.
    """
    spec = importlib.util.spec_from_file_location(
        f"misquote_{name}_emitter", REPO / "scripts" / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


venue_report = _script("venue_report")
vetting_report = _script("vetting_report")


@pytest.mark.parametrize("pool", KNOWN_POOLS, ids=lambda p: p.label)
def test_every_verified_pool_reaches_the_venue_page(pool) -> None:
    published = {row["address"].lower() for row in venue_report.pool_rows()}
    assert pool.address.lower() in published, (
        f"{pool.label} is in KNOWN_POOLS and not in venue.json's pool table, "
        "under a heading that reads 'The pools we actually read'."
    )


@pytest.mark.parametrize("pool", KNOWN_POOLS, ids=lambda p: p.label)
def test_every_verified_pool_is_described(pool) -> None:
    """The role is the one field not read off the `PoolRef`, so it is the one
    that can go missing. An empty role publishes a blank cell on the page whose
    argument is that these details were read rather than assumed."""
    role = venue_report.POOL_ROLES.get(pool.address.lower(), "")
    assert role, (
        f"{pool.label} has no entry in venue_report.POOL_ROLES. A pool nobody "
        "has described is a pool nobody has thought about."
    )


@pytest.mark.parametrize("pool", KNOWN_POOLS, ids=lambda p: p.label)
def test_every_verified_pool_is_listed_for_vetting(pool) -> None:
    """Listed, not badged. A pool with no badge on disk is reported by name as
    unbadged — which is the whole point of `listed_pools` — but a pool that is
    not listed at all is invisible in both directions."""
    listed = {address for address, _ in vetting_report.listed_pools(pool.chain_id)}
    assert pool.address.lower() in listed, (
        f"{pool.label} is verified on chain {pool.chain_id} and `make vet` will "
        "never point the nine checks at it."
    )


@pytest.mark.parametrize("pool", KNOWN_POOLS, ids=lambda p: p.label)
def test_the_badge_can_compare_every_verified_pool_against_the_repo(pool) -> None:
    """`recorded_for` returning `None` does not fail — it drops the
    repo-versus-chain comparison for that pool while every other check still
    passes. That is how a wrong `fee_protocol` survived being published once."""
    assert recorded_for(pool.address) == {
        "fee_pips": pool.fee_pips,
        "tick_spacing": pool.tick_spacing,
        "fee_protocol": pool.fee_protocol,
        "dec0": pool.dec0,
        "dec1": pool.dec1,
    }


@pytest.mark.parametrize("chain_id", [BSC_MAINNET, BSC_TESTNET])
def test_the_default_pool_comes_first(chain_id: int) -> None:
    """Both pages lead with the pool this project actually trades. Ordering by
    declaration would put whichever was declared earliest at the top."""
    pools = known_pools_on(chain_id)
    assert pools, f"no verified pool on chain {chain_id}"
    assert pools[0] is POOLS[chain_id]
    assert len({p.address.lower() for p in pools}) == len(pools), "duplicated pool"


def test_the_two_venues_the_report_compares_are_both_published() -> None:
    """The named case, kept as its own test.

    The third task compares two pools and quotes a delta between them. One of
    them had never been checked and appeared on neither page. Parameterised
    coverage above would have caught it, but only as one of eight identical
    failures — this one says what it was.
    """
    from misquote.chain.addresses import TARGET_POOL, TARGET_POOL_WIDE

    published = {row["address"].lower() for row in venue_report.pool_rows()}
    listed = {address for address, _ in vetting_report.listed_pools(BSC_MAINNET)}

    for pool in (TARGET_POOL, TARGET_POOL_WIDE):
        assert pool.address.lower() in published
        assert pool.address.lower() in listed

    assert TARGET_POOL.fee_protocol != TARGET_POOL_WIDE.fee_protocol, (
        "the two venues no longer differ on the protocol fee, which was the "
        "reason each needed its own PoolMeta — retarget this test"
    )
