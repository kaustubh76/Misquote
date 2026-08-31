"""Grant a session key on chain, read it back, revoke it, and read that back.

    uv run python scripts/grant_session_key.py --chain 97            # dry run
    MISQUOTE_DRY_RUN=0 uv run python scripts/grant_session_key.py --chain 97 --out

## What this is for

`Readme.md` §5's definition of done for activation is a **round trip**: grant ->
visible -> revoke -> the agent's next transaction fails. Every part of that was
described in `sessions/keys.py` and none of it had happened. This is the part
that happens.

It is the sibling of `scripts/register_identity.py`, which put four ERC-8004
identities on chapel, and it borrows that script's shape deliberately: same
`BscSigner`, same dry-run default, same JSON record of what was mined. A
transaction hash is a third-party-hosted record of an action, checkable without
this repository's cooperation — which is a different and better class of evidence
than a reading we took ourselves and ask you to trust.

## What it refuses to pretend

The keystore enforces an **expiry**. It does not enforce an allowlist or a spend
cap: those live in the `validator` module's `metadata` and on the per-wallet
Altana account, and every grant observed on this deployment — including other
people's — carries `validator = 0x0` and empty metadata. So this passes
`allow_unenforced_caps=True` explicitly, and the record says `caps_enforced:
false` in as many words. A page that renders four caps over a key the chain
bounds by one would be the misquote this project is named after.

## The two transactions, and why the first exists

A fresh wallet cannot `registerKey` — it reverts `KeyStore: account not
bootstrapped`. The first key goes through `initialRegisterKey` and **must not
expire** (`KeyStore: root key must not expire`). Both facts came from running it,
not from the SDK, and both are now in `keys.grant_plan()`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from eth_account import Account
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from misquote.chain.signer import BscSigner
from misquote.sessions import calls
from misquote.sessions.keys import Cap, grant_plan, revoke_plan

RPCS: dict[int, tuple[str, ...]] = {
    56: ("https://bsc-rpc.publicnode.com", "https://bsc-dataseed.bnbchain.org"),
    97: (
        "https://bsc-testnet-rpc.publicnode.com",
        "https://data-seed-prebsc-1-s1.bnbchain.org:8545",
    ),
}
RECORD_DIR = Path(__file__).resolve().parents[1] / "vetting" / "identity"
EXPLORER = {56: "https://bscscan.com/tx/", 97: "https://testnet.bscscan.com/tx/"}


def connect(chain_id: int) -> Web3:
    for url in RPCS[chain_id]:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30}))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if w3.eth.chain_id == chain_id:
                print(f"rpc       {url}  (head {w3.eth.block_number:,})")
                return w3
        except Exception:  # noqa: BLE001
            continue
    raise SystemExit(f"no reachable RPC for chain {chain_id}")


def session_keypair() -> tuple[Any, bytes]:
    """A fresh keypair for the grant. Never the signer's own key.

    The whole point of a session key is that it is not the key that owns the
    funds, so generating one here rather than accepting one as an argument makes
    the wrong thing impossible to pass in.
    """
    account = Account.create()
    public_key = b"\x04" + bytes.fromhex(account._key_obj.public_key.to_hex()[2:])
    return account, public_key


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chain", type=int, default=97, choices=(56, 97))
    ap.add_argument("--hours", type=float, default=1.0, help="how long the session key lives")
    ap.add_argument(
        "--out", nargs="?", const=str(RECORD_DIR / "session-keys-{chain}.json"), help="record it"
    )
    ap.add_argument("--keep", action="store_true", help="grant without revoking (leaves it live)")
    args = ap.parse_args()

    w3 = connect(args.chain)
    signer = BscSigner(w3)
    writer = calls.SessionKeyWriter(signer, args.chain)
    owner = signer.address

    print(f"signer    {owner}")
    print(f"dry run   {signer.dry_run}")
    print(f"module    {calls._module(args.chain)}  (keyStore)")
    print(f"controller{calls._controller(args.chain)}")

    bootstrapped = writer.is_bootstrapped(owner)
    fee = calls.registration_fee(w3, args.chain)
    print(f"fee       {fee:,} wei ({fee / 1e18:.6f} BNB) — read now, not cached")
    print(f"account   {'bootstrapped' if bootstrapped else 'NOT bootstrapped'}")
    print("plan      " + " -> ".join(s.name for s in grant_plan(bootstrapped=bootstrapped)))
    print("revoke    " + " -> ".join(s.name for s in revoke_plan()))

    if signer.dry_run:
        print(
            "\nMISQUOTE_DRY_RUN is set, so nothing was sent. That is the default and "
            "an unset variable cannot spend.\nSet MISQUOTE_DRY_RUN=0 to run it."
        )
        return 0

    record: dict[str, Any] = {
        "chain_id": args.chain,
        "owner": owner,
        "key_store": calls._module(args.chain),
        "key_store_controller": calls._controller(args.chain),
        "registration_fee_wei": fee,
        "caps_enforced": False,
        "caps_note": (
            "The keystore enforces the expiry. The allowlist and spend cap are not "
            "enforced here: they belong to the validator module's metadata and to the "
            "per-wallet Altana account, and this grant carries validator=0x0 and empty "
            "metadata — the same shape every other grant observed on this deployment uses."
        ),
        "transactions": [],
    }

    def note(name: str, receipt) -> None:
        # `SentTransaction.tx_hash` is unprefixed. An explorer URL built by
        # concatenating it still resolves, which is exactly why this would have
        # survived review — but the field is also what a page renders and what a
        # reader copies, and a bare hash is not the form anything else in this
        # repo publishes.
        digest = receipt.tx_hash if receipt.tx_hash.startswith("0x") else "0x" + receipt.tx_hash
        record["transactions"].append(
            {
                "call": name,
                "tx": digest,
                "explorer": EXPLORER[args.chain] + digest,
                "gas_cost_wei": receipt.gas_cost_wei,
            }
        )
        print(f"  {name:<20} {digest}")

    session, public_key = session_keypair()
    print(f"\nsession   {session.address}  (a fresh keypair, never the signer's)")

    if not bootstrapped:
        root, root_public = session_keypair()
        print(f"root      {root.address}  (bootstrap key; the contract forbids it expiring)")
        kid, receipt = writer.bootstrap(public_key=root_public, fee_wei=fee)
        note("initialRegisterKey", receipt)
        record["root_key_id"] = "0x" + kid.hex()

    expiry = int(time.time() + args.hours * 3600)
    cap = Cap(
        targets=(calls._module(args.chain),),
        token="0x" + "00" * 20,
        amount=0,
        expiry_ts=expiry,
    )
    kid, receipt = writer.grant(
        cap,
        public_key=public_key,
        validator=calls.NO_VALIDATOR,
        fee_wei=calls.registration_fee(w3, args.chain),
        # Stated at the call site, because the chain will not enforce the
        # allowlist or the cap and the record must not imply that it does.
        allow_unenforced_caps=True,
    )
    note("registerKey", receipt)
    record["session_key_id"] = "0x" + kid.hex()
    record["expiry_ts"] = expiry

    live = calls.is_valid(w3, args.chain, owner, kid)
    print(f"\n  isValidKey after grant   {live}")
    record["valid_after_grant"] = live
    if not live:
        print("  the grant mined and the key is not live — stopping rather than revoking")
        return 1

    if args.keep:
        print("\n  --keep: the key is live and was not revoked.")
    else:
        receipt = writer.revoke(owner, kid)
        note("revokeKey", receipt)
        dead = calls.is_valid(w3, args.chain, owner, kid)
        print(f"  isValidKey after revoke  {dead}")
        record["valid_after_revoke"] = dead
        if dead:
            print("  the revoke mined and the key is STILL live — that is the finding")
            return 1

    record["gas_spent_wei"] = writer.gas_spent_wei
    record["grants_now"] = calls.grants_for(w3, args.chain, owner)

    if args.out:
        out = Path(args.out.replace("{chain}", str(args.chain)))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(f"\nrecorded -> {out}")

    print(
        "\nGranted, read back live, revoked, read back dead — on chain, with hashes.\n"
        "That is Readme.md §5's definition of done for activation, minus the caps,\n"
        "which this deployment does not enforce at this layer and the record says so."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
