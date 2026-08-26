"""The declared operator, and the two places it is allowed to matter.

The interesting assertions here are the negative ones. A guard that refuses a
mismatched key is easy to write and easy to write wrongly — the failure modes
are "refuses when nothing was declared", which breaks every fork run, and
"accepts when the declaration was garbage", which is worse than having no guard
at all because the gate reports amber and everyone reads amber as "not set up
yet" rather than "misconfigured".
"""

from __future__ import annotations

import os

import pytest

from misquote.chain.operator import (
    ENV_VAR,
    OPERATOR_KEY_ENV,
    SIGNER_ENV,
    OperatorMismatch,
    assert_signs_as_declared,
    assert_signs_for_operator,
    declared_operator,
    declared_signer,
    declared_wallets,
    operator_key,
    role_for,
    signing_declaration,
    signs_as_delegate,
)

# anvil's first account, and a second address that is not it. Both literals,
# because deriving them from a key here would test `eth_account` rather than
# this module.
ANVIL_0 = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
SOMEONE_ELSE = "0x0c501EE1924bfb91a028DB4BcD68f4861B0Ff6eE"

# A well-formed key that has never held anything, and the address it derives.
GATE_KEY = "0x" + "11" * 32
GATE_ADDRESS = "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A"


def test_nothing_declared_reads_as_nothing_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert declared_operator() is None


def test_blank_is_the_same_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """A variable exported empty is the ordinary shape of a `.env` line nobody
    filled in, and must not be a third state."""
    monkeypatch.setenv(ENV_VAR, "   ")
    assert declared_operator() is None


def test_lowercase_is_accepted_and_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every explorer copy button and every `.env` in the wild is lowercase."""
    monkeypatch.setenv(ENV_VAR, SOMEONE_ELSE.lower())
    assert declared_operator() == SOMEONE_ELSE


@pytest.mark.parametrize(
    "bad",
    [
        "not-an-address",
        "0x0c501EE1924bfb91a028DB4BcD68f4861B0Ff6e",  # one nibble short
        "0x0c501ee1924bfb91a028db4bcd68f4861b0ff6ee1",  # one too many
        # Mixed case claims a checksum; one character moved from the real one.
        "0x0c501EE1924bfb91a028DB4BcD68f4861B0Ff6Ee",
    ],
)
def test_a_malformed_declaration_raises_rather_than_reading_as_absent(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    """The one that matters.

    `None` is the permissive branch. If a typo collapsed into it, the single
    action a careful operator takes to tighten this check would be the action
    that silently disables it.
    """
    monkeypatch.setenv(ENV_VAR, bad)
    with pytest.raises(ValueError, match=r"not an address|checksum does not verify"):
        declared_operator()


def test_uniform_case_carries_no_checksum_and_is_not_judged_on_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All-upper is what some explorers and a shouted `.env` produce. It makes no
    checksum claim, so rejecting it would be rejecting a correct address."""
    monkeypatch.setenv(ENV_VAR, "0x" + SOMEONE_ELSE[2:].upper())
    assert declared_operator() == SOMEONE_ELSE


def test_a_correct_checksum_is_accepted_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, SOMEONE_ELSE)
    assert declared_operator() == SOMEONE_ELSE


def test_no_declaration_permits_any_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fork suite signs as anvil and must keep working."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert assert_signs_for_operator(ANVIL_0) is None


def test_a_matching_key_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, ANVIL_0)
    assert assert_signs_for_operator(ANVIL_0) == "operator"


def test_case_is_not_what_decides_a_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """`eth_account` returns checksummed; a `.env` usually is not. Comparing the
    two as strings would refuse a correctly configured deployment."""
    monkeypatch.setenv(ENV_VAR, ANVIL_0.lower())
    assert assert_signs_for_operator(ANVIL_0.upper().replace("0X", "0x")) == "operator"


def test_a_mismatched_key_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, SOMEONE_ELSE)
    with pytest.raises(OperatorMismatch) as caught:
        assert_signs_for_operator(ANVIL_0)
    # Both addresses in the message. A refusal that names only one of them
    # leaves the reader to guess which half is wrong.
    assert ANVIL_0 in str(caught.value)
    assert SOMEONE_ELSE in str(caught.value)


def test_the_variables_this_module_names_are_the_variables_it_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both readers spell their name out as a literal so the template guard in
    `tests/test_env_template.py` can see it, which means the constants and the
    strings they read can drift. This is what holds them together."""
    monkeypatch.setenv(ENV_VAR, SOMEONE_ELSE)
    monkeypatch.setenv(SIGNER_ENV, ANVIL_0)
    assert declared_operator() == SOMEONE_ELSE
    assert declared_signer() == ANVIL_0


# --- the split: who the project is, vs which wallet is spending -------------
#
# One variable conflated two questions. Registering the four agents on chapel
# needs a funded burn-in wallet to sign while the identities land on a
# submission address whose key is deliberately not on this machine — which the
# single-variable version made impossible without either putting that key on
# disk or turning the guard off.


def test_the_signer_declaration_is_what_the_key_is_checked_against(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_VAR, SOMEONE_ELSE)
    monkeypatch.setenv(SIGNER_ENV, ANVIL_0)
    assert assert_signs_as_declared(ANVIL_0) == "signer"


def test_the_operator_key_is_accepted_even_when_a_delegate_is_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule this test used to assert was the opposite, and it was wrong.

    It said the narrower claim wins: declaring a signer means "the key here is
    that one", so an operator key is not what was declared. True while only one
    key could be on a machine. False the moment an operator key joined it —
    `setAgentURI` is owner-only, so correcting a card the operator owns must be
    signed by the operator, and the old rule refused the one wallet with the
    authority to do it.

    Both are declared. Both are answers to "who may spend here". What did not
    change is the test below: a key deriving neither is still refused.
    """
    monkeypatch.setenv(ENV_VAR, SOMEONE_ELSE)
    monkeypatch.setenv(SIGNER_ENV, ANVIL_0)
    assert assert_signs_as_declared(SOMEONE_ELSE) == "operator"
    assert assert_signs_as_declared(ANVIL_0) == "signer"


