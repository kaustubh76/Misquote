"""The write path's guards, and whether the ABI we assume is the ABI deployed.

Two kinds of test here. The offline ones check that the guards refuse what they
should refuse — wrong chain, missing key, unaligned ticks, dry run, kill file.
The `chainfork` ones check the claim that is not checkable offline: that every
selector we intend to call actually exists in the bytecode at that address.

That second kind is not theoretical. Step 10 lost a debugging session to a
router whose `exactInputSingle` keeps `deadline` inside the params struct where
SwapRouter02 drops it. The ABI we assumed and the ABI deployed were different
claims, and only one of them was checkable.
"""

from __future__ import annotations

import json

import pytest
from web3 import Web3

from misquote.chain.addresses import MAINNET, TARGET_POOL
from misquote.chain.nfpm import build_abi_selectors
from misquote.chain.signer import (
    DEFAULT_MAX_GAS_PRICE_WEI,
    SUPPORTED_CHAINS,
    BscSigner,
    GasPriceTooHigh,
    KillSwitchEngaged,
    TransactionReverted,
)

# A well-formed key that has never held anything. Only ever used to construct a
# signer object in tests that then refuse to send.
BURNER_KEY = "0x" + "11" * 32


class FakeEth:
    def __init__(self, chain_id: int) -> None:
        self.chain_id = chain_id
        self.gas_price = 3_000_000_000

    def get_transaction_count(self, *_args, **_kwargs) -> int:
        return 7

    def get_block(self, _which):
        return {"timestamp": 1_700_000_000}


class FakeW3:
    def __init__(self, chain_id: int = 56) -> None:
        self.eth = FakeEth(chain_id)


# --- the chain-id guard ----------------------------------------------------


def test_a_signer_refuses_to_exist_for_an_unknown_chain() -> None:
    """Constructed, not signed: the object cannot be brought into being at all.

    Guarding at construction means there is no window in which a correctly
    configured-looking signer is pointed at Ethereum.
    """
    with pytest.raises(ValueError, match="refusing to sign for chain"):
        BscSigner(FakeW3(chain_id=1), BURNER_KEY)


@pytest.mark.parametrize("chain_id", SUPPORTED_CHAINS)
def test_the_supported_chains_are_bsc_and_chapel_only(chain_id: int) -> None:
    signer = BscSigner(FakeW3(chain_id=chain_id), BURNER_KEY)
    assert signer.chain_id == chain_id


def test_a_transaction_for_another_chain_is_refused_before_it_is_signed() -> None:
    """Order matters. A signature over a wrong-chain payload is a replayable
    artefact that exists whether or not it is ever broadcast, so the check has
    to happen while backing out is still free."""
    signer = BscSigner(FakeW3(chain_id=56), BURNER_KEY)
    with pytest.raises(ValueError, match="declares chain 1 but the node is 56"):
        signer._assert_chain({"chainId": 1})


def test_a_transaction_with_no_chain_id_is_refused_as_ambiguous() -> None:
    signer = BscSigner(FakeW3(chain_id=56), BURNER_KEY)
    with pytest.raises(ValueError, match="ambiguous"):
        signer._assert_chain({"nonce": 1})


# --- the key ---------------------------------------------------------------


def test_a_missing_key_is_an_error_not_a_default(monkeypatch) -> None:
    monkeypatch.delenv("MISQUOTE_PRIVATE_KEY", raising=False)
    with pytest.raises(ValueError, match="dedicated hot wallet"):
        BscSigner(FakeW3(), None)


# --- the declared operator -------------------------------------------------
#
# `chain/operator.py` owns the parsing and is tested directly in
# `test_operator.py`. What is checked here is only the wiring: which of the
# signer's two modes consults it, and that the refusal happens at construction
# rather than at `send()`.


def _burner_address() -> str:
    from eth_account import Account

    return Account.from_key(BURNER_KEY).address


