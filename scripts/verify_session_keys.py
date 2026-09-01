"""Verify the Altana session-key deployment, before anything points at it.

    uv run python scripts/verify_session_keys.py --chain 97
    uv run python scripts/verify_session_keys.py --chain 56 --out

## Why this exists

`sessions/keys.py` keeps `SESSION_KEY_MODULE` empty, and the reason it gave was:

> nobody has run the three-way check against an Altana session-key module the way
> `scripts/verify_erc8183.py` did for `JOB_ESCROW`

That was true, and the sentence beside it was not. `SEARCHED` named three files
in `vetting/addresses/` and concluded there was "nothing session-key shaped" —
which is a statement about this repository's own output directory, not about the
world. **`@altananetwork/sdk@0.8.0` publishes the addresses**, in `dist/config.js`,
for chains 1, 56, 97 and 8453; the ABI is in `dist/internal/keystore.js`. It is
the same package, at the same version, that `JOB_ESCROW` was verified from — this
repository had already read one table out of it and never looked at the other.

That is **P-24 exactly**, one module over: *"no verified deployment exists"* and
*"we have not verified a deployment"* are different sentences, and `keys.py` was
publishing the first while only the second was supported.

So this looks, the same three ways `verify_erc8183.py` and `verify_venus.py` do:
the addresses hold code, the accessors answer, and the answers agree with each
other and with something we already knew.

**Nothing here signs.** No account, no key path, and no call that is not
`eth_call` or `eth_getCode`.

## The rule this does not relax

A passing run here is what *permits* an entry in `SESSION_KEY_MODULE`; it does
not create one, and the entry names what was read. P-18 is the standing reason:
`TermixEscrow` passed four real checks and implemented none of the standard those
checks were taken to establish.

It is also **not** sufficient in a second way, which the record states rather than
leaves for a reader to discover. What is verified here is the *keystore*: where
keys are registered, read and revoked. The caps themselves — the allowlist and
the spend cap — live in `registerKey`'s `validator` and `metadata` arguments and
on the per-wallet Altana account, and nothing here has verified those. A grant
whose expiry is enforced and whose allowlist is not would be a worse product than
no grant at all, so the gap is named on the record.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from eth_abi import decode
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

RPCS: dict[int, tuple[str, ...]] = {
    56: (
        "https://bsc-rpc.publicnode.com",
        "https://bsc-dataseed.bnbchain.org",
    ),
    97: (
        "https://bsc-testnet-rpc.publicnode.com",
        "https://data-seed-prebsc-1-s1.bnbchain.org:8545",
    ),
}

RECORD_DIR = Path(__file__).resolve().parents[1] / "vetting" / "addresses"

#: Read out of `@altananetwork/sdk@0.8.0`'s `dist/config.js`, verbatim.
#: **Candidates to verify, not facts to trust** — the same words
#: `verify_erc8183.py` and `verify_addresses.py` put over their own tables.
CANDIDATES: dict[int, dict[str, str]] = {
    56: {
        "keyStore": "0x6572427ED530BadcF7375Cf9A4709D8d2b0E7E0a",
        "keyStoreController": "0x0834Ee2C9BdC3E3efF0a2dC34393D4B0e546A555",
    },
    97: {
        "keyStore": "0x6b8361C29d05D498b1a12B54A37310f94171E94A",
        "keyStoreController": "0xb530D1971f5453F3359518343F05D0AedFfF7e12",
    },
}

#: The ABI, from `dist/internal/keystore.js`. Recorded as signature -> return
#: type so the naming can be re-derived from a dispatch table rather than
#: trusted, which is the form `aacp.ESCROW_INTERFACE` settled on after P-18.
KEYSTORE_READS: dict[str, str] = {
    "getKeys(address)": "bytes32[]",
    "isValidKey(address,bytes32)": "bool",
    "getPublicKey(address,bytes32)": "bytes",
}
CONTROLLER_READS: dict[str, str] = {
    "getRegistrationFeeInWei()": "uint256",
}

#: The two writes, carried for completeness and **not called here**. `revokeKey`
#: is the one the product's never-cut claim rests on: one transaction, sent by
#: the owner, and it is on the keyStore rather than the controller — so a grant
#: and its revoke go to two different contracts, which is the kind of thing a
#: flow diagram gets wrong when nobody has read the ABI.
WRITES: dict[str, str] = {
    "registerKey(bytes32,address,bytes,bytes,uint40)": "keyStoreController, payable",
    "revokeKey(address,bytes32)": "keyStore",
}

#: An address with no keys, used to prove the accessors answer rather than that
#: any particular wallet holds a grant. The zero address is deliberate: it cannot
#: hold a key, so a non-empty answer here would mean the decode is wrong.
PROBE_ADDRESS = "0x" + "00" * 20

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"


class Report:
    def __init__(self, chain_id: int, block: int | None = None) -> None:
        self.chain_id = chain_id
        self.block = block
        self.checks: list[dict[str, str]] = []

    def add(self, name: str, status: str, detail: str, provenance: str = "P-27") -> None:
        self.checks.append(
            {"name": name, "status": status, "detail": detail, "provenance": provenance}
        )
        mark = {"PASS": "ok  ", "FAIL": "FAIL", "UNKNOWN": "????"}[status]
        print(f"  [{mark}] {name}  {detail}")

    @property
    def verdict(self) -> str:
        if any(c["status"] == FAIL for c in self.checks):
            return FAIL
        if any(c["status"] == UNKNOWN for c in self.checks):
            return UNKNOWN
        return PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "block": self.block,
            "chain_id": self.chain_id,
            "surveyed": True,
            "reason": "",
            "verdict": self.verdict,
            "source": "@altananetwork/sdk@0.8.0 dist/config.js + dist/internal/keystore.js",
            "checks": self.checks,
            "not_verified": list(NOT_VERIFIED),
            "summary": {
                "checked": len(self.checks),
                "failed": sum(1 for c in self.checks if c["status"] == FAIL),
                "unknown": sum(1 for c in self.checks if c["status"] == UNKNOWN),
            },
        }


#: What a passing run does **not** establish. Carried in the record itself, in
#: the house style `erc8183.JOB_ESCROW_EVIDENCE` set: the readings are the
#: interesting output, and the half that says what they do not cover is the half
#: a reader needs most.
NOT_VERIFIED = (
    "NOT VERIFIED: the caps. This checks the keystore, where a key is registered, read and revoked. The allowlist and spend cap live elsewhere and nothing here has read them.",
    "NOT VERIFIED: the write path. Every reading here is a call, never a send — a contract that answers and one that will accept *our* grant are different claims.",
    "NOT VERIFIED: the relay. Altana's own SDK grants through ERC-4337 userOps via a bundler, not plain EOA sends. Whether a direct send is accepted is unread here.",
)


def connect(chain_id: int) -> Web3:
    for url in RPCS[chain_id]:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if w3.eth.chain_id == chain_id:
                print(f"rpc      {url}  (head {w3.eth.block_number:,})")
                return w3
        except Exception:  # noqa: BLE001
            continue
    raise SystemExit(f"no reachable RPC for chain {chain_id}")


def _encoded(signature: str, address: str) -> bytes:
    """Selector plus whatever `PROBE_ADDRESS`-shaped arguments the signature takes.

    Only the two shapes this module reads — `(address)` and `(address,bytes32)` —
    because encoding a shape we do not call would be pricing a flow that does not
    exist, which is the mistake `erc8183.steps()` was corrected for.
    """
    selector = Web3.keccak(text=signature)[:4]
    args = signature.split("(", 1)[1].rstrip(")")
    if args == "":
        return selector
    word = bytes(12) + bytes.fromhex(address[2:])
    if args == "address":
        return selector + word
    if args == "address,bytes32":
        return selector + word + bytes(32)
    raise ValueError(f"no encoder for {signature}")


def survey(w3: Web3, chain_id: int) -> Report:
    try:
        head = w3.eth.block_number
    except Exception:  # noqa: BLE001
        head = None
    report = Report(chain_id, block=head)
    table = CANDIDATES[chain_id]

    # 1. Bytecode.
    for role, address in table.items():
        try:
            size = len(w3.eth.get_code(Web3.to_checksum_address(address)))
        except Exception as error:  # noqa: BLE001
            report.add(f"{role} has code", UNKNOWN, f"could not read {address}: {error}")
            continue
        report.add(
            f"{role} has code",
            PASS if size > 0 else FAIL,
            f"{size:,} bytes at {address}" if size else f"no code at {address}",
        )

    # 2. The interface answers.
    def answers(role: str, signature: str, kind: str) -> Any | None:
        try:
            raw = w3.eth.call(
                {
                    "to": Web3.to_checksum_address(table[role]),
                    "data": _encoded(signature, PROBE_ADDRESS),
                }
            )
            value = decode([kind], raw)[0]
        except Exception as error:  # noqa: BLE001
            report.add(
                f"{role}.{signature} answers",
                FAIL,
                f"reverted or returned nothing: {type(error).__name__}",
            )
            return None
        shown = value.hex() if isinstance(value, bytes) else value
        report.add(f"{role}.{signature} answers", PASS, f"returns {shown!r}")
        return value

    for signature, kind in KEYSTORE_READS.items():
        answers("keyStore", signature, kind)
    fee = answers("keyStoreController", "getRegistrationFeeInWei()", "uint256")

    # 3. The answers agree — with each other, and with something checkable.
    keys = None
    try:
        raw = w3.eth.call(
            {
                "to": Web3.to_checksum_address(table["keyStore"]),
                "data": _encoded("getKeys(address)", PROBE_ADDRESS),
            }
        )
        keys = decode(["bytes32[]"], raw)[0]
    except Exception:  # noqa: BLE001 — already recorded as a failed check above
        pass

    if keys is not None:
        # The zero address cannot hold a key. A non-empty answer would mean the
        # decode is wrong, not that the deployment is interesting.
        report.add(
            "an address with no keys reads as having none",
            PASS if len(keys) == 0 else FAIL,
            f"getKeys(0x00..00) returned {len(keys)} keys"
            + ("" if len(keys) == 0 else " — the decode is wrong, not the chain"),
        )

    if fee is not None:
        # A reading, not a threshold. A fee of zero is a real deployment that
        # charges nothing, and saying so beats inventing a bound for it.
        report.add(
            "the registration fee is readable",
            PASS,
            f"getRegistrationFeeInWei() is {int(fee):,} wei"
            + (f" ({int(fee) / 1e18:.6f} native)" if fee else " — free"),
        )

    # 4. The two contracts are not the same contract. The grant goes to the
    #    controller and the revoke to the keyStore, and a table that had
    #    accidentally repeated one address would still pass every check above.
    report.add(
        "keyStore and controller are different contracts",
        PASS if table["keyStore"].lower() != table["keyStoreController"].lower() else FAIL,
        f"{table['keyStore']} vs {table['keyStoreController']}",
    )

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chain", type=int, default=97, choices=(56, 97))
    ap.add_argument(
        "--out",
        nargs="?",
        const=str(RECORD_DIR / "session-keys-{chain}.json"),
        help="record the survey",
    )
    args = ap.parse_args()

    w3 = connect(args.chain)
    print(f"\nAltana session-key candidates, chain {args.chain}\n")
    report = survey(w3, args.chain)
    print(f"\nverdict  {report.verdict}")

    print("\n  writes, recorded and not called:")
    for signature, where in WRITES.items():
        print(f"    {signature:<52} {where}")
    print("\n  what this does not establish:")
    for line in NOT_VERIFIED:
        print(f"    - {line}")

    if args.out:
        out = Path(args.out.replace("{chain}", str(args.chain)))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
        print(f"\nrecorded -> {out}")

    if report.verdict != PASS:
        print(
            "\nSESSION_KEY_MODULE stays empty. A passing run is necessary and not "
            "sufficient (P-18), and this did not even pass."
        )
        return 1
    print(
        "\nEvery check passed. That permits an entry in SESSION_KEY_MODULE; it does "
        "not create one. The entry names what was read, including what it did not."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
