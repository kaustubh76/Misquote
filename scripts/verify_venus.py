"""Verify every Venus market against the chain, and refuse to clear what it cannot read.

`verify_addresses.py` does this for the PancakeSwap deployment; this is the
lending venue's half, and it exists for the same reason. `Readme.md` rule 6 says
every displayed number traces to a chain query, and the addresses a router is
aimed at are the first thing that has to hold.

    uv run python scripts/verify_venus.py --chain 56          # report only
    uv run python scripts/verify_venus.py --chain 56 --out    # and record it
    uv run python scripts/verify_venus.py --chain 56 --scan   # walk all 52 markets

## The two-market floor is enforced here, not documented here

A router with one venue has nothing to choose between: every decision it makes
is "stay", the switching boundary is never consulted, and a card built on it
would describe a policy that never ran. So this exits non-zero below two
verified markets, and Router's card cannot quote until it exits zero. The
floor is a gate rather than a note because the failure it prevents — a Yield
agent that renders as built and cannot choose — is exactly the shape of thing
this repository's ledger exists to disclose.

## `--scan` is discovery, not verification

It walks `getAllMarkets()` and prints what each market says about itself, which
is how the two in `chain/venus.py` were found. Nothing it prints is a fact until
it has been through `survey()` and written into that module by hand. The
distinction is the same one `verify_addresses.py` draws, and it matters more
here: Venus lists 52 markets and several are deprecated stubs that still answer
every getter.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from eth_abi import decode, encode
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from misquote.chain.venus import MARKETS, UNITROLLER, UNVERIFIED_VENUES
from misquote.vetting import venus

RPCS: dict[int, tuple[str, ...]] = {
    56: (
        "https://bsc-rpc.publicnode.com",
        "https://bsc-dataseed.bnbchain.org",
        "https://bsc-dataseed1.defibit.io",
    ),
}

RECORD_DIR = Path(__file__).resolve().parents[1] / "vetting" / "addresses"

#: The router's floor. See the module docstring.
MIN_MARKETS = 2

#: Return type by function name. Every signature this script uses returns one
#: value and the return type is not in the signature string, so it is looked up
#: rather than parsed — a new check with a different shape has to add itself
#: here, which is the right place to notice.
_RETURNS: dict[str, str] = {
    "getAllMarkets": "address[]",
    "comptroller": "address",
    "underlying": "address",
    "symbol": "string",
    "decimals": "uint8",
    "borrowIndex": "uint256",
    "getCash": "uint256",
    "totalBorrows": "uint256",
    "reserveFactorMantissa": "uint256",
    "exchangeRateStored": "uint256",
    "supplyRatePerBlock": "uint256",
}


class Web3Reader:
    """`vetting.venus.Reader`, backed by a real node.

    The judgement lives in `packages/misquote/vetting/venus.py` and takes a
    protocol, so every verdict in it is exercised without a chain. This is the
    thin half that cannot be: it turns a signature and some arguments into an
    `eth_call`.

    Raising is the contract. `survey()` turns any exception into `UNKNOWN`,
    which is blocking — a read that did not happen must never be a pass — so
    swallowing an error here would break the one guarantee the module makes.
    """

    def __init__(self, w3: Web3) -> None:
        self.w3 = w3

    def code_size(self, address: str) -> int:
        return len(self.w3.eth.get_code(Web3.to_checksum_address(address)))

    def call(self, address: str, signature: str, *args: Any) -> Any:
        types = [t for t in signature[signature.index("(") + 1 : -1].split(",") if t]
        selector = Web3.keccak(text=signature)[:4]
        encoded = encode(types, list(args)) if types else b""
        raw = self.w3.eth.call(
            {"to": Web3.to_checksum_address(address), "data": selector + encoded}
        )
        return _decode(signature, raw)


def _decode(signature: str, raw: bytes) -> Any:
    """Decode one return value, tolerating the wide returndata Venus emits.

    Measured on vUSDT at block 117,186,608: `getCash()`, `supplyRatePerBlock()`
    and `exchangeRateStored()` each return **96 bytes** where the ABI declares a
    single `uint256`, while `borrowIndex()`, `totalBorrows()` and
    `reserveFactorMantissa()` return 32. The value is word 0 in every case,
    cross-checked against the accrual logs, which carry `cashPrior` and
    `totalBorrows` in their own data.

    So this asserts `len % 32 == 0` and takes the first word for fixed-width
    types. Asserting `len == 32` would refuse three live getters; indexing by a
    position nobody checked is P-8, where `slot0[2]` was read for `slot0[5]` and
    returned a plausible small integer.

    Empty returndata raises rather than decoding to a zero value. `vBNB` has no
    `underlying()` — it holds native BNB — and returns zero bytes, which a
    tolerant decoder turns into `address(0)` and then into a silent mis-mapping.
    """
    name = signature.split("(")[0]
    kind = _RETURNS[name]
    if not raw:
        raise ValueError(
            f"{name}() returned zero bytes. That is not a zero value — it is a function "
            f"this contract does not implement (vBNB's `underlying()` is the live example)."
        )
    if len(raw) % 32 != 0:
        raise ValueError(
            f"{name}() returned {len(raw)} bytes, which is not a whole number of words"
        )
    # Dynamic types need the whole buffer; fixed-width ones are in word 0.
    if kind.endswith("]") or kind == "string" or kind == "bytes":
        return decode([kind], raw)[0]
    return decode([kind], raw[:32])[0]


def connect(chain_id: int) -> Web3:
    for url in RPCS[chain_id]:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))
            # BSC is proof-of-authority and puts more than 32 bytes in
            # `extraData`, which the default block validator rejects. Same
            # injection `indexer/reader.py` makes, for the same reason.
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if w3.eth.chain_id == chain_id:
                print(f"rpc      {url}  (head {w3.eth.block_number:,})")
                return w3
        except Exception:  # noqa: BLE001 — try the next endpoint
            continue
    raise SystemExit(f"no reachable RPC for chain {chain_id}")


def scan(w3: Web3, chain_id: int) -> int:
    """Walk every market the Unitroller lists and print what it says about itself."""
    reader = Web3Reader(w3)
    unitroller = UNITROLLER[chain_id]
    markets = reader.call(unitroller, "getAllMarkets()")
    print(f"\n{unitroller} lists {len(markets)} markets\n")
    print(f"{'symbol':10s} {'market':44s} {'underlying':44s} {'cash':>22s}")
    for address in markets:
        try:
            symbol = str(reader.call(address, "symbol()"))
        except Exception as error:  # noqa: BLE001
            print(f"{'?':10s} {address:44s} symbol() failed: {error}")
            continue
        try:
            underlying = str(reader.call(address, "underlying()"))
        except Exception:  # noqa: BLE001
            # Not an error worth a stack trace: vBNB holds native BNB and has no
            # underlying ERC-20. Printed as what it is.
            underlying = "— native (no underlying())"
        try:
            cash = f"{int(reader.call(address, 'getCash()')):,}"
        except Exception:  # noqa: BLE001
            cash = "unreadable"
        print(f"{symbol:10s} {address:44s} {underlying:44s} {cash:>22s}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chain", type=int, default=56, choices=(56,))
    ap.add_argument("--scan", action="store_true", help="walk every market the Unitroller lists")
    ap.add_argument(
        "--out",
        nargs="?",
        const=str(RECORD_DIR / "venus-{chain}.json"),
        help="record the survey as JSON",
    )
    args = ap.parse_args()

    w3 = connect(args.chain)
    if args.scan:
        return scan(w3, args.chain)

    report = venus.survey(Web3Reader(w3), args.chain)
    report.block = w3.eth.block_number

    print(f"\nVenus Core Pool, chain {args.chain}\n")
    for check in report.checks:
        mark = {"PASS": "ok  ", "FAIL": "FAIL", "UNKNOWN": "????"}.get(check.status, check.status)
        print(f"  [{mark}] {check.name}  {check.detail}")

    if UNVERIFIED_VENUES:
        print("\nvenues deliberately not carried, and why:")
        for name, reason in UNVERIFIED_VENUES.items():
            print(f"  {name}: {reason}")

    passing = report.markets_passing
    configured = len(MARKETS.get(args.chain, ()))
    print(f"\nverdict  {report.verdict}   markets passing {passing}/{configured}")

    if args.out:
        out = Path(args.out.replace("{chain}", str(args.chain)))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
        print(f"recorded {report.to_dict()['summary']['checked']} checks -> {out}")

    if passing < MIN_MARKETS:
        print(
            f"\nFLOOR NOT MET: {passing} verified market(s), the router needs {MIN_MARKETS}.\n"
            f"One venue is not a choice — every decision would be 'stay' and the "
            f"switching boundary would never be consulted.\n"
            f"Router publishes a withheld card until this exits zero."
        )
        return 1
    return 0 if report.verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
