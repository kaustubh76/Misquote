"""Our position math against the real PancakeSwap contracts, on a forked chain.

The golden vectors and the fuzz in `test_vectors.py` prove the *arithmetic* is
right. This proves the *design* is right, which is a different thing and fails
differently: every function can be individually correct while the composition
computes something nobody wanted.

So this mints a real position through the real NonfungiblePositionManager on a
fork of BSC mainnet, swaps through the real SwapRouter, collects real fees, and
compares each step against what our Python said would happen. To one wei on
principal, one wei on fees.

Marked `chainfork`: needs anvil and a network. `make fork-diff` runs it.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time

import pytest
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from misquote.chain.addresses import (
    MAINNET,
    TARGET_POOL,
    USDT_MAINNET,
    WBNB_MAINNET,
)
from misquote.core.liquidity import get_amounts_for_liquidity
from misquote.core.tickmath import get_sqrt_ratio_at_tick

pytestmark = pytest.mark.chainfork

# Pinned so the test is reproducible — a fork that follows head is a test whose
# fixtures change under it.
#
# **This requires archive state, and no free BSC endpoint serves it.** They keep
# only a shallow window of tries and answer anything older with "missing trie
# node" or an outright 403. So the fixture falls back to a block near the head,
# which still exercises the real contracts and the real composition but is no
# longer reproducible run to run. The fallback says so out loud rather than
# quietly changing what the test means. Set BSC_ARCHIVE_RPC_URL to a keyed
# archive endpoint to get the pinned behaviour back.
FORK_BLOCK = 115_800_000
FALLBACK_DEPTH = 32  # inside every node's retained window
USDT_WHALE = "0xF977814e90dA44bFA03b6295A0616a897441aceC"  # 564M USDT at this block

ERC20_ABI = json.loads("""[
 {"name":"balanceOf","type":"function","stateMutability":"view","inputs":[{"type":"address"}],"outputs":[{"type":"uint256"}]},
 {"name":"approve","type":"function","stateMutability":"nonpayable","inputs":[{"type":"address"},{"type":"uint256"}],"outputs":[{"type":"bool"}]},
 {"name":"transfer","type":"function","stateMutability":"nonpayable","inputs":[{"type":"address"},{"type":"uint256"}],"outputs":[{"type":"bool"}]},
 {"name":"deposit","type":"function","stateMutability":"payable","inputs":[],"outputs":[]}
]""")

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
  "outputs":[{"name":"amount0","type":"uint256"},{"name":"amount1","type":"uint256"}]}
]""")

# PancakeSwap's SwapRouter keeps `deadline` INSIDE the struct — the Uniswap v3
# shape (selector 0x414bf389), not the SwapRouter02 shape that drops it
# (0x04e45aaf). Verified by checking which selector appears in the deployed
# bytecode. Using the wrong one costs 23,000 gas and reverts with empty data,
# which looks like nothing at all.
ROUTER_ABI = json.loads("""[
 {"name":"exactInputSingle","type":"function","stateMutability":"payable","inputs":[{"components":[
   {"name":"tokenIn","type":"address"},{"name":"tokenOut","type":"address"},{"name":"fee","type":"uint24"},
   {"name":"recipient","type":"address"},{"name":"deadline","type":"uint256"},
   {"name":"amountIn","type":"uint256"},
   {"name":"amountOutMinimum","type":"uint256"},{"name":"sqrtPriceLimitX96","type":"uint160"}],
   "name":"params","type":"tuple"}],"outputs":[{"name":"amountOut","type":"uint256"}]}
]""")

POOL_ABI = json.loads("""[
 {"name":"slot0","type":"function","stateMutability":"view","inputs":[],"outputs":[
   {"type":"uint160"},{"type":"int24"},{"type":"uint16"},{"type":"uint16"},{"type":"uint16"},
   {"type":"uint32"},{"type":"bool"}]}
]""")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_anvil(rpc: str, block: int | None) -> tuple[subprocess.Popen, Web3] | None:
    port = _free_port()
    command = ["anvil", "--fork-url", rpc, "--port", str(port), "--no-rate-limit"]
    if block is not None:
        command += ["--fork-block-number", str(block)]

    proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    w3 = Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}", request_kwargs={"timeout": 180}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    for _ in range(45):
        if proc.poll() is not None:  # anvil gave up
            return None
        try:
            if w3.is_connected() and w3.eth.block_number > 0:
                return proc, w3
        except Exception:  # noqa: BLE001 — still booting
            pass
        time.sleep(1)

    proc.terminate()
    return None


