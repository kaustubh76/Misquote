"""The position manager: mint, adjust, collect, burn.

Every position transaction the agent makes is built here, so the details that
are easy to get wrong live in one place and are wrong once rather than four
times.

Three of those details cost a debugging session each on the fork (step 10):

**Never derive a pool address offline.** PancakeSwap deploys pools from a
separate `PancakeV3PoolDeployer` with a different init code hash, so Uniswap's
`computeAddress` constants produce a plausible address that is not the pool.
Resolve through `factory.getPool()`.

**Go through the position manager, never the pool.** Pancake renamed the
callbacks (`pancakeV3MintCallback`), so a direct pool call built against the
Uniswap ABI reverts.

**Check the selector, not the documentation.** Pancake's router keeps `deadline`
inside the params struct where SwapRouter02 drops it; the wrong shape costs
23,000 gas and reverts with empty data, which looks like nothing at all.

Withdrawal is deliberately two steps — `decreaseLiquidity` moves the principal
into `tokensOwed`, and only `collect` moves it to the wallet. A "withdraw" that
forgets the second call leaves the money in the contract and reports success.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from web3 import Web3

from misquote.chain.addresses import Deployment
from misquote.chain.signer import BscSigner, SentTransaction
from misquote.core.liquidity import get_amounts_for_liquidity, get_liquidity_for_amounts
from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import PoolMeta, Tick

MAX_UINT128 = 2**128 - 1

NFPM_ABI = json.loads("""[
 {"name":"mint","type":"function","stateMutability":"payable","inputs":[{"components":[
   {"name":"token0","type":"address"},{"name":"token1","type":"address"},{"name":"fee","type":"uint24"},
   {"name":"tickLower","type":"int24"},{"name":"tickUpper","type":"int24"},
   {"name":"amount0Desired","type":"uint256"},{"name":"amount1Desired","type":"uint256"},
   {"name":"amount0Min","type":"uint256"},{"name":"amount1Min","type":"uint256"},
   {"name":"recipient","type":"address"},{"name":"deadline","type":"uint256"}],
   "name":"params","type":"tuple"}],
  "outputs":[{"name":"tokenId","type":"uint256"},{"name":"liquidity","type":"uint128"},
             {"name":"amount0","type":"uint256"},{"name":"amount1","type":"uint256"}]},
 {"name":"positions","type":"function","stateMutability":"view","inputs":[{"type":"uint256"}],
  "outputs":[{"name":"nonce","type":"uint96"},{"name":"operator","type":"address"},
             {"name":"token0","type":"address"},{"name":"token1","type":"address"},
             {"name":"fee","type":"uint24"},{"name":"tickLower","type":"int24"},
             {"name":"tickUpper","type":"int24"},{"name":"liquidity","type":"uint128"},
             {"name":"feeGrowthInside0LastX128","type":"uint256"},
             {"name":"feeGrowthInside1LastX128","type":"uint256"},
             {"name":"tokensOwed0","type":"uint128"},{"name":"tokensOwed1","type":"uint128"}]},
 {"name":"decreaseLiquidity","type":"function","stateMutability":"payable","inputs":[{"components":[
   {"name":"tokenId","type":"uint256"},{"name":"liquidity","type":"uint128"},
   {"name":"amount0Min","type":"uint256"},{"name":"amount1Min","type":"uint256"},
   {"name":"deadline","type":"uint256"}],"name":"params","type":"tuple"}],
  "outputs":[{"name":"amount0","type":"uint256"},{"name":"amount1","type":"uint256"}]},
 {"name":"collect","type":"function","stateMutability":"payable","inputs":[{"components":[
   {"name":"tokenId","type":"uint256"},{"name":"recipient","type":"address"},
   {"name":"amount0Max","type":"uint128"},{"name":"amount1Max","type":"uint128"}],
   "name":"params","type":"tuple"}],
  "outputs":[{"name":"amount0","type":"uint256"},{"name":"amount1","type":"uint256"}]},
 {"name":"burn","type":"function","stateMutability":"payable",
  "inputs":[{"name":"tokenId","type":"uint256"}],"outputs":[]},
 {"name":"ownerOf","type":"function","stateMutability":"view",
  "inputs":[{"type":"uint256"}],"outputs":[{"type":"address"}]}
]""")

ERC20_ABI = json.loads("""[
 {"name":"balanceOf","type":"function","stateMutability":"view",
  "inputs":[{"type":"address"}],"outputs":[{"type":"uint256"}]},
 {"name":"allowance","type":"function","stateMutability":"view",
  "inputs":[{"type":"address"},{"type":"address"}],"outputs":[{"type":"uint256"}]},
 {"name":"approve","type":"function","stateMutability":"nonpayable",
  "inputs":[{"type":"address"},{"type":"uint256"}],"outputs":[{"type":"bool"}]}
]""")

POOL_ABI = json.loads("""[
 {"name":"slot0","type":"function","stateMutability":"view","inputs":[],"outputs":[
   {"type":"uint160"},{"type":"int24"},{"type":"uint16"},{"type":"uint16"},{"type":"uint16"},
   {"type":"uint32"},{"type":"bool"}]}
]""")

FACTORY_ABI = json.loads("""[
 {"name":"getPool","type":"function","stateMutability":"view",
  "inputs":[{"type":"address"},{"type":"address"},{"type":"uint24"}],
  "outputs":[{"type":"address"}]}
]""")


@dataclass(frozen=True, slots=True)
class OnChainPosition:
    """A position as the manager reports it."""

    token_id: int
    lower: Tick
    upper: Tick
    liquidity: int
    tokens_owed0: int
    tokens_owed1: int

    @property
    def is_open(self) -> bool:
        return self.liquidity > 0


class PositionManager:
    """Builds and sends position transactions through the verified NFPM."""

    __slots__ = ("w3", "signer", "meta", "deployment", "contract", "_slippage_bps")

    def __init__(
        self,
        signer: BscSigner,
        meta: PoolMeta,
        deployment: Deployment,
        *,
        slippage_bps: float = 50.0,
    ) -> None:
        if meta.chain_id != signer.chain_id:
            raise ValueError(
                f"pool is on chain {meta.chain_id} but the signer is on {signer.chain_id}"
            )
        self.w3 = signer.w3
        self.signer = signer
        self.meta = meta
        self.deployment = deployment
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(deployment.position_manager), abi=NFPM_ABI
        )
        self._slippage_bps = slippage_bps

    # --- reads -------------------------------------------------------------

    def resolve_pool(self) -> str:
        """Ask the factory. Never compute this address offline.

        Pancake deploys from a separate `PancakeV3PoolDeployer` with its own init
        code hash, so Uniswap's `computeAddress` returns a well-formed address
        that belongs to nothing.
        """
        factory = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.deployment.factory), abi=FACTORY_ABI
        )
        address = factory.functions.getPool(
            Web3.to_checksum_address(self.meta.token0),
            Web3.to_checksum_address(self.meta.token1),
            self.meta.fee_pips,
        ).call()
        if int(address, 16) == 0:
            raise ValueError(
                f"no pool for {self.meta.token0}/{self.meta.token1} at {self.meta.fee_pips} pips"
            )
        return address

    def position(self, token_id: int) -> OnChainPosition:
        raw = self.contract.functions.positions(token_id).call()
        return OnChainPosition(
            token_id=token_id,
            lower=raw[5],
            upper=raw[6],
            liquidity=raw[7],
            tokens_owed0=raw[10],
            tokens_owed1=raw[11],
        )

    def owns(self, token_id: int) -> bool:
        """Whether our signer still holds the NFT.

        False after staking into MasterChefV3, which takes ownership — and then
        every direct call here reverts. Warden never stakes, and this is how that
        non-goal is checked rather than assumed.
        """
        try:
            owner = self.contract.functions.ownerOf(token_id).call()
        except Exception:  # noqa: BLE001 — a burned token has no owner
            return False
        return owner.lower() == self.signer.address.lower()

    # --- writes ------------------------------------------------------------

    def ensure_allowance(self, token: str, amount: int) -> SentTransaction | None:
        """Approve the manager if it cannot already move enough. Idempotent."""
        erc20 = self.w3.eth.contract(address=Web3.to_checksum_address(token), abi=ERC20_ABI)
        current = erc20.functions.allowance(
            self.signer.address, Web3.to_checksum_address(self.deployment.position_manager)
        ).call()
        if current >= amount:
            return None

        call = erc20.functions.approve(
            Web3.to_checksum_address(self.deployment.position_manager), 2**256 - 1
        )
        return self.signer.send(self.signer.build(call))

    def mint(
        self,
        lower: Tick,
        upper: Tick,
        amount0_desired: int,
        amount1_desired: int,
        *,
        deadline_seconds: int = 600,
    ) -> SentTransaction:
        """Open a position. Slippage bounds are not optional, and not naive.

        `amount*Min` of zero tells the pool "take whatever you like at whatever
        price", which on a pool that moved between simulation and inclusion is an
        invitation.

        But bounding each *desired* amount at 99.5% is worse than useless — it
        reverts every time. The curve consumes the two tokens in whatever ratio
        the current price dictates, so one side is nearly exhausted and the other
        barely touched; demanding 99.5% of both is asking for something the pool
        can never do. The fork test found this as "Price slippage check" on the
        very first mint.

        So the bound is computed against what the curve will *actually* take:
        derive the liquidity these amounts buy at the current price, ask our own
        (differential-tested) math what that liquidity costs, and bound those.
        """
        self._require_aligned(lower, upper)

        sqrt_price = self._sqrt_price_now()
        sqrt_lower = get_sqrt_ratio_at_tick(lower)
        sqrt_upper = get_sqrt_ratio_at_tick(upper)

        liquidity = get_liquidity_for_amounts(
            sqrt_price, sqrt_lower, sqrt_upper, amount0_desired, amount1_desired
        )
        if liquidity <= 0:
            raise ValueError("those amounts buy no liquidity at the current price")

        expected0, expected1 = get_amounts_for_liquidity(
            sqrt_price, sqrt_lower, sqrt_upper, liquidity
        )

        call = self.contract.functions.mint(
            (
                Web3.to_checksum_address(self.meta.token0),
                Web3.to_checksum_address(self.meta.token1),
                self.meta.fee_pips,
                lower,
                upper,
                amount0_desired,
                amount1_desired,
                self._with_slippage(expected0),
                self._with_slippage(expected1),
                self.signer.address,
                self._deadline(deadline_seconds),
            )
        )
        return self.signer.send(self.signer.build(call))

    def _sqrt_price_now(self) -> int:
        pool = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.resolve_pool()), abi=POOL_ABI
        )
        return int(pool.functions.slot0().call()[0])

    def decrease_liquidity(
        self,
        token_id: int,
        liquidity: int,
        *,
        min0: int = 0,
        min1: int = 0,
        deadline_seconds: int = 600,
    ) -> SentTransaction:
        """Move principal out of the pool and into `tokensOwed`.

        This does **not** move anything to the wallet. `collect` does that, and
        forgetting it is a withdrawal that reports success and leaves the money
        in the contract.
        """
        call = self.contract.functions.decreaseLiquidity(
            (token_id, liquidity, min0, min1, self._deadline(deadline_seconds))
        )
        return self.signer.send(self.signer.build(call))

    def collect(self, token_id: int) -> SentTransaction:
        """Sweep everything owed — principal from a decrease, plus fees."""
        call = self.contract.functions.collect(
            (token_id, self.signer.address, MAX_UINT128, MAX_UINT128)
        )
        return self.signer.send(self.signer.build(call))

    def burn(self, token_id: int) -> SentTransaction:
        """Destroy an empty position NFT. Reverts unless it is fully collected."""
        return self.signer.send(self.signer.build(self.contract.functions.burn(token_id)))

    def close(self, token_id: int) -> list[SentTransaction]:
        """The whole exit: decrease, collect, burn. What the kill switch calls.

        Ordered so that a failure part-way leaves the funds recoverable by
        re-running: after `decreaseLiquidity` the principal is owed to us and
        `collect` alone recovers it.
        """
        position = self.position(token_id)
        sent: list[SentTransaction] = []
        if position.liquidity > 0:
            sent.append(self.decrease_liquidity(token_id, position.liquidity))
        sent.append(self.collect(token_id))
        sent.append(self.burn(token_id))
        return sent

    # --- helpers -----------------------------------------------------------

    def _require_aligned(self, lower: Tick, upper: Tick) -> None:
        spacing = self.meta.tick_spacing
        if lower % spacing or upper % spacing:
            raise ValueError(
                f"ticks [{lower}, {upper}] are not multiples of the pool's spacing {spacing}; "
                "the mint would revert"
            )
        if lower >= upper:
            raise ValueError(f"range is empty: [{lower}, {upper})")

    def _with_slippage(self, amount: int) -> int:
        return int(amount * (1.0 - self._slippage_bps / 10_000.0))

    def _deadline(self, seconds: int) -> int:
        return int(self.w3.eth.get_block("latest")["timestamp"]) + seconds


def build_abi_selectors() -> dict[str, str]:
    """Selectors for the functions we call, for verifying against bytecode.

    Checking a selector is present in the deployed code is how the router's
    `deadline` discrepancy was found — the ABI you assume and the ABI that is
    deployed are different claims, and only one of them is checkable.
    """
    signatures = {
        "mint": "mint((address,address,uint24,int24,int24,uint256,uint256,uint256,uint256,address,uint256))",
        "decreaseLiquidity": "decreaseLiquidity((uint256,uint128,uint256,uint256,uint256))",
        "collect": "collect((uint256,address,uint128,uint128))",
        "burn": "burn(uint256)",
        "positions": "positions(uint256)",
    }
    return {
        name: "0x" + Web3.keccak(text=sig)[:4].hex().removeprefix("0x")
        for name, sig in signatures.items()
    }
