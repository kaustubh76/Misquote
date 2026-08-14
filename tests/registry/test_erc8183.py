"""ERC-8183: the hire flow, and the evidence behind the one address it carries.

Every competing submission will put a Hire button on a card. Two properties of
ours are worth testing: it states the real cost of hiring — six transactions, not
one click — and it cannot send any of them.

`JOB_ESCROW` was empty when this module shipped, because we had verified nothing.
It has one entry now, TermiX's own escrow, checked on chain rather than copied
from their website. So the invariant under test is no longer "this must be
empty" but the stronger **no address without recorded evidence, including the
part that failed** — which is a rule that survives the mapping growing.
"""

from __future__ import annotations

import pytest

from misquote.registry.erc8183 import (
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


def test_hiring_takes_six_transactions_end_to_end() -> None:
    """Four from the client, then the provider's submit and the evaluator's
    complete. Our docs said "3-4" for weeks, which was a guess in roughly the
    right place — the way a wrong number survives is by looking careful."""
    assert transaction_count() == 6
    assert client_transaction_count() == 4


def test_the_count_is_derived_from_the_sequence_not_written_down() -> None:
    """If the two could disagree, the published number would eventually be the
    stale one. `len()` of the thing it describes cannot drift from it."""
    assert transaction_count() == len(steps())
    assert client_transaction_count() == sum(1 for s in steps() if s.sender == "client")


def test_an_open_call_for_bids_costs_one_more() -> None:
    """`setProvider` is needed only when `createJob` passed address(0)."""
    assert transaction_count(provider_known_at_creation=False) == 7
    calls = [s.call for s in steps(provider_known_at_creation=False)]
    assert "setProvider" in calls
    assert calls.index("setProvider") < calls.index("setBudget"), "provider before price"
    assert "setProvider" not in [s.call for s in steps()]


def test_the_approve_is_not_part_of_the_standard() -> None:
    """"ERC-8183 needs four transactions" and "hiring needs four transactions"
    are different claims, and only the second is true."""
    approve = [s for s in steps() if s.call == "approve"]
    assert len(approve) == 1
    assert not approve[0].is_erc8183
    assert approve[0].contract == "erc20"
    assert sum(1 for s in steps() if s.is_erc8183) == 5


def test_the_order_is_the_one_the_state_machine_requires() -> None:
    calls = [s.call for s in steps()]
    assert calls == ["approve", "createJob", "setBudget", "fund", "submit", "complete"]
    # fund() pulls the budget, so the allowance has to exist first, and the
    # budget has to be set before there is an amount to pull.
    assert calls.index("approve") < calls.index("fund")
    assert calls.index("setBudget") < calls.index("fund")


def test_only_the_evaluator_settles_and_only_the_provider_delivers() -> None:
    """The authorisation that makes "who is the evaluator" a product question
    rather than a detail: whoever it is can withhold payment."""
    by_call = {s.call: s.sender for s in steps()}
    assert by_call["submit"] == "provider"
    assert by_call["complete"] == "evaluator"
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

    The gap between "a live escrow settling in the token we use" and "we have
    exercised ERC-8183's job interface here" is exactly the slippage this project
    exists to catch, so it must be written down at the address that has it.
    """
    for chain_id in JOB_ESCROW:
        evidence = " ".join(JOB_ESCROW_EVIDENCE[chain_id])
        assert "NOT VERIFIED" in evidence, "no statement of what remains unproven"
        assert "job interface" in evidence
        # An upgradeable contract holding escrowed funds is a property a
        # marketplace routing user money through it has to disclose.
        assert "upgradeable" in evidence.lower()


def test_a_chain_with_no_verified_deployment_still_raises() -> None:
    """There is no TermiX testnet. Asking for one must fail, not fall back."""
    with pytest.raises(NoVerifiedDeployment, match="no verified"):
        escrow_address(97)
    with pytest.raises(NoVerifiedDeployment):
        escrow_address(1)


def test_the_verified_chain_returns_its_address() -> None:
    assert escrow_address(56) == JOB_ESCROW[56]


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
    assert "6 transactions" in text
    assert "4 from the client" in text
    assert "unsigned" in text
    # Whichever state the escrow mapping is in, the page says which.
    assert ("Escrow verified on chain" in text) == bool(JOB_ESCROW)
    # Every step appears, so the rendered flow cannot silently omit one.
    for step in steps():
        assert step.call in text
