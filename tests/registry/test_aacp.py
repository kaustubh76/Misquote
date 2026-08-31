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


def test_erc8183_carries_no_address_for_this_escrow() -> None:
    """The two modules agree, and what they agree on has changed.

    They used to hold the same address, and the test was that they had not
    drifted. Then `erc8183.JOB_ESCROW` was emptied — TermiX's escrow is
    order-keyed by bytes32 and implements none of the seven ERC-8183 calls
    (P-18) — and the invariant became "it must not reappear there".

    It has still not reappeared. `JOB_ESCROW` is no longer empty, but what is in
    it is a **different contract**: the AgenticCommerce kernel, which answers
    `jobCounter()` and `paymentToken()` and carries 56,632 jobs. That is
    evidence of exactly the different kind this test demanded, about a different
    address — so the invariant is unchanged and now has something to bite on.
    """
    from misquote.registry.erc8183 import JOB_ESCROW

    termix = CONTRACTS[BSC_MAINNET]["TermixEscrow_USDT"]
    assert JOB_ESCROW[BSC_MAINNET].lower() != termix.lower(), (
        "the escrow disproved by P-18 is back in JOB_ESCROW"
    )
    # Still recorded here, because the contract is real and the snapshot is what
    # `mismatches()` checks their live config against.
    assert CONTRACTS[BSC_MAINNET]["TermixEscrow_USDT"].startswith("0x")


def test_the_recovered_interface_is_selectors_not_names() -> None:
    """Every entry is a signature paired with the 4 bytes it hashes to.

    Recorded as selectors because that is what was actually observed in the
    deployed dispatch table. A name alone would be a claim about a contract
    whose source we have never read.
    """
    from eth_utils import keccak

    from misquote.registry.aacp import ESCROW_INTERFACE

    assert ESCROW_INTERFACE, "the finding is the interface; an empty dict states nothing"
    for signature, selector in ESCROW_INTERFACE.items():
        assert selector == "0x" + keccak(text=signature)[:4].hex(), signature


def test_the_unresolved_selectors_are_counted_not_hidden() -> None:
    """44 of 65 selectors were not resolved, and that is published.

    A partial decode reported as a decode is how a plausible-looking ABI gets
    built out of guesses. The ratio is the honest headline.
    """
    from misquote.registry.aacp import (
        ESCROW_INTERFACE,
        ESCROW_SELECTORS_RESOLVED,
        ESCROW_SELECTORS_TOTAL,
    )

    assert ESCROW_SELECTORS_RESOLVED < ESCROW_SELECTORS_TOTAL
    assert len(ESCROW_INTERFACE) <= ESCROW_SELECTORS_RESOLVED


def test_the_order_state_is_not_claimed() -> None:
    """No word in the struct separates SETTLED from PENDING_ACCEPT.

    So this module does not offer a way to read an order's state, and the flag
    saying so is asserted rather than left as a comment somebody deletes.
    """
    from misquote.registry.aacp import ORDER_STATE_IS_UNDECODED

    assert ORDER_STATE_IS_UNDECODED is True


# --- against the chain ------------------------------------------------------


@pytest.mark.chainfork
def test_the_recorded_table_still_verifies_on_chain() -> None:
    """A recorded chain reading that nobody re-reads is one that rots.

    This asserted `evidence.ok`, and **it had been failing since P-18** — silently,
    because `chainfork` is deselected from `make test` and only `make fork-diff`
    and the go/no-go's chain suite ever run it.

    `verify()` is the gate on `JOB_ESCROW`, and P-18's whole finding is that
    `TermixEscrow` must not pass it. So `ok` is False *by construction* and will
    stay False for as long as the finding holds: the test was demanding the
    opposite of what the module was written to conclude.

    What re-reading this table is actually for is **drift**, and the escrow is an
    upgradeable proxy — the module's own evidence records that escrowed funds sit
    behind code its owner can replace. So the readings are asserted one by one:
    the four table facts still hold, and the interface is still absent. If TermiX
    ever upgrades that proxy into an ERC-8183 escrow, the last assertion goes red
    and P-18 needs rewriting rather than re-passing.
    """
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
    readings = {name: (ok, detail) for name, ok, detail in evidence.checks}

    for name in (
        "escrow has code",
        "identity registry is ours",
        "identity registry answers",
        "settlement token is ours",
    ):
        assert readings[name][0], f"{name}: {readings[name][1]}\n{evidence.render()}"

    implements, detail = readings["implements ERC-8183"]
    assert implements is False, (
        "TermixEscrow now answers an ERC-8183 accessor. It is an upgradeable "
        "proxy, so this is a real possibility rather than a flaky read — and it "
        f"would mean P-18 is stale, not that this test is. Reading: {detail}"
    )

    assert not evidence.ok, (
        "verify() is the gate on JOB_ESCROW and P-18 is the finding that this "
        "address must not clear it"
    )


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