def test_the_role_is_returned_so_a_caller_need_not_re_derive_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`go_no_go` colours its gate on which wallet signed. Returning the role
    means it reads the answer rather than comparing addresses a second time."""
    monkeypatch.setenv(ENV_VAR, SOMEONE_ELSE)
    monkeypatch.delenv(SIGNER_ENV, raising=False)
    assert role_for(SOMEONE_ELSE) == "operator"
    assert role_for(ANVIL_0) is None


def test_nothing_declared_returns_no_role_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.delenv(SIGNER_ENV, raising=False)
    assert assert_signs_as_declared(ANVIL_0) is None
    assert declared_wallets() == {}


def test_no_signer_declared_falls_back_to_the_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single-wallet case, which is what every test above this line
    describes. The split must not change it."""
    monkeypatch.setenv(ENV_VAR, SOMEONE_ELSE)
    monkeypatch.delenv(SIGNER_ENV, raising=False)
    assert signing_declaration() == (SOMEONE_ELSE, ENV_VAR)
    with pytest.raises(OperatorMismatch):
        assert_signs_as_declared(ANVIL_0)


def test_matching_neither_declaration_is_still_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property the split must not cost. A second variable is an escape
    hatch for *naming* another wallet, never for naming none."""
    monkeypatch.setenv(ENV_VAR, SOMEONE_ELSE)
    monkeypatch.setenv(SIGNER_ENV, "0x" + "33" * 20)
    with pytest.raises(OperatorMismatch, match="neither wallet") as caught:
        assert_signs_as_declared(ANVIL_0)
    # It names both, because "which one did you mean" is the next question.
    assert SOMEONE_ELSE in str(caught.value)
    assert "0x" + "33" * 20 in str(caught.value).lower()


def test_a_malformed_signer_declaration_raises_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both declarations parse through one function, so neither can be the lax
    one. Asserted rather than assumed — they were separate code once."""
    monkeypatch.setenv(SIGNER_ENV, "0xnope")
    with pytest.raises(ValueError, match=SIGNER_ENV):
        declared_signer()


def test_delegate_is_both_declared_and_different(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, SOMEONE_ELSE)
    monkeypatch.setenv(SIGNER_ENV, ANVIL_0)
    assert signs_as_delegate() is True


@pytest.mark.parametrize(
    ("operator", "signer"),
    [
        (SOMEONE_ELSE, SOMEONE_ELSE),  # the same wallet named twice is not a delegate
        (SOMEONE_ELSE, None),  # nor is the ordinary single-wallet case
        (None, ANVIL_0),  # nor a signer with nobody to be a delegate *of*
        (None, None),
    ],
)
def test_delegate_is_false_for_everything_else(
    monkeypatch: pytest.MonkeyPatch, operator: str | None, signer: str | None
) -> None:
    for var, value in ((ENV_VAR, operator), (SIGNER_ENV, signer)):
        if value is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, value)
    assert signs_as_delegate() is False


def test_the_old_name_still_points_at_the_guard() -> None:
    """`chain/signer.py` and the tests written before the split call it by the
    old name. An alias, not a copy — two functions would drift."""
    assert assert_signs_for_operator is assert_signs_as_declared


def test_the_suite_does_not_inherit_a_configured_env() -> None:
    """The rail in `tests/conftest.py`, asserted where it matters most.

    Every test in this file reasons about what is declared. Run in a shell with
    `.env` exported — which is how `make identity-register` and every other
    chain target are meant to be run — the ones that cleared only the operator
    still saw a signer, and the suite passed on a clean machine and failed on a
    configured one.
    """
    assert os.environ.get(ENV_VAR) is None
    assert os.environ.get(SIGNER_ENV) is None


# --- the operator's own key ------------------------------------------------


def test_no_operator_key_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every path that does not need an operator signature must be unaffected
    by not having one."""
    monkeypatch.delenv(OPERATOR_KEY_ENV, raising=False)
    assert operator_key() is None


def test_an_operator_key_matching_the_declaration_is_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, GATE_KEY)
    monkeypatch.setenv(ENV_VAR, GATE_ADDRESS)
    assert operator_key() == GATE_KEY


def test_an_operator_key_for_a_different_address_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure this function exists for.

    A mistyped key is not a key that fails — it is a key that succeeds *as
    somebody else*. Two variables are the only things that can catch it, and
    catching it here names the cause; catching it later, at the broadcast guard,
    reports only that some unknown wallet turned up.
    """
    monkeypatch.setenv(OPERATOR_KEY_ENV, GATE_KEY)
    monkeypatch.setenv(ENV_VAR, SOMEONE_ELSE)
    with pytest.raises(ValueError, match="derives"):
        operator_key()


def test_an_unparseable_operator_key_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, "not-a-key")
    monkeypatch.setenv(ENV_VAR, SOMEONE_ELSE)
    with pytest.raises(ValueError, match="not a private key"):
        operator_key()


def test_an_operator_key_with_nothing_declared_is_taken_at_its_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing to compare against is not the same as a mismatch. Unset stays the
    permissive branch here as everywhere else in this module."""
    monkeypatch.setenv(OPERATOR_KEY_ENV, GATE_KEY)
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert operator_key() == GATE_KEY
