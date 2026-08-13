"""Contract addresses, every one verified on-chain rather than copied.

Regenerate and re-check with:

    uv run python scripts/verify_addresses.py --chain 56
    uv run python scripts/verify_addresses.py --chain 97 --scan

That script checks each address three ways — bytecode present, its interface
answers, and its answers agree with the other contracts' (the position manager
and the router must both name this factory; the pool must name it too, and must
report the fee tier and tick spacing we intend to trade). Nothing here was taken
on trust from documentation.

Verified 2026-08-13: mainnet at block 115,653,558, chapel at block 124,796,408.
"""

from __future__ import annotations

from dataclasses import dataclass

BSC_MAINNET = 56
BSC_TESTNET = 97  # chapel


@dataclass(frozen=True, slots=True)
class Deployment:
    """One chain's PancakeSwap v3 surface."""

    chain_id: int
    factory: str
    position_manager: str
    swap_router: str
    quoter_v2: str
    multicall3: str
    explorer: str


@dataclass(frozen=True, slots=True)
class PoolRef:
    """A pool we have actually read, not one we assume exists.

    `token0`/`token1` are in the pool's own ordering, which is address-sorted and
    is *not* the order the pair is named in. On both of our pools the quote asset
    happens to sort first, so token0 is the stablecoin and token1 is WBNB — the
    price `token1 per token0` is therefore BNB-per-dollar, a number below one.
    Getting this backwards inverts every price in the system, so it is read from
    the pool rather than inferred.
    """

    chain_id: int
    address: str
    token0: str
    token1: str
    dec0: int
    dec1: int
    fee_pips: int
    tick_spacing: int
    label: str

    @property
    def w_min_ticks(self) -> int:
        """Spec section 3.2's anti-dust floor on the range half-width."""
        return 4 * self.tick_spacing


MAINNET = Deployment(
    chain_id=BSC_MAINNET,
    factory="0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865",
    position_manager="0x46A15B0b27311cedF172AB29E4f4766fbE7F4364",
    swap_router="0x1b81D678ffb9C0263b24A97847620C99d213eB14",
    quoter_v2="0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997",
    multicall3="0xcA11bde05977b3631167028862bE2a173976CA11",
    explorer="https://bscscan.com",
)

TESTNET = Deployment(
    chain_id=BSC_TESTNET,
    factory="0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865",
    position_manager="0x427bF5b37357632377eCbEC9de3626C71A5396c1",
    swap_router="0x9a489505a00cE272eAa5e07Dba6491314CaE3796",
    quoter_v2="0xbC203d7f83677c7ed3F7acEc959963E7F4ECC5C2",
    multicall3="0xcA11bde05977b3631167028862bE2a173976CA11",
    explorer="https://testnet.bscscan.com",
)

DEPLOYMENTS: dict[int, Deployment] = {BSC_MAINNET: MAINNET, BSC_TESTNET: TESTNET}

# --- tokens ----------------------------------------------------------------
# BSC's USDT and USDC are 18 decimals, not the 6 they use on Ethereum. Assuming
# 6 here would misprice every position by twelve orders of magnitude, so the
# verification script reads `decimals()` and this file records what it returned.
WBNB_MAINNET = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
USDT_MAINNET = "0x55d398326f99059fF775485246999027B3197955"

WBNB_TESTNET = "0xae13d989daC2f0dEbFf460aC112a837C89BAa7cd"
BUSD_TESTNET = "0xaB1a4d4f1D656d2450692D237fdD6C7f9146e814"

# --- pools -----------------------------------------------------------------
TARGET_POOL = PoolRef(
    chain_id=BSC_MAINNET,
    address="0x36696169C63e42cd08ce11f5deeBbCeBae652050",
    token0=USDT_MAINNET,
    token1=WBNB_MAINNET,
    dec0=18,
    dec1=18,
    fee_pips=500,
    tick_spacing=10,
    label="PancakeSwap v3 WBNB/USDT 0.05%",
)

# Chapel's own WBNB/USDT pool at this tier exists but was initialized at MAX_TICK
# and never seeded — zero liquidity, price pinned at the top of the range. Of the
# twelve usable v3 pools on chapel, WBNB/BUSD 0.05% is the exact structural
# mirror of the mainnet target: same fee tier, so the same tick spacing, so the
# same w_min and the same rounding behaviour the policy will meet on mainnet.
# Burn-in therefore runs against a real pool rather than a fork.
TESTNET_MIRROR_POOL = PoolRef(
    chain_id=BSC_TESTNET,
    address="0xEF1509b7feF4a7dFc94c45Fe9AF2028CA083d11d",
    token0=BUSD_TESTNET,
    token1=WBNB_TESTNET,
    dec0=18,
    dec1=18,
    fee_pips=500,
    tick_spacing=10,
    label="PancakeSwap v3 WBNB/BUSD 0.05% (chapel mirror)",
)

POOLS: dict[int, PoolRef] = {
    BSC_MAINNET: TARGET_POOL,
    BSC_TESTNET: TESTNET_MIRROR_POOL,
}

# Warden never stakes a position into MasterChefV3. Staking transfers the NFT,
# which puts a third party between the kill switch and the position, and CAKE
# emissions would contaminate a metric that claims to be fee APR net of LVR with
# a number that is not a fee. Recorded here so the address is conspicuously
# absent on purpose.
MASTERCHEF_V3_IS_A_NON_GOAL = True


def deployment_for(chain_id: int) -> Deployment:
    try:
        return DEPLOYMENTS[chain_id]
    except KeyError:
        raise ValueError(f"no verified deployment for chain {chain_id}") from None


def pool_for(chain_id: int) -> PoolRef:
    try:
        return POOLS[chain_id]
    except KeyError:
        raise ValueError(f"no verified pool for chain {chain_id}") from None
