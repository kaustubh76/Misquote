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

from misquote.registry.aacp import ERC8183_ACCESSORS, answering_accessors
from misquote.registry.aacp import verify as verify_termix
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
    def __init__(self, chain_id: int, block: int | None = None) -> None:
        self.chain_id = chain_id
        # What block the readings were taken at. Its siblings record one —
        # `56.json` and `venus-56.json` both carry `block` — and these two did
        # not, so a record justifying two mainnet escrow addresses could not be
        # dated by anything except the file's mtime. The evidence strings in
        # `registry/erc8183.py` carry "read 21 Aug 2026 at block 117,226,038" as
        # *prose*, which is a number nothing can re-derive or contradict.
        self.block = block
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
            "block": self.block,
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
    try:
        head = w3.eth.block_number
    except Exception:  # noqa: BLE001 — an undated record beats a run that dies dating it
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

    # Which accessors answer, driven by `aacp.ERC8183_ACCESSORS` rather than by a
    # spelling written down here. This script hardcoded `jobCounter()` while the
    # probe that gates `JOB_ESCROW` checked three *other* names — so the two
    # halves of one question disagreed about what the question was, and the
    # module's own docstring cited this script as the reason it had been widened.
    # One tuple, both readers.
    answered = answering_accessors(w3, table["commerce"])
    report.add(
        "kernel answers an ERC-8183 accessor",
        PASS if answered else FAIL,
        f"{', '.join(answered)} answers"
        + (
            f"; {', '.join(a for a in ERC8183_ACCESSORS if a not in answered)} revert"
            if len(answered) < len(ERC8183_ACCESSORS)
            else ""
        )
        if answered
        else f"all of {', '.join(ERC8183_ACCESSORS)} revert",
    )

    counter = answers("commerce", "jobCounter()")
    token = answers("commerce", "paymentToken()")
    answers("policy", "disputeWindow()")

    # 3. The answers agree with each other, and with what we already verified.
    ours = IDENTITY_REGISTRY.get(chain_id, "")
    report.add(
        "registry agrees with the ERC-8004 reader",
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


def contrast(w3: Web3, chain_id: int) -> dict[str, Any] | None:
    """The other contract, checked by the same probe, in the same run.

    `aacp.verify()` is that module's headline function and it had **no caller
    outside its own tests** — no script, no Makefile target, no API route. A
    verification nobody runs is a verification that rots, which is the same
    complaint this script exists to answer for the addresses above.

    Running both here is not tidiness. P-18 (TermiX's escrow implements none of
    ERC-8183) and P-24 (Altana's kernel implements it, with 56,632 jobs) are one
    finding pointed in two directions, and they were established months apart by
    code that never met. Printed together, the same probe produces both, and a
    reader can see that the negative is about a contract rather than about the
    standard.

    Returns None off mainnet: TermiX documents chains 56 and 8453 only, and
    `aacp` raises rather than defaulting for anything else.
    """
    from misquote.registry.aacp import NoDeployment

    try:
        evidence = verify_termix(w3, chain_id)
    except NoDeployment as error:
        print(f"\n  (no TermiX contrast on chain {chain_id}: {error})")
        return None

    print()
    print(evidence.render())
    print(
        "\n  Expected. P-18 is the finding that this escrow is order-keyed, not\n"
        "  job-keyed, so `verify()` refusing it is the gate working rather than\n"
        "  a failure. It is recorded here, beside a kernel that does implement\n"
        "  the standard, so neither reading can be mistaken for the other."
    )
    return {
        "subject": "TermiX TermixEscrow_USDT (P-18)",
        "verified": evidence.ok,
        "expected_verified": False,
        "checks": [
            {"name": name, "status": PASS if ok else FAIL, "detail": detail}
            for name, ok, detail in evidence.checks
        ],
    }


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

    termix = contrast(w3, args.chain)

    if args.out:
        out = Path(args.out.replace("{chain}", str(args.chain)))
        out.parent.mkdir(parents=True, exist_ok=True)
        record = report.to_dict()
        # Kept beside the survey rather than inside its `checks`: the verdict is
        # about the Altana deployment, and a failing-by-design contrast folded
        # into the same list would drag it to FAIL and read as this script
        # refusing the addresses it just verified.
        if termix is not None:
            record["termix_contrast"] = termix
        out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
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
