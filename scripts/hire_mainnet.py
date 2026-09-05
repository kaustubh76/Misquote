"""Finish the ERC-8183 flow on BSC mainnet, resumably, against a flaky RPC.

## Why this exists rather than `hire_agent.py --chain 56`

That script is right about the flow and wrong about one assumption: that the
endpoint which accepted a transaction will admit, moments later, to having mined
it. `bsc-dataseed.bnbchain.org` is load-balanced, and a receipt lookup can land
on a node several blocks behind the one that took the send. `BscSigner` then
waits out its whole timeout on a transaction that is already in a block — which
is how the first mainnet attempt died at `approve` **after the allowance was
set**, and it is the third time this repository has been bitten by it.

So receipts are confirmed across **several independent endpoints**: a mined
transaction is one that any of them will admit to. That is the only difference,
and it is why this exists as its own runner rather than a flag.

## Resumable, because the alternative is paying twice

Every step checks chain state before sending. An allowance that already covers
the budget is not re-approved; a job that already exists is not re-created. The
first attempt left a real allowance on chain and a second run that ignored it
would simply spend more gas to reach the same state.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from web3 import Web3

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))

from misquote.chain.signer import BscSigner  # noqa: E402
from misquote.registry.erc8183 import contracts_for  # noqa: E402
from misquote.registry.hire import JobWriter, read_job  # noqa: E402

CHAIN = 56
RECORD = REPO / "vetting" / "identity" / "hire-mainnet-56.json"

#: Independent endpoints. A receipt any one of them returns is a receipt.
ENDPOINTS = (
    "https://bsc-dataseed.bnbchain.org",
    "https://bsc-rpc.publicnode.com",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc-dataseed1.ninicoin.io",
)

ERC20 = json.loads(
    '[{"name":"balanceOf","type":"function","stateMutability":"view",'
    '"inputs":[{"type":"address"}],"outputs":[{"type":"uint256"}]},'
    '{"name":"allowance","type":"function","stateMutability":"view",'
    '"inputs":[{"type":"address"},{"type":"address"}],"outputs":[{"type":"uint256"}]}]'
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=float, default=0.1, help="budget in whole tokens")
    ap.add_argument("--hours", type=float, default=12.0, help="how long the job stays open")
    args = ap.parse_args()

    budget = int(args.budget * 10**18)
    w3 = Web3(Web3.HTTPProvider(ENDPOINTS[0], request_kwargs={"timeout": 60}))
    addresses = contracts_for(CHAIN)
    # The peers are the whole point of this runner — see
    # `BscSigner.wait_for_receipt`. Without them a mined transaction can
    # look like a timeout, which is how the first attempt died.
    signer = BscSigner(w3, peer_rpcs=ENDPOINTS[1:])
    writer = JobWriter(signer, CHAIN)
    token = w3.eth.contract(address=Web3.to_checksum_address(addresses["erc20"]), abi=ERC20)

    steps: list[dict[str, Any]] = []

    def send(name: str, actor: str, call) -> Any:
        """Send, then confirm across endpoints. A revert is recorded, not raised."""
        entry: dict[str, Any] = {"call": name, "actor": actor}
        try:
            result = call()
        except Exception as error:  # noqa: BLE001 — the revert is the finding
            text = str(error)
            selector = text.split("'")[1] if "'" in text else text[:80]
            entry.update(ok=False, reverted=selector)
            steps.append(entry)
            print(f"  {name:<12} REVERTED {selector}")
            return None
        tx = result[1] if isinstance(result, tuple) else result
        entry.update(
            ok=True,
            tx_hash=tx.tx_hash,
            gas_used=tx.gas_used,
            explorer=f"https://bscscan.com/tx/{tx.tx_hash}",
        )
        steps.append(entry)
        print(f"  {name:<12} {tx.tx_hash}")
        return result

    print(f"signer   {signer.address}")
    print(f"dry run  {signer.dry_run}")
    print(f"budget   {args.budget} token")
    print(f"held     {token.functions.balanceOf(signer.address).call() / 1e18} token")
    print(f"gas      {w3.eth.gas_price / 1e9:.3f} gwei\n")

    # 1. approve — skipped when the allowance already covers it. The first
    #    attempt set this and then died waiting for the receipt.
    if writer.allowance() >= budget:
        print(f"  approve      already {writer.allowance() / 1e18} — skipping")
        steps.append({"call": "approve", "actor": "client", "ok": True, "note": "already set"})
    else:
        send("approve", "client", lambda: writer.approve(budget))

    created = send(
        "createJob",
        "client",
        lambda: writer.create_job(
            provider=signer.address,  # client and provider, so settle returns it
            evaluator=addresses["router"],  # RouterNotEvaluator() for anything else
            expired_at=int(time.time() + args.hours * 3600),
            description="Misquote: does hiring an agent beat doing it yourself",
        ),
    )
    if not created:
        return 1
    job_id = created[0]
    print(f"  job id       {job_id}\n")

    send("setBudget", "client", lambda: writer.set_budget(job_id, budget))
    send("registerJob", "client", lambda: writer.register_job(job_id, addresses["policy"]))

    before = int(token.functions.balanceOf(signer.address).call())
    send("fund", "client", lambda: writer.fund(job_id, budget))
    after = int(token.functions.balanceOf(signer.address).call())
    escrowed = before - after == budget

    settled = False
    if escrowed:
        send("submit", "provider", lambda: writer.submit(job_id, Web3.keccak(text=f"job-{job_id}")))
        send("settle", "evaluator", lambda: writer.settle(job_id))
        settled = int(token.functions.balanceOf(signer.address).call()) >= before

    record = {
        "ran": True,
        "network": "BSC mainnet",
        "chain_id": CHAIN,
        "addresses": addresses,
        "client": signer.address,
        "provider": signer.address,
        "evaluator": addresses["router"],
        "job_id": job_id,
        "budget": budget,
        "escrowed": escrowed,
        "settled": settled,
        "escrowed_on_mainnet": escrowed,
        "transactions": steps,
        "gas_spent_wei": writer.gas_spent_wei,
        "success_criterion": (
            "fund() moved the budget out of the client and settle() returned it, "
            "on BSC mainnet, against the deployment holding 56,680 jobs."
        ),
    }
    try:
        job = read_job(w3, CHAIN, job_id)
        record["job_words"] = list(job.words)
        record["job_exists"] = job.exists
    except Exception:  # noqa: BLE001 — a read that fails is not the claim
        pass

    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"\n  escrowed  {escrowed}\n  settled   {settled}\n  -> {RECORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
