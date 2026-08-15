"""Resolve a tokenized-equity PancakeSwap v3 pool on BSC, from chain.

    uv run python scripts/find_equity_pool.py

The TermiX track weights "trading, equities, and security" highest. We are deep
in trading and have real security surface; equities was a category we could not
honestly claim at all.

xStocks changes that, and cheaply: Backed issues tokenized US equities as BEP-20
on BNB Chain, and they trade **on PancakeSwap**. So an equity venue is the same
v3 pool our tick math, LVR accountant, fee logic and all three agents already
handle — differential-tested against the real Solidity, 19,546 comparisons. The
only thing that changes is which address we point at. That makes equities a
**fourth generality proof** rather than a new subsystem.

## Why this script exists rather than a hardcoded address

The token addresses came from CoinGecko, which is a secondary source, and this
project does not put a secondary source in `addresses.py`. So this reads the
token's own `symbol()`, `name()` and `decimals()` off BSC, asks the PancakeSwap
factory for every fee tier, and reports `slot0`, `liquidity` and `feeProtocol`
for whatever it finds.

**It is allowed to conclude that no usable pool exists.** If the equity tokens
are bridged to BSC but nobody has opened a v3 pool against them, or the pools
exist with dust, then the honest answer is that the equities venue is not
available and the report says so — not that we quote a dead pool. That refusal is
the same one `registry/erc8183.py` makes about a deployment address it does not
have.

## The finding to look for, stated before running

Tokenized equities carry a structural adverse-selection source WBNB/USDT does
not. The underlying market closes at 21:00 UTC and does not reopen until 14:30
the next weekday; the token keeps trading against a reference price that has
stopped moving. Whoever arrives first at the Monday open takes the gap from
whoever is providing liquidity through it.

That is precisely what the LVR accountant measures and what Sentinel exists to
withdraw from — so an equity pool is where this project's thesis should show up
most strongly, or fail to, and either is worth publishing. The sigma estimator is
already gap-aware (matrix V-8), which matters far more on an asset with a
sixty-five-hour weekend than on a pair that trades continuously.
"""

from __future__ import annotations

import argparse
import sys

from web3 import Web3
from web3.exceptions import Web3Exception

from misquote.chain.addresses import MAINNET, USDT_MAINNET, WBNB_MAINNET

# Same list scripts/verify_addresses.py uses. A handful of eth_call is well
# inside what free endpoints allow — it is sustained eth_getLogs they refuse.
RPCS = (
    "https://bsc-rpc.publicnode.com",
    "https://bsc-dataseed.bnbchain.org",
    "https://bsc-dataseed1.defibit.io",
)

# Sourced from CoinGecko's `platforms.binance-smart-chain`, and treated as
# candidates to verify rather than as facts. Backed issues the same address
# across every EVM chain it deploys to, which is itself a claim this script
# checks by reading the symbol back off BSC.
CANDIDATES = {
    "TSLAx": "0x8ad3c73f833d3f9a523ab01476625f269aeb7cf0",
    "NVDAx": "0xc845b2894dbddd03858fd2d643b4ef725fe0849d",
    "AAPLx": "0x9d275685dc284c8eb1c79f6aba7a63dc75ec890a",
}

QUOTES = {"USDT": USDT_MAINNET, "WBNB": WBNB_MAINNET}
FEE_TIERS = (100, 500, 2500, 10000)

ERC20_ABI = [
    {
        "name": "symbol",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "string"}],
    },
    {
        "name": "name",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "string"}],
    },
    {
        "name": "decimals",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint8"}],
    },
    {
        "name": "totalSupply",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint256"}],
    },
]

FACTORY_ABI = [
    {
        "name": "getPool",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint24"}],
        "outputs": [{"type": "address"}],
    },
]

POOL_ABI = [
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
    },
    {
        "name": "liquidity",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint128"}],
    },
    {
        "name": "token0",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "address"}],
    },
    {
        "name": "token1",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "address"}],
    },
    {
        "name": "tickSpacing",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "int24"}],
    },
]

ZERO = "0x0000000000000000000000000000000000000000"

# Below this, the pool exists on paper and cannot be replayed against. A position
# capped at assumption A1's 1% of pool liquidity would be dust, and every quote
# drawn from it would describe the fixture rather than the market.
MIN_USABLE_LIQUIDITY = 10**15


def erc20(w3: Web3, address: str) -> dict | None:
    """Read a token's own identity off chain, or report that nothing is there."""
    try:
        c = w3.eth.contract(address=Web3.to_checksum_address(address), abi=ERC20_ABI)
        return {
            "symbol": c.functions.symbol().call(),
            "name": c.functions.name().call(),
            "decimals": c.functions.decimals().call(),
            "supply": c.functions.totalSupply().call(),
        }
    except (Web3Exception, ValueError, OverflowError):
        return None