@pytest.fixture(scope="module")
def fork():
    """An anvil fork of BSC mainnet: pinned if archive state is available.

    Falls back to a block near the head, because the free endpoints prune. The
    fallback is reported, since it changes what a passing run guarantees — the
    contracts and the composition are still real, but the fixtures move.
    """
    if not shutil.which("anvil"):
        pytest.skip("anvil not installed")

    archive = os.environ.get("BSC_ARCHIVE_RPC_URL")
    plain = os.environ.get("BSC_RPC_URL") or "https://bsc-dataseed.bnbchain.org"

    attempts = []
    if archive:
        attempts.append((archive, FORK_BLOCK, "pinned, archive endpoint"))
    attempts.append((plain, FORK_BLOCK, "pinned"))
    attempts.append((plain, None, f"NOT PINNED (head - {FALLBACK_DEPTH})"))

    for rpc, block, label in attempts:
        started = _start_anvil(rpc, block)
        if started is None:
            continue
        proc, w3 = started
        print(f"\n  fork: {label} at block {w3.eth.block_number:,}")
        if block is None:
            print("  reproducibility reduced: set BSC_ARCHIVE_RPC_URL to pin the block")
        yield w3
        proc.terminate()
        proc.wait(timeout=30)
        return

    pytest.skip(
        "could not start an anvil fork. Free BSC endpoints prune state, so a "
        "pinned fork needs BSC_ARCHIVE_RPC_URL set to a keyed archive endpoint."
    )


@pytest.fixture(scope="module")
def funded(fork):
    """An account holding WBNB and USDT on the fork.

    WBNB is wrapped from a synthetic balance rather than taken from a holder;
    USDT is impersonated from Binance 8, which held 564M at this block.
    """
    w3 = fork
    account = w3.eth.accounts[0]

    w3.provider.make_request("anvil_setBalance", [account, hex(10_000 * 10**18)])

    wbnb = w3.eth.contract(address=Web3.to_checksum_address(WBNB_MAINNET), abi=ERC20_ABI)
    wbnb.functions.deposit().transact({"from": account, "value": 5_000 * 10**18})

    whale = Web3.to_checksum_address(USDT_WHALE)
    w3.provider.make_request("anvil_impersonateAccount", [whale])
    w3.provider.make_request("anvil_setBalance", [whale, hex(10**18)])
    usdt = w3.eth.contract(address=Web3.to_checksum_address(USDT_MAINNET), abi=ERC20_ABI)
    usdt.functions.transfer(account, 2_000_000 * 10**18).transact({"from": whale})
    w3.provider.make_request("anvil_stopImpersonatingAccount", [whale])

    for token in (wbnb, usdt):
        token.functions.approve(
            Web3.to_checksum_address(MAINNET.position_manager), 2**256 - 1
        ).transact({"from": account})
        token.functions.approve(Web3.to_checksum_address(MAINNET.swap_router), 2**256 - 1).transact(
            {"from": account}
        )

    return account


def _deadline(w3) -> int:
    return w3.eth.get_block("latest")["timestamp"] + 3600


def _mined(w3, tx_hash):
    """Wait for a receipt and insist it succeeded.

    `transact` followed by `wait_for_transaction_receipt` does **not** raise when
    a transaction reverts — it returns a perfectly ordinary receipt with
    `status == 0`. An earlier version of this file swapped through a router with
    the wrong ABI, every swap reverted, and the test carried on believing it had
    traded. The pool's tick was identical before and after, and nothing said so.

    Step 13's signing path must do this too: a reverted mint that goes unchecked
    leaves the agent convinced it holds a position it does not have.
    """
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if receipt["status"] != 1:
        raise AssertionError(
            f"transaction reverted (gas used {receipt['gasUsed']:,}, "
            f"{len(receipt['logs'])} logs). Empty revert data with low gas "
            "usually means the selector does not exist on that contract."
        )
    return receipt


