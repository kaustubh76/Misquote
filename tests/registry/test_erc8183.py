"""ERC-8183: the hire flow, and the evidence behind the addresses it does not carry.

Every competing submission will put a Hire button on a card. Two properties of
ours are worth testing: it states the real cost of hiring — seven transactions, not
one click — and it cannot send any of them.

`JOB_ESCROW` was empty when this module shipped, because we had verified nothing.
It then held one entry, TermiX's own escrow, checked on chain rather than copied
from their website. It was emptied, then refilled with a different contract that passed the same checks, and that round trip is the point: the
entry was justified by everything *around* the interface — real bytecode, a
settlement token we already record, an identity registry byte-identical to ours
— and its own evidence flagged the hole, that nobody had read an ERC-8183 job
back out of it. Reading one closed the hole in the unexpected direction. The
contract is an order-keyed escrow, `orders(bytes32)`, and implements none of the
seven calls this module models.

So the invariant under test is stronger than "this must be empty" and stronger
than "no address without evidence": **no address without evidence that it
implements this standard**. A real, verified, well-behaved escrow that does not
is still not one.
"""

from __future__ import annotations

import pytest

from misquote.registry.erc8183 import (
    FORMER_CANDIDATE_EVIDENCE,
    JOB_ESCROW,
    JOB_ESCROW_EVIDENCE,
    STATES,
    TERMINAL,
    NoVerifiedDeployment,
    client_transaction_count,
    escrow_address,
    render,
    steps,
    success_criterion,
    transaction_count,
)


def test_hiring_takes_seven_transactions_end_to_end() -> None:
    """Five from the client, then the provider's submit and the evaluator's settle.

    Six for as long as the sequence was read off the Draft EIP. The deployed
    AgenticCommerce kernel needs one more, and it is not a step anybody would
    guess: `registerJob` binds the dispute policy on a **separate**
    EvaluatorRouter contract. Our docs said "3-4" originally, which was a guess
    in roughly the right place — the way a wrong number survives is by looking
    careful.
    """
    assert transaction_count() == 7
    assert client_transaction_count() == 5


def test_the_count_is_derived_from_the_sequence_not_written_down() -> None:
    """If the two could disagree, the published number would eventually be the
    stale one. `len()` of the thing it describes cannot drift from it."""
    assert transaction_count() == len(steps())
    assert client_transaction_count() == sum(1 for s in steps() if s.sender == "client")


def test_an_open_call_for_bids_is_refused_rather_than_priced() -> None:
    """There is no `setProvider` on the deployed kernel.

    This used to assert that an open call cost one extra transaction. That was
    modelled from the EIP; the kernel takes the provider as an argument to
    `createJob` and exposes no setter, so the shape does not exist and pricing
    it would be fiction. Refusing is the same rule `escrow_address` follows for
    an unverified chain.
    """
    with pytest.raises(ValueError, match="no setProvider"):
        steps(provider_known_at_creation=False)
    assert "setProvider" not in [s.call for s in steps()]


def test_the_approve_is_not_part_of_the_standard() -> None:
    """ "ERC-8183 needs four transactions" and "hiring needs four transactions"
    are different claims, and only the second is true."""
    approve = [s for s in steps() if s.call == "approve"]
    assert len(approve) == 1
    assert not approve[0].is_erc8183
    assert approve[0].contract == "erc20"
    assert sum(1 for s in steps() if s.is_erc8183) == 6


def test_the_order_is_the_one_the_state_machine_requires() -> None:
    calls = [s.call for s in steps()]
    assert calls == [
        "approve",
        "createJob",
        "setBudget",
        "registerJob",
        "fund",
        "submit",
        "settle",
    ]
    # fund() pulls the budget, so the allowance has to exist first, and the
    # budget has to be set before there is an amount to pull.
    assert calls.index("approve") < calls.index("fund")
    assert calls.index("setBudget") < calls.index("fund")