# --- the check verify() was missing -----------------------------------------


class _FakeEth:
    """Enough chain to drive `verify()` without one.

    `implements_erc8183` decides by whether three `eth_call`s revert, so a fake
    that raises for all of them models a non-8183 escrow exactly, and one that
    returns models the opposite.
    """

    def __init__(self, *, jobs_answer: bool) -> None:
        self.jobs_answer = jobs_answer

    def get_code(self, _address):
        return b"\x60" * 200

    def call(self, _tx):
        if not self.jobs_answer:
            raise ValueError("execution reverted")
        return (0).to_bytes(32, "big")

    def contract(self, **_kwargs):
        class _Fn:
            def name(self):
                class _C:
                    def call(self_inner):
                        return "AgentIdentity"

                return _C()

        class _Contract:
            functions = _Fn()

        return _Contract()


class _FakeW3:
    def __init__(self, *, jobs_answer: bool) -> None:
        self.eth = _FakeEth(jobs_answer=jobs_answer)

    @staticmethod
    def to_checksum_address(address):
        return address

    def contract(self, **kwargs):
        return self.eth.contract(**kwargs)


def _verify(*, jobs_answer: bool):
    from misquote.registry import aacp

    w3 = _FakeW3(jobs_answer=jobs_answer)
    w3.eth.contract = w3.eth.contract  # noqa: PLW0127 — explicit, the fake is the point
    return aacp.verify(w3, aacp.BSC_MAINNET)


def test_verify_records_whether_the_escrow_implements_the_standard() -> None:
    """The defect this test exists for is an omission, not a wrong value.

    `verify()` checked four things — code present, identity registry is ours,
    registry answers, settlement token is ours — and every one of them passed on
    a contract that implements none of ERC-8183. The module's own instructions
    said a passing `verify()` was what gated `JOB_ESCROW`, so following them
    reproduced P-18. So this asserts the check is *present*, which is the
    property that was missing.
    """
    evidence = _verify(jobs_answer=False)
    names = [name for name, _, _ in evidence.checks]

    assert "implements ERC-8183" in names, (
        "verify() omits the one check that distinguishes a real escrow from an "
        "ERC-8183 escrow — this is exactly the omission that caused P-18"
    )


def test_a_non_8183_escrow_cannot_produce_a_passing_verification() -> None:
    """`Evidence.ok` is `all(...)`, so recording the check is enough to sink it.

    Without this, the four true-but-irrelevant checks made `ok` true and the
    caller was told to populate the mapping.
    """
    evidence = _verify(jobs_answer=False)

    assert not evidence.ok
    assert any("P-18" in detail for _, ok, detail in evidence.checks if not ok)


def test_the_verification_can_still_pass_when_the_interface_is_there() -> None:
    """A gate that can never go green says nothing. If an escrow ever does
    answer the ERC-8183 accessors, `verify()` must be able to say so."""
    evidence = _verify(jobs_answer=True)

    assert evidence.ok, evidence.failures
    assert ("implements ERC-8183", True) in [(n, ok) for n, ok, _ in evidence.checks]


def test_the_accessor_probe_is_a_set_not_a_spelling() -> None:
    """P-18 and P-24 are the same defect pointed in opposite directions.

    P-18 found `TermixEscrow` implements none of ERC-8183 — true, and still
    true. P-24 then found a kernel that does, in a table the EIP does not
    publish and the ecosystem does, reading 56,632 jobs on BSC mainnet. Its
    accessor is `jobCounter()`.

    This probe checked `jobs(uint256)`, `nextJobId()` and `jobCount()` — none of
    them that one — so it returned False for a contract that had passed every
    check `scripts/verify_erc8183.py` makes. A false negative in the function
    written to gate `JOB_ESCROW` is exactly as bad as the false positive it was
    written to prevent.

    The EIP is Draft and deployments differ in how they spell the accessor, so
    the probe tests an interface only if it tests a set of names.
    """
    from misquote.registry.aacp import ERC8183_ACCESSORS

    assert "jobCounter()" in ERC8183_ACCESSORS, (
        "the one deployment this repository has verified answers jobCounter(), "
        "and a probe that omits it refuses a real ERC-8183 kernel"
    )
    assert len(ERC8183_ACCESSORS) > 1, "one spelling is a vocabulary, not an interface"


