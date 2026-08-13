"""The addresses module must stay self-consistent, and must still match the chain.

The offline tests catch a fat-fingered edit. The `chainfork` test catches the
thing offline tests never can: an address that was right when it was written and
is wrong now. Run it with `make fork-diff`, and before any go/no-go.
"""

from __future__ import annotations

import pytest

from misquote.chain.addresses import (
    BSC_MAINNET,
    BSC_TESTNET,
    DEPLOYMENTS,
    POOLS,
    TARGET_POOL,
    TESTNET_MIRROR_POOL,
    deployment_for,
    pool_for,
)

# PancakeSwap v3's fee tiers and their tick spacings. Uniswap's 3000 -> 60 does
# not exist here, so a range width copied from a Uniswap example would be wrong.
PANCAKE_FEE_TIERS = {100: 1, 500: 10, 2500: 50, 10000: 200}


def _is_address(value: str) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("0x")
        and len(value) == 42
        and all(c in "0123456789abcdefABCDEF" for c in value[2:])
    )


@pytest.mark.parametrize("chain_id", sorted(DEPLOYMENTS))
def test_every_deployment_field_looks_like_an_address(chain_id: int) -> None:
    dep = DEPLOYMENTS[chain_id]
    for field in ("factory", "position_manager", "swap_router", "quoter_v2", "multicall3"):
        assert _is_address(getattr(dep, field)), f"{chain_id}.{field}"
    assert dep.chain_id == chain_id
    assert dep.explorer.startswith("https://")


@pytest.mark.parametrize("chain_id", sorted(POOLS))
def test_pool_matches_its_chain_and_fee_tier(chain_id: int) -> None:
    pool = POOLS[chain_id]
    assert pool.chain_id == chain_id
    assert _is_address(pool.address)
    assert _is_address(pool.token0) and _is_address(pool.token1)
    assert pool.token0.lower() != pool.token1.lower()
    assert pool.fee_pips in PANCAKE_FEE_TIERS
    assert pool.tick_spacing == PANCAKE_FEE_TIERS[pool.fee_pips]


@pytest.mark.parametrize("chain_id", sorted(POOLS))
def test_token_ordering_is_address_sorted(chain_id: int) -> None:
    """v3 stores the pair address-sorted, and every price in the system is
    token1-per-token0. A swapped pair inverts every quote silently."""
    pool = POOLS[chain_id]
    assert int(pool.token0, 16) < int(pool.token1, 16)


def test_w_min_is_four_tick_spacings() -> None:
    """Spec section 3.2's anti-dust floor. At 0.05% this is 40 ticks on both chains."""
    assert TARGET_POOL.w_min_ticks == 40
    assert TESTNET_MIRROR_POOL.w_min_ticks == 40


def test_testnet_mirrors_mainnets_tick_geometry() -> None:
    """The mirror only earns the name if the policy meets identical rounding.

    Same fee tier means same tick spacing means same w_min, so a range computed
    on chapel is structurally the range that will be computed on mainnet.
    """
    assert TESTNET_MIRROR_POOL.fee_pips == TARGET_POOL.fee_pips
    assert TESTNET_MIRROR_POOL.tick_spacing == TARGET_POOL.tick_spacing
    assert TESTNET_MIRROR_POOL.w_min_ticks == TARGET_POOL.w_min_ticks


def test_decimals_are_recorded_not_guessed() -> None:
    """BSC's USDT is 18 decimals, not Ethereum's 6. Assuming 6 misprices
    every position by twelve orders of magnitude."""
    assert TARGET_POOL.dec0 == 18
    assert TARGET_POOL.dec1 == 18


def test_lookups_reject_unknown_chains() -> None:
    assert deployment_for(BSC_MAINNET).chain_id == BSC_MAINNET
    assert pool_for(BSC_TESTNET).address == TESTNET_MIRROR_POOL.address
    with pytest.raises(ValueError, match="no verified deployment"):
        deployment_for(1)
    with pytest.raises(ValueError, match="no verified pool"):
        pool_for(1)


@pytest.mark.chainfork
@pytest.mark.parametrize("chain_id", sorted(POOLS))
def test_recorded_pool_still_matches_the_chain(chain_id: int) -> None:
    """An address that was right when written can be wrong now."""
    import os

    from web3 import Web3

    rpc = os.environ.get(
        "BSC_RPC_URL" if chain_id == BSC_MAINNET else "BSC_TESTNET_RPC_URL",
        "https://bsc-rpc.publicnode.com"
        if chain_id == BSC_MAINNET
        else "https://bsc-testnet-rpc.publicnode.com",
    )
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 15}))
    if w3.eth.chain_id != chain_id:
        pytest.skip(f"RPC is chain {w3.eth.chain_id}, not {chain_id}")

    pool_ref = POOLS[chain_id]
    abi = [
        {
            "name": n,
            "type": "function",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"type": t}],
        }
        for n, t in (
            ("token0", "address"),
            ("token1", "address"),
            ("fee", "uint24"),
            ("tickSpacing", "int24"),
            ("factory", "address"),
            ("liquidity", "uint128"),
        )
    ]
    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_ref.address), abi=abi)

    assert pool.functions.token0().call().lower() == pool_ref.token0.lower()
    assert pool.functions.token1().call().lower() == pool_ref.token1.lower()
    assert pool.functions.fee().call() == pool_ref.fee_pips
    assert pool.functions.tickSpacing().call() == pool_ref.tick_spacing
    assert pool.functions.factory().call().lower() == DEPLOYMENTS[chain_id].factory.lower()
    assert pool.functions.liquidity().call() > 0, "pool has drained since it was recorded"
