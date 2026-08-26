"""Which wallet this deployment says it is, and which wallet it says may spend.

    export MISQUOTE_OPERATOR_ADDRESS=0x…   # who the project is
    export MISQUOTE_SIGNER_ADDRESS=0x…     # which wallet the key belongs to

Every other address in this repository is *read* — a pool from the factory, an
escrow from a three-way check, a wallet from whatever a reader pasted into
`/quote`. These two are *declared*: they are the operator saying, before
anything is signed, who is spending and on whose behalf. Nothing about that is
knowable from chain, which is exactly why it has to be written down somewhere a
program can compare against.

## What they are for

`go_no_go.py::check_signer_configured` ended, for the whole life of this
repository, on the sentence "a key is set; verify by hand that it is not a main
wallet". A gate whose final instruction is *by hand* is the gate that does not
run, and it sat directly in front of the only code path that can move money.

A declared address turns that into arithmetic. `MISQUOTE_PRIVATE_KEY` derives an
address; the declaration names one; they match or they do not.

## Why two variables and not one

The first version had only `MISQUOTE_OPERATOR_ADDRESS`, and it conflated two
questions that have different answers the moment anything real happens:

- *Who is this project?* — the identity it publishes, receives ERC-8004
  identities at, and would be judged as. A submission address. Its key is
  usually **not** on the machine doing the work, and that is a feature.
- *Which wallet is about to spend?* — a hot wallet holding faucet funds, whose
  key is right here because it has to be.

Registering the four agents on chapel needs exactly this shape: a funded burn-in
wallet signs, and the identities are transferred to an address whose key nobody
has typed into this checkout. Collapsing the two would have forced a choice
between putting the submission key on disk and not doing the work.

So `MISQUOTE_SIGNER_ADDRESS` is what the key is checked against. Unset, it falls
back to the operator — which is the single-wallet case, and the behaviour every
test written against the first version still describes.

**The escape hatch is a second declaration, never an absent one.** A key that
matches neither is refused exactly as before. What the split buys is the ability
to *say* "this wallet signs on the operator's behalf" and have that be a
different, weaker, visible claim — `check_signer_configured` reports it amber
rather than green, because a delegate arrangement is not the operator signing
for itself.

## Why a mistyped value raises rather than reads as absent

`declared_operator()` returns `None` when nothing is declared, and `None` is the
permissive branch — no declaration, no comparison, the gate stays amber and says
so. So a value that fails to parse must never collapse into it. Someone who sets
the variable and fat-fingers a character has *declared* an address; answering
"none declared" would take the one action that was supposed to tighten the gate
and use it to silently disable the gate.

## What "not an address" means here

Length and hex-ness, and then EIP-55 — but only when the input carries a
checksum to check. `to_checksum_address` on its own is not enough: it
*normalises* mixed case rather than validating it, so a checksummed address with
one character mistyped comes back happily re-cased and the one error-detecting
property EIP-55 exists to provide is thrown away silently.

So the rule is conditional on the input. An address whose letters are uniformly
cased — all lower, all upper — carries no checksum information at all, and that
is what every explorer's copy button and every `.env` in the wild produces; it is
accepted and normalised. An address with mixed case is *claiming* a checksum,
and a claim that does not verify is a typo, not a preference.

## Why this is not in `addresses.py`

`chain/addresses.py` holds contracts, and its whole claim is that "nothing here
was taken on trust from documentation" — every entry re-checked three ways by
`scripts/verify_addresses.py`. Neither of these can pass that check and neither
should be filed beside things that did: they are EOAs, they have no bytecode to
find and no interface to answer, and a fresh one has no history at all. They are
statements of intent, kept separate from the statements of fact.
"""

from __future__ import annotations

import os

from eth_utils import to_checksum_address

#: The identity this deployment publishes as its own.
OPERATOR_ENV = "MISQUOTE_OPERATOR_ADDRESS"