def test_dry_run_does_not_consult_the_declaration(monkeypatch) -> None:
    """The offline suite and every read-only run construct signers with keys
    that are nobody's declared operator. A guard that fired here would make the
    declaration unusable for the one case it exists for."""
    monkeypatch.setenv("MISQUOTE_DRY_RUN", "1")
    monkeypatch.setenv("MISQUOTE_OPERATOR_ADDRESS", "0x" + "22" * 20)
    signer = BscSigner(FakeW3(), BURNER_KEY)
    assert signer.dry_run is True


@pytest.mark.live_signing
def test_broadcasting_from_an_undeclared_wallet_is_refused_at_construction(monkeypatch) -> None:
    """The failure this exists for.

    A checkout can easily hold a burn-in key for one address while declaring
    another as its own — this one does. `MISQUOTE_DRY_RUN=0` is then the only
    thing between that and a transaction from a wallet nobody wrote down.

    Refused while the object is being built, for the same reason the unknown
    chain is: there must be no window in which a correctly configured-looking
    signer exists pointing at the wrong wallet.
    """
    from misquote.chain.operator import OperatorMismatch

    monkeypatch.setenv("MISQUOTE_DRY_RUN", "0")
    monkeypatch.setenv("MISQUOTE_OPERATOR_ADDRESS", "0x" + "22" * 20)
    with pytest.raises(OperatorMismatch, match="neither wallet this deployment declared"):
        BscSigner(FakeW3(), BURNER_KEY)


@pytest.mark.live_signing
def test_broadcasting_with_no_declaration_is_left_alone(monkeypatch) -> None:
    """Unchanged behaviour for anyone who has not opted in — notably the fork
    fixtures, which broadcast as one of anvil's own funded accounts."""
    monkeypatch.setenv("MISQUOTE_DRY_RUN", "0")
    monkeypatch.delenv("MISQUOTE_OPERATOR_ADDRESS", raising=False)
    assert BscSigner(FakeW3(), BURNER_KEY).dry_run is False


@pytest.mark.live_signing
def test_a_matching_declaration_broadcasts(monkeypatch) -> None:
    monkeypatch.setenv("MISQUOTE_DRY_RUN", "0")
    monkeypatch.setenv("MISQUOTE_OPERATOR_ADDRESS", _burner_address().lower())
    assert BscSigner(FakeW3(), BURNER_KEY).dry_run is False


# --- the kill switch -------------------------------------------------------


def test_the_kill_file_stops_a_broadcast(tmp_path) -> None:
    """Checked inside the signer rather than only in the event loop.

    A kill switch that lives in the loop is one that works only while the loop
    is healthy, which is not when you need it.
    """
    kill = tmp_path / "KILL"
    signer = BscSigner(FakeW3(), BURNER_KEY, kill_file=kill)

    signer.check_kill_switch()  # absent: fine
    kill.write_text("stop")
    with pytest.raises(KillSwitchEngaged, match="refusing to broadcast"):
        signer.check_kill_switch()


@pytest.mark.live_signing
def test_the_kill_switch_is_checked_before_anything_else_in_send(tmp_path) -> None:
    """Even a transaction that would fail the chain check must not get that far
    — the kill file means stop, not stop-unless-something-else-is-also-wrong.

    Marked `live_signing` because it calls `send` directly, which the autouse
    rail otherwise replaces. That marker is exactly for this: a test that touches
    the write path deliberately, and says so in its own source. Nothing can be
    broadcast here regardless — the web3 object is a stub with no network, and
    the assertion is that we never get past the first guard.
    """
    kill = tmp_path / "KILL"
    kill.write_text("stop")
    signer = BscSigner(FakeW3(), BURNER_KEY, kill_file=kill)

    with pytest.raises(KillSwitchEngaged):
        signer.send({"chainId": 999})  # wrong chain too, but kill wins


# --- dry run is the default ------------------------------------------------


def test_broadcasting_requires_dry_run_to_be_explicitly_disabled(monkeypatch) -> None:
    """An unset environment variable must not be able to spend anything.

    The failure mode of a missing config is refusing to trade, never trading
    unintentionally.
    """
    monkeypatch.delenv("MISQUOTE_DRY_RUN", raising=False)
    assert BscSigner(FakeW3(), BURNER_KEY).dry_run is True

    monkeypatch.setenv("MISQUOTE_DRY_RUN", "")
    assert BscSigner(FakeW3(), BURNER_KEY).dry_run is True

    monkeypatch.setenv("MISQUOTE_DRY_RUN", "0")
    assert BscSigner(FakeW3(), BURNER_KEY).dry_run is False


