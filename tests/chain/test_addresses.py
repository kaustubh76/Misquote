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
    EQUITY_POOL,
    KNOWN_POOLS,
    POOLS,
    TARGET_POOL,
    TARGET_POOL_WIDE,
    TESTNET_MIRROR_POOL,
    PoolRef,
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


# Derived, not listed. The previous literal held three of the four pools this
# module records, so adding one left it silently uncovered by every test below.
ALL_POOLS = KNOWN_POOLS


@pytest.mark.parametrize("pool", ALL_POOLS, ids=lambda p: p.label)
def test_quote_symbol_names_token1_and_not_the_quote_asset(pool: PoolRef) -> None:
    """`quote_symbol` is the unit of every `*_quote` figure, which is token1.

    The trap: on all three pools the *quote asset* in the trading sense is the
    stablecoin, and it is token0. Labels are written base-first, so the symbol
    before the slash is token1 and the one after it is token0. A reader — human
    or regex — who takes "the quote" from the label's second half gets USDT,
    and every money figure on the front end would then be labelled in the one
    token it is definitely not denominated in.

    Asserting both halves, because asserting only the first would pass on a
    `quote_symbol` that happened to be right for the wrong reason.
    """
    base, _, quote_asset = pool.label.split()[2].partition("/")
    assert pool.quote_symbol == base
    assert pool.quote_symbol != quote_asset


def test_the_equity_pool_is_quoted_in_shares() -> None:
    """Not a curiosity — the reason the unit has to be carried rather than assumed.

    Swap the target pool for the equity one and every `net_quote` in the system
    is denominated in tokenized Tesla. Nothing else in the engine changes, which
    is the generality proof; it also means no default unit is safe.
    """
    assert EQUITY_POOL.quote_symbol == "TSLAx"
    assert EQUITY_POOL.quote_symbol != TARGET_POOL.quote_symbol


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
@pytest.mark.parametrize("pool_ref", KNOWN_POOLS, ids=lambda p: p.label)
def test_recorded_pool_still_matches_the_chain(pool_ref: PoolRef) -> None:
    """An address that was right when written can be wrong now.

    Over `KNOWN_POOLS` rather than `POOLS`: the latter is one default pool per
    chain, so the equity pool and the wide tier — the two whose `fee_protocol`
    differs from the flagship's, which is the field most worth re-reading — were
    never checked against chain at all.
    """
    import os

    chain_id = pool_ref.chain_id

    from web3 import Web3

    # `or`, not `os.environ.get(name, default)`. `.env` carries
    # `BSC_TESTNET_RPC_URL=` with nothing after it — the ordinary way to say "use
    # the public endpoints" — and a set-but-empty variable is a value, so the
    # default never applied and this failed with `Invalid URL ''`. It surfaced
    # the first time the gate was run with `.env` sourced, which is the first
    # time anything ran `--mainnet`. `indexer/reader.py::connect` had already got
    # this right, by filtering falsy candidates.
    rpc = os.environ.get("BSC_RPC_URL" if chain_id == BSC_MAINNET else "BSC_TESTNET_RPC_URL") or (
        "https://bsc-rpc.publicnode.com"
        if chain_id == BSC_MAINNET
        else "https://bsc-testnet-rpc.publicnode.com"
    )
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 15}))
    if w3.eth.chain_id != chain_id:
        pytest.skip(f"RPC is chain {w3.eth.chain_id}, not {chain_id}")

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
    abi.append(
        {
            "name": "slot0",
            "type": "function",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [
                {"type": "uint160"},
                {"type": "int24"},
                {"type": "uint16"},
                {"type": "uint16"},
                {"type": "uint16"},
                {"type": "uint32"},
                {"type": "bool"},
            ],
        }
    )
    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_ref.address), abi=abi)

    assert pool.functions.token0().call().lower() == pool_ref.token0.lower()
    assert pool.functions.token1().call().lower() == pool_ref.token1.lower()
    assert pool.functions.fee().call() == pool_ref.fee_pips
    assert pool.functions.tickSpacing().call() == pool_ref.tick_spacing
    assert pool.functions.factory().call().lower() == DEPLOYMENTS[chain_id].factory.lower()
    assert pool.functions.liquidity().call() > 0, "pool has drained since it was recorded"

    # The field P-1 and P-8 are both about. It is settable by governance per
    # pool, so a recorded value going stale is a live possibility rather than a
    # theoretical one — and it silently rescales every fee the engine computes.
    from misquote.core.fees import unpack_fee_protocol

    fee0, fee1 = unpack_fee_protocol(pool.functions.slot0().call()[5])
    assert fee0 == fee1, f"asymmetric protocol fee {fee0}/{fee1}; lp_fee_share assumes one"
    assert fee0 == pool_ref.fee_protocol, (
        f"{pool_ref.label} now takes {fee0}/10000, recorded {pool_ref.fee_protocol}"
    )


def test_the_same_pair_takes_a_different_protocol_cut_at_every_tier() -> None:
    """Three WBNB/USDT tiers on one DEX, three different protocol fees.

    This is P-8 a third time, and it is the reason `fee_protocol` is a recorded
    per-pool field rather than a module constant. Read from chain 18 Aug 2026:

        0.01%   feeProtocol 3300    LPs keep 67%
        0.05%   feeProtocol 3400    LPs keep 66%   <- the flagship
        0.25%   feeProtocol 3200    LPs keep 68%   <- the wide tier

    Same pair, same factory, same deployer. Anything that hardcodes one of them
    misprices the other two, and the error lands on NetFeeAPR — the headline
    number on every card.
    """
    assert TARGET_POOL.fee_protocol == 3400
    assert TARGET_POOL_WIDE.fee_protocol == 3200
    assert TARGET_POOL.fee_protocol != TARGET_POOL_WIDE.fee_protocol

    assert TARGET_POOL.lp_fee_share == pytest.approx(0.66)
    assert TARGET_POOL_WIDE.lp_fee_share == pytest.approx(0.68)


def test_the_wide_tier_is_the_same_pair_and_the_same_unit() -> None:
    """It is only a comparable venue if the money is denominated identically.

    Task 3 of the advantage report puts these two side by side and states a
    difference in percentage points. Different token ordering, different
    decimals or a different `quote_symbol` would make that subtraction
    meaningless while still producing a number.
    """
    assert TARGET_POOL_WIDE.token0 == TARGET_POOL.token0
    assert TARGET_POOL_WIDE.token1 == TARGET_POOL.token1
    assert TARGET_POOL_WIDE.dec0 == TARGET_POOL.dec0
    assert TARGET_POOL_WIDE.dec1 == TARGET_POOL.dec1
    assert TARGET_POOL_WIDE.quote_symbol == TARGET_POOL.quote_symbol

    # ...and genuinely a different venue, or the task compares a pool to itself.
    assert TARGET_POOL_WIDE.address != TARGET_POOL.address
    assert TARGET_POOL_WIDE.fee_pips != TARGET_POOL.fee_pips
    assert TARGET_POOL_WIDE.w_min_ticks == 200  # 4 * 50, against the flagship's 40