#: The wallet whose key is in `MISQUOTE_PRIVATE_KEY`, when it is not the
#: operator's. Named separately so "somebody else is signing" is a thing the
#: configuration can state rather than a thing the gate has to tolerate.
SIGNER_ENV = "MISQUOTE_SIGNER_ADDRESS"

#: The operator's own key, when the operator itself must sign. See
#: `.env.example` for the trade-off; unset is the safe default.
OPERATOR_KEY_ENV = "MISQUOTE_OPERATOR_PRIVATE_KEY"

#: Which variable declares which role. Refusals name the variable rather than
#: the role, because the variable is the thing a reader has to go and edit.
ROLE_ENV = {"operator": OPERATOR_ENV, "signer": SIGNER_ENV}

#: Retained spelling. The first version of this module had one variable and
#: called it `ENV_VAR`; imports and tests still use that name for the operator.
ENV_VAR = OPERATOR_ENV


class OperatorMismatch(Exception):
    """The loaded key does not sign for any address this deployment declared."""


def _parse(raw: str, env_var: str) -> str | None:
    """Shared by both declarations, so they cannot drift in strictness."""
    raw = raw.strip()
    if not raw:
        return None

    reason = ""
    try:
        checksummed = to_checksum_address(raw)
    except (ValueError, TypeError):
        reason = "which is not an address"
    else:
        body = raw[2:] if raw.lower().startswith("0x") else raw
        letters = [c for c in body if c.isalpha()]
        # Uniform case carries no checksum, so there is nothing to disagree
        # with. Mixed case is a claim, and `to_checksum_address` will have
        # silently rewritten a wrong one rather than rejecting it.
        claims_a_checksum = bool(letters) and not (
            all(c.islower() for c in letters) or all(c.isupper() for c in letters)
        )
        if not claims_a_checksum or checksummed == raw:
            return checksummed
        reason = (
            "whose EIP-55 checksum does not verify — it is a mixed-case address, "
            f"so it claims one, and the address that checksum belongs to is {checksummed}"
        )

    raise ValueError(
        f"{env_var} is set to {raw!r}, {reason}. Unset it or fix it — a value that "
        "cannot be parsed is not the same as no value, and this one would "
        "otherwise disable the check it was set to enable."
    )


def declared_operator() -> str | None:
    """The identity this deployment publishes, checksummed — or `None`.

    Raises `ValueError` on a value that is not an address.
    """
    # Spelled out rather than read through `OPERATOR_ENV`, following
    # `registry/scan8004.py::tier`: `tests/test_env_template.py` walks the AST
    # for string *constants* inside an `os.environ` access, and a variable there
    # reads as no variable at all — the template guard would pass while the
    # template said nothing, which is the one direction that guard exists to
    # catch. Held in step by
    # `test_the_variables_this_module_names_are_the_variables_it_reads`.
    return _parse(os.environ.get("MISQUOTE_OPERATOR_ADDRESS") or "", OPERATOR_ENV)


def declared_signer() -> str | None:
    """The wallet declared to hold the key, checksummed — or `None`."""
    return _parse(os.environ.get("MISQUOTE_SIGNER_ADDRESS") or "", SIGNER_ENV)


def declared_wallets() -> dict[str, str]:
    """Every address this deployment declared, keyed by the role it fills.

    Empty when nothing is declared, which is the permissive case.
    """
    wallets = {}
    operator = declared_operator()
    if operator is not None:
        wallets["operator"] = operator
    signer = declared_signer()
    if signer is not None:
        wallets["signer"] = signer
    return wallets


def role_for(address: str) -> str | None:
    """Which declared role `address` fills, or `None` if it fills none."""
    wanted = to_checksum_address(address)
    for role, declared in declared_wallets().items():
        if declared == wanted:
            return role
    return None


def signing_declaration() -> tuple[str | None, str]:
    """The wallet a key is *expected* to be, and which variable said so.

    The signer wins when both are set: it is the more specific claim, and it
    describes the machine the key is normally on. This is what a message says
    when it has to name one — the guard itself accepts either, see
    `assert_signs_as_declared`.
    """
    signer = declared_signer()
    if signer is not None:
        return signer, SIGNER_ENV
    return declared_operator(), OPERATOR_ENV