# --- reverts ---------------------------------------------------------------


def test_a_reverted_receipt_raises_rather_than_being_returned() -> None:
    """The step-10 finding, encoded.

    `wait_for_transaction_receipt` returns an ordinary receipt with `status == 0`
    when a transaction reverts. Every write funnels through `send`, which raises,
    because an unchecked revert leaves the agent believing it holds a position it
    does not — and it keeps deciding on that belief.
    """
    error = TransactionReverted("0xabc", {"gasUsed": 23_003, "logs": []})
    assert "reverted" in str(error)
    assert "23,003" in str(error)
    assert "selector does not exist" in str(error)


# --- what the position manager refuses to build ---------------------------


def test_unaligned_ticks_are_refused_before_a_transaction_is_built() -> None:
    from misquote.chain.nfpm import PositionManager

    signer = BscSigner(FakeW3(chain_id=56), BURNER_KEY)
    meta = _meta()
    manager = PositionManager.__new__(PositionManager)
    object.__setattr__(manager, "meta", meta) if False else None
    manager.meta = meta  # type: ignore[misc]

    with pytest.raises(ValueError, match="not multiples of the pool's spacing"):
        manager._require_aligned(-64403, -64000)
    with pytest.raises(ValueError, match="range is empty"):
        manager._require_aligned(-64000, -64400)
    manager._require_aligned(-64400, -64000)  # aligned: fine
    assert signer.chain_id == 56


def test_slippage_bounds_are_applied_rather_than_left_at_zero() -> None:
    """`amount*Min = 0` tells the pool to take whatever it likes at whatever
    price, which on a pool that moved between simulation and inclusion is an
    invitation rather than a default."""
    from misquote.chain.nfpm import PositionManager

    manager = PositionManager.__new__(PositionManager)
    manager._slippage_bps = 50.0  # type: ignore[misc]

    assert manager._with_slippage(10_000) == 9_950
    assert manager._with_slippage(0) == 0


def _meta():
    from misquote.core.types import PoolMeta

    return PoolMeta(
        address=TARGET_POOL.address,
        chain_id=56,
        token0=TARGET_POOL.token0,
        token1=TARGET_POOL.token1,
        dec0=18,
        dec1=18,
        fee_pips=500,
        tick_spacing=10,
        fee_protocol=3400,
    )


# --- the ABI we assume vs the ABI deployed --------------------------------


@pytest.mark.chainfork
def test_every_selector_we_call_exists_in_the_deployed_bytecode() -> None:
    """The check that would have caught the router's `deadline`.

    An ABI is a claim about a contract. Reading the deployed bytecode is how you
    check it, and it costs one `eth_getCode`.
    """
    from misquote.indexer.reader import connect

    w3 = connect(56)
    code = w3.eth.get_code(Web3.to_checksum_address(MAINNET.position_manager)).hex()
    assert len(code) > 2, "no bytecode at the position manager address"

    missing = [
        name
        for name, selector in build_abi_selectors().items()
        if selector.removeprefix("0x") not in code
    ]
    assert not missing, f"selectors absent from the deployed NFPM: {missing}"


@pytest.mark.chainfork
def test_the_router_keeps_deadline_inside_the_struct() -> None:
    """Pinned, because it is the opposite of what the newer Uniswap router does
    and the wrong guess reverts with empty data and 23,000 gas."""
    from misquote.indexer.reader import connect

    w3 = connect(56)
    code = w3.eth.get_code(Web3.to_checksum_address(MAINNET.swap_router)).hex()

    with_deadline = (
        Web3.keccak(
            text="exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))"
        )[:4]
        .hex()
        .removeprefix("0x")
    )
    without = (
        Web3.keccak(
            text="exactInputSingle((address,address,uint24,address,uint256,uint256,uint160))"
        )[:4]
        .hex()
        .removeprefix("0x")
    )

    assert with_deadline in code, "expected the Uniswap v3 shape"
    assert without not in code, "SwapRouter02 shape is not what is deployed here"


