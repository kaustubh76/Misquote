"""The writer's guards, and whether the ABI we assume is the ABI deployed.

Two kinds, following `tests/chain/test_write_path.py`. The offline ones check
that nothing can be registered by accident — wrong chain, empty card, a transfer
of something the signer does not own, a mint log this process cannot find. The
`chainfork` ones check the claim that is not checkable offline: that
`register(string)` and `safeTransferFrom` exist in the bytecode at the address
we intend to call, which is the whole reason `IDENTITY_IMPLEMENTATION` was
recorded — the registry is a 130-byte proxy and a selector's presence is a fact
about the implementation behind it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from web3 import Web3

from misquote.chain.signer import BscSigner
from misquote.registry.erc8004 import (
    IDENTITY_IMPLEMENTATION,
    IDENTITY_IMPLEMENTATION_EVIDENCE,
    IDENTITY_REGISTRY,
)
from misquote.registry.identity import (
    TRANSFER_TOPIC,
    WRITE_ABI,
    IdentityWriter,
    RegistrationNotObserved,
)

#: `scripts/` is a directory of entrypoints, not an importable package — there
#: is no `__init__.py` and nothing puts the repository root on `sys.path`, so
#: `from scripts.register_identity import ...` raises `ModuleNotFoundError`
#: under `make test`. `tests/test_go_no_go.py` loads its script by path for
#: exactly this reason; this follows it rather than adding a second convention.
_REGISTER = Path(__file__).resolve().parents[2] / "scripts" / "register_identity.py"


def _register_identity():
    """The registration script, loaded by path."""
    spec = importlib.util.spec_from_file_location("misquote_register_identity", _REGISTER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BURNER_KEY = "0x" + "11" * 32
BURNER = "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A"


class FakeEth:
    def __init__(self, chain_id: int) -> None:
        self.chain_id = chain_id
        self.gas_price = 3_000_000_000
        self.receipt: dict = {"logs": []}

    def contract(self, address, abi):  # noqa: ANN001
        return Web3().eth.contract(address=address, abi=abi)

    def get_transaction_count(self, *_a, **_k) -> int:
        return 7

    def get_transaction_receipt(self, _tx_hash):  # noqa: ANN001
        return self.receipt


class FakeW3:
    def __init__(self, chain_id: int = 97) -> None:
        self.eth = FakeEth(chain_id)

    @staticmethod
    def to_checksum_address(value):  # noqa: ANN001
        return Web3.to_checksum_address(value)


def writer_for(chain_id: int = 97) -> IdentityWriter:
    return IdentityWriter(BscSigner(FakeW3(chain_id), BURNER_KEY))


# --- what it refuses to be -------------------------------------------------


def test_it_binds_the_registry_recorded_for_the_signers_chain() -> None:
    writer = writer_for(97)
    assert writer.address == Web3.to_checksum_address(IDENTITY_REGISTRY[97])


def test_a_chain_with_no_recorded_registry_is_refused() -> None:
    """Not a `None` and not an empty string cast to an address. `erc8183.py`'s
    reasoning carries over: a caller that ignores a None builds an unsigned
    transaction to the zero address."""
    signer = BscSigner(FakeW3(56), BURNER_KEY)
    signer.chain_id = 999  # a chain the registry map has never heard of
    with pytest.raises(ValueError, match="no ERC-8004 identity registry"):
        IdentityWriter(signer)


def test_a_registry_on_a_different_chain_than_the_signer_is_refused() -> None:
    with pytest.raises(ValueError, match="registry is on chain"):
        IdentityWriter(BscSigner(FakeW3(97), BURNER_KEY), chain_id=56)


# --- what it refuses to send -----------------------------------------------


def test_an_empty_card_is_refused_before_a_transaction_exists() -> None:
    """A registration with a blank tokenURI is a permanent row in a public
    registry saying nothing. It costs the same gas as a real one."""
    with pytest.raises(ValueError, match="empty tokenURI"):
        writer_for().register("   ")


def test_a_transfer_to_the_zero_address_is_refused() -> None:
    with pytest.raises(ValueError, match="zero address"):
        writer_for().transfer(1, "0x" + "00" * 20)


def test_a_transfer_of_something_the_signer_does_not_own_is_refused(monkeypatch) -> None:
    """It would revert on chain anyway. Refusing here says *which* agent and
    *who* holds it, which a reverted receipt does not."""
    writer = writer_for()
    # On the class: `IdentityWriter` uses `__slots__`, so an instance attribute
    # cannot shadow a method.
    monkeypatch.setattr(IdentityWriter, "owner_of", lambda _self, _id: "0x" + "22" * 20)
    with pytest.raises(ValueError, match="owned by"):
        writer.transfer(1913, "0x" + "33" * 20)


# --- reading the id back out of the mint -----------------------------------


def _mint_log(registry: str, to: str, agent_id: int) -> dict:
    return {
        "address": registry,
        "topics": [
            TRANSFER_TOPIC,
            "0x" + "00" * 32,
            "0x" + "00" * 12 + to[2:].lower(),
            "0x" + f"{agent_id:064x}",
        ],
    }


def test_the_id_comes_from_the_mint_log_of_this_transaction() -> None:
    writer = writer_for()
    sent = _sent("0xabc")
    writer.signer.w3.eth.receipt = {
        "logs": [_mint_log(writer.address, BURNER, 1913)],
    }
    assert writer._minted_id(sent) == 1913


def test_a_mint_to_somebody_else_in_the_same_block_is_not_ours() -> None:
    """The failure the log-reading exists to prevent. Asking the registry for
    the highest id after registering would return this one."""
    writer = writer_for()
    writer.signer.w3.eth.receipt = {
        "logs": [_mint_log(writer.address, "0x" + "44" * 20, 9999)],
    }
    with pytest.raises(RegistrationNotObserved):
        writer._minted_id(_sent("0xabc"))


def test_a_log_from_another_contract_is_ignored() -> None:
    writer = writer_for()
    writer.signer.w3.eth.receipt = {"logs": [_mint_log("0x" + "55" * 20, BURNER, 5)]}
    with pytest.raises(RegistrationNotObserved):
        writer._minted_id(_sent("0xabc"))


def test_an_ordinary_transfer_is_not_read_as_a_mint() -> None:
    """`from` must be the zero address. A plain ERC-721 transfer carries the
    same topic and would otherwise be read as a registration."""
    writer = writer_for()
    log = _mint_log(writer.address, BURNER, 7)
    log["topics"][1] = "0x" + "00" * 12 + "66" * 20
    writer.signer.w3.eth.receipt = {"logs": [log]}
    with pytest.raises(RegistrationNotObserved):
        writer._minted_id(_sent("0xabc"))


def test_the_refusal_says_not_to_retry() -> None:
    """Something is registered and this process cannot say under which id.
    Retrying registers a second one, which is why the message says so."""
    writer = writer_for()
    writer.signer.w3.eth.receipt = {"logs": []}
    with pytest.raises(RegistrationNotObserved, match="retrying would register a second one"):
        writer._minted_id(_sent("0xabc"))


def _sent(tx_hash: str):
    from misquote.chain.signer import SentTransaction

    return SentTransaction(tx_hash=tx_hash, block=1, gas_used=100, effective_gas_price=10**9)


# --- the ABI is a capability, so check who holds it -------------------------


def test_the_write_abi_is_not_the_read_abi() -> None:
    """`erc8004.IDENTITY_ABI` is bound by the reader the API uses on every
    request. Adding `register` to it would put a nonpayable call on an object
    whose whole point is that it cannot make one."""
    from misquote.registry.erc8004 import IDENTITY_ABI

    assert all(entry["stateMutability"] == "view" for entry in IDENTITY_ABI)
    assert {e["name"] for e in WRITE_ABI if e["stateMutability"] == "nonpayable"} == {
        "register",
        "setAgentURI",
        "safeTransferFrom",
    }


def test_every_recorded_implementation_carries_its_readings() -> None:
    """An address without its evidence is a number somebody typed —
    `erc8183.py::JOB_ESCROW_EVIDENCE`'s rule, applied to the entry this module
    depends on."""
    assert set(IDENTITY_IMPLEMENTATION) == set(IDENTITY_IMPLEMENTATION_EVIDENCE)
    for chain_id, readings in IDENTITY_IMPLEMENTATION_EVIDENCE.items():
        assert len(readings) >= 2, f"chain {chain_id} has {len(readings)} reading(s)"


@pytest.mark.chainfork
@pytest.mark.parametrize("chain_id", sorted(IDENTITY_REGISTRY))
def test_every_selector_we_call_exists_in_the_deployed_implementation(chain_id: int) -> None:
    """The registry is a proxy, so this asks the implementation.

    Offline tests can only check that we believe `register(string)` is there.
    This is the one that would have caught believing it wrongly.
    """
    from scripts.register_identity import connect  # noqa: PLC0415

    w3 = connect(chain_id)
    code = w3.eth.get_code(Web3.to_checksum_address(IDENTITY_IMPLEMENTATION[chain_id])).hex()
    assert len(code) > 2, "the recorded implementation has no bytecode"

    for entry in WRITE_ABI:
        signature = f"{entry['name']}({','.join(i['type'] for i in entry['inputs'])})"
        selector = Web3.keccak(text=signature)[:4].hex().removeprefix("0x")
        assert selector in code, f"{signature} ({selector}) is not in the implementation"


# --- rewriting a card ------------------------------------------------------


def test_an_empty_card_is_refused_on_update_too() -> None:
    with pytest.raises(ValueError, match="empty tokenURI"):
        writer_for().set_agent_uri(1927, "  ")


def test_setting_a_card_on_an_agent_the_signer_does_not_own_is_refused(monkeypatch) -> None:
    """`setAgentURI` is owner-only on chain. Refusing here names which agent and
    who holds it, which `execution reverted: Not authorized` does not.

    This is the exact shape the first chapel run hit: the identities had already
    been transferred, so the wallet that registered them could no longer correct
    their cards.
    """
    writer = writer_for()
    monkeypatch.setattr(IdentityWriter, "owner_of", lambda _self, _id: "0x" + "22" * 20)
    with pytest.raises(ValueError, match="owner-only"):
        writer.set_agent_uri(1927, "data:application/json;base64,e30=")


def test_a_re_read_does_not_drop_what_it_cannot_re_derive() -> None:
    """`--verify-only` overwrites the record with a fresh report.

    That is right for the checks — re-reading them is the point — and wrong for
    everything a later run has no way to observe. The funding transfer happens
    once; the first verification after it silently dropped the line, leaving a
    record that looked complete and had quietly lost a transaction hash.
    """
    script = _register_identity()

    report = script.Report(97)
    script.carry_forward(
        {"signer": "0xbF4ef75a443E00415Ee2E368caC089e0834930E6", "funding": {"tx": "0xabc"}},
        report,
    )
    assert report.funding == {"tx": "0xabc"}
    assert report.signer == "0xbF4ef75a443E00415Ee2E368caC089e0834930E6"
    assert report.to_dict()["funding"] == {"tx": "0xabc"}


def test_a_record_with_no_funding_publishes_no_funding_key() -> None:
    """Omitted rather than null, so a record with no funding line is a record
    where none happened rather than one where it is unknown."""
    script = _register_identity()

    report = script.Report(97)
    script.carry_forward({"signer": "0x" + "11" * 20}, report)
    assert "funding" not in report.to_dict()
