"""Unlocking a v3 keystore, because one wallet here does not live in `.env`.

`.env.example` has said "keystore unlocking is not implemented; the signer reads
`MISQUOTE_PRIVATE_KEY`" since it was written, and that was true and limiting.
This repository has two wallets with two custody mechanisms: the operator's key
is an environment variable, and the Agent Studio seller's is a scrypt-encrypted
v3 file under a gitignored directory with its password beside it. Nothing in
Python could sign as the second one, so every recorded hire had one address in
both the client and the provider column — not because that is the product, but
because it was the only shape the signer could produce.

`BscSigner.__init__` already accepts a `private_key` argument, so nothing about
signing changes: this only turns a file and a password into the string that
argument wants.

## What this deliberately does not do

It does not read the password from an argument. `eth_account` will happily take
one, and a password on a command line is in the shell history, in `ps` output
and in any process listing on the machine — the same argument
`scripts/termix_login.py` makes about a nonce. It comes from the environment or
it does not come.

It does not log, return or repr the key. The decrypted material is handed
straight back to the caller as a hex string and never touches this module's
error messages: a `ValueError` from a wrong password says the password was
wrong, not what was tried.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from eth_account import Account


class KeystoreError(RuntimeError):
    """A keystore that cannot be opened, described without quoting its contents."""


def unlock(path: str | Path, *, password_env: str = "WALLET_PASSWORD") -> str:
    """Return the private key in a v3 keystore, as `0x`-prefixed hex.

    `password_env` names the variable holding the password — the name is an
    argument, the value never is.
    """
    keyfile = Path(path)
    if not keyfile.exists():
        raise KeystoreError(f"no keystore at {keyfile}")

    password = os.environ.get(password_env)
    if not password:
        raise KeystoreError(
            f"{password_env} is unset, so {keyfile.name} cannot be opened. "
            f"It lives beside the keystore in `.studio/.env.local`; export it "
            f"for this one command rather than passing it as an argument."
        )

    try:
        payload = json.loads(keyfile.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise KeystoreError(f"{keyfile.name} is not readable JSON: {error}") from error

    try:
        key = Account.decrypt(payload, password)
    except ValueError as error:
        # Deliberately not chained with the original text: `eth_account` puts the
        # MAC comparison in the message, and a decryption failure should say the
        # password was wrong rather than anything about what was tried.
        raise KeystoreError(
            f"{keyfile.name} did not open — {password_env} is wrong for this file"
        ) from error

    return "0x" + key.hex()


def address_of(path: str | Path) -> str:
    """The address a keystore claims, read from the file without opening it.

    Useful for refusing early: a run that is about to spend from the wrong wallet
    should say so before it asks for a password, not after.
    """
    keyfile = Path(path)
    try:
        declared = json.loads(keyfile.read_text()).get("address", "")
    except (OSError, json.JSONDecodeError) as error:
        raise KeystoreError(f"{keyfile.name} is not readable JSON: {error}") from error
    if not declared:
        raise KeystoreError(f"{keyfile.name} declares no address")
    from web3 import Web3

    return Web3.to_checksum_address(declared if declared.startswith("0x") else f"0x{declared}")