@pytest.mark.chainfork
def test_the_factory_resolves_the_pool_we_have_been_using() -> None:
    """Never derive this offline: Pancake's deployer and init code hash differ
    from Uniswap's, so `computeAddress` returns an address that belongs to
    nothing."""
    from misquote.indexer.reader import connect

    factory_abi = json.loads(
        '[{"name":"getPool","type":"function","stateMutability":"view",'
        '"inputs":[{"type":"address"},{"type":"address"},{"type":"uint24"}],'
        '"outputs":[{"type":"address"}]}]'
    )
    w3 = connect(56)
    factory = w3.eth.contract(address=Web3.to_checksum_address(MAINNET.factory), abi=factory_abi)
    resolved = factory.functions.getPool(
        Web3.to_checksum_address(TARGET_POOL.token0),
        Web3.to_checksum_address(TARGET_POOL.token1),
        TARGET_POOL.fee_pips,
    ).call()

    assert resolved.lower() == TARGET_POOL.address.lower()


# --- the gas-price ceiling -------------------------------------------------
#
# There was no ceiling until a mainnet run with 0.005757 BNB in the wallet went
# looking for one. `build` took `w3.eth.gas_price` verbatim, so the only thing
# between a price spike and an empty wallet was the balance — a limit that
# announces itself by a transaction failing, after the earlier ones in the
# sequence have already been paid for.


class _Call:
    """The smallest thing `build` will accept: an estimate and a build."""

    def __init__(self) -> None:
        self.estimated = False

    def estimate_gas(self, _tx):
        self.estimated = True
        return 21_000

    def build_transaction(self, tx):
        return dict(tx)


def test_a_gas_price_above_the_ceiling_is_refused_before_anything_is_estimated() -> None:
    """And *before* the estimate, which is the placement that matters.

    `estimate_gas` is an RPC round trip and the caller usually has more
    transactions queued behind this one. Refusing here stops a run at the first
    expensive block rather than part-way through a sequence — for a small
    wallet that is the difference between "nothing happened" and "half the
    agents are registered".
    """
    w3 = FakeW3()
    w3.eth.gas_price = DEFAULT_MAX_GAS_PRICE_WEI + 1
    signer = BscSigner(w3, BURNER_KEY)
    call = _Call()

    with pytest.raises(GasPriceTooHigh) as excinfo:
        signer.build(call)

    assert call.estimated is False, "the estimate ran despite the price refusal"
    # Both numbers, because "too high" without them is not actionable.
    assert "1.000 gwei" in str(excinfo.value)


def test_a_price_at_the_ceiling_is_allowed() -> None:
    """Boundary, not a spot check: `>` and `>=` differ by exactly this case."""
    w3 = FakeW3()
    w3.eth.gas_price = DEFAULT_MAX_GAS_PRICE_WEI
    built = BscSigner(w3, BURNER_KEY).build(_Call())
    assert built["gasPrice"] == DEFAULT_MAX_GAS_PRICE_WEI


def test_the_ceiling_can_be_raised_for_a_price_somebody_means_to_pay() -> None:
    w3 = FakeW3()
    w3.eth.gas_price = 5_000_000_000
    signer = BscSigner(w3, BURNER_KEY, max_gas_price_wei=10_000_000_000)
    assert signer.build(_Call())["gasPrice"] == 5_000_000_000


def test_zero_disables_the_ceiling_and_is_a_choice_rather_than_a_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset means the default; `0` means somebody decided. Different states.

    Collapsing them would make "I want no ceiling" indistinguishable from "I
    forgot to set one", on the single variable standing between a spike and the
    balance.
    """
    monkeypatch.setenv("MISQUOTE_MAX_GAS_PRICE_WEI", "0")
    w3 = FakeW3()
    w3.eth.gas_price = 500_000_000_000
    assert BscSigner(w3, BURNER_KEY).build(_Call())["gasPrice"] == 500_000_000_000
