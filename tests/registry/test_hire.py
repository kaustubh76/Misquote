"""Escrowing a job, and the readings that stop it claiming more than it did.

Most of what can go wrong here is a *plausible* answer rather than a wrong one:
a job that does not exist answering with well-formed words, a sequence that
looks complete because the step that moves money was skipped quietly. So these
assert against the shape of a refusal as much as against a value.
"""

from __future__ import annotations

import re

import pytest

from misquote.registry import hire
from misquote.registry.erc8183 import NoVerifiedDeployment


def test_an_unverified_chain_raises_rather_than_reading_zero() -> None:
    """`erc8183.NoVerifiedDeployment`, applied to the read path too.

    A `read_job` that returned an empty `Job` for a chain with no deployment
    would be indistinguishable from a job that does not exist on a chain that
    has one.
    """
    with pytest.raises(NoVerifiedDeployment):
        hire.read_job(object(), 1, 1)
    with pytest.raises(NoVerifiedDeployment):
        hire.job_count(object(), 1)


def test_existence_is_the_id_coming_back_not_a_non_empty_answer() -> None:
    """The defect this constant exists for, asserted rather than commented.

    `getJob` on an id that has never existed returns thirteen words of which two
    are non-zero — `0x20` and `0x160`, the ABI head offsets every dynamic-struct
    return carries. So `any(word)` answers **true for every unknown id**, which is
    P-18's trap wearing a different costume: a confident, well-formed, entirely
    fictional job.
    """
    assert hire.UNKNOWN_JOB_ANSWERS_WITH_ABI_OFFSETS is True
    assert hire.JOB_WORD_ID == 1

    class _Eth:
        def __init__(self, words: list[int]) -> None:
            self.words = words

        def call(self, _tx):
            return b"".join(w.to_bytes(32, "big") for w in self.words)

    class _W3:
        def __init__(self, words: list[int]) -> None:
            self.eth = _Eth(words)

    # An unknown job: offsets present, id word zero.
    unknown = hire.read_job(_W3([0x20, 0, 0, 0, 0, 0x160, 0, 0, 0, 0, 0, 0, 0]), 97, 999)
    assert not unknown.exists, (
        "two non-zero ABI offsets are not a job; this is the exact check that was "
        "wrong the first time"
    )

    # A real one: the id we asked for comes back in word 1.
    real = hire.read_job(_W3([0x20, 743, 0, 0, 0, 0x160, 0, 0, 0, 0, 0, 0, 0]), 97, 743)
    assert real.exists
    assert real.word_count == 13


def test_job_zero_is_never_reported_as_existing() -> None:
    """Word 1 reads zero for an unknown id, so id 0 would compare equal to it.

    A job numbered zero and a job that is not there would be the same answer.
    """

    class _W3:
        class eth:  # noqa: N801
            @staticmethod
            def call(_tx):
                return b"".join(w.to_bytes(32, "big") for w in [0x20, 0, 0, 0x160])

    assert not hire.read_job(_W3(), 97, 0).exists


def test_the_create_job_errors_are_recorded_with_their_unresolved_ones() -> None:
    """Counted, not guessed — `aacp.py`'s rule, applied to error selectors.

    Most of these now carry a name, and the two that changed are why this test
    is worth keeping. `0x32d53d69` was recorded as *"fund() from a wallet
    holding none of the payment token"*, inferred from a run whose balance
    happened to be zero; it is `PolicyNotSet()`. `0xc94463e3` was recorded as
    *"consistent with the hook having registered the job already"*; it is
    `PolicyNotWhitelisted()`, which is the opposite claim.

    Both readings were plausible, both were quoted, and both were wrong. What
    replaced them is a resolved preimage plus a fork that drives the flow to
    settlement — a name and a check, rather than a name.
    """
    every = {**hire.CREATE_JOB_ERRORS, **hire.FLOW_ERRORS}
    for selector, meaning in every.items():
        # Prefix-and-length accepted "0xGGGGGGGG". These are looked up by
        # `lib/escrow.ts::selectorFrom`, which lowercases what it scrapes out of
        # a revert message, so a mixed-case or non-hex key here is a meaning
        # that silently never renders.
        assert re.fullmatch(r"0x[0-9a-f]{8}", selector), selector
        assert meaning.strip(), selector

    named = [m for m in every.values() if "()" in m and "unresolved" not in m]
    unresolved = [m for m in every.values() if "unresolved" in m]
    assert len(named) + len(unresolved) == len(every), (
        "every selector is either named or explicitly unresolved; there is no "
        "third state in which one is described without saying which"
    )
    assert len(named) >= 7, "the resolved ones stay resolved"

    # The specific corrections, pinned so a regression cannot quietly restore a
    # reading the fork proof disproved.
    assert "PolicyNotSet()" in hire.FLOW_ERRORS["0x32d53d69"]
    assert "holding none of the payment token" not in hire.FLOW_ERRORS["0x32d53d69"]
    assert "PolicyNotWhitelisted()" in hire.FLOW_ERRORS["0xc94463e3"]
    assert hire.EVALUATOR_MUST_BE_THE_ROUTER is True


def test_the_hook_defaults_to_the_router_and_never_to_zero() -> None:
    """The EIP calls the hook an optional extension. This deployment does not.

    `address(0)` — the natural way to say *no hook* — reverts `HookRequired()`,
    and so does every other contract tried. A client built from the standard
    fails on transaction two of seven with a bare four-byte selector.
    """
    assert hire.REQUIRED_HOOK_IS_THE_ROUTER is True


def test_drift_returns_a_list_so_inapplicable_is_not_a_pass() -> None:
    """`aacp.mismatches` had no caller; this is the signing path it was for.

    Chapel has no TermiX config to drift from, so the honest answer there is an
    empty list of mismatches — and a bool would have collapsed "nothing moved"
    and "there was nothing to check" into one `True`.
    """
    assert hire.drift(97) == []


# --- against the chain ------------------------------------------------------


@pytest.mark.chainfork
def test_a_real_job_reads_back_and_an_unknown_one_does_not() -> None:
    """Both halves, because only the pair is evidence.

    A read that returns something for a real id proves the selector; a read that
    returns nothing for an unknown one proves the existence test. Either alone
    would pass with the broken check this test was written after.
    """
    from web3 import Web3
    from web3.middleware import ExtraDataToPOAMiddleware

    try:
        w3 = Web3(
            Web3.HTTPProvider(
                "https://bsc-testnet-rpc.publicnode.com", request_kwargs={"timeout": 20}
            )
        )
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        if w3.eth.chain_id != 97:
            pytest.skip("endpoint is not chapel")
        count = hire.job_count(w3, 97)
    except Exception:  # noqa: BLE001
        pytest.skip("no chapel endpoint answered")

    assert count > 0, "a kernel with no jobs would make this test vacuous"

    latest = hire.read_job(w3, 97, count)
    assert latest.exists, f"job {count} should exist when jobCounter reads {count}"
    assert int(latest.words[hire.JOB_WORD_ID], 16) == count

    absent = hire.read_job(w3, 97, 10**9)
    assert not absent.exists, (
        "an id that has never existed answers with ABI offsets rather than "
        "reverting — the trap this existence check is for"
    )
