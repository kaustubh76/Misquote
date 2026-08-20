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
    fee_protocol: int  # numerator out of 10,000, from slot0.feeProtocol
    label: str

    # The symbol of **token1**, because every `*_quote` field in this codebase
    # is denominated in token1 — `CostModel.gas_quote` is BNB, `net_quote` is
    # BNB, `capital_quote` is BNB.
    #
    # This field exists because two meanings of "quote" collide here and they
    # point at *different tokens*. In the trading sense the quote asset is the
    # one you price in, which on this pool is USDT — the docstring above says
    # exactly that. In the field-name sense `_quote` means token1, which is
    # WBNB. So the pair reads WBNB/USDT, the quote asset is USDT, and a figure
    # named `net_quote` is in WBNB. Anything that derives the unit from `label`
    # by taking the second symbol gets the wrong token, confidently.
    #
    # Recorded rather than derived for that reason, and cross-checked against
    # `label` by `tests/chain/test_addresses.py`.
    quote_symbol: str

    @property
    def lp_fee_share(self) -> float:
        """Fraction of each swap fee that reaches liquidity providers.

        PancakeSwap's protocol fee is on by default; Uniswap's is not. Assuming
        LPs keep the whole fee overstates earnings by 1/0.66 on this pool, and
        that error lands on NetFeeAPR, the headline number.
        """
        return 1.0 - self.fee_protocol / 10_000.0

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
    fee_protocol=3400,  # LPs keep 66%; effective fee 0.033%, not 0.05%
    label="PancakeSwap v3 WBNB/USDT 0.05%",
    quote_symbol="WBNB",
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
    fee_protocol=3400,
    label="PancakeSwap v3 WBNB/BUSD 0.05% (chapel mirror)",
    quote_symbol="WBNB",
)

# Tesla xStock — a *tokenized equity*, and the reason this project can say
# anything about the equities category at all.
#
# Backed issues xStocks as BEP-20 on BNB Chain and they trade on PancakeSwap, so
# an equity venue is the same v3 pool the tick math, the LVR accountant and all
# three agents already handle. Nothing in the engine changes; only this address
# does. That makes equities a fourth generality proof rather than a subsystem.
#
# **Every field below was read off chain by `scripts/find_equity_pool.py`**,
# which resolves the pool through `factory.getPool()` and reads the token's own
# `symbol()` back to check it against the source it came from.
#
# `fee_protocol = 3200` against the flagship's 3400, and the way that number was
# arrived at is worth more than the number.
#
# It was first recorded as **0**, and published as finding P-8 claiming LPs kept
# the entire fee here. That was wrong: the reader took `slot0[2]`, which is
# `observationIndex`, not `slot0[5]`, which is `feeProtocol`. Index 2 happened to
# hold 0 on this pool and 101 on the flagship — plausible small integers that
# neither reverted nor looked absurd. Pancake packs the real field as
# `fee0 | (fee1 << 16)`, both uint16, so the flagship's 222,825,800 is 3400 twice
# and this pool's 209,718,400 is 3200 twice.
#
# The finding survives in kind and not in degree: two pools on one DEX really do
# charge different protocol fees, so `PoolMeta.fee_protocol` still has no default
# and still must be read. But it is 34% against 32%, not 34% against nothing, and
# the dramatic version was an artefact of reading the wrong tuple element.
# `vetting/badge.py` now cross-checks every recorded value against chain, which
# is what would have caught it the first time.
#
# Thin, and said plainly: this is the *only* xStocks v3 pool on BSC with real
# liquidity. NVDAx and AAPLx are bridged and have no pool at any fee tier, and
# the 1.00% TSLAx/USDT pool exists with zero liquidity — a pool on paper.
TSLAX_MAINNET = "0x8Ad3c73F833d3f9a523ab01476625F269AeB7cf0"

EQUITY_POOL = PoolRef(
    chain_id=BSC_MAINNET,
    address="0x5E12d6EdB2b7D5330e474ea2D2694A3b3E35d492",
    token0=USDT_MAINNET,  # 0x55d3... sorts before 0x8ad3..., so USDT is token0
    token1=TSLAX_MAINNET,
    dec0=18,
    dec1=18,
    fee_pips=2500,
    tick_spacing=50,
    fee_protocol=3200,  # slot0[5] & 0xFFFF — LPs keep 68%, not 100%. See P-8.
    label="PancakeSwap v3 TSLAx/USDT 0.25%",
    quote_symbol="TSLAx",
)