#: The runs this order is answerable to. `hire-97.json` is deliberately not among
#: them: that run sent `registerJob` before `setBudget` — the order this module
#: used to publish — and its `fund` reverted `PolicyNotSet()`.
SUCCESSFUL_RUNS = ("hire-mainnet-56.json", "hire-mainnet-56-submitted.json", "hire-fork-56.json")


def test_the_published_order_is_one_that_has_actually_been_sent() -> None:
    """The correction of 7 Sep, as a check rather than a memory.

    This module published `registerJob` third and `setBudget` fourth, and no run
    had ever sent them that way. A hand-typed list above cannot notice that; it
    is the same list that was wrong. So the order is also held against the
    records of the runs that mined, which are the only authority on what the
    kernel accepts.
    """
    import json
    from pathlib import Path

    records = Path(__file__).resolve().parents[2] / "vetting/identity"
    published = [s.call for s in steps()]
    checked = 0

    for name in SUCCESSFUL_RUNS:
        path = records / name
        if not path.exists():
            continue
        sent = [
            entry.get("call")
            for entry in json.loads(path.read_text()).get("transactions", [])
        ]
        # The fork run mints itself a balance first; that is not part of a hire.
        sent = [call for call in sent if call in set(published)]
        assert sent == published, (
            f"{name} sent {sent}; steps() publishes {published}. The record is "
            f"the authority — a sequence nobody has executed is not a sequence."
        )
        checked += 1

    # A parity check that found no records to compare against would pass while
    # proving nothing, which is the failure mode this repository keeps finding.
    assert checked, f"no hire records found in {records} — nothing was compared"


def test_only_the_evaluator_settles_and_only_the_provider_delivers() -> None:
    """The authorisation that makes "who is the evaluator" a product question
    rather than a detail: whoever it is can withhold payment."""
    by_call = {s.call: s.sender for s in steps()}
    assert by_call["submit"] == "provider"
    # `complete` on the EIP; `settle` on the deployed EvaluatorRouter.
    assert by_call["settle"] == "evaluator"
    assert by_call["fund"] == "client"


def test_the_state_machine_is_the_eips() -> None:
    assert STATES == ("Open", "Funded", "Submitted", "Completed", "Rejected", "Expired")
    assert TERMINAL == ("Completed", "Rejected", "Expired")
    assert all(state in STATES for state in TERMINAL)


def test_the_success_criterion_is_the_one_already_published() -> None:
    """Inventing a second metric for the escrow would let the number an agent is
    paid on disagree with the number it is advertised on, which is the misquote
    again in a new place."""
    text = success_criterion(0.70)
    assert "70%" in text
    assert "G-3" in text
    assert "no counterfactual" in text


# --- the one that matters ---------------------------------------------------


def test_no_address_may_exist_without_recorded_evidence() -> None:
    """The invariant that replaced "this mapping must be empty".

    Empty was the right state while we had verified nothing. Now that TermiX's
    `TermixEscrow` has been checked on chain, the useful rule is stricter than
    emptiness and stronger than a boolean: **every address carries the readings
    that justify it**, including the ones that failed.
    """
    for chain_id, address in JOB_ESCROW.items():
        assert chain_id in JOB_ESCROW_EVIDENCE, (
            f"chain {chain_id} has an escrow address with no recorded evidence — "
            "a table on a vendor's website is a claim, not a verification"
        )
        assert address.startswith("0x") and len(address) == 42
        assert len(JOB_ESCROW_EVIDENCE[chain_id]) >= 3


def test_the_evidence_states_what_was_not_verified() -> None:
    """Evidence that only lists successes is marketing.

    Repointed rather than deleted. It used to assert that the *populated* entry
    disclosed its own hole — "nobody has read an ERC-8183 job back out of it".
    Somebody did, the answer was no, and the entry is gone; the caveats that
    survive belong to the rejected candidate, and they are still the part a
    reader needs.
    """
    for address, evidence_lines in FORMER_CANDIDATE_EVIDENCE.items():
        assert address.startswith("0x") and len(address) == 42
        evidence = " ".join(evidence_lines)
        assert "NOT ERC-8183" in evidence, "no statement of why this was rejected"
        # An upgradeable contract holding escrowed funds is a property a
        # marketplace routing user money through it has to disclose, and that is
        # true of a contract we declined to use as much as one we did.
        assert "upgradeable" in evidence.lower()
        assert "NO TESTNET" in evidence