def signs_as_delegate() -> bool:
    """Both declared, and different — a wallet nominated to spend for another.

    Not an error. It is the arrangement that lets a funded burn-in wallet do
    work for an identity whose key is deliberately elsewhere. It is reported
    rather than accepted silently, because "the operator signed this" and "a
    wallet the operator nominated signed this" are different claims and only one
    of them is what a green gate would otherwise imply.

    Whether a *particular* key is the delegate is `role_for`; this answers only
    whether the arrangement exists at all.
    """
    operator, signer = declared_operator(), declared_signer()
    return operator is not None and signer is not None and operator != signer


def assert_signs_as_declared(address: str) -> str | None:
    """Refuse unless `address` is one of the wallets this deployment declared.

    Returns the role it filled — `"operator"`, `"signer"`, or `None` when
    nothing is declared and there was nothing to check.

    ## Either, not just the more specific one

    An earlier version compared only against `MISQUOTE_SIGNER_ADDRESS` when both
    were set, on the reasoning that the narrower claim wins. That was right while
    only one key could exist on a machine, and wrong the moment an operator key
    joined it: correcting a card the operator owns has to be signed *by* the
    operator, and the guard was refusing the one wallet with the authority to do
    it.

    Both are addresses this deployment named, so both are answers to "who is
    allowed to spend here". What is not relaxed is the property that matters: a
    key deriving neither is refused exactly as before, and the escape hatch
    remains a second *declaration* rather than an absent one.

    A no-op when nothing is declared. That is the deliberate half: this
    repository runs against anvil forks with anvil's own funded accounts, and a
    guard that demanded a declaration would make the fork suite depend on a
    variable that has nothing to do with it.
    """
    wallets = declared_wallets()
    if not wallets:
        return None

    role = role_for(address)
    if role is None:
        named = ", ".join(f"{ROLE_ENV[r]}={a}" for r, a in sorted(wallets.items()))
        raise OperatorMismatch(
            f"the loaded key signs for {to_checksum_address(address)}, which is "
            f"neither wallet this deployment declared ({named}). Refusing to "
            "broadcast from a wallet nobody wrote down."
        )
    return role


#: The name this had before the split. `chain/signer.py` calls it, and so does
#: anything written against the single-variable version.
assert_signs_for_operator = assert_signs_as_declared


def operator_key() -> str | None:
    """The operator's private key, or `None` when it is not configured.

    Raises `ValueError` when a key is present but derives an address other than
    `MISQUOTE_OPERATOR_ADDRESS`. That check is the whole reason this function
    exists rather than a bare `os.environ` read at the call site: a mistyped
    operator key is not a key that fails, it is a key that succeeds *as somebody
    else*, and the two variables are the only things that can catch it. The
    failure would otherwise be a transaction signed by a wallet nobody named,
    which `assert_signs_as_declared` would then refuse far away from the cause.

    Unset returns `None` rather than raising, so every path that does not need
    an operator signature is unaffected by not having one.
    """
    # Spelled out for `tests/test_env_template.py`'s AST walk, as above.
    key = (os.environ.get("MISQUOTE_OPERATOR_PRIVATE_KEY") or "").strip()
    if not key:
        return None

    from eth_account import Account

    try:
        signs_for = Account.from_key(key).address
    except (ValueError, TypeError) as error:
        raise ValueError(f"{OPERATOR_KEY_ENV} is not a private key: {error}") from error

    declared = declared_operator()
    if declared is not None and to_checksum_address(signs_for) != declared:
        raise ValueError(
            f"{OPERATOR_KEY_ENV} derives {signs_for}, but {OPERATOR_ENV} declares "
            f"{declared}. One of the two is wrong, and the dangerous reading is "
            "that the key is fine and the identity is somebody else's."
        )
    return key
