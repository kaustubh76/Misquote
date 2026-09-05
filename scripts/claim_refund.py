#!/usr/bin/env python3
"""Recover the budget from a funded ERC-8183 job nobody settled.

Job 56681 holds 0.1 of the payment token on BSC mainnet. `submit` reverted and
`settle` reverted `NotDecided()`, so the money sits in the kernel with exactly
one way out: `claimRefund`, after `expiredAt`.

`expiredAt` is compared against `block.timestamp`, which is why this cannot be
hurried. `evm_increaseTime` is an anvil cheat code; BSC has no equivalent and
should not. So the same script does both jobs:

    --fork   rehearse it against a fork of mainnet at the current block, where
             the job is really there, really funded, and the clock can be moved
    (none)   broadcast it, once the real clock has passed expiredAt

One code path, so the rehearsal is not a different program from the broadcast.
The fork run also calls `claimRefund` *before* warping, because a guard that has
never been seen refusing is a guard nobody has tested.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))
sys.path.insert(0, str(REPO / "scripts"))

from misquote.chain.signer import BscSigner  # noqa: E402
from misquote.registry.erc8183 import contracts_for  # noqa: E402
from misquote.registry.hire import JobWriter, read_job  # noqa: E402
from vetting_proof import Anvil  # noqa: E402

CHAIN = 56
JOB_ID = 56681
RECORD = REPO / "vetting" / "identity" / "refund-56.json"

#: `getJob` returns a struct this repository reads as words. Word 7 is
#: `expiredAt` and word 8 the status — both confirmed against the funded job
#: rather than assumed from an ABI.
WORD_BUDGET, WORD_EXPIRES, WORD_STATUS = 6, 7, 8

#: The endpoints `hire_mainnet.py` confirms receipts across. `bsc-dataseed` is
#: load balanced and a mined transaction has looked like a timeout three times.
ENDPOINTS = (
    "https://bsc-dataseed.bnbchain.org",
    "https://bsc-dataseed1.defibit.io",
    "https://rpc.ankr.com/bsc",
)

ERC20_ABI = [
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "a", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    }
]


def _utc(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M UTC")


def job_state(w3, job_id: int) -> dict[str, Any]:
    """Budget, expiry and status, read from the chain rather than the record."""
    job = read_job(w3, CHAIN, job_id)
    words = job.words
    return {
        "exists": job.exists,
        "budget": int(words[WORD_BUDGET], 16),
        "expires_at": int(words[WORD_EXPIRES], 16),
        "status": int(words[WORD_STATUS], 16),
    }


def claim(
    w3,
    *,
    key: str,
    client: str,
    job_id: int,
    on_fork: bool,
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """The claim itself, identical on a fork and on mainnet.

    Only two things differ, and both are properties of the network rather than
    of the call: a fork lets the clock move, and a fork quotes exactly the 1
    gwei default that the gas ceiling exists to refuse.
    """
    addresses = contracts_for(CHAIN)
    token = w3.eth.contract(address=Web3.to_checksum_address(addresses["erc20"]), abi=ERC20_ABI)
    before = int(token.functions.balanceOf(client).call())
    state = job_state(w3, job_id)
    now = int(w3.eth.get_block("latest")["timestamp"])

    # On a fork: no kill file (there is nothing to stop) and no gas ceiling,
    # because anvil quotes exactly the 1 gwei default the ceiling exists to
    # refuse. On mainnet: the signer's own default kill file, the ceiling on,
    # and receipts confirmed across peers.
    extra: dict[str, Any] = (
        {"kill_file": REPO / "ops" / "NO_SUCH_KILL_FILE", "max_gas_price_wei": 0}
        if on_fork
        else {"peer_rpcs": ENDPOINTS[1:]}
    )
    writer = JobWriter(BscSigner(w3, key, **extra), CHAIN)

    def attempt(label: str) -> str | None:
        entry: dict[str, Any] = {"call": "claimRefund", "when": label}
        try:
            sent = writer.claim_refund(job_id)
        except Exception as error:  # noqa: BLE001 — a refusal is the finding
            entry.update(ok=False, error=f"{type(error).__name__}: {error}"[:300])
            steps.append(entry)
            return None
        entry.update(ok=True, tx=sent.tx_hash, gas_used=int(getattr(sent, "gas_used", 0)))
        steps.append(entry)
        return sent.tx_hash

    if on_fork:
        # A guard nobody has watched refuse is a guard nobody has tested.
        print("  before expiry ", end="", flush=True)
        print(
            "REFUSED (as it must)"
            if attempt("before expiry") is None
            else "MINED — the expiry does not hold"
        )
        ahead = state["expires_at"] - now + 60
        w3.provider.make_request("evm_increaseTime", [ahead])
        w3.provider.make_request("evm_mine", [])
        print(f"  clock      +{ahead / 3600:.1f}h -> past {_utc(state['expires_at'])}")

    print("  claimRefund  ", end="", flush=True)
    tx = attempt("after expiry")
    after = int(token.functions.balanceOf(client).call())
    recovered = after - before
    print(tx or "REFUSED")

    return {
        "job_id": job_id,
        "client": client,
        "budget": state["budget"],
        "expires_at": state["expires_at"],
        "expires_at_utc": _utc(state["expires_at"]),
        "status_before": state["status"],
        "status_after": job_state(w3, job_id)["status"],
        "balance_before": before,
        "balance_after": after,
        "recovered": recovered,
        "refunded": recovered == state["budget"],
        "transactions": steps,
        "gas_spent_wei": writer.gas_spent_wei,
    }


def rehearse(rpc: str, job_id: int = JOB_ID, *, key: str | None = None) -> dict[str, Any]:
    """The claim on a fork of mainnet at the current block, clock moved.

    The job is really there and really funded; only the timestamp is a fiction.
    Returns the same record shape the mainnet run writes, so a test cannot pass
    against a rehearsal and fail against the thing it rehearses.
    """
    key = (
        key
        or os.environ.get("MISQUOTE_OPERATOR_PRIVATE_KEY")
        or os.environ.get("MISQUOTE_PRIVATE_KEY")
    )
    if not key:
        return {"ran": False, "reason": "no key: export MISQUOTE_OPERATOR_PRIVATE_KEY"}
    client = Web3().eth.account.from_key(key).address
    steps: list[dict[str, Any]] = []

    with Anvil(rpc, None) as anvil:
        w3 = Web3(Web3.HTTPProvider(anvil.endpoint, request_kwargs={"timeout": 180}))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        for _ in range(60):
            try:
                if w3.is_connected() and w3.eth.block_number > 0:
                    break
            except Exception:  # noqa: BLE001 — still booting
                pass
            time.sleep(1)
        else:
            return {"ran": False, "reason": "anvil did not answer after boot"}
        print(f"fork of BSC mainnet at block {w3.eth.block_number:,}")
        print(f"client   {client}")
        # A fork signs as itself; `chain/operator.py` refuses a key that does
        # not match a declared wallet, which is right for mainnet and
        # meaningless here.
        previous = {
            n: os.environ.pop(n, None)
            for n in ("MISQUOTE_OPERATOR_ADDRESS", "MISQUOTE_SIGNER_ADDRESS")
        }
        os.environ["MISQUOTE_DRY_RUN"] = "0"
        w3.provider.make_request("anvil_setBalance", [client, hex(10**18)])
        try:
            out = claim(w3, key=key, client=client, job_id=job_id, on_fork=True, steps=steps)
        finally:
            os.environ["MISQUOTE_DRY_RUN"] = "1"
            for n, v in previous.items():
                if v is not None:
                    os.environ[n] = v
    out["network"] = "fork"
    out["ran"] = True
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fork", action="store_true", help="rehearse on a fork, moving the clock")
    ap.add_argument("--job", type=int, default=JOB_ID)
    ap.add_argument("--rpc", default=os.environ.get("BSC_RPC_URL") or ENDPOINTS[0])
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    key = os.environ.get("MISQUOTE_OPERATOR_PRIVATE_KEY") or os.environ.get("MISQUOTE_PRIVATE_KEY")
    if not key:
        print("no key: export MISQUOTE_OPERATOR_PRIVATE_KEY", file=sys.stderr)
        return 2
    client = Web3().eth.account.from_key(key).address

    steps: list[dict[str, Any]] = []
    if args.fork:
        out = rehearse(args.rpc, args.job, key=key)
        if not out.get("ran"):
            print(out.get("reason"), file=sys.stderr)
            return 1
    else:
        w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": 180}))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        state = job_state(w3, args.job)
        now = int(w3.eth.get_block("latest")["timestamp"])
        print(f"BSC mainnet, block {w3.eth.block_number:,}")
        print(f"client   {client}")
        print(f"expires  {_utc(state['expires_at'])}")
        if now < state["expires_at"]:
            left = state["expires_at"] - now
            print(f"\nnot yet: {left // 3600}h {left % 3600 // 60}m to go. Nothing broadcast.")
            return 3
        out = claim(w3, key=key, client=client, job_id=args.job, on_fork=False, steps=steps)
        out["network"] = "BSC mainnet"

    out["ran"] = True
    destination = args.out or (RECORD.with_name("refund-fork-56.json") if args.fork else RECORD)
    destination.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"\n  recovered {out['recovered'] / 1e18:g} token   refunded={out['refunded']}")
    print(f"  -> {destination}")
    return 0 if out["refunded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