def test_a_contract_answering_any_accessor_counts_as_erc8183() -> None:
    """Any one is sufficient. Requiring all of them would refuse every real
    deployment, since no contract implements four spellings of one idea."""
    from eth_utils import keccak

    from misquote.registry import aacp

    def only(signature: str):
        """A chain where exactly one accessor answers and the rest revert."""
        wanted = keccak(text=signature)[:4]

        class _Eth:
            @staticmethod
            def call(tx):
                if tx["data"][:4] == wanted:
                    return (0).to_bytes(32, "big")
                raise ValueError("execution reverted")

        class _W3:
            eth = _Eth()

            @staticmethod
            def to_checksum_address(address):
                return address

        return _W3()

    for answered in aacp.ERC8183_ACCESSORS:
        assert aacp.implements_erc8183(only(answered), "0x" + "11" * 20), answered

    # And a contract answering none of them is not one.
    assert not aacp.implements_erc8183(only("somethingElse()"), "0x" + "11" * 20)


def test_the_verify_script_reads_the_shared_accessor_tuple() -> None:
    """One tuple, both readers — asserted, because it was two before.

    `scripts/verify_erc8183.py` hardcoded `"jobCounter()"` while
    `implements_erc8183` probed three *other* names, and the accessor tuple's own
    docstring cited that script as the reason it had been widened. So the module
    pointed at the script and the script had never heard of the module: the two
    halves of one question disagreed about what the question was, and neither
    could catch the other drifting.

    A source read rather than a call, because the defect is *duplication* and a
    behavioural test cannot see it — a script with its own private copy of the
    right four names passes every runtime assertion.
    """
    from pathlib import Path

    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "verify_erc8183.py"
    ).read_text()

    assert "ERC8183_ACCESSORS" in script, (
        "the script must take the accessor spellings from aacp rather than "
        "keeping its own list"
    )
    assert "answering_accessors" in script

    body = script.split('"""', 2)[-1]  # skip the module docstring, which names them as prose
    for spelling in ("jobCount()", "nextJobId()", "jobs(uint256)"):
        assert spelling not in body, (
            f"{spelling} is written out in the script body — it belongs in "
            "ERC8183_ACCESSORS, where both readers can see it"
        )


def test_the_verify_script_runs_the_termix_contrast() -> None:
    """`aacp.verify()` had no caller outside these tests.

    No script, no Makefile target, no API route, no page — the module's headline
    function, exercised only by the file asserting it exists. That is the same
    rot this script was written to prevent for the addresses it checks, and it
    had it.
    """
    from pathlib import Path

    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "verify_erc8183.py"
    ).read_text()

    assert "verify as verify_termix" in script
    assert "verify_termix(w3" in script, "imported and not called is not a caller"


def test_answering_accessors_reports_which_one_answered() -> None:
    """`True` loses the reading that mattered.

    P-18 recorded three reverting names and concluded "the accessors are named
    something else"; P-24 found the name that answers. A probe that returns only
    a boolean throws away exactly the fact that separated those two findings, so
    this one returns the spellings and `implements_erc8183` is derived from it.
    """
    from eth_utils import keccak

    from misquote.registry import aacp

    def only(*signatures: str):
        wanted = {keccak(text=s)[:4] for s in signatures}

        class _Eth:
            @staticmethod
            def call(tx):
                if tx["data"][:4] in wanted:
                    return (0).to_bytes(32, "big")
                raise ValueError("execution reverted")

        class _W3:
            eth = _Eth()

            @staticmethod
            def to_checksum_address(address):
                return address

        return _W3()

    address = "0x" + "11" * 20

    # The real chapel/mainnet kernel: one spelling answers, three revert.
    assert aacp.answering_accessors(only("jobCounter()"), address) == ("jobCounter()",)

    # TermiX's escrow: none of them.
    assert aacp.answering_accessors(only("orders(bytes32)"), address) == ()
    assert not aacp.implements_erc8183(only("orders(bytes32)"), address)

    # Order follows ERC8183_ACCESSORS, not the order they happened to answer in.
    every = aacp.answering_accessors(only(*aacp.ERC8183_ACCESSORS), address)
    assert every == aacp.ERC8183_ACCESSORS
