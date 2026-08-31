"""The hire ABI, and the property that makes it an ABI rather than a guess.

`aacp.py` recovered `TermixEscrow`'s dispatch table from bytecode and concluded
the interface was different from ERC-8183's — right about the contract, and
partly wrong about the names it had probed for, which is P-24. So the standing
rule here is that a signature earns its place by being present in deployed code,
not by appearing in a vendor's table.
"""

from __future__ import annotations

import pytest
from eth_utils import keccak

from misquote.registry import erc8183_abi as abi


def test_every_recorded_selector_matches_its_signature() -> None:
    """The tables carry both, so the two can be compared.

    Recording a derivable value is only worth anything if something derives it
    and checks. Otherwise it is a second place for the same typo to live.
    """
    for table in (abi.KERNEL_INTERFACE, abi.ROUTER_INTERFACE):
        for signature, selector in table.items():
            assert abi.selector_for(signature) == selector, signature
            assert selector == "0x" + keccak(text=signature)[:4].hex()


def test_submit_takes_three_arguments_not_the_eip_s_two() -> None:
    """The finding that justifies deriving instead of copying.

    `erc8183.steps()` describes `submit(jobId, deliverable)`. The deployment's is
    `submit(uint256,bytes32,bytes)`. A client encoding the standard's shape hits
    a selector that does not exist and reverts with no reason string — the
    failure mode that looks like a chain problem and is a vocabulary problem.
    """
    assert "submit(uint256,bytes32,bytes)" in abi.KERNEL_INTERFACE
    assert "submit(uint256,bytes32)" not in abi.KERNEL_INTERFACE
    assert abi.selector_for("submit(uint256,bytes32,bytes)") != abi.selector_for(
        "submit(uint256,bytes32)"
    )


def test_the_unresolved_selectors_are_counted_not_hidden() -> None:
    """21 of 65 was `aacp.py`'s honest form and it is this module's too.

    Publishing ten names and implying that is the interface would be the same
    over-claim in a new place.
    """
    assert abi.KERNEL_SELECTORS_RESOLVED == len(abi.KERNEL_INTERFACE)
    assert abi.ROUTER_SELECTORS_RESOLVED == len(abi.ROUTER_INTERFACE)
    assert abi.KERNEL_SELECTORS_RESOLVED < abi.KERNEL_SELECTORS_TOTAL
    assert abi.ROUTER_SELECTORS_RESOLVED < abi.ROUTER_SELECTORS_TOTAL
    assert abi.SIGNATURES_SEARCHED > 20_000, (
        "the search size is what makes 'not present' a measurement rather than a "
        "failure to think of the right name"
    )


def test_the_job_struct_is_not_decoded() -> None:
    """`getJob` is absent from KERNEL_ABI on purpose.

    Its return is a struct nobody here has confirmed field by field, and web3
    needs output types to build a call — so declaring one would produce
    confidently wrong names. `aacp.ORDER_STATE_IS_UNDECODED` is the precedent:
    thirteen well-formed words, one of them ever confirmed.
    """
    assert abi.JOB_STRUCT_IS_UNDECODED is True
    assert not any(item["name"] == "getJob" for item in abi.KERNEL_ABI)
    # It is still named in the interface table, because it exists and answers.
    assert "getJob(uint256)" in abi.KERNEL_INTERFACE


def test_the_abi_only_declares_functions_the_interface_table_names() -> None:
    """No call may be built that was not first found in bytecode."""
    for contract_abi, table in (
        (abi.KERNEL_ABI, abi.KERNEL_INTERFACE),
        (abi.ROUTER_ABI, abi.ROUTER_INTERFACE),
    ):
        for item in contract_abi:
            types = ",".join(i["type"] for i in item["inputs"])
            assert f"{item['name']}({types})" in table, (
                f"{item['name']} is callable and was never resolved against a "
                f"deployed dispatch table"
            )


# --- against the chain ------------------------------------------------------


@pytest.mark.chainfork
def test_every_signature_is_present_in_the_deployed_bytecode() -> None:
    """The check the whole module exists to be able to pass.

    Run forwards, the technique that found P-18 says our names are real. It is
    cheap, and not making P-18's mistake is worth more than the two seconds.
    """
    from web3 import Web3
    from web3.middleware import ExtraDataToPOAMiddleware

    from misquote.registry.erc8183 import EVALUATOR_ROUTER, JOB_ESCROW

    try:
        w3 = Web3(
            Web3.HTTPProvider(
                "https://bsc-testnet-rpc.publicnode.com", request_kwargs={"timeout": 20}
            )
        )
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        if w3.eth.chain_id != 97:
            pytest.skip("endpoint is not chapel")
    except Exception:  # noqa: BLE001
        pytest.skip("no chapel endpoint answered")

    slot = int("0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc", 16)

    def implementation(address: str) -> str:
        raw = w3.eth.get_storage_at(Web3.to_checksum_address(address), slot)
        return Web3.to_checksum_address("0x" + raw.hex()[-40:])

    def selectors(address: str) -> set[str]:
        code = w3.eth.get_code(Web3.to_checksum_address(address))
        found: set[str] = set()
        i = 0
        while i < len(code):
            op = code[i]
            if op == 0x63 and i + 5 <= len(code):  # PUSH4
                found.add(code[i + 1 : i + 5].hex())
                i += 5
                continue
            if 0x60 <= op <= 0x7F:
                i += 1 + (op - 0x5F)
                continue
            i += 1
        return found

    # Both are EIP-1967 proxies, so the dispatch table is on the implementation.
    for table, address, label in (
        (abi.KERNEL_INTERFACE, JOB_ESCROW[97], "kernel"),
        (abi.ROUTER_INTERFACE, EVALUATOR_ROUTER[97], "router"),
    ):
        deployed = selectors(implementation(address))
        assert deployed, f"{label} implementation has no dispatch table"
        for signature, selector in table.items():
            assert selector[2:] in deployed, (
                f"{label}.{signature} is in our ABI and not in the deployed "
                f"bytecode — the name is guessed, not read"
            )
