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
import os
from dataclasses import dataclass

from web3 import Web3

from misquote.chain.addresses import Deployment
from misquote.chain.signer import BscSigner, SentTransaction
from misquote.core.errors import PositionCapExceeded
from misquote.core.liquidity import get_amounts_for_liquidity, get_liquidity_for_amounts
from misquote.core.tickmath import Q96, get_sqrt_ratio_at_tick
from misquote.core.types import PoolMeta, Tick

# The declared ceiling on what one position may hold, in the pool's token1.
#
# Read here rather than passed in, for the reason `BscSigner` reads its own key
# here rather than taking one: a guard supplied by the caller is a guard the
# caller can decline to supply. Unset means unenforced, and the go/no-go FAILs on
# unset under --mainnet, so the two halves meet.
POSITION_CAP_ENV = "MISQUOTE_POSITION_CAP_QUOTE"

MAX_UINT128 = 2**128 - 1

# `balanceOf` and `tokenOfOwnerByIndex` are ERC-721 Enumerable, and Pancake's
# manager supports it — `supportsInterface(0x780e9d63)` returns true on mainnet,
# verified rather than inferred from Uniswap's ABI. That is what lets a restarted
# agent ask the chain what it holds instead of trusting an empty memory and
# minting a second position on top of the first.
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
  "inputs":[{"type":"uint256"}],"outputs":[{"type":"address"}]},
 {"name":"balanceOf","type":"function","stateMutability":"view",
  "inputs":[{"type":"address"}],"outputs":[{"type":"uint256"}]},
 {"name":"tokenOfOwnerByIndex","type":"function","stateMutability":"view",
  "inputs":[{"type":"address"},{"type":"uint256"}],"outputs":[{"type":"uint256"}]}
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


