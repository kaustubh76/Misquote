"""Authenticate against TermiX's platform, and read the half that needs it.

    uv run python scripts/termix_login.py                # plan and price it
    uv run python scripts/termix_login.py --authenticate --out

## What this is

The ledger said this was blocked on "a wallet-signed nonce exchanged for a
session JWT, which is the same signing path the 24h burn-in needs and which does
not exist yet". Every clause of that is wrong — see `registry/authenticate.py`
and **P-29**. The endpoints are public, the nonce is SIWE, and the signing
primitive was one wrapper away.

## Why it does not run by default

`--authenticate` is required, and that is a deliberate asymmetry with the write
scripts. Those default to safe because `MISQUOTE_DRY_RUN` stops them spending. A
signature spends nothing, so no environment variable protects this one — the flag
is the whole guard, and it is at the call site rather than in a config file
somebody set last month.

## The token

Never printed, never written. `--out` records that the exchange completed, for
which wallet, against which endpoint — `Session.evidence()` has no field that
could hold a credential, so this cannot leak one by reaching for the obvious
attribute.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from misquote.chain.signer import BscSigner
from misquote.registry import authenticate as auth
from misquote.registry.aacp import BSC_MAINNET, api_base

RECORD_DIR = Path(__file__).resolve().parents[1] / "vetting" / "identity"

#: Reads that need the token. Kept as a list so a run reports which of them the
#: session could actually serve — "authenticated" and "authenticated and useful"
#: are different claims.
AUTHENTICATED_READS = ("/api/v1/agents", "/api/v1/user/profile")


def connect() -> Web3:
    """A chain connection, only because `BscSigner` requires one.

    Nothing here reads chain state. The signer's constructor asserts the chain id
    is one it knows and refuses otherwise, which is a guard worth keeping even
    when the thing being signed is an HTTP message — it is the same key.
    """
    for url in (
        os.environ.get("BSC_TESTNET_RPC_URL") or "",
        "https://bsc-testnet-rpc.publicnode.com",
    ):
        if not url:
            continue
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if w3.eth.chain_id in (56, 97):
                return w3
        except Exception:  # noqa: BLE001
            continue
    raise SystemExit("no reachable RPC; BscSigner needs one even to sign a message")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--authenticate",
        action="store_true",
        help="complete the exchange. Without it, nothing is signed and nothing is sent.",
    )
    ap.add_argument(
        "--operator",
        action="store_true",
        default=True,
        help="sign as MISQUOTE_OPERATOR_PRIVATE_KEY (the address this project publishes)",
    )
    ap.add_argument("--out", nargs="?", const=str(RECORD_DIR / "termix-auth.json"))
    args = ap.parse_args(argv)

    key = os.environ.get("MISQUOTE_OPERATOR_PRIVATE_KEY") if args.operator else None
    signer = BscSigner(connect(), key)
    client = auth.TermixSession(signer, BSC_MAINNET)

    print(f"platform  {api_base(BSC_MAINNET)}")
    print(f"wallet    {signer.address}")
    print(f"nonce     POST {auth.NONCE_PATH}")
    print(f"verify    POST {auth.WALLET_PATH}  {list(auth.WALLET_FIELDS)}")
    print(
        "note      the platform is chain 56 only; our four agents are on chapel, "
        "so a token\n          authenticates us and still cannot list them"
    )

    if not args.authenticate:
        print(
            "\nNothing was signed and nothing was sent. `--authenticate` is the guard:\n"
            "a signature spends nothing, so MISQUOTE_DRY_RUN does not cover this and\n"
            "the flag is at the call site instead."
        )
        return 0

    challenge = client.challenge()
    print(f"\n  nonce     {challenge.nonce}")
    print(f"  domain    {challenge.domain}  (chain {challenge.chain_id})")
    print(f"  siwe      {challenge.is_siwe}  — signing their message verbatim")
    print(f"  expires   {challenge.expires_at}")

    try:
        session = client.authenticate()
    except auth.AuthFailed as error:
        print(f"\n  exchange failed: {error}")
        return 1

    print("\n  authenticated. The token is held in memory and is not printed.")
    print(f"  refresh   {'issued' if session.refresh_token else 'not issued'}")

    record = session.evidence()
    reads: dict[str, str] = {}
    for path in AUTHENTICATED_READS:
        try:
            payload = client.get(path)
        except Exception as error:  # noqa: BLE001 — a refusal is a reading
            reads[path] = f"{type(error).__name__}: {str(error)[:120]}"
            print(f"  {path:<26} refused: {str(error)[:80]}")
        else:
            # The **count**, not just the shape. An authenticated listing that
            # answers with zero items is the strongest available evidence for the
            # "their dashboard reads zero" finding — stronger than the public
            # explorer, because this is the endpoint their own dashboard reads.
            # Reporting only `['items']` would throw that away.
            if isinstance(payload, dict) and isinstance(payload.get("items"), list):
                count = len(payload["items"])
                total = payload.get("total")
                reads[path] = f"answered: {count} item(s)" + (
                    f" of {total} total" if isinstance(total, int) else ""
                )
            else:
                reads[path] = (
                    f"answered: {sorted(payload) if isinstance(payload, dict) else type(payload).__name__}"
                )
            print(f"  {path:<26} {reads[path]}")
    record["authenticated_reads"] = reads

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(f"\nrecorded -> {out}  (no token in it)")

    print(
        "\nThe exchange completes. What it does not do is list our agents: their\n"
        "backend has no chain-97 base URL, and the four are on chapel."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
