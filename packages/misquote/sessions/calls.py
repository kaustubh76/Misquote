"""The session-key module, called rather than described.

`keys.py` publishes the *plan* — what a grant consists of and who sends each
transaction — which was worth publishing before an address existed and is still
worth publishing now. This module is the other half: the ABI, the calldata, and
the four reads `capability()` had been promising.

## The promise that had no implementation

`capability()["readable_without_a_signer"]` listed four things:

    the allowlist a key was granted
    its spend cap and how much is left
    its expiry
    whether it has been revoked

**No function implemented any of them.** The list was accurate about what the
caps subset means and silent about whether anything here could read it, and
`api/sessions.py::sessions_for` returned 501 for every wallet — which was the
honest answer while it was true.

Reading the deployment changed what that list can honestly say, and not in the
direction the list assumed. `getKeys` / `isValidKey` / `getPublicKey` are what
the keystore exposes, so **revocation and existence are readable and the caps are
not**: the allowlist and the spend cap live in `registerKey`'s `validator` and
`metadata` arguments and on the per-wallet Altana account. So the list is now
split into what is read and what is still only claimed, rather than left as four
promises with one implementation between them.

## Two contracts, and why that is not trivia

`registerKey` is on the **keyStoreController**. `revokeKey` is on the
**keyStore**. A grant and its revoke go to different addresses, which no reading
of the caps subset would have predicted and which a demo built from the plan
alone would discover at transaction time.

## Nothing here decides to send

Every write is built and returned; `SessionKeyWriter` is the only thing that
signs, it takes a `BscSigner`, and that signer carries the kill file, the
chain-id guard and the dry-run refusal it always has.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from eth_utils import keccak
from web3 import Web3

from misquote.sessions.keys import (
    SESSION_KEY_CONTROLLER,
    SESSION_KEY_MODULE,
    VALIDATOR_MODULE,
    Cap,
    NoVerifiedSessionModule,
)

#: From `@altananetwork/sdk@0.8.0` `dist/internal/keystore.js`, and re-derivable:
#: `test_session_calls.py` recomputes every selector below from its signature, so
#: a typo is a failing test rather than a transaction to a function that does not
#: exist. `aacp.ESCROW_INTERFACE` settled on this shape after P-18.
KEYSTORE_ABI = json.loads("""[
  {"name":"getKeys","type":"function","stateMutability":"view",
   "inputs":[{"name":"user","type":"address"}],
   "outputs":[{"type":"bytes32[]"}]},
  {"name":"getPublicKey","type":"function","stateMutability":"view",
   "inputs":[{"name":"user","type":"address"},{"name":"keyId","type":"bytes32"}],
   "outputs":[{"type":"bytes"}]},
  {"name":"isValidKey","type":"function","stateMutability":"view",
   "inputs":[{"name":"user","type":"address"},{"name":"keyId","type":"bytes32"}],
   "outputs":[{"type":"bool"}]},
  {"name":"getValidator","type":"function","stateMutability":"view",
   "inputs":[{"name":"user","type":"address"},{"name":"keyId","type":"bytes32"}],
   "outputs":[{"type":"address"}]},
  {"name":"getExpiry","type":"function","stateMutability":"view",
   "inputs":[{"name":"user","type":"address"},{"name":"keyId","type":"bytes32"}],
   "outputs":[{"type":"uint40"}]},
  {"name":"getMetadata","type":"function","stateMutability":"view",
   "inputs":[{"name":"user","type":"address"},{"name":"keyId","type":"bytes32"}],
   "outputs":[{"type":"bytes"}]},
  {"name":"revokeKey","type":"function","stateMutability":"nonpayable",
   "inputs":[{"name":"user","type":"address"},{"name":"keyId","type":"bytes32"}],
   "outputs":[]}
]""")


def verified_validator(chain_id: int) -> str | None:
    """The verified permission-validator module for a chain, or None.

    `None` rather than an exception, unlike `_module`: a missing validator is a
    grant that enforces less, not a call that cannot be built. The refusal for
    that case lives in `grant()`, where the caller can say whether they meant it.
    """
    return VALIDATOR_MODULE.get(chain_id)


#: A grant with no validator module. **This is what the deployment's own users
#: do** — every registration observed on chapel carries `validator = 0`, empty
#: metadata, and an expiry. It is not a placeholder for an address we failed to
#: find; it is the shape the live contract is used in.
#:
#: What it means is the whole reason `grant()` will not send one by accident: a
#: key registered against the zero validator is bounded by its **expiry alone**.
#: The allowlist and the spend cap are enforced by nothing at this layer.
NO_VALIDATOR = "0x" + "00" * 20

CONTROLLER_ABI = json.loads("""[
  {"name":"getRegistrationFeeInWei","type":"function","stateMutability":"view",
   "inputs":[],"outputs":[{"type":"uint256"}]},
  {"name":"initialRegisterKey","type":"function","stateMutability":"payable",
   "inputs":[{"name":"keyId","type":"bytes32"},{"name":"validator","type":"address"},
             {"name":"metadata","type":"bytes"},{"name":"publicKey","type":"bytes"},
             {"name":"expiry","type":"uint40"}],
   "outputs":[]},
  {"name":"registerKey","type":"function","stateMutability":"payable",
   "inputs":[{"name":"keyId","type":"bytes32"},{"name":"validator","type":"address"},
             {"name":"metadata","type":"bytes"},{"name":"publicKey","type":"bytes"},
             {"name":"expiry","type":"uint40"}],
   "outputs":[]}
]""")

#: `uint40` is the expiry's width on chain. A grant that overflows it does not
#: revert into a smaller number — it reverts, or worse, wraps — and "expiry" is
#: the one cap whose failure mode is a key that never dies.
MAX_EXPIRY = 2**40 - 1


def key_id(public_key: bytes) -> bytes:
    """`keccak256(publicKey)`, which is how the SDK derives a key's id.

    Derived rather than chosen: a caller that invents an id registers a key it
    cannot later find, because `getKeys` returns ids and `getPublicKey` is keyed
    by them.
    """
    if not public_key:
        raise ValueError("refusing to derive a key id from an empty public key")
    return keccak(public_key)


@dataclass(frozen=True, slots=True)
class Call:
    """One built transaction: where it goes, what it carries, what it costs.

    `value` is separate from the calldata because `registerKey` is payable and
    the fee is **not a constant** — three reads minutes apart returned three
    different numbers. A builder that baked a fee in would quote a price the
    chain declines.
    """

    to: str
    data: bytes
    value: int
    signature: str
    contract: str  # "keyStore" | "keyStoreController"

    @property
    def selector(self) -> str:
        return "0x" + self.data[:4].hex()


def _module(chain_id: int) -> str:
    try:
        return SESSION_KEY_MODULE[chain_id]
    except KeyError:
        raise NoVerifiedSessionModule(
            f"no verified Altana session-key module for chain {chain_id}. "
            f"Verify one with scripts/verify_session_keys.py and record it in "
            f"sessions/keys.py::SESSION_KEY_MODULE with its readings."
        ) from None


def _controller(chain_id: int) -> str:
    try:
        return SESSION_KEY_CONTROLLER[chain_id]
    except KeyError:
        raise NoVerifiedSessionModule(
            f"no verified Altana keyStoreController for chain {chain_id}"
        ) from None


def keystore(w3, chain_id: int):
    return w3.eth.contract(address=Web3.to_checksum_address(_module(chain_id)), abi=KEYSTORE_ABI)


def controller(w3, chain_id: int):
    return w3.eth.contract(
        address=Web3.to_checksum_address(_controller(chain_id)), abi=CONTROLLER_ABI
    )


# --- reads, none of which needs a signer ------------------------------------


def registration_fee(w3, chain_id: int) -> int:
    """What a grant costs right now, in wei.

    **Read per grant, never cached.** Three reads minutes apart returned
    723,464,592,130,675 / 725,716,783,448,241 / 726,868,274,705,776, so it tracks
    something that moves. A page that renders a stored figure is quoting a price
    the chain will not honour — which is the misquote this project is named for,
    committed by us, on the activation page.
    """
    return int(controller(w3, chain_id).functions.getRegistrationFeeInWei().call())


def keys_of(w3, chain_id: int, owner: str) -> tuple[bytes, ...]:
    """Every key id this wallet has registered. Empty is the common answer."""
    return tuple(keystore(w3, chain_id).functions.getKeys(Web3.to_checksum_address(owner)).call())


def is_valid(w3, chain_id: int, owner: str, kid: bytes) -> bool:
    """Is this key live? The read that makes a revoke checkable by a stranger.

    The whole activation claim is that a grant can be withdrawn. A revoke
    transaction is a receipt that something was *sent*; this is the reading that
    says it *took*, and it needs nothing from us to run.
    """
    return bool(
        keystore(w3, chain_id).functions.isValidKey(Web3.to_checksum_address(owner), kid).call()
    )


def public_key(w3, chain_id: int, owner: str, kid: bytes) -> bytes:
    return bytes(
        keystore(w3, chain_id).functions.getPublicKey(Web3.to_checksum_address(owner), kid).call()
    )


def grants_for(w3, chain_id: int, owner: str) -> list[dict]:
    """Every key this wallet holds, with what is readable about each.

    What is **not** here is the caps. `getKeys` gives ids, `isValidKey` gives
    liveness, `getPublicKey` gives the key — the allowlist and the spend cap are
    in `registerKey`'s `validator` and `metadata` and on the Altana account, and
    are not read by anything in this repository. Each row says so in `caps`
    rather than omitting the field, because a row with no caps key reads as a
    grant with no caps.
    """
    store = keystore(w3, chain_id)
    rows: list[dict] = []
    for kid in keys_of(w3, chain_id, owner):
        who = Web3.to_checksum_address(owner)
        validator = str(store.functions.getValidator(who, kid).call())
        metadata = bytes(store.functions.getMetadata(who, kid).call())
        enforced = Web3.to_checksum_address(validator) != Web3.to_checksum_address(NO_VALIDATOR)
        rows.append(
            {
                "key_id": "0x" + bytes(kid).hex(),
                "valid": bool(store.functions.isValidKey(who, kid).call()),
                "public_key": "0x" + bytes(store.functions.getPublicKey(who, kid).call()).hex(),
                "expiry_ts": int(store.functions.getExpiry(who, kid).call()),
                "validator": validator,
                "metadata": "0x" + metadata.hex(),
                # The field that stops a page rendering four caps when the chain
                # enforces one. `caps_enforced` is derived from the validator
                # rather than from what the grant was *asked* for.
                "caps_enforced": enforced,
                # What actually bounds this key, derived rather than assumed.
                #
                # A live key on chapel reads `expiry_ts: 0` and `valid: true` at
                # the same time, which is the reading that makes this field
                # necessary: zero is not "expired", it is "no expiry", and a
                # grant with no validator and no expiry is bounded by revocation
                # and by nothing else. Rendering that as "expires: 1970-01-01"
                # would be the misquote, and rendering it as a capped grant would
                # be worse.
                "bounded_by": (
                    "a validator module (unread)"
                    if enforced
                    else "an expiry"
                    if int(store.functions.getExpiry(who, kid).call())
                    else "revocation alone — no validator and no expiry"
                ),
                "caps_note": (
                    "a validator module is set; this repository has not read it, so "
                    "what it enforces is unknown"
                    if enforced
                    else "no validator module: the allowlist and spend cap are "
                    "enforced by nothing at this layer"
                ),
            }
        )
    return rows


# --- writes, built and not sent ---------------------------------------------


def grant_call(
    chain_id: int,
    cap: Cap,
    *,
    public_key: bytes,
    validator: str,
    fee_wei: int,
    metadata: bytes = b"",
) -> Call:
    """`registerKey` on the controller, priced at the fee that was just read.

    `cap.targets` and `cap.amount` are **not encoded into the arguments below**,
    and pretending otherwise is the one thing this function must not do. They
    belong to the `validator` module and its `metadata`, whose encoding this
    repository has not verified. So the allowlist and the cap ride in `metadata`
    only if a caller encodes them there, and the caller has to know what the
    validator expects. What is genuinely enforced by this call is `expiry`.
    """
    if fee_wei < 0:
        raise ValueError("a negative registration fee is not a fee")
    if not 0 < cap.expiry_ts <= MAX_EXPIRY:
        raise ValueError(
            f"expiry {cap.expiry_ts} does not fit uint40. A grant whose expiry "
            f"wraps is a grant that never dies, which is the one cap whose "
            f"failure mode is unbounded."
        )

    contract = _controller(chain_id)
    kid = key_id(public_key)
    data = Web3.keccak(text="registerKey(bytes32,address,bytes,bytes,uint40)")[:4]
    from eth_abi import encode

    data += encode(
        ["bytes32", "address", "bytes", "bytes", "uint40"],
        [kid, Web3.to_checksum_address(validator), metadata, public_key, cap.expiry_ts],
    )
    return Call(
        to=Web3.to_checksum_address(contract),
        data=data,
        value=int(fee_wei),
        signature="registerKey(bytes32,address,bytes,bytes,uint40)",
        contract="keyStoreController",
    )


def revoke_call(chain_id: int, owner: str, kid: bytes) -> Call:
    """`revokeKey` on the keyStore. One transaction, and the product's claim.

    A different contract from the grant, which is the correction reading the ABI
    produced: `revoke_plan()` was right that revoking is one transaction and had
    no way to know it goes somewhere else.
    """
    if len(kid) != 32:
        raise ValueError(f"a key id is 32 bytes, got {len(kid)}")

    from eth_abi import encode

    data = Web3.keccak(text="revokeKey(address,bytes32)")[:4]
    data += encode(["address", "bytes32"], [Web3.to_checksum_address(owner), kid])
    return Call(
        to=Web3.to_checksum_address(_module(chain_id)),
        data=data,
        value=0,
        signature="revokeKey(address,bytes32)",
        contract="keyStore",
    )


class SessionKeyWriter:
    """One keystore, one signer, one transaction per call.

    `registry/identity.py::IdentityWriter` is the shape, deliberately: same
    `BscSigner`, same receipt list, same gas accounting derived from receipts
    rather than from estimates. It is the writer that put four ERC-8004
    identities on chapel, so the parts that matter here — kill file, chain-id
    guard, dry-run refusal, nonce-race retry — are the ones already exercised by
    mined transactions rather than a second implementation of them.

    Two contracts, not one, which is the difference from `IdentityWriter`:
    `grant` goes to the keyStoreController and `revoke` to the keyStore.
    """

    __slots__ = ("signer", "chain_id", "keystore", "controller", "sent")

    def __init__(self, signer, chain_id: int | None = None) -> None:
        chain_id = signer.chain_id if chain_id is None else int(chain_id)
        if chain_id != signer.chain_id:
            raise ValueError(
                f"the keystore is on chain {chain_id} and the signer is on {signer.chain_id}"
            )
        _module(chain_id)  # raises NoVerifiedSessionModule for an unverified chain
        _controller(chain_id)

        self.signer = signer
        self.chain_id = chain_id
        self.keystore = keystore(signer.w3, chain_id)
        self.controller = controller(signer.w3, chain_id)
        self.sent: list = []

    def grant(
        self,
        cap: Cap,
        *,
        public_key: bytes,
        validator: str,
        metadata: bytes = b"",
        fee_wei: int | None = None,
        allow_unenforced_caps: bool = False,
    ):
        """Register a session key. Returns `(key_id, receipt)`.

        The fee is **read at send time** unless one is passed. It moved between
        three reads minutes apart, so a cached figure is a transaction that
        reverts for underpayment — and paying a stale higher figure would be
        worse, because it succeeds and overpays silently.
        """
        if not 0 < cap.expiry_ts <= MAX_EXPIRY:
            raise ValueError(
                f"expiry {cap.expiry_ts} does not fit uint40; a grant whose "
                f"expiry wraps is a grant that never dies. Zero is rejected here "
                f"rather than passed through: the keystore reads 0 as *no expiry* "
                f"and reports such a key as valid, so an accidental zero is an "
                f"unbounded grant rather than an expired one."
            )
        if (
            Web3.to_checksum_address(validator) == Web3.to_checksum_address(NO_VALIDATOR)
            and not allow_unenforced_caps
        ):
            raise ValueError(
                "refusing to register a key against the zero validator while `cap` "
                "carries an allowlist and a spend cap that nothing would enforce. "
                "This is the shape every observed grant on this deployment uses, so "
                "it is a real option and not a mistake — but it bounds the key by its "
                "expiry alone, and a grant that renders four caps while the chain "
                "enforces one is the misquote this project is named after. Pass "
                "allow_unenforced_caps=True to send it, and say so wherever it renders."
            )
        kid = key_id(public_key)
        fee = registration_fee(self.signer.w3, self.chain_id) if fee_wei is None else int(fee_wei)

        call = self.controller.functions.registerKey(
            kid, Web3.to_checksum_address(validator), metadata, public_key, cap.expiry_ts
        )
        result = self.signer.send(self.signer.build(call, value=fee))
        self.sent.append(result)
        return kid, result

    def revoke(self, owner: str, kid: bytes):
        """Revoke a session key. One transaction, and the product's whole claim.

        Checks the key is live first. A revoke of an already-dead key either
        reverts or succeeds as a no-op depending on the implementation, and
        neither outcome tells the caller what they wanted to know — so the
        reading is taken before the transaction rather than inferred from it.
        """
        if len(kid) != 32:
            raise ValueError(f"a key id is 32 bytes, got {len(kid)}")
        if not is_valid(self.signer.w3, self.chain_id, owner, kid):
            raise ValueError(
                f"key 0x{bytes(kid).hex()} is not live for {owner}; revoking it "
                f"would say nothing about whether revocation works"
            )

        call = self.keystore.functions.revokeKey(Web3.to_checksum_address(owner), kid)
        result = self.signer.send(self.signer.build(call))
        self.sent.append(result)
        return result

    def bootstrap(self, *, public_key: bytes, fee_wei: int | None = None):
        """Register the account's root key. Returns `(key_id, receipt)`.

        Needed once per wallet and discovered by running it: `registerKey` on a
        fresh account reverts `KeyStore: account not bootstrapped`, and this is
        the call that clears that.

        **The root key must not expire.** `initialRegisterKey` with any non-zero
        expiry reverts `KeyStore: root key must not expire`, so no expiry is
        offered here rather than accepted and discarded. A parameter that must
        always be zero is a parameter that will eventually be passed something
        else.
        """
        kid = key_id(public_key)
        fee = registration_fee(self.signer.w3, self.chain_id) if fee_wei is None else int(fee_wei)
        call = self.controller.functions.initialRegisterKey(
            kid, Web3.to_checksum_address(NO_VALIDATOR), b"", public_key, 0
        )
        result = self.signer.send(self.signer.build(call, value=fee))
        self.sent.append(result)
        return kid, result

    def is_bootstrapped(self, owner: str) -> bool:
        """Has this wallet ever registered a key? Read, not remembered."""
        return bool(keys_of(self.signer.w3, self.chain_id, owner))

    @property
    def gas_spent_wei(self) -> int:
        return sum(tx.gas_cost_wei for tx in self.sent)


__all__ = [
    "CONTROLLER_ABI",
    "KEYSTORE_ABI",
    "MAX_EXPIRY",
    "NO_VALIDATOR",
    "VALIDATOR_MODULE",
    "Call",
    "SessionKeyWriter",
    "controller",
    "grant_call",
    "grants_for",
    "is_valid",
    "key_id",
    "keys_of",
    "keystore",
    "public_key",
    "registration_fee",
    "revoke_call",
    "verified_validator",
]