# The same pair, one fee tier up. This is the second venue task 3 of the Agent
# Advantage Report needs, and it has to be a real pool for that task to be a real
# task — `synthetic_events()` on both sides made "which pool would you choose?"
# a question about a random seed.
#
# It earns the slot by being genuinely different where it matters:
#
#   liquidity     1.99e22   against the flagship's 1.19e24 — 60x shallower
#   fee_protocol  3200      against the flagship's 3400 — LPs keep 68%, not 66%
#
# That second line is P-8 happening a third time on one DEX. Three WBNB/USDT
# tiers, three different protocol fees: 3300 at 0.01%, 3400 at 0.05%, 3200 here.
# Anything that hardcodes one of them misprices the other two, and the error
# lands on NetFeeAPR.
#
# Resolved through `factory.getPool(WBNB, USDT, 2500)` and read back from the
# pool — never derived offline, per P-6.
TARGET_POOL_WIDE = PoolRef(
    chain_id=BSC_MAINNET,
    address="0x1401ff943D08a7E098328C1d3a9d388923B115D2",
    token0=USDT_MAINNET,  # same ordering as the flagship: USDT sorts before WBNB
    token1=WBNB_MAINNET,
    dec0=18,
    dec1=18,
    fee_pips=2500,
    tick_spacing=50,
    fee_protocol=3200,  # LPs keep 68%; effective fee 0.17%, not 0.25%
    label="PancakeSwap v3 WBNB/USDT 0.25%",
    quote_symbol="WBNB",
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


# Every pool this repository has verified on chain, by address. `POOLS` maps a
# chain to its *default* pool and cannot answer "which pool is this address".
KNOWN_POOLS: tuple[PoolRef, ...] = (
    TARGET_POOL,
    TARGET_POOL_WIDE,
    EQUITY_POOL,
    TESTNET_MIRROR_POOL,
)


def known_pools_on(chain_id: int) -> tuple[PoolRef, ...]:
    """Every verified pool on one chain, the default one first.

    ## Why this exists rather than three lists

    Four places needed "the pools we care about on this chain" and each grew its
    own answer: `vetting/read.py` had two — one in `recorded_for`, one in
    `_known_pools` — `vetting_report.py::listed_pools` had a third that its own
    docstring describes as mirroring the second, and `venue_report.py` wrote a
    fourth out by hand as three literal rows.

    `TARGET_POOL_WIDE` was in none of them. It is in `KNOWN_POOLS`, it is
    indexed with 14,016 real swaps, its `fee_protocol` of 3200 against the
    flagship's 3400 is asserted by a test, and it is the second venue in the
    Agent Advantage Report's third task — so half of a judged comparison ran on
    a pool that had never been through the nine checks, and that appeared on
    neither of the two pages whose subject is which pools were read.

    Four hand-maintained subsets of one tuple is why. Deriving them removes the
    class of error rather than this instance of it: a pool added to
    `KNOWN_POOLS` is now published and vetted by construction, and
    `tests/chain/test_known_pools_are_published.py` fails if a caller goes back
    to writing its own list.

    Default first because `/vetting` and `/venue` both lead with the flagship,
    and ordering by declaration would put whichever pool was declared earliest
    at the top of a page about the one this project actually trades.
    """
    default = POOLS.get(chain_id)
    rest = [p for p in KNOWN_POOLS if p.chain_id == chain_id and p is not default]
    return tuple(([default] if default is not None else []) + rest)


def pool_by_address(address: str) -> PoolRef:
    """The verified reference for a pool address, or a refusal.

    Refusing is the point. A pool's `fee_pips`, `tick_spacing`, decimals and
    especially `fee_protocol` decide what its swaps *mean* — reconstructing fees
    with the wrong protocol cut overstates LP earnings by 1.52x on this venue
    (P-1), and the two pools here differ on all four. Indexing an address we have
    not checked would produce a complete, plausible, wrongly-denominated tape,
    which is the failure mode with this project's name on it.
    """
    wanted = address.lower()
    for ref in KNOWN_POOLS:
        if ref.address.lower() == wanted:
            return ref
    known = "\n  ".join(f"{r.address}  {r.label}" for r in KNOWN_POOLS)
    raise ValueError(
        f"{address} is not a pool this repository has verified on chain.\n"
        f"Its fee tier, tick spacing and protocol fee decide what its swaps mean, "
        f"and guessing them produces a tape that looks right and is not.\n"
        f"Verified pools:\n  {known}\n"
        f"To add one: resolve it with scripts/verify_addresses.py and record it here."
    )
