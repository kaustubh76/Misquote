"""The full position lifecycle, through the real classes, against real contracts.

The plan called for a manual testnet mint before the live loop exists, on the
grounds that approvals, slippage bounds, deadlines and the decrease-then-collect
two-step all bite at once, and debugging them alongside an asyncio loop means
debugging both at the same time. This is that, automated and on a fork — same
contracts, no real money, and it runs in CI.

It exercises `BscSigner` and `PositionManager` themselves rather than raw web3
calls, so what is proven is the code the agent will actually run.

Marked `live_signing`: it genuinely signs, with anvil's well-known burner key
against a local fork. The autouse rail is opted out of deliberately and the
marker says so in the source, which is the whole point of the marker.
"""

from __future__ import annotations

import pytest
from web3 import Web3

from conftest import FUNDING_ABI, range_around
from misquote.chain.addresses import MAINNET, USDT_MAINNET, WBNB_MAINNET
from misquote.chain.nfpm import PositionManager
from misquote.chain.signer import DryRunRefusal, KillSwitchEngaged

pytestmark = [pytest.mark.chainfork, pytest.mark.live_signing]


def test_mint_then_withdraw_returns_the_capital(manager: PositionManager) -> None:
    """Open a position and close it, through the code the agent will run.

    The assertion that matters is the last one: after decrease, collect and burn,
    the capital is back in the wallet. A withdrawal that stops after
    `decreaseLiquidity` reports success and leaves the money in the contract, and
    nothing about the transaction receipt would say so.
    """
    w3 = manager.w3
    usdt = w3.eth.contract(address=Web3.to_checksum_address(USDT_MAINNET), abi=FUNDING_ABI)
    wbnb = w3.eth.contract(address=Web3.to_checksum_address(WBNB_MAINNET), abi=FUNDING_ABI)
    account = manager.signer.address

    lower, upper = range_around(manager, 400)
    before0 = usdt.functions.balanceOf(account).call()
    before1 = wbnb.functions.balanceOf(account).call()

    sent = manager.mint(lower, upper, 50_000 * 10**18, 100 * 10**18)
    assert sent.gas_used > 0
    assert sent.gas_cost_wei > 0

    token_id = _last_token_id(manager, sent.block)
    position = manager.position(token_id)
    assert position.is_open
    assert (position.lower, position.upper) == (lower, upper)
    assert manager.owns(token_id), "the NFT must be ours; staking would break the kill switch"

    manager.close(token_id)

    after0 = usdt.functions.balanceOf(account).call()
    after1 = wbnb.functions.balanceOf(account).call()

    # Principal comes back. Not to the wei — the pool rounds in its own favour on
    # both the way in and the way out — but within a hair of what went in.
    spent0, spent1 = before0 - after0, before1 - after1
    assert spent0 < 10**15, f"token0 not returned: {spent0} wei still out"
    assert spent1 < 10**12, f"token1 not returned: {spent1} wei still out"


def _last_token_id(manager: PositionManager, block: int) -> int:
    logs = manager.w3.eth.get_logs(
        {
            "address": Web3.to_checksum_address(MAINNET.position_manager),
            "fromBlock": block,
            "toBlock": block,
        }
    )
    for log in reversed(logs):
        if len(log["topics"]) == 4:
            return int(log["topics"][3].hex(), 16)
    raise AssertionError("no mint Transfer log in that block")


def test_the_position_manager_refuses_a_range_the_pool_would_reject(
    manager: PositionManager,
) -> None:
    """Caught before a transaction is built, rather than as an on-chain revert.

    A revert costs gas and tells you almost nothing; this says which tick and
    which spacing.
    """
    lower, upper = range_around(manager, 400)
    with pytest.raises(ValueError, match="not multiples of the pool's spacing"):
        manager.mint(lower + 3, upper, 1000, 1000)


def test_the_kill_file_stops_a_real_mint(manager: PositionManager, tmp_path) -> None:
    """The switch, exercised against a live signer rather than a stub.

    This is the assertion the go/no-go depends on: with the file present, the
    agent cannot open a position no matter what it decides.
    """
    lower, upper = range_around(manager, 400)
    manager.signer.kill_file.write_text("stop")
    try:
        with pytest.raises(KillSwitchEngaged):
            manager.mint(lower, upper, 1_000 * 10**18, 2 * 10**18)
    finally:
        manager.signer.kill_file.unlink()


def test_dry_run_refuses_to_broadcast_even_with_a_valid_transaction(
    manager: PositionManager, monkeypatch
) -> None:
    """Dry run is not advisory. The build succeeds, the broadcast does not."""
    lower, upper = range_around(manager, 400)
    monkeypatch.setattr(manager.signer, "_dry_run", True)
    with pytest.raises(DryRunRefusal):
        manager.mint(lower, upper, 1_000 * 10**18, 2 * 10**18)


def test_allowance_is_idempotent(manager: PositionManager) -> None:
    """Already approved: no transaction, no gas, no nonce consumed."""
    assert manager.ensure_allowance(USDT_MAINNET, 10**18) is None
