"""The chain executor, sending real transactions against real contracts.

`agents/warden/live.py` has defined an `Executor` protocol since Step 13 with one
implementation — `SimulatedExecutor`, which moves a position in memory. That is
why `make warden` has no `--live` flag: the decisions were real and nothing could
act on them.

An executor cannot be proven by a stub. The only evidence that
`mint → rebalance → pull` works is a chain that accepts the transactions and a
wallet whose balance comes back, so all of this runs against a forked BSC with
anvil's own funded account. Same contracts as mainnet, no real money.

The assertions to care about are the ones about **what a failure leaves behind**.
A recentre is a close and an open; if the close succeeds and the open does not,
the agent must be flat and solvent rather than holding a position it has lost
track of.
"""

from __future__ import annotations

import pytest
from web3 import Web3

from conftest import FUNDING_ABI, range_around
from misquote.agents.warden.live import Executor
from misquote.chain.addresses import USDT_MAINNET, WBNB_MAINNET
from misquote.chain.executor import ChainExecutor
from misquote.chain.nfpm import PositionManager
from misquote.chain.signer import DryRunRefusal, KillSwitchEngaged
from misquote.core.liquidity import get_liquidity_for_amounts
from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import PositionState

pytestmark = [pytest.mark.chainfork, pytest.mark.live_signing]


def _position(token_id: int | None, lower: int, upper: int, liquidity: int) -> PositionState:
    return PositionState(
        lower=lower,
        upper=upper,
        liquidity=liquidity,
        token_id=token_id,
        minted_ts=0,
        last_rebalance_ts=0,
        rebalances_today=0,
    )


def _liquidity_for(manager: PositionManager, lower: int, upper: int, quote: float) -> int:
    """What `quote` units of each token buys at the current price."""
    sqrt_price = manager._sqrt_price_now()  # noqa: SLF001 — a test may look inside
    return get_liquidity_for_amounts(
        sqrt_price,
        get_sqrt_ratio_at_tick(lower),
        get_sqrt_ratio_at_tick(upper),
        int(quote * 10**18),
        int(quote * 10**18),
    )


def _burned(manager: PositionManager, token_id: int) -> bool:
    """Has the NFT been destroyed?

    `close` ends in `burn`, so afterwards `positions(tokenId)` **reverts** with
    "Invalid token ID" rather than returning an empty position. Asserting
    `liquidity == 0` therefore fails with a contract error rather than an
    assertion, which is how this test first read as a broken executor when the
    executor was right.
    """
    from web3.exceptions import ContractLogicError

    try:
        manager.position(token_id)
    except ContractLogicError as revert:
        # Only a revert counts. Catching `Exception` here would report "burned"
        # for a dropped connection, and the test would pass for the wrong reason.
        assert "Invalid token ID" in str(revert), f"reverted, but not for being gone: {revert}"
        return True
    return False


def _balances(manager: PositionManager) -> tuple[int, int]:
    w3 = manager.w3
    account = manager.signer.address
    usdt = w3.eth.contract(address=Web3.to_checksum_address(USDT_MAINNET), abi=FUNDING_ABI)
    wbnb = w3.eth.contract(address=Web3.to_checksum_address(WBNB_MAINNET), abi=FUNDING_ABI)
    return (
        usdt.functions.balanceOf(account).call(),
        wbnb.functions.balanceOf(account).call(),
    )


# --- it is the thing the protocol asks for ----------------------------------


def test_it_satisfies_the_executor_protocol(manager: PositionManager) -> None:
    """`WardenLive` accepts anything with these three methods. If this drifted,
    the live agent would fail at the first decision rather than at import."""
    executor = ChainExecutor(manager)
    assert isinstance(executor, Executor)


# --- the round trip ---------------------------------------------------------


def test_mint_returns_a_real_token_id_read_from_the_mints_own_log(
    manager: PositionManager,
) -> None:
    """The id comes from the `IncreaseLiquidity` event, not from `balanceOf`.

    `tokenOfOwnerByIndex(owner, balanceOf-1)` returns the newest token the
    *wallet* holds, which is a different thing the moment it holds any other
    position — and it would be wrong silently rather than loudly.
    """
    executor = ChainExecutor(manager)
    lower, upper = range_around(manager, 400)
    liquidity = _liquidity_for(manager, lower, upper, 200)

    token_id = executor.mint(lower, upper, liquidity, ts=0)
    assert token_id is not None and token_id > 0

    on_chain = manager.position(token_id)
    assert on_chain.is_open
    assert (on_chain.lower, on_chain.upper) == (lower, upper)
    assert manager.owns(token_id), "the NFT must be ours or the kill switch cannot close it"

    executor.pull(_position(token_id, lower, upper, on_chain.liquidity), ts=0)
    assert _burned(manager, token_id), "pull must burn the NFT, not merely empty it"