def find_pools(w3: Web3, token: str, decimals: int) -> list[dict]:
    """Every fee tier of every quote asset that actually has a pool."""
    factory = w3.eth.contract(address=Web3.to_checksum_address(MAINNET.factory), abi=FACTORY_ABI)
    found = []
    for quote_name, quote_addr in QUOTES.items():
        for fee in FEE_TIERS:
            try:
                pool = factory.functions.getPool(
                    Web3.to_checksum_address(token),
                    Web3.to_checksum_address(quote_addr),
                    fee,
                ).call()
            except (Web3Exception, ValueError):
                continue
            if pool == ZERO:
                continue

            c = w3.eth.contract(address=pool, abi=POOL_ABI)
            try:
                slot0 = c.functions.slot0().call()
                liquidity = c.functions.liquidity().call()
                token0 = c.functions.token0().call()
                token1 = c.functions.token1().call()
                spacing = c.functions.tickSpacing().call()
            except (Web3Exception, ValueError):
                continue

            found.append(
                {
                    "quote": quote_name,
                    "fee_pips": fee,
                    "address": pool,
                    "sqrt_price_x96": slot0[0],
                    "tick": slot0[1],
                    # slot0 index **5**, not 2. Index 2 is observationIndex, and
                    # reading it produced a confident, plausible, wrong answer:
                    # 0 for this pool, which became a published finding (P-8)
                    # claiming LPs kept the whole fee here. They keep 68%.
                    # Pancake packs feeProtocol as fee0 | (fee1 << 16), both
                    # uint16; the low half applies to token0-in swaps.
                    "fee_protocol": slot0[5] & 0xFFFF,
                    "liquidity": liquidity,
                    "token0": token0,
                    "token1": token1,
                    "tick_spacing": spacing,
                    "dec_equity": decimals,
                }
            )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token", help="verify one address instead of the candidate list")
    parser.add_argument("--symbol", default="CUSTOM")
    args = parser.parse_args()

    candidates = {args.symbol: args.token} if args.token else CANDIDATES

    print("  Tokenized-equity pool discovery — PancakeSwap v3, BSC mainnet")
    print(f"  factory {MAINNET.factory}\n")

    w3 = None
    for url in RPCS:
        try:
            candidate = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 12}))
            if candidate.eth.chain_id == 56:
                print(f"  rpc     {url}  (head {candidate.eth.block_number:,})\n")
                w3 = candidate
                break
        except (Web3Exception, ValueError, OSError):
            continue
    if w3 is None:
        print("  no BSC endpoint answered. This needs an RPC, not a key —")
        print("  a handful of eth_call is well inside what free endpoints allow.")
        return 1

    usable: list[dict] = []
    for symbol, address in candidates.items():
        info = erc20(w3, address)
        if info is None:
            print(f"  {symbol:<8} {address}  -> no ERC-20 at this address on BSC")
            continue

        # The address came from a secondary source. Reading the symbol back is
        # what turns it into a verified one.
        matches = info["symbol"].upper() == symbol.upper()
        mark = "ok" if matches else "MISMATCH"
        print(f"  {symbol:<8} {address}")
        print(
            f"           symbol={info['symbol']!r} ({mark})  name={info['name']!r}  "
            f"decimals={info['decimals']}  supply={info['supply'] / 10 ** info['decimals']:,.2f}"
        )
        if not matches:
            print("           refusing this candidate: the chain disagrees with the source\n")
            continue

        pools = find_pools(w3, address, info["decimals"])
        if not pools:
            print("           no PancakeSwap v3 pool against USDT or WBNB, any fee tier\n")
            continue

        for p in pools:
            deep = p["liquidity"] >= MIN_USABLE_LIQUIDITY
            print(
                f"           v3 {symbol}/{p['quote']} {p['fee_pips'] / 10_000:.2f}%  {p['address']}"
            )
            print(
                f"              liquidity={p['liquidity']:,}  tick={p['tick']}  "
                f"spacing={p['tick_spacing']}  feeProtocol={p['fee_protocol']}  "
                f"{'USABLE' if deep else 'too thin to replay'}"
            )
            if deep:
                p["symbol"] = symbol
                usable.append(p)
        print()

    print(f"  {len(usable)} usable pool(s).")
    if not usable:
        print()
        print("  The equities venue is NOT available, and the report must say so.")
        print("  Tokenized equities are bridged to BSC, but without a v3 pool holding")
        print("  real liquidity there is nothing to replay. Quoting a dust pool would")
        print("  describe the fixture rather than the market — the same refusal")
        print("  registry/erc8183.py makes about a deployment address it does not have.")
        return 2

    best = max(usable, key=lambda p: p["liquidity"])
    print(f"\n  deepest: {best['symbol']}/{best['quote']} at {best['address']}")
    print("  Add it to chain/addresses.py as a PoolRef with these read values.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
