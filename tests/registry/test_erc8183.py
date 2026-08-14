"""ERC-8183: the hire flow, and the address we deliberately do not have.

The load-bearing test in this file is the last one. Every competing submission
will put a Hire button on a card; the interesting property of ours is that it
cannot send a mainnet transaction, because no mainnet deployment exists to send
one to and we caught ourselves believing otherwise.
"""

from __future__ import annotations

import pytest

from misquote.registry.erc8183 import (
    JOB_ESCROW,
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


def test_there_is_no_deployment_address_and_asking_for_one_raises() -> None:
    """We wrote "live on both BSC networks" in our own verified-facts table.

    It is not. The EIP is Draft with no reference deployments, and BNB Chain's
    SDK is live on testnet only with "mainnet coming soon". So there is no
    address here, and code that needs one fails loudly rather than reaching for
    a plausible-looking constant.
    """
    assert JOB_ESCROW == {}, (
        "an ERC-8183 address appeared — it must be verified on chain first, with "
        "its evidence recorded, the way the ERC-8004 registries were"
    )
    for chain_id in (56, 97):
        with pytest.raises(NoVerifiedDeployment, match="no verified"):
            escrow_address(chain_id)


def test_nothing_here_can_send_a_transaction() -> None:
    """The module builds and prices a sequence. It has no signer, no web3, and no
    import that could acquire one — so a hire button wired to this cannot spend."""
    import inspect

    from misquote.registry import erc8183

    source = inspect.getsource(erc8183)
    for forbidden in ("web3", "eth_account", "send_raw", "signer", "private_key"):
        assert forbidden not in source.lower(), f"{forbidden!r} — this must stay unsigned"


def test_render_states_the_count_and_the_missing_deployment() -> None:
    text = render()
    assert "6 transactions" in text
    assert "4 from the client" in text
    assert "testnet-only" in text
    assert "unsigned" in text
    # Every step appears, so the rendered flow cannot silently omit one.
    for step in steps():
        assert step.call in text
