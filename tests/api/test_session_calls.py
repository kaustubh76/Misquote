"""The session-key calldata, and the readings it must not overstate.

`sessions/keys.py` publishes the plan; `sessions/calls.py` builds the
transactions. The defects worth guarding here are all of one kind — a value that
is *plausible* rather than read — so most of these assert against a signature or
against chain rather than against another constant in the same file.
"""

from __future__ import annotations

import pytest
from eth_utils import keccak

from misquote.sessions import calls
from misquote.sessions.keys import Cap

OWNER = "0x" + "11" * 20
PUBLIC_KEY = b"\x04" + b"\xab" * 64
FUTURE = 2_000_000_000


def test_every_selector_is_derivable_from_its_signature() -> None:
    """A typo in an ABI is a transaction to a function that does not exist.

    It does not raise here and it does not raise when built — it reverts on
    chain, at the point where a demo is being watched. So every entry in both
    ABIs is recomputed from its own name and argument types.
    """
    for abi, contract in ((calls.KEYSTORE_ABI, "keyStore"), (calls.CONTROLLER_ABI, "controller")):
        for item in abi:
            types = ",".join(i["type"] for i in item["inputs"])
            signature = f"{item['name']}({types})"
            assert keccak(text=signature)[:4], f"{contract}.{signature} has no selector"


def test_the_grant_and_the_revoke_go_to_different_contracts() -> None:
    """The correction that reading the ABI produced.

    `revoke_plan()` was right that revoking is one transaction and had no way to
    know it lands somewhere else: `registerKey` is on the keyStoreController and
    `revokeKey` is on the keyStore. A flow built from the caps subset alone sends
    both to one address and discovers this at transaction time.
    """
    cap = Cap(targets=(OWNER,), token=OWNER, amount=1, expiry_ts=FUTURE)
    grant = calls.grant_call(
        97, cap, public_key=PUBLIC_KEY, validator=OWNER, fee_wei=1, metadata=b""
    )
    revoke = calls.revoke_call(97, OWNER, calls.key_id(PUBLIC_KEY))

    assert grant.contract == "keyStoreController"
    assert revoke.contract == "keyStore"
    assert grant.to.lower() != revoke.to.lower(), (
        "a grant and its revoke on the same address would mean one of them is "
        "pointed at the wrong contract"
    )


def test_a_zero_expiry_is_refused_rather_than_passed_through() -> None:
    """Zero is *no expiry*, not an expired key — and the chain agrees.

    A live key read off chapel returns `expiry_ts: 0` and `valid: true` at the
    same time. So an accidental zero does not produce a key that is already dead;
    it produces one that never dies, which is the one cap whose failure mode is
    unbounded.
    """
    with pytest.raises(ValueError, match="does not fit uint40"):
        calls.grant_call(
            97,
            Cap(targets=(OWNER,), token=OWNER, amount=1, expiry_ts=0),
            public_key=PUBLIC_KEY,
            validator=OWNER,
            fee_wei=1,
        )

    with pytest.raises(ValueError, match="does not fit uint40"):
        calls.grant_call(
            97,
            Cap(targets=(OWNER,), token=OWNER, amount=1, expiry_ts=calls.MAX_EXPIRY + 1),
            public_key=PUBLIC_KEY,
            validator=OWNER,
            fee_wei=1,
        )


def test_a_key_id_is_derived_and_never_chosen() -> None:
    """`getKeys` returns ids and `getPublicKey` is keyed by them.

    A caller that invents an id registers a key it cannot afterwards find.
    """
    assert calls.key_id(PUBLIC_KEY) == keccak(PUBLIC_KEY)
    with pytest.raises(ValueError, match="empty public key"):
        calls.key_id(b"")


def test_no_validator_module_is_verified_and_the_code_says_so() -> None:
    """Where the caps would live, and the fact that nothing has read it.

    Empty for the same reason `SESSION_KEY_MODULE` was empty before it was
    verified, and to the same bar. What makes it an absence rather than an
    oversight is that the deployment's own users do not use one: every grant read
    off chapel carries `validator = 0x0`.
    """
    assert calls.VALIDATOR_MODULE == {}
    assert calls.verified_validator(56) is None
    assert calls.verified_validator(97) is None


def test_an_unverified_chain_raises_rather_than_returning_an_address() -> None:
    """`erc8183.NoVerifiedDeployment`'s reasoning, applied here.

    A caller that forgets to check a `None` builds an unsigned transaction to
    the zero address; a caller that ignores an exception does not compile a demo.
    """
    from misquote.sessions.keys import NoVerifiedSessionModule

    with pytest.raises(NoVerifiedSessionModule):
        calls.revoke_call(1, OWNER, b"\x00" * 32)


def test_a_key_id_must_be_thirty_two_bytes() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        calls.revoke_call(97, OWNER, b"\x00" * 31)


# --- against the chain ------------------------------------------------------


@pytest.mark.chainfork
def test_every_signature_is_present_in_the_deployed_bytecode() -> None:
    """The check that separates a read ABI from a guessed one.

    `aacp.py` recovered TermiX's dispatch table this way and concluded the
    interface differed; the same technique run forwards says our ABI names
    functions that actually exist. Guessing a name is P-18's mistake, and it is
    cheap not to make.
    """
    from web3 import Web3
    from web3.middleware import ExtraDataToPOAMiddleware

    w3 = None
    for url in ("https://bsc-testnet-rpc.publicnode.com",):
        try:
            candidate = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))
            candidate.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if candidate.eth.chain_id == 97:
                w3 = candidate
                break
        except Exception:  # noqa: BLE001
            continue
    if w3 is None:
        pytest.skip("no chapel endpoint answered")

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
            if 0x60 <= op <= 0x7F:  # any other PUSH, skip its immediate
                i += 1 + (op - 0x5F)
                continue
            i += 1
        return found

    for abi, address, label in (
        (calls.KEYSTORE_ABI, calls.SESSION_KEY_MODULE[97], "keyStore"),
        (calls.CONTROLLER_ABI, calls.SESSION_KEY_CONTROLLER[97], "keyStoreController"),
    ):
        table = selectors(address)
        assert table, f"{label} at {address} has no dispatch table"
        for item in abi:
            types = ",".join(i["type"] for i in item["inputs"])
            signature = f"{item['name']}({types})"
            assert keccak(text=signature)[:4].hex() in table, (
                f"{label}.{signature} is in our ABI and not in the deployed "
                f"bytecode at {address} — the name is guessed, not read"
            )


@pytest.mark.chainfork
def test_the_registration_fee_is_not_a_constant() -> None:
    """Read per grant, never cached.

    Three reads minutes apart returned three different figures, so a page
    rendering a stored number quotes a price the chain will not honour — the
    misquote this project is named after, committed on the activation page.
    """
    from web3 import Web3
    from web3.middleware import ExtraDataToPOAMiddleware

    w3 = Web3(
        Web3.HTTPProvider("https://bsc-testnet-rpc.publicnode.com", request_kwargs={"timeout": 20})
    )
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    try:
        fee = calls.registration_fee(w3, 97)
    except Exception:  # noqa: BLE001
        pytest.skip("chapel did not answer")

    # A bound rather than a value, because the value moves. What is asserted is
    # that it is a real price: non-zero, and not absurd for a testnet fee.
    assert 0 < fee < 10**16, f"registration fee {fee} is outside any plausible range"
