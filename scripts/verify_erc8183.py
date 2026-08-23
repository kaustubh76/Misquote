"""Verify the ERC-8183 deployment Altana publishes, before anything points at it.

    uv run python scripts/verify_erc8183.py --chain 56
    uv run python scripts/verify_erc8183.py --chain 97 --out

## Why this exists

`registry/erc8183.py` keeps `JOB_ESCROW` empty because *"the EIP is Draft and
lists no reference deployment addresses at all"*. That is still true of the EIP.
It is not true of the ecosystem: `@altananetwork/sdk@0.8.0` ships an
`ERC8183_ADDRESSES` table with a kernel, an EvaluatorRouter, an OptimisticPolicy,
a registry and a payment token for **both** BSC mainnet and testnet.

One field in that table is independently checkable, and it checks out: the
`registry` entry is byte-identical to this repository's own `IDENTITY_REGISTRY`
on **both** chains, an address arrived at from a completely different direction.
That is a reason to look, not a reason to believe — so this looks, the same
three ways `verify_venus.py` and `verify_addresses.py` do.

**Nothing here signs.** There is no web3 account, no key path, and no call that
is not `eth_call` or `eth_getCode`.

## The rule this does not relax

`registry/aacp.py` states it: a passing `verify()` is necessary and not
sufficient. TermiX's `TermixEscrow` was carried in `JOB_ESCROW` once on the
strength of being a real, verified, USDT-settling escrow, and it implements none
of ERC-8183 (P-18). So a green run here is what *permits* an entry; it does not
create one, and the entry names what was read.
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

from misquote.registry.erc8004 import IDENTITY_REGISTRY

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

#: Read out of `@altananetwork/sdk@0.8.0`'s `dist/erc8183.js`, verbatim.
#: **Candidates to verify, not facts to trust** — the same words
#: `verify_addresses.py` puts over its own table.
CANDIDATES: dict[int, dict[str, str]] = {
    56: {
        "commerce": "0xEa4DAa3100A767e86FDed867729ae7446476EBA6",
        "router": "0x51895229E12F9876011789B04f8698af06cCD6DA",
        "policy": "0x9C01845705b3078Aa2e8cfF7520a6376FD766dE5",
        "registry": "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
        "paymentToken": "0xcE24439F2D9C6a2289F741120FE202248B666666",
    },
    97: {
        "commerce": "0xa206c0517B6371C6638CD9e4a42Cc9f02A33B0DE",
        "router": "0xD7d36D66d2F1B608A0F943f722D27e3744f66F25",
        "policy": "0x4F4678D4439feC812Ac7674Bb3Efb4C8f5Fb78A6",
        "registry": "0x8004A818BFB912233c491871b3d84c89A494BD9e",
        "paymentToken": "0xc70B8741B8B07A6d61E54fd4B20f22Fa648E5565",
    },
}

_RETURNS: dict[str, str] = {
    "jobCounter": "uint256",
    "paymentToken": "address",
    "disputeWindow": "uint64",
    "symbol": "string",
    "decimals": "uint8",
}

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"


class Report:
    def __init__(self, chain_id: int) -> None:
        self.chain_id = chain_id
        self.checks: list[dict[str, str]] = []

    def add(self, name: str, status: str, detail: str, provenance: str = "P-24") -> None:
        # `provenance` matches the shape `vetting/addresses.py` and
        # `vetting/venus.py` emit. Without it these checks published a blank
        # column in any renderer that shows where a finding came from — and the
        # whole point of these particular readings is that they overturned a
        # published claim, so the citation is the most load-bearing field.
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
            "chain_id": self.chain_id,
            # Present because every sibling record carries it, and the shared
            # renderer branches on it: a block without `surveyed` renders as a
            # refusal, which would have shown "not surveyed" over eleven passing
            # checks.
            "surveyed": True,
            "reason": "",
            "verdict": self.verdict,
            "source": "@altananetwork/sdk@0.8.0 ERC8183_ADDRESSES",
            "checks": self.checks,
            "summary": {
                "checked": len(self.checks),
                "failed": sum(1 for c in self.checks if c["status"] == FAIL),
                "unknown": sum(1 for c in self.checks if c["status"] == UNKNOWN),
            },
        }


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


def call(w3: Web3, address: str, signature: str) -> Any:
    name = signature.split("(")[0]
    raw = w3.eth.call(
        {"to": Web3.to_checksum_address(address), "data": Web3.keccak(text=signature)[:4]}
    )
    if not raw:
        raise ValueError(f"{name}() returned zero bytes — the function is not implemented here")
    kind = _RETURNS[name]
    if kind in ("string", "bytes"):
        return decode([kind], raw)[0]
    return decode([kind], raw[:32])[0]


def survey(w3: Web3, chain_id: int) -> Report:
    report = Report(chain_id)
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
    def answers(role: str, signature: str) -> Any | None:
        try:
            value = call(w3, table[role], signature)
        except Exception as error:  # noqa: BLE001
            report.add(
                f"{role}.{signature} answers",
                FAIL,
                f"reverted or returned nothing: {type(error).__name__}",
            )
            return None
        report.add(f"{role}.{signature} answers", PASS, f"returns {value}")
        return value

    counter = answers("commerce", "jobCounter()")
    token = answers("commerce", "paymentToken()")
    answers("policy", "disputeWindow()")

    # 3. The answers agree with each other, and with what we already verified.
    ours = IDENTITY_REGISTRY.get(chain_id, "")
    report.add(
        "registry agrees with erc8004.py",
        PASS if table["registry"].lower() == ours.lower() else FAIL,
        f"SDK says {table['registry']}, we verified {ours}",
    )

    if token is not None:
        report.add(
            "kernel names the table's payment token",
            PASS if str(token).lower() == table["paymentToken"].lower() else FAIL,
            f"kernel returns {token}, table says {table['paymentToken']}",
        )

    if counter is not None:
        # Not a pass/fail — a reading. A kernel with no jobs is a real kernel
        # that nobody has used, and saying so is more useful than a verdict.
        report.add(
            "jobs created on this deployment",
            PASS if int(counter) >= 0 else FAIL,
            f"jobCounter() is {int(counter):,}"
            + ("" if int(counter) else " — deployed, and nobody has used it"),
        )

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chain", type=int, default=56, choices=(56, 97))
    ap.add_argument(
        "--out", nargs="?", const=str(RECORD_DIR / "erc8183-{chain}.json"), help="record the survey"
    )
    args = ap.parse_args()

    w3 = connect(args.chain)
    print(f"\nERC-8183 candidates, chain {args.chain}\n")
    report = survey(w3, args.chain)
    print(f"\nverdict  {report.verdict}")

    if args.out:
        out = Path(args.out.replace("{chain}", str(args.chain)))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
        print(f"recorded -> {out}")

    if report.verdict != PASS:
        print(
            "\nJOB_ESCROW stays empty. A passing verify() is necessary and not "
            "sufficient (registry/aacp.py), and this did not even pass."
        )
        return 1
    print(
        "\nEvery check passed. That permits an entry in JOB_ESCROW; it does not "
        "create one. The entry names what was read."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