def test_the_rejected_candidate_names_the_interface_it_actually_has() -> None:
    """A rejection that does not say what was found instead is an assertion.

    The useful half of this finding is not "it is not ERC-8183" — it is that the
    escrow is order-keyed by bytes32, which explains every revert we saw and
    predicts the next one.
    """
    evidence = " ".join(next(iter(FORMER_CANDIDATE_EVIDENCE.values())))
    assert "orders(bytes32)" in evidence
    assert "5,894" in evidence, "the size of the search belongs in the claim"
    for call in ("createJob", "setBudget", "fund", "submit", "complete", "reject"):
        assert call in evidence, f"{call} not named among what was searched for"


def test_a_chain_with_no_verified_deployment_still_raises() -> None:
    """A chain nobody has checked must fail, not fall back.

    Chapel used to be in this test on the grounds that there was no TermiX
    testnet. There is a verified ERC-8183 deployment on chapel now — a different
    contract, checked directly — so the example moved to a chain that genuinely
    has none. The property under test never changed: absence raises.
    """
    with pytest.raises(NoVerifiedDeployment, match="no verified"):
        escrow_address(1)
    with pytest.raises(NoVerifiedDeployment):
        escrow_address(137)


def test_both_bsc_networks_resolve_to_the_verified_kernel() -> None:
    """The refusal lifted, and only because something was actually checked.

    This test has now been all three states, which is the module working rather
    than the module churning. It returned an address while we believed TermiX's
    escrow implemented the standard; it raised once that was disproved (P-18);
    and it returns an address again now that `scripts/verify_erc8183.py` has
    read a *different* contract three ways on both chains — bytecode present,
    `jobCounter()` and `paymentToken()` answering, and the kernel's own payment
    token agreeing with the published table.

    Every entry carries its readings, which is the condition the module set.
    """
    from misquote.registry.erc8183 import JOB_ESCROW, JOB_ESCROW_EVIDENCE

    for chain in (56, 97):
        address = escrow_address(chain)
        assert address == JOB_ESCROW[chain]
        assert address.startswith("0x") and len(address) == 42
        assert JOB_ESCROW_EVIDENCE.get(chain), (
            f"chain {chain} has an escrow address and no evidence — the rule is "
            f"no entry without evidence, and a test enforces it"
        )


def test_nothing_here_can_send_a_transaction() -> None:
    """The module builds and prices a sequence; it cannot spend.

    Checks **imports and calls**, via the AST, rather than scanning the source
    text. The substring version of this test failed the moment the docstring
    explained that there is no signer — a guard that cannot tell `import web3`
    from the words "no web3" is a guard that punishes documentation.
    """
    import ast
    import inspect

    from misquote.registry import erc8183

    tree = ast.parse(inspect.getsource(erc8183))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            imported.add((node.module or "").split(".")[0])

    for forbidden in ("web3", "eth_account", "eth_utils", "httpx", "requests"):
        assert forbidden not in imported, f"{forbidden!r} imported — this must stay unsigned"

    # And nothing that *looks* like broadcasting, however it got a handle.
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("send_raw_transaction", "send_transaction", "sign_transaction", "transact"):
        assert forbidden not in called, f"{forbidden!r} called — this must stay unsigned"


def test_render_states_the_count_and_the_missing_deployment() -> None:
    text = render()
    assert "7 transactions" in text
    assert "5 from the client" in text
    assert "unsigned" in text
    # Whichever state the escrow mapping is in, the page says which.
    assert ("Escrow verified on chain" in text) == bool(JOB_ESCROW)
    # Every step appears, so the rendered flow cannot silently omit one.
    for step in steps():
        assert step.call in text
