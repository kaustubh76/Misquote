"""Escrow an ERC-8183 job against the verified kernel, and read it back.

    uv run python scripts/hire_agent.py --chain 97                  # dry run
    MISQUOTE_DRY_RUN=0 uv run python scripts/hire_agent.py --chain 97 --out

## What this is

`erc8183.steps()` has priced this sequence since before there was an address to
send it to, and `Readme.md` §8's D1 checklist has carried *"ERC-8183 hire call
invoked from an external script successfully (no permissioning surprises)"* as an
open box for as long. This is the external script.

It is the sibling of `scripts/register_identity.py` and `scripts/grant_session_key.py`:
same `BscSigner`, same dry-run default, same JSON record of what was mined.

## The permissioning surprises, since the checklist asks

There were four, and none is in any ABI. `createJob` reverts with bare four-byte
selectors and no reason string, so each was found by varying one argument at a
time against the live kernel — see `hire.CREATE_JOB_ERRORS`:

- **The hook is mandatory.** `address(0)` — the natural way to say *no hook* —
  reverts `0x55c45de1`. The EvaluatorRouter is the only address observed to be
  accepted; the kernel itself, the OptimisticPolicy and an EOA all revert
  `0x1a5d3d5f`. The EIP treats the hook as an optional extension point.
- **`expiredAt` is an absolute timestamp**, not a duration (`0xf7a0748c`), and
  there is a ceiling on how far ahead it may be (`0xb40b2a0e`).
- **The evaluator may not be zero** (`0xd92e233d`), which the EIP does say.

## Why the budget is zero, and why that is disclosed rather than hidden

`fund()` pulls the budget through the deployment's payment token, and that token
is **owner-minted**: `mint(address,uint256)` reverts `Ownable: caller is not the
owner`, there is no faucet among its 59 selectors, and the signer's balance is 0.
It is not unobtainable, though — it trades on PancakeSwap, and
`scripts/prove_escrow_fund.py` drives the funded flow to settlement on a fork.
So the escrow half of this flow has not been exercised from here — which is a
fact about a balance, not about a price: the token trades on PancakeSwap.

What that means is stated on the record rather than glossed: this creates,
registers and budgets a real job on a real deployment, and **does not escrow
money**, because it cannot. A run that quietly used a zero budget and reported
"hire flow: complete" would be the misquote.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from misquote.chain.signer import BscSigner
from misquote.registry import hire
from misquote.registry.erc8183 import (
    client_transaction_count,
    contracts_for,
    recourse,
    render,
    steps,
    success_criterion,
)

RPCS: dict[int, tuple[str, ...]] = {
    56: ("https://bsc-rpc.publicnode.com", "https://bsc-dataseed.bnbchain.org"),
    97: (
        "https://bsc-testnet-rpc.publicnode.com",
        "https://data-seed-prebsc-1-s1.bnbchain.org:8545",
    ),
}
RECORD_DIR = Path(__file__).resolve().parents[1] / "vetting" / "identity"
EXPLORER = {56: "https://bscscan.com/tx/", 97: "https://testnet.bscscan.com/tx/"}

#: Spec §4.2 / gap item G-3. The job's success condition is the InRange% the
#: tearsheet already publishes, so the thing the agent is paid on and the thing
#: it is measured on cannot disagree. `success_criterion()` renders it and had no
#: caller outside a unit test until this one.
IN_RANGE_FLOOR = 0.70


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chain", type=int, default=97, choices=(56, 97))
    ap.add_argument("--days", type=float, default=7.0, help="how long the job stays open")
    ap.add_argument("--budget", type=int, default=0, help="budget in token base units")
    ap.add_argument(
        "--out", nargs="?", const=str(RECORD_DIR / "hire-{chain}.json"), help="record it"
    )
    args = ap.parse_args()

    w3 = connect(args.chain)
    signer = BscSigner(w3)
    writer = hire.JobWriter(signer, args.chain)
    addresses = contracts_for(args.chain)

    print(f"signer    {signer.address}")
    print(f"dry run   {signer.dry_run}")
    for role, address in addresses.items():
        print(f"{role:<10}{address}")
    # `erc8183.render()` — "the hire flow as a marketplace should show it" — had
    # **no caller anywhere in the repository**, and passed the dead-definition
    # scan only because `render` is a common attribute name elsewhere. This is
    # the surface it was written for.
    print()
    print(render())

    print(f"jobs      {writer.counter():,} on this deployment")
    print(f"balance   {writer.balance()} of the payment token")
    print(f"plan      {client_transaction_count()} client transactions of {len(steps())}")
    print(f"recourse  {', '.join(s.call for s in recourse())}")

    # The pre-flight drift check. `aacp.fetch_live_contracts` and `mismatches`
    # were written for exactly this moment and had no caller until now.
    drifted = hire.drift(args.chain)
    print(f"drift     {'none' if not drifted else drifted}")
    if drifted:
        print("\nRecorded addresses have moved. Stopping rather than guessing the new ones.")
        return 1

    if signer.dry_run:
        print(
            "\nMISQUOTE_DRY_RUN is set, so nothing was sent. That is the default and "
            "an unset variable cannot spend.\nSet MISQUOTE_DRY_RUN=0 to run it."
        )
        return 0

    record: dict[str, Any] = {
        "chain_id": args.chain,
        "client": signer.address,
        "addresses": addresses,
        "budget": args.budget,
        "escrowed": False,
        "success_criterion": success_criterion(IN_RANGE_FLOOR),
        "transactions": [],
    }

    def note(name: str, receipt) -> None:
        digest = receipt.tx_hash if receipt.tx_hash.startswith("0x") else "0x" + receipt.tx_hash
        record["transactions"].append(
            {
                "call": name,
                # `tx_hash`, not `tx`: `ours.funding.tx` is a different leaf in
                # the same artifact, and the field contract matches leaves by
                # name. Two same-named leaves make one of them invisible to it.
                "tx_hash": digest,
                "explorer": EXPLORER[args.chain] + digest,
                "gas_cost_wei": receipt.gas_cost_wei,
            }
        )
        print(f"  {name:<16} {digest}")

    expired_at = int(time.time() + args.days * 86400)

    # 1. approve — ERC-20, not ERC-8183. Sent even at a zero budget, because it
    #    is step one of the published sequence and skipping it would make this a
    #    demonstration of a different flow.
    note("approve", writer.approve(args.budget))

    # 2. createJob — the provider is an argument; there is no setProvider.
    job_id, receipt = writer.create_job(
        provider=signer.address,
        evaluator=signer.address,
        expired_at=expired_at,
        description=success_criterion(IN_RANGE_FLOOR),
        # None means the router, which is the only accepted hook here.
        hook=None,
    )
    note("createJob", receipt)
    record["job_id"] = job_id
    print(f"  job id           {job_id}")

    # A step that reverts is a reading, not a crash.
    #
    # The first version of this let the exception out, and the run died at
    # `registerJob` having already mined two transactions — leaving a real job on
    # chain and no record of it. A flow that cannot report where it stopped is
    # worse than one that stops.
    def attempt(name: str, send) -> bool:
        try:
            note(name, send())
            return True
        except Exception as error:  # noqa: BLE001 — the revert is the result
            selector = str(error).split("'")[1] if "'" in str(error) else str(error)[:60]
            known = hire.FLOW_ERRORS.get(selector) or hire.CREATE_JOB_ERRORS.get(selector)
            record["transactions"].append(
                {
                    "call": name,
                    "reverted": selector,
                    "meaning": known or "unresolved — the selector is recorded, not guessed",
                }
            )
            print(f"  {name:<16} REVERTED {selector}")
            if known:
                print(f"                   {known}")
            return False

    # 3. registerJob — on the router, not the kernel. A client sending all seven
    #    to one address reverts here for a different reason than this one does.
    attempt("registerJob", lambda: writer.register_job(job_id))

    # 4. setBudget
    attempt("setBudget", lambda: writer.set_budget(job_id, args.budget))

    # 5. fund — attempted whatever the budget, because the revert is the finding.
    if attempt("fund", lambda: writer.fund(job_id, args.budget)):
        record["escrowed"] = True
    else:
        record["not_escrowed_because"] = (
            "This signer holds none of the payment token, and nothing has been "
            "spent to change that: it is owner-minted with no faucet, but it "
            "**trades on PancakeSwap** against USDT at about 0.9996 — so the escrow "
            "is a purchase away rather than out of reach. `fund()` also refuses a "
            "zero budget outright (`ZeroBudget()`, `0xff97b861`). `createJob` and "
            "`setBudget` are real transactions on a real deployment; `fund` is not "
            "among them, and this field is why rather than an omission. The funded "
            "flow runs to settlement on a mainnet fork — see the fork proof below."
        )

    job = hire.read_job(w3, args.chain, job_id)
    record["job_words"] = list(job.words)
    record["job_exists"] = job.exists
    record["gas_spent_wei"] = writer.gas_spent_wei
    print(f"\n  getJob({job_id}) exists={job.exists}, {job.word_count} words")

    if args.out:
        out = Path(args.out.replace("{chain}", str(args.chain)))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(f"\nrecorded -> {out}")

    # Derived from what mined, not written down.
    #
    # The first version of this line read "created, registered and budgeted" —
    # while `registerJob` had reverted in the run above it. A closing summary
    # that names steps the run did not complete is the misquote, printed by the
    # script whose subject is not misquoting.
    mined = [sent["call"] for sent in record["transactions"] if "tx_hash" in sent]
    reverted = [sent["call"] for sent in record["transactions"] if "reverted" in sent]
    record["mined"] = mined
    record["reverted"] = reverted
    print(
        f"\nJob {job_id} on chain and read back.\n"
        f"  mined:    {', '.join(mined) or 'nothing'}\n"
        f"  reverted: {', '.join(reverted) or 'nothing'}\n"
        f"  escrowed: {record['escrowed']}\n"
        f"\nThe D1 checklist asked for this call invoked from an external script "
        f"with no\npermissioning surprises. There were "
        f"{len(hire.CREATE_JOB_ERRORS) + len(hire.FLOW_ERRORS)}, and they are in "
        f"hire.CREATE_JOB_ERRORS and\nhire.FLOW_ERRORS rather than in a paragraph."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
