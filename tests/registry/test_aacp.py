"""TermiX AACP: the sponsor's protocol, and the contract we turned out to share.

The offline tests pin what was read off chain and, more importantly, pin the
*shape* of the refusals — no testnet, no defaulting, no signing on a table that
has moved. The chain-marked ones go and read it again.
"""

from __future__ import annotations

import pytest

from misquote.registry.aacp import (
    BASE_MAINNET,
    BSC_MAINNET,
    CONTRACTS,
    Evidence,
    NoDeployment,
    api_base,
    contracts,
    mismatches,
    shares_our_identity_registry,
)
from misquote.registry.erc8004 import IDENTITY_REGISTRY


def test_termix_reads_the_same_identity_registry_we_do() -> None:
    """The finding that started this module.

    We were reading TermiX's ERC-8004 identity registry before we had heard of
    AACP, because both followed the standard to the address it deploys at on BNB
    Chain. Byte-identical, case aside.
    """
    assert shares_our_identity_registry(BSC_MAINNET)
    assert (
        CONTRACTS[BSC_MAINNET]["IdentityRegistry"].lower() == IDENTITY_REGISTRY[BSC_MAINNET].lower()
    )


def test_the_settlement_token_is_the_one_we_already_record() -> None:
    """Their USDT is our USDT, and token0 of the flagship pool."""
    from misquote.chain.addresses import TARGET_POOL, USDT_MAINNET

    assert CONTRACTS[BSC_MAINNET]["SettlementToken_USDT"].lower() == USDT_MAINNET.lower()
    assert TARGET_POOL.token0.lower() == USDT_MAINNET.lower()


def test_there_is_no_testnet_and_asking_for_one_raises() -> None:
    """TermiX documents chains 56 and 8453 only.

    That matters against a dry-run-by-default posture: with no testnet, anything
    that writes has to run on a fork first. A silent fallback to some other chain
    would be the worst possible answer, so there is none.
    """
    assert api_base(BSC_MAINNET).startswith("https://")
    assert api_base(BASE_MAINNET).startswith("https://")

    for chain_id in (97, 1, 31337):
        with pytest.raises(NoDeployment):
            api_base(chain_id)
        with pytest.raises(NoDeployment):
            contracts(chain_id)


def test_a_moved_address_is_reported_rather_than_guessed() -> None:
    """Their docs say to fetch live addresses before signing. So the snapshot is
    a thing to *check*, and a mismatch stops the caller instead of prompting a
    guess at the new address."""
    live = {k: v for k, v in CONTRACTS[BSC_MAINNET].items()}
    assert mismatches(BSC_MAINNET, live) == []

    moved = dict(live)
    moved["TermixEscrow_USDT"] = "0x" + "9" * 40
    problems = mismatches(BSC_MAINNET, moved)
    assert len(problems) == 1
    assert "TermixEscrow_USDT" in problems[0]


def test_an_empty_live_config_is_a_problem_not_a_pass() -> None:
    """Zero addresses back would make a naive subset check pass vacuously, which
    is how a broken endpoint becomes a green light to sign."""
    assert mismatches(BSC_MAINNET, {}) == ["live config contained no addresses at all"]


def test_evidence_reports_readings_rather_than_a_boolean() -> None:
    """A verification's useful output is what it read, because that is what a
    reader needs in order to disagree with us."""
    evidence = Evidence(chain_id=BSC_MAINNET)
    assert not evidence.ok, "an empty verification must not read as verified"

    evidence.record("escrow has code", True, "170 bytes")
    assert evidence.ok
    evidence.record("interface", False, "jobs() reverted")
    assert not evidence.ok
    assert evidence.failures == ["interface: jobs() reverted"]
    assert "170 bytes" in evidence.render()
    assert "NOT VERIFIED" in evidence.render()


def test_the_escrow_address_matches_the_one_erc8183_carries() -> None:
    """Two modules, one address. If they drifted, the hire flow would price a
    sequence against a contract nobody verified."""
    from misquote.registry.erc8183 import JOB_ESCROW

    assert JOB_ESCROW[BSC_MAINNET].lower() == CONTRACTS[BSC_MAINNET]["TermixEscrow_USDT"].lower()


# --- against the chain ------------------------------------------------------


@pytest.mark.chainfork
def test_the_recorded_table_still_verifies_on_chain() -> None:
    """A recorded chain reading that nobody re-reads is one that rots."""
    from web3 import Web3

    from misquote.registry.aacp import verify

    w3 = None
    for url in ("https://bsc-rpc.publicnode.com", "https://bsc-dataseed.bnbchain.org"):
        try:
            candidate = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 15}))
            if candidate.eth.chain_id == 56:
                w3 = candidate
                break
        except Exception:  # noqa: BLE001 — any endpoint failure means try the next
            continue
    if w3 is None:
        pytest.skip("no BSC endpoint answered")

    evidence = verify(w3, BSC_MAINNET)
    assert evidence.ok, evidence.render()


@pytest.mark.chainfork
def test_the_escrow_is_an_upgradeable_proxy_settling_in_our_usdt() -> None:
    """The two readings that justify the `JOB_ESCROW` entry, and the one that
    qualifies it: escrowed funds sit behind code its owner can replace."""
    from web3 import Web3

    from misquote.chain.addresses import USDT_MAINNET

    w3 = None
    for url in ("https://bsc-rpc.publicnode.com", "https://bsc-dataseed.bnbchain.org"):
        try:
            candidate = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 15}))
            if candidate.eth.chain_id == 56:
                w3 = candidate
                break
        except Exception:  # noqa: BLE001
            continue
    if w3 is None:
        pytest.skip("no BSC endpoint answered")

    escrow = Web3.to_checksum_address(CONTRACTS[BSC_MAINNET]["TermixEscrow_USDT"])

    # EIP-1967 implementation slot. The proxy's own bytecode carries this
    # constant, which is what identifies it as a 1967 proxy rather than a guess.
    slot = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
    implementation = "0x" + w3.eth.get_storage_at(escrow, slot).hex()[-40:]
    assert int(implementation, 16) != 0, "no implementation behind the proxy"
    assert len(w3.eth.get_code(Web3.to_checksum_address(implementation))) > 1000

    # `settlementToken()` read off the escrow itself rather than taken from the
    # documentation. Through the ABI rather than a hand-computed selector — the
    # hardcoded one was wrong, and a magic four bytes is not self-checking.
    contract = w3.eth.contract(
        address=escrow,
        abi=[
            {
                "name": "settlementToken",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [{"type": "address"}],
            }
        ],
    )
    assert contract.functions.settlementToken().call().lower() == USDT_MAINNET.lower()
