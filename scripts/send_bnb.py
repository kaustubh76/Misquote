"""Send native BNB from the operator to another wallet this project controls.

    uv run python scripts/send_bnb.py --to 0x… --amount 0.0005
    MISQUOTE_DRY_RUN=0 uv run python scripts/send_bnb.py --to 0x… --amount 0.0005 --broadcast

## Why a script for something this small

Because there was not one, and the alternative is a private key on a command
line or in a Python REPL. Every other chain write here goes through `BscSigner`
— the kill switch, the dry-run default, the gas ceiling, the receipt confirmed
across independent endpoints — and a plain transfer is the one that would have
skipped all of it precisely because it looks too simple to need them.

It exists for one real task: the ERC-8183 provider signs its own `submit`, and a
wallet with no gas cannot. The Agent Studio seller had never held mainnet BNB, so
until it does, a two-party hire is unreachable and `hire_mainnet.py` refuses
before escrowing anything.

## What it will not do

Send to an address this repository has never named. The recipient must be one of
the wallets recorded in `.env` or in a keystore under `.studio/wallets/` —
a typo in a 42-character hex string is unrecoverable, and "the address I meant"
is not a thing the chain can be asked about afterwards.

Send more than a cap. `MAX_WEI` is a tenth of a BNB: this is for bootstrapping
gas, and a transfer larger than that is a different operation that should be
looked at by a person rather than typed after midnight.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from web3 import Web3

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))

from misquote.chain.operator import operator_key  # noqa: E402
from misquote.chain.signer import BscSigner  # noqa: E402

CHAIN = 56
RPC = "https://bsc-dataseed.bnbchain.org"

#: Gas bootstrapping only. Anything larger is a different decision.
MAX_WEI = 10**17

#: Where a recipient may be recognised from. A destination this project has not
#: already written down is a destination it should not be sending to unattended.
KEYSTORE_DIR = REPO / "studio" / "misquoterouter" / ".studio" / "wallets"


def known_addresses() -> dict[str, str]:
    """Every wallet this checkout can name, address -> where it was found."""
    found: dict[str, str] = {}
    from eth_account import Account

    key = operator_key()
    if key:
        found[Account.from_key(key).address] = "MISQUOTE_OPERATOR_PRIVATE_KEY"
    if KEYSTORE_DIR.is_dir():
        for path in KEYSTORE_DIR.glob("0x*.json"):
            found[Web3.to_checksum_address(path.stem)] = f".studio/wallets/{path.name}"
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--to", required=True, help="recipient; must be a wallet this repo names")
    ap.add_argument("--amount", type=float, required=True, help="BNB, e.g. 0.0005")
    ap.add_argument(
        "--broadcast",
        action="store_true",
        help="actually send. Needs MISQUOTE_DRY_RUN=0 as well; without it this plans only.",
    )
    args = ap.parse_args()

    to = Web3.to_checksum_address(args.to)
    wei = int(args.amount * 10**18)
    if wei <= 0 or wei > MAX_WEI:
        print(f"refusing {args.amount} BNB — this sends gas, and the cap is {MAX_WEI / 1e18} BNB.")
        return 1

    known = known_addresses()
    if to not in known:
        print(f"refusing: {to} is not a wallet this checkout names.")
        print("  known:")
        for address, where in sorted(known.items()):
            print(f"    {address}  ({where})")
        return 1

    w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 60}))
    signer = BscSigner(w3, operator_key())
    held = w3.eth.get_balance(signer.address)

    print(f"from     {signer.address}  holds {held / 1e18:.6f} BNB")
    print(f"to       {to}  ({known[to]})")
    print(f"amount   {args.amount} BNB")
    print(f"gas      {w3.eth.gas_price / 1e9:.3f} gwei")
    print(f"dry run  {signer.dry_run}")

    # A transfer that leaves the sender unable to pay for its own next call is
    # the shape that strands a run halfway. 21,000 is the transfer itself; the
    # margin is for whatever this wallet was funding the recipient in order to do.
    fee = 21_000 * w3.eth.gas_price
    if held < wei + fee * 20:
        print(f"\nrefusing: {held / 1e18:.6f} BNB does not leave working margin after this.")
        return 1

    if not args.broadcast:
        print("\nplan only. Pass --broadcast with MISQUOTE_DRY_RUN=0 to send.")
        return 0

    sent = signer.send(signer.build({"to": to, "value": wei}))
    print(f"\n  {sent.tx_hash}  gas {sent.gas_used:,}")
    print(f"  https://bscscan.com/tx/{sent.tx_hash}")
    print(f"  recipient now holds {w3.eth.get_balance(to) / 1e18:.6f} BNB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