def _cap_from_env() -> float | None:
    """The declared position cap, or None when this deployment declares none.

    Malformed raises rather than reading as absent, the same rule
    `chain/operator.py::_parse` applies to a mistyped address: `None` is the
    permissive branch, so a typo that fell into it would disable the check it was
    set to enable.
    """
    raw = os.environ.get(POSITION_CAP_ENV, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{POSITION_CAP_ENV}={raw!r} is not a number") from error
    if value <= 0.0:
        raise ValueError(f"{POSITION_CAP_ENV}={value} must be positive; unset it to disable")
    return value


@dataclass(frozen=True, slots=True)
class OnChainPosition:
    """A position as the manager reports it."""

    token_id: int
    lower: Tick
    upper: Tick
    liquidity: int
    tokens_owed0: int
    tokens_owed1: int
    # Which pool this position is actually in. The manager holds positions for
    # every pool on the DEX, so a wallet's token list has to be filtered — and
    # filtering on anything less than (token0, token1, fee) would adopt a
    # position in a different pool as our own.
    token0: str = ""
    token1: str = ""
    fee_pips: int = 0

    @property
    def is_open(self) -> bool:
        return self.liquidity > 0


class PositionManager:
    """Builds and sends position transactions through the verified NFPM."""

    __slots__ = (
        "w3",
        "signer",
        "meta",
        "deployment",
        "contract",
        "_slippage_bps",
        "_position_cap_quote",
    )

    def __init__(
        self,
        signer: BscSigner,
        meta: PoolMeta,
        deployment: Deployment,
        *,
        slippage_bps: float = 50.0,
        position_cap_quote: float | None = None,
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
        self._position_cap_quote = (
            position_cap_quote if position_cap_quote is not None else _cap_from_env()
        )

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
            token0=raw[2],
            token1=raw[3],
            fee_pips=raw[4],
        )

    def tokens_of(self, owner: str) -> list[int]:
        """Every NFPM token id the address holds, across all pools.

        `balanceOf` then `tokenOfOwnerByIndex`, which the manager supports —
        checked on chain, not inferred from Uniswap's ABI. A wallet with no
        positions returns an empty list rather than raising, because holding
        nothing is the ordinary state.
        """
        address = Web3.to_checksum_address(owner)
        try:
            count = int(self.contract.functions.balanceOf(address).call())
        except Exception:  # noqa: BLE001 — an unreachable node is not an empty wallet
            raise
        out: list[int] = []
        for index in range(count):
            try:
                out.append(int(self.contract.functions.tokenOfOwnerByIndex(address, index).call()))
            except Exception:  # noqa: BLE001 — a token moving mid-scan shifts the index
                continue
        return out

    def is_for_pool(self, held: OnChainPosition) -> bool:
        """Is this position in *our* pool?

        All three of token0, token1 and the fee tier, because the first two alone
        name a pair that PancakeSwap runs at four different fee tiers — and
        adopting a position from the 1% pool as though it were the 0.05% one
        would price every fee it earns against the wrong rate.
        """
        return (
            held.token0.lower() == self.meta.token0.lower()
            and held.token1.lower() == self.meta.token1.lower()
            and held.fee_pips == self.meta.fee_pips
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
        """Approve the manager if it cannot already move enough. Idempotent.

        **Approves `amount`, not `2**256 - 1`.** The infinite approval was the
        original, and on a wallet holding only capped capital its marginal risk is
        genuinely small — a compromised manager could take the balance either way.
        The reason to bound it is not risk arithmetic, it is that this project
        sells bounded, revocable grants: `sessions/keys.py` refuses to publish a
        session-key module it cannot verify precisely so that no control here
        promises more than it delivers. An unbounded standing approval sitting
        underneath that page would be the same overclaim in the other direction.

        The cost is one approval per mint, since an exact allowance is consumed by
        the mint that uses it. That is a real gas cost and it is the price of the
        property.
        """
        erc20 = self.w3.eth.contract(address=Web3.to_checksum_address(token), abi=ERC20_ABI)
        current = erc20.functions.allowance(
            self.signer.address, Web3.to_checksum_address(self.deployment.position_manager)
        ).call()
        if current >= amount:
            return None

        call = erc20.functions.approve(
            Web3.to_checksum_address(self.deployment.position_manager), amount
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
        self._assert_within_cap(expected0, expected1, sqrt_price)

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

    def _position_value_quote(self, amount0: int, amount1: int, sqrt_price: int) -> float:
        """What a position holding these amounts is worth, in token1.

        `sqrt_price_x96` squared is token1 per token0 in *raw* units, so the
        decimal adjustment is `dec0 - dec1` — the same conversion
        `replay/engine.py::_inventory` makes, and it has to stay the same one or
        the cap would bind at a different size than the policy believes it sized.
        """
        price = ((sqrt_price / Q96) ** 2) * 10.0 ** (self.meta.dec0 - self.meta.dec1)
        return amount1 / 10.0**self.meta.dec1 + (amount0 / 10.0**self.meta.dec0) * price

    def _assert_within_cap(self, amount0: int, amount1: int, sqrt_price: int) -> None:
        """Refuse a mint that would hold more than this deployment declared.

        Checked against `expected*` rather than `amount*Desired`, because the
        curve takes the two tokens in whatever ratio the price dictates: the
        desired amounts are an offer and the expected ones are what the position
        will actually hold. Capping the offer would refuse mints that were always
        going to be within the cap.

        Placed here, below every caller, for the reason the kill switch sits in
        `signer.send()` — a guard one level up is a guard the next caller forgets.
        `ChainExecutor`, the Warden entrypoint and any script all reach the chain
        through this method.
        """
        if self._position_cap_quote is None:
            return
        value = self._position_value_quote(amount0, amount1, sqrt_price)
        if value > self._position_cap_quote:
            # "token1", not a ticker. `quote_symbol` lives on `PoolRef` and this
            # class holds a `PoolMeta`, and reaching into the pool registry to
            # prettify an error would couple the write path to the verified-pool
            # table for the sake of a word. `.env.example` documents the cap's
            # unit as "the pool's token1", so this is the unit it was set in.
            raise PositionCapExceeded(value, self._position_cap_quote, "token1")

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