def test_pull_returns_the_capital_to_the_wallet_not_just_out_of_the_pool(
    manager: PositionManager,
) -> None:
    """`decreaseLiquidity` alone moves principal into `tokensOwed` and leaves it
    in the contract — a withdrawal that reports success and withdraws nothing."""
    executor = ChainExecutor(manager)
    lower, upper = range_around(manager, 400)
    before = _balances(manager)

    token_id = executor.mint(lower, upper, _liquidity_for(manager, lower, upper, 200), ts=0)
    on_chain = manager.position(token_id)
    executor.pull(_position(token_id, lower, upper, on_chain.liquidity), ts=0)

    after = _balances(manager)
    spent0, spent1 = before[0] - after[0], before[1] - after[1]
    assert spent0 < 10**15, f"token0 did not come back: {spent0} wei still out"
    assert spent1 < 10**12, f"token1 did not come back: {spent1} wei still out"


def test_rebalance_returns_the_new_token_id_not_the_old_one(
    manager: PositionManager,
) -> None:
    """`decreaseLiquidity` plus `burn` destroys the NFT. Reusing the id would be
    a lie the journal then carries forward, and every later `position(token_id)`
    would read a token that no longer exists."""
    executor = ChainExecutor(manager)
    lower, upper = range_around(manager, 400)
    first = executor.mint(lower, upper, _liquidity_for(manager, lower, upper, 200), ts=0)
    held = manager.position(first)

    new_lower, new_upper = lower + 200, upper + 200
    second = executor.rebalance(
        _position(first, lower, upper, held.liquidity),
        new_lower,
        new_upper,
        _liquidity_for(manager, new_lower, new_upper, 200),
        ts=0,
    )

    assert second is not None
    assert second != first, "the old NFT was burned; this must be a different token"
    moved = manager.position(second)
    assert (moved.lower, moved.upper) == (new_lower, new_upper)
    assert moved.is_open

    executor.pull(_position(second, new_lower, new_upper, moved.liquidity), ts=0)


def test_a_rebalance_that_cannot_open_leaves_the_agent_flat_not_stranded(
    manager: PositionManager,
) -> None:
    """The ordering assertion, and the reason close comes before open.

    A failure between the two legs must leave the wallet holding its own tokens —
    flat, solvent, recoverable by re-running. Opening first would need the
    capital twice and would leave two overlapping positions with no record of
    which is current.
    """
    executor = ChainExecutor(manager)
    lower, upper = range_around(manager, 400)
    token_id = executor.mint(lower, upper, _liquidity_for(manager, lower, upper, 200), ts=0)
    held = manager.position(token_id)
    before = _balances(manager)

    # An unmintable range: the close will succeed and the open will refuse.
    with pytest.raises(ValueError, match="not multiples of the pool's spacing"):
        executor.rebalance(
            _position(token_id, lower, upper, held.liquidity), lower + 3, upper, 10**18, ts=0
        )

    assert _burned(manager, token_id), "the close did not happen"
    after = _balances(manager)
    assert after[0] > before[0] or after[1] > before[1], (
        "the close ran but the capital is not in the wallet — this is the stranded "
        "state the ordering exists to prevent"
    )


# --- it inherits every refusal, and adds none of its own --------------------


def test_the_kill_file_stops_the_executor(manager: PositionManager) -> None:
    """The executor holds no key and makes no safety decision. `BscSigner` does,
    and this asserts the executor did not acquire a second opinion."""
    executor = ChainExecutor(manager)
    lower, upper = range_around(manager, 400)
    manager.signer.kill_file.write_text("stop")
    try:
        with pytest.raises(KillSwitchEngaged):
            executor.mint(lower, upper, _liquidity_for(manager, lower, upper, 100), ts=0)
    finally:
        manager.signer.kill_file.unlink()


def test_dry_run_refuses_the_executor_too(manager: PositionManager, monkeypatch) -> None:
    monkeypatch.setattr(manager.signer, "_dry_run", True)
    executor = ChainExecutor(manager)
    lower, upper = range_around(manager, 400)
    with pytest.raises(DryRunRefusal):
        executor.mint(lower, upper, _liquidity_for(manager, lower, upper, 100), ts=0)


def test_zero_liquidity_is_refused_before_a_transaction_is_built(
    manager: PositionManager,
) -> None:
    """Cheaper than an on-chain revert, and it says which number was wrong."""
    executor = ChainExecutor(manager)
    lower, upper = range_around(manager, 400)
    with pytest.raises(ValueError, match="cannot mint"):
        executor.mint(lower, upper, 0, ts=0)


def test_gas_is_reported_from_receipts_rather_than_estimated(
    manager: PositionManager,
) -> None:
    """What a run actually cost, so the cost model can be checked against it."""
    executor = ChainExecutor(manager)
    lower, upper = range_around(manager, 400)
    token_id = executor.mint(lower, upper, _liquidity_for(manager, lower, upper, 100), ts=0)
    held = manager.position(token_id)
    executor.pull(_position(token_id, lower, upper, held.liquidity), ts=0)

    assert len(executor.sent) == 4, "mint, then decrease + collect + burn"
    assert executor.gas_spent_wei > 0
    assert all(tx.gas_used > 0 for tx in executor.sent)