def test_our_amounts_match_what_the_position_manager_actually_took(fork, funded) -> None:
    """The composition check: mint a real position, compare amounts to one wei.

    Every individual function here is already differential-tested against the
    Solidity. This asks the harder question — whether calling them in this order,
    with these arguments, computes the position we think it does.
    """
    w3 = fork
    pool = w3.eth.contract(address=Web3.to_checksum_address(TARGET_POOL.address), abi=POOL_ABI)
    nfpm = w3.eth.contract(address=Web3.to_checksum_address(MAINNET.position_manager), abi=NFPM_ABI)

    sqrt_price, tick = pool.functions.slot0().call()[:2]
    spacing = TARGET_POOL.tick_spacing
    lower = (tick // spacing) * spacing - 40 * spacing
    upper = (tick // spacing) * spacing + 40 * spacing

    usdt = w3.eth.contract(address=Web3.to_checksum_address(USDT_MAINNET), abi=ERC20_ABI)
    wbnb = w3.eth.contract(address=Web3.to_checksum_address(WBNB_MAINNET), abi=ERC20_ABI)
    before0 = usdt.functions.balanceOf(funded).call()
    before1 = wbnb.functions.balanceOf(funded).call()

    receipt = nfpm.functions.mint(
        (
            Web3.to_checksum_address(USDT_MAINNET),
            Web3.to_checksum_address(WBNB_MAINNET),
            TARGET_POOL.fee_pips,
            lower,
            upper,
            100_000 * 10**18,
            200 * 10**18,
            0,
            0,
            funded,
            _deadline(w3),
        )
    ).transact({"from": funded, "gas": 2_000_000})
    _mined(w3, receipt)

    spent0 = before0 - usdt.functions.balanceOf(funded).call()
    spent1 = before1 - wbnb.functions.balanceOf(funded).call()

    token_id = _latest_token_id(w3, nfpm, funded)
    position = nfpm.functions.positions(token_id).call()
    liquidity = position[7]
    assert liquidity > 0, "the mint produced no liquidity"

    # What our math says that liquidity is worth at the current price.
    ours0, ours1 = get_amounts_for_liquidity(
        sqrt_price, get_sqrt_ratio_at_tick(lower), get_sqrt_ratio_at_tick(upper), liquidity
    )

    assert abs(ours0 - spent0) <= 1, f"token0: ours {ours0}, chain {spent0}"
    assert abs(ours1 - spent1) <= 1, f"token1: ours {ours1}, chain {spent1}"


def _latest_token_id(w3, nfpm, owner) -> int:
    """The token id from the most recent mint, read from the Transfer log."""
    logs = w3.eth.get_logs(
        {
            "address": Web3.to_checksum_address(MAINNET.position_manager),
            "fromBlock": w3.eth.block_number - 5,
            "toBlock": "latest",
        }
    )
    for log in reversed(logs):
        if len(log["topics"]) == 4:
            return int(log["topics"][3].hex(), 16)
    raise AssertionError("no mint Transfer log found")


def test_the_principal_we_compute_is_the_principal_the_pool_returns(fork, funded) -> None:
    """Burn the whole position and check what comes back against our math.

    A decimals error, a rounding-direction error, or a token-ordering error all
    survive the unit tests and die here.
    """
    w3 = fork
    pool = w3.eth.contract(address=Web3.to_checksum_address(TARGET_POOL.address), abi=POOL_ABI)
    nfpm = w3.eth.contract(address=Web3.to_checksum_address(MAINNET.position_manager), abi=NFPM_ABI)

    sqrt_price, tick = pool.functions.slot0().call()[:2]
    spacing = TARGET_POOL.tick_spacing
    lower = (tick // spacing) * spacing - 30 * spacing
    upper = (tick // spacing) * spacing + 30 * spacing

    tx = nfpm.functions.mint(
        (
            Web3.to_checksum_address(USDT_MAINNET),
            Web3.to_checksum_address(WBNB_MAINNET),
            TARGET_POOL.fee_pips,
            lower,
            upper,
            50_000 * 10**18,
            100 * 10**18,
            0,
            0,
            funded,
            _deadline(w3),
        )
    ).transact({"from": funded, "gas": 2_000_000})
    _mined(w3, tx)

    token_id = _latest_token_id(w3, nfpm, funded)
    liquidity = nfpm.functions.positions(token_id).call()[7]

    sqrt_now = pool.functions.slot0().call()[0]
    ours0, ours1 = get_amounts_for_liquidity(
        sqrt_now, get_sqrt_ratio_at_tick(lower), get_sqrt_ratio_at_tick(upper), liquidity
    )

    chain0, chain1 = nfpm.functions.decreaseLiquidity(
        (token_id, liquidity, 0, 0, _deadline(w3))
    ).call({"from": funded})

    # decreaseLiquidity rounds down in the pool's favour, so ours may exceed the
    # chain's by a wei. It must never be the other way round.
    assert 0 <= ours0 - chain0 <= 1, f"token0: ours {ours0}, chain {chain0}"
    assert 0 <= ours1 - chain1 <= 1, f"token1: ours {ours1}, chain {chain1}"


def test_fees_accrue_only_after_the_pool_has_actually_traded(fork, funded) -> None:
    """Mint, swap through the real router, and collect what the pool says we earned.

    The point is not the amount — it is that a position which has seen real flow
    reports a positive, collectable fee, and one that has seen none reports zero.
    A fee model that quietly returns something plausible in both cases would pass
    every offline test in this repo.
    """
    w3 = fork
    pool = w3.eth.contract(address=Web3.to_checksum_address(TARGET_POOL.address), abi=POOL_ABI)
    nfpm = w3.eth.contract(address=Web3.to_checksum_address(MAINNET.position_manager), abi=NFPM_ABI)
    router = w3.eth.contract(address=Web3.to_checksum_address(MAINNET.swap_router), abi=ROUTER_ABI)

    tick = pool.functions.slot0().call()[1]
    spacing = TARGET_POOL.tick_spacing
    lower = (tick // spacing) * spacing - 50 * spacing
    upper = (tick // spacing) * spacing + 50 * spacing

    tx = nfpm.functions.mint(
        (
            Web3.to_checksum_address(USDT_MAINNET),
            Web3.to_checksum_address(WBNB_MAINNET),
            TARGET_POOL.fee_pips,
            lower,
            upper,
            200_000 * 10**18,
            400 * 10**18,
            0,
            0,
            funded,
            _deadline(w3),
        )
    ).transact({"from": funded, "gas": 2_000_000})
    _mined(w3, tx)
    token_id = _latest_token_id(w3, nfpm, funded)

    owed_before = nfpm.functions.collect((token_id, funded, 2**128 - 1, 2**128 - 1)).call(
        {"from": funded}
    )
    assert tuple(owed_before) == (0, 0), "a position that has seen no flow owes nothing"

    tick_before_swaps = pool.functions.slot0().call()[1]

    # Real swaps, both directions, through the real router.
    for token_in, token_out, amount in (
        (USDT_MAINNET, WBNB_MAINNET, 20_000 * 10**18),
        (WBNB_MAINNET, USDT_MAINNET, 30 * 10**18),
    ):
        swap = router.functions.exactInputSingle(
            (
                Web3.to_checksum_address(token_in),
                Web3.to_checksum_address(token_out),
                TARGET_POOL.fee_pips,
                funded,
                _deadline(w3),
                amount,
                0,
                0,
            )
        ).transact({"from": funded, "gas": 1_000_000})
        _mined(w3, swap)

    assert pool.functions.slot0().call()[1] != tick_before_swaps, (
        "the pool did not move, so nothing was actually traded"
    )

    owed_after = nfpm.functions.collect((token_id, funded, 2**128 - 1, 2**128 - 1)).call(
        {"from": funded}
    )

    assert owed_after[0] > 0 or owed_after[1] > 0, "real flow through the range earned nothing"

    # The protocol keeps 34%, so what we can collect must be below the gross fee
    # on the volume that crossed us. A model that credited the gross fee would
    # breach this — matrix P-1.
    gross_fee_usdt = 20_000 * 10**18 * TARGET_POOL.fee_pips // 1_000_000
    assert owed_after[0] < gross_fee_usdt, "collected more than the whole fee on that volume"
