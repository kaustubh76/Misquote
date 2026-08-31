"""Altana session keys: the caps subset, and the address it does not have.

`Readme.md` §1 puts activation on the never-cut list — grant with visible caps,
inspect, one-transaction revoke — and this package has been a docstring since it
was created. What follows is the honest half: the shape of the grant, priced and
enumerated, and a refusal where a verified deployment would go.

## Why there was no address here, and why there is one now

This module said `SESSION_KEY_MODULE` was empty "on purpose rather than
pending", because `vetting/addresses/` held nothing session-key shaped and
"nobody has run the three-way check against an Altana session-key module the way
`scripts/verify_erc8183.py` did for `JOB_ESCROW`".

The second half was true. The first half was a **statement about this
repository's own output directory**, dressed as a statement about the world.
`@altananetwork/sdk@0.8.0` publishes the addresses in `dist/config.js` — chains
1, 56, 97 and 8453 — and the ABI in `dist/internal/keystore.js`. That is the
same package, at the same version, that `JOB_ESCROW` was verified from. This
repository had already read one table out of it and never opened the other.

**That is P-24 verbatim, one module over.** *"No verified deployment exists"* and
*"we have not verified a deployment"* are different sentences, and this file was
publishing the first while only the second was supported. The lesson P-24 ends
on — the refusal was correct and the reason attached to it was not — applies here
without a word changed.

`scripts/verify_session_keys.py` now runs that three-way check on both chains,
and every check passed. The entries below carry the readings, and
`SESSION_KEY_EVIDENCE` carries the three things they do **not** establish.

The precedent is `registry/erc8183.py::NoVerifiedDeployment`, and its reasoning
still governs every chain we have *not* verified: an exception rather than a
`None`, because a caller that forgets to check a `None` builds an unsigned
transaction to the zero address, and a caller that ignores an exception does not
compile a demo.

## What was real before the address, and still is

The *plan*. `grant_plan` and `revoke_plan` enumerate the transactions a grant
consists of and who sends each — a fact about the caps subset rather than about
any deployment, the same thing `erc8183.steps()` publishes for the hire flow.
Reading the deployment confirmed the load-bearing half and corrected the other:

- **Revoking is one transaction.** `revokeKey(address,bytes32)`, sent by the
  owner. The never-cut claim survives contact with the ABI.
- **It goes to a different contract from the grant.** `registerKey` is on the
  keyStoreController and `revokeKey` is on the keyStore. The two-transaction
  grant shape is about the standard, not about this deployment, and Altana's own
  SDK sends both as ERC-4337 userOps through a bundler rather than as EOA sends.

## What a verified keystore is not

The keystore is where a key is registered, read and revoked. **The caps are
somewhere else** — the allowlist and spend cap live in `registerKey`'s
`validator` and `metadata` arguments and on the per-wallet Altana account, and
nothing here has read either. An expiry that is enforced and an allowlist that is
not would be a worse product than no grant at all, so that gap is on the record
rather than in a comment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

#: Verified Altana session-key modules, by chain id.
#:
#: The keyStore: where a key is registered, read and revoked. An entry belongs
#: here only after the same three-way check `JOB_ESCROW` passed — the address is
#: a contract, it answers the calls this module makes, and its behaviour was
#: observed on a live network rather than inferred from an SDK's constants.
#: `scripts/verify_session_keys.py` is that check, and its records are in
#: `vetting/addresses/session-keys-{56,97}.json`.
SESSION_KEY_MODULE: dict[int, str] = {
    56: "0x6572427ED530BadcF7375Cf9A4709D8d2b0E7E0a",
    97: "0x6b8361C29d05D498b1a12B54A37310f94171E94A",
}

#: Where a grant is registered. Separate from the keyStore, and the separation is
#: load-bearing rather than trivia: `registerKey` is here and `revokeKey` is on
#: the keyStore, so a grant and its revoke go to two different contracts. A flow
#: diagram drawn from the standard rather than from the ABI gets that wrong.
SESSION_KEY_CONTROLLER: dict[int, str] = {
    56: "0x0834Ee2C9BdC3E3efF0a2dC34393D4B0e546A555",
    97: "0xb530D1971f5453F3359518343F05D0AedFfF7e12",
}

#: Verified permission-validator modules, by chain id. **Deliberately empty**,
#: and this is where the caps actually live.
#:
#: `registerKey` takes a `validator` address and a `metadata` blob, and together
#: they are what could enforce an allowlist and a spend cap. This mapping is
#: empty for exactly the reason `SESSION_KEY_MODULE` was empty until it was
#: verified, and the bar is the same: an entry belongs here only after the
#: address is a contract, it answers the calls we would make, and its behaviour
#: was observed on a live network.
#:
#: What makes this an absence rather than an oversight is that the deployment's
#: own users do not use one. Every grant read off chapel — other people's, and
#: now ours — carries `validator = 0x0` and empty metadata. So a session key here
#: is bounded by its **expiry** and by **revocation**, both of which are enforced
#: and both of which have been exercised on chain. The allowlist and the spend
#: cap are enforced by nothing at this layer, and `SessionKeyWriter.grant`
#: refuses to send a grant that would imply otherwise.
VALIDATOR_MODULE: dict[int, str] = {}

#: What was read to justify each entry above, by chain id — and, the half that
#: matters more, what those readings do not establish. The shape is
#: `erc8183.JOB_ESCROW_EVIDENCE`'s, deliberately: an address can never arrive
#: here without its readings, and the readings can never arrive without their
#: limits.
SESSION_KEY_EVIDENCE: dict[int, tuple[str, ...]] = {
    56: (
        "Bytecode at both addresses: keyStore 8,756 bytes, keyStoreController "
        "3,609. Real code, not a proxy — unlike the ERC-8183 kernel, which is a "
        "130-byte proxy. Read 29 Aug 2026 at block 118,718,462.",
        "The interface answers: `getKeys(address)` returns an empty array for an "
        "address holding no keys, `isValidKey(address,bytes32)` returns false, "
        "`getPublicKey(address,bytes32)` returns empty bytes, and the "
        "controller's `getRegistrationFeeInWei()` returns 726,868,274,705,776 "
        "wei (0.000727 BNB).",
        "The fee is NOT A CONSTANT. Three reads minutes apart returned "
        "723,464,592,130,675 / 725,716,783,448,241 / 726,868,274,705,776 — it "
        "tracks something that moves, so a page that caches it quotes a price "
        "the chain will not honour. Read it per grant.",
        "keyStore and keyStoreController are different addresses, checked "
        "explicitly: a table that had accidentally repeated one of them would "
        "pass every other check here while sending the revoke to the wrong "
        "contract.",
        "Recorded in vetting/addresses/session-keys-56.json.",
        "NOT VERIFIED: the caps. This is the keystore. The allowlist and the "
        "spend cap live in `registerKey`'s `validator` and `metadata` arguments "
        "and on the per-wallet Altana account, and nothing here has read either. "
        "An expiry that is enforced and an allowlist that is not would be worse "
        "than no grant at all.",
        "NOT VERIFIED: the write path on mainnet. Every reading above is an "
        "`eth_call` or an `eth_getCode`. A contract that answers "
        "`getRegistrationFeeInWei()` and a contract that will accept *our* "
        "`registerKey` are different claims, and only the first is supported — "
        "which is P-18 pointed at ourselves.",
        "NOT VERIFIED: the relay. Altana's SDK grants through ERC-4337 userOps "
        "via a bundler (`grantSession.js` -> `submitCalls`), not plain EOA "
        "sends. Whether the controller accepts a direct EOA `registerKey` is "
        "unread on this chain.",
    ),
    97: (
        "Same two checks, same shapes, chapel testnet: keyStore 8,756 bytes and "
        "keyStoreController 3,609 — byte-for-byte the same sizes as mainnet, so "
        "what is exercised here is not a different contract from the one on 56. "
        "Read 29 Aug 2026 at block 127,862,076.",
        "`getRegistrationFeeInWei()` returns 725,716,783,448,241 wei, within a "
        "third of a percent of mainnet's — the fee is not a testnet discount.",
        "Recorded in vetting/addresses/session-keys-97.json.",
        "NOT VERIFIED: the caps, here too. Same reason, same absence of a reading.",
    ),
}

#: Where a verifier looked. Named so a refusal can say what was searched rather
#: than only that nothing was found — and the list is the whole defect this
#: module was corrected for.
#:
#: It used to name three files under `vetting/addresses/`, all of them this
#: repository's own output, and concluded from their contents that no session-key
#: module had been verified anywhere. That is a search of a directory reported as
#: a search of the world. The SDK was publishing the addresses the entire time,
#: in the same package this repository had already read `ERC8183_ADDRESSES` out
#: of. A search list that contains only your own artifacts can only ever tell you
#: what you already knew.
SEARCHED = (
    "@altananetwork/sdk@0.8.0 dist/config.js",
    "@altananetwork/sdk@0.8.0 dist/internal/keystore.js",
    "vetting/addresses/session-keys-56.json",
    "vetting/addresses/session-keys-97.json",
    "vetting/addresses/56.json",
    "vetting/addresses/erc8183-56.json",
    "vetting/addresses/erc8183-97.json",
)


class NoVerifiedSessionModule(RuntimeError):
    """Raised by anything that would need an address we do not have.

    An exception rather than a `None` return, for the reason
    `registry/erc8183.py::NoVerifiedDeployment` gives: a caller that forgets to
    check a `None` builds an unsigned transaction to the zero address; a caller
    that ignores this does not compile a demo.
    """


@dataclass(frozen=True, slots=True)
class Cap:
    """The caps subset, and nothing beyond it.

    Four fields because four is what `Readme.md` §1 commits to — allowlist,
    spend cap, expiry, revoke — and a session key that could do a fifth thing
    would not be the bounded grant the page promises. `targets` is an allowlist
    and never a wildcard: a grant that can call anything is not a cap.
    """

    targets: tuple[str, ...]
    token: str
    amount: int
    expiry_ts: int

    def __post_init__(self) -> None:
        if not self.targets:
            raise ValueError("a grant with no allowlist is not a bounded grant")


@dataclass(frozen=True, slots=True)
class Step:
    """One transaction in the activation sequence, and who has to send it."""

    name: str
    sender: str
    what: str


def module_for(chain_id: int) -> str:
    """The verified session-key module for a chain, or a refusal naming the search."""
    try:
        return SESSION_KEY_MODULE[chain_id]
    except KeyError:
        raise NoVerifiedSessionModule(
            f"no verified Altana session-key module for chain {chain_id}. "
            f"Searched {', '.join(SEARCHED)}. Verify one the way "
            f"scripts/verify_erc8183.py verified JOB_ESCROW, and record it in "
            f"sessions/keys.py::SESSION_KEY_MODULE with its readings."
        ) from None


def grant_plan(*, bootstrapped: bool = False) -> tuple[Step, ...]:
    """The transactions a grant consists of, checked against the deployment.

    **The count was right and every reason for it was wrong.** This returned two
    steps — `approve` then `grant` — on the reasoning that "a session key that may
    spend a token needs that token approved to the module first". Running it
    against the verified keystore produced two different transactions:

    1. **There is no `approve`.** The fee is paid in native BNB as the call's
       `value`, and the spend cap is not an ERC-20 allowance to this module at
       all — it belongs to the per-wallet Altana account. A demo built from the
       old plan would have sent an `approve` to a contract that never pulls a
       token.
    2. **`registerKey` reverts on a fresh wallet.** `KeyStore: account not
       bootstrapped`. The first key must go through `initialRegisterKey`, which
       is a different function on the same contract.
    3. **The root key must not expire.** `initialRegisterKey` with any non-zero
       expiry reverts `KeyStore: root key must not expire`. That is also the
       explanation for a live chapel key reading `expiry_ts: 0` and
       `valid: true` at once — not an expired key still working, a root key
       doing what the contract requires of it.

    So a first-time wallet sends two transactions and a bootstrapped one sends
    one, and `bootstrapped` is a parameter rather than an assumption because the
    answer is readable: `keys_of()` returns empty for a wallet that has never
    registered.

    Every sentence above is a revert message or a chain reading, not a reading of
    the SDK. `erc8183.steps()` was corrected the same way and for the same
    reason — a sequence modelled on a standard prices a flow the deployment does
    not implement.
    """
    session = Step(
        name="registerKey",
        sender="owner",
        what=(
            "register the session key with its expiry, on the keyStoreController; "
            "payable, and the fee is read at send time because it moves"
        ),
    )
    if bootstrapped:
        return (session,)
    return (
        Step(
            name="initialRegisterKey",
            sender="owner",
            what=(
                "bootstrap the account with a root key, on the keyStoreController. "
                "Payable, and its expiry must be zero — the contract refuses a root "
                "key that expires"
            ),
        ),
        session,
    )


def revoke_plan() -> tuple[Step, ...]:
    """One transaction, sent by the owner. The claim the product makes.

    The one claim in this module that survived contact with the ABI unchanged:
    `revokeKey(address,bytes32)`, one call, owner-sent. What reading the
    deployment added is *where* — the keyStore, not the keyStoreController the
    grant goes to. A grant and its revoke are on two different contracts, which
    nothing about the caps subset would have predicted.
    """
    return (
        Step(
            name="revokeKey",
            sender="owner",
            what=(
                "revoke the session key, on the keyStore — a different contract "
                "from the grant; the agent's next transaction reverts"
            ),
        ),
    )


def capability(chain_id: int = 56) -> dict[str, Any]:
    """The whole honest answer: what is readable, what needs a signer, what is absent."""
    try:
        module = module_for(chain_id)
        available = True
        reason = ""
    except NoVerifiedSessionModule as error:
        module = ""
        available = False
        reason = str(error)

    return {
        "chain_id": chain_id,
        "available": available,
        "module": module or None,
        "reason": reason,
        "searched": list(SEARCHED),
        "evidence": list(SESSION_KEY_EVIDENCE.get(chain_id, ())),
        # `asdict`, not `__dict__`: `Step` uses slots, so it has no instance
        # dict and the attribute access raises. Safe here where it was not in
        # `api/journal.py` — every field is a string, so there is no container
        # for `asdict` to rebuild wrongly.
        "grant_plan": [asdict(step) for step in grant_plan()],
        "revoke_plan": [asdict(step) for step in revoke_plan()],
        # Split, because this was four promises with no implementation between
        # them. The list said "the allowlist a key was granted / its spend cap
        # and how much is left / its expiry / whether it has been revoked" and
        # no function read any of them.
        #
        # Reading the deployment did not turn four promises into four reads. It
        # showed that two of them are somewhere else: the keystore answers
        # existence, liveness and the public key, while the allowlist and the
        # cap live in `registerKey`'s `validator` and `metadata` and on the
        # per-wallet Altana account. So the honest shape is two lists, not one.
        "readable_without_a_signer": [
            "which key ids a wallet has registered (keyStore.getKeys)",
            "whether a key is still live, i.e. not revoked (keyStore.isValidKey)",
            "the key itself (keyStore.getPublicKey)",
            "what a grant costs right now (keyStoreController.getRegistrationFeeInWei)",
        ],
        "not_readable_here": [
            "the allowlist a key was granted — it is the `validator` module's, "
            "and this repository has not read that module",
            "its spend cap and how much is left — same place, same absence",
        ],
        "needs_a_signer": ["grant", "revoke"],
        "note": (
            "The plans above are facts about the caps subset, not about a deployment: "
            "revoking is one transaction whether or not anyone has deployed the module. "
            "Reading the deployment confirmed that and corrected the shape around it — "
            "the grant goes to the keyStoreController and the revoke to the keyStore, "
            "two different contracts, and Altana's own SDK sends both as ERC-4337 "
            "userOps through a bundler rather than as EOA transactions. What a verified "
            "keystore does not give us is the caps themselves, which is why "
            "not_readable_here is a field rather than a silence."
        ),
    }
