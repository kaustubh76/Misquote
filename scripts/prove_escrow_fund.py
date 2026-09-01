"""Fund an ERC-8183 job and settle it, on a fork, and record what happened.

## The blocker this closes

`tearsheet/ledger.py` recorded the ERC-8183 escrow as not built because *"the
payment token is owner-minted with no faucet, so no wallet here can hold any"*.
The first half is true and the conclusion does not follow: the token has deep
PancakeSwap liquidity, so any wallet can hold it for about a dollar a unit. That
is the altitude error this repository has now made four times. `registry/hire.py` has implemented `fund`
since it was written. Nothing has ever called it with a balance.

A fork supplies the balance. The token's `owner()` may mint; on a fork that
address is one `anvil_impersonateAccount` away, exactly as
`tests/chain/conftest.py` impersonates a USDT whale and `scripts/vetting_proof.py`
impersonates for a mint. So the seven-step flow can be driven to settlement
against the **real mainnet deployment** — the kernel with 56,632 jobs on it —
without inventing a contract or a balance sheet.

## What this does not prove

That we can escrow real money. We cannot: the token is unobtainable without its
owner, and that is a fact about the deployment rather than about this code. The
record this writes says `network: "fork"` in the shape every consumer must read,
and `escrowed_on_mainnet` stays false. Publishing a fork as a chain run is the
misquote this project is named after; the two records live in different files
for that reason — `hire-97.json` is chapel, mined, and does not escrow.

## Why mainnet rather than chapel

Chapel would be the softer target and `make hire` already runs there. The point
of a fork is that it costs nothing to aim at the contract that matters, and the
mainnet kernel is the one a reader would check.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))
# One way of forking in this repository — `Anvil`'s own docstring makes the rule,
# and importing it is how this stays true rather than becoming a third boot.
sys.path.insert(0, str(REPO / "scripts"))

from misquote.chain.signer import BscSigner  # noqa: E402
from misquote.registry.erc8183 import contracts_for  # noqa: E402
from misquote.registry.hire import JobWriter, read_job  # noqa: E402
from vetting_proof import ANVIL_KEY, Anvil  # noqa: E402

CHAIN = 56
RECORD = REPO / "vetting" / "identity" / "hire-fork-56.json"

#: anvil's second and third accounts. The flow needs three distinct roles —
#: `createJob` refuses a zero evaluator, and only the provider may submit — and
#: three published test keys is the honest way to have them on a fork.
PROVIDER_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
EVALUATOR_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"

#: What the owner mints to the client. Generous: the claim under test is "the
#: kernel accepts a funded job", not "this budget is right".
MINT = 10_000 * 10**18
BUDGET = 1_000 * 10**18

#: `mint` and `owner` are not in `ERC20_ABI` and must not be — the agent's token
#: surface is `approve`/`allowance`/`balanceOf`/`decimals` and widening it for a
#: fork would put a mint on the production path.
OWNER_ABI = json.loads(
    '[{"name":"owner","type":"function","stateMutability":"view","inputs":[],'
    '"outputs":[{"type":"address"}]},'
    '{"name":"mint","type":"function","stateMutability":"nonpayable",'
    '"inputs":[{"type":"address"},{"type":"uint256"}],"outputs":[]},'
    '{"name":"balanceOf","type":"function","stateMutability":"view",'
    '"inputs":[{"type":"address"}],"outputs":[{"type":"uint256"}]}]'
)

#: The OptimisticPolicy's window, read rather than assumed. `settle` before it
#: elapses is the case a fork can test and a live chain cannot wait for.
POLICY_ABI = json.loads(
    '[{"name":"disputeWindow","type":"function","stateMutability":"view",'
    '"inputs":[],"outputs":[{"type":"uint256"}]}]'
)


def _step(steps: list[dict[str, Any]], call: str, actor: str, fn) -> Any:
    """Run one call, record it either way, and keep going.

    Recording a revert rather than raising is the whole method here: the vetting
    prover found two silent failures precisely because it published `held:
    false` instead of crashing, and a flow that stops at the first revert cannot
    say which of the seven steps is the wall.
    """
    entry: dict[str, Any] = {"call": call, "actor": actor}
    started = time.monotonic()
    try:
        result = fn()
    except Exception as error:  # noqa: BLE001 — the failure is the finding
        entry.update(ok=False, error=f"{type(error).__name__}: {error}"[:400])
        steps.append(entry)
        return None
    entry["ok"] = True
    entry["seconds"] = round(time.monotonic() - started, 2)
    tx = result[1] if isinstance(result, tuple) else result
    if hasattr(tx, "tx_hash"):
        entry["tx"] = tx.tx_hash
        entry["gas_used"] = int(getattr(tx, "gas_used", 0)) or None
    steps.append(entry)
    return result


def run(fork_url: str, block: int | None) -> dict[str, Any]:
    addresses = contracts_for(CHAIN)
    steps: list[dict[str, Any]] = []

    with Anvil(fork_url, block) as anvil:
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

        forked_at = int(w3.eth.block_number)
        client = Web3().eth.account.from_key(ANVIL_KEY).address
        provider = Web3().eth.account.from_key(PROVIDER_KEY).address
        evaluator = Web3().eth.account.from_key(EVALUATOR_KEY).address
        for who in (client, provider, evaluator):
            w3.provider.make_request("anvil_setBalance", [who, hex(100 * 10**18)])

        token = w3.eth.contract(
            address=Web3.to_checksum_address(addresses["erc20"]), abi=OWNER_ABI
        )
        owner = Web3.to_checksum_address(token.functions.owner().call())

        # The blocker, and its whole cost on a fork.
        w3.provider.make_request("anvil_impersonateAccount", [owner])
        w3.provider.make_request("anvil_setBalance", [owner, hex(10**18)])
        _step(steps, "mint", "token owner", lambda: token.functions.mint(client, MINT).transact({"from": owner}))
        w3.provider.make_request("anvil_stopImpersonatingAccount", [owner])
        minted = int(token.functions.balanceOf(client).call())

        # This fixture broadcasts, on a fork, as anvil rather than as the
        # operator — the same clearing `tests/chain/conftest.py` does and for the
        # same reason: `chain/operator.py` refuses a key that does not sign for a
        # declared wallet, which is right for a real network and meaningless here.
        previous = {
            name: os.environ.pop(name, None)
            for name in ("MISQUOTE_OPERATOR_ADDRESS", "MISQUOTE_SIGNER_ADDRESS")
        }
        os.environ["MISQUOTE_DRY_RUN"] = "0"
        kill = REPO / "ops" / "NO_SUCH_KILL_FILE"
        try:
            # The gas ceiling is off, which `BscSigner` documents as a real
            # choice rather than an accident. It is the right one here: anvil
            # quotes exactly the 1 gwei default, and a ceiling exists to stop a
            # thin real wallet overpaying — a fork has neither a wallet nor a
            # price. Off here and nowhere else.
            def signer(key: str) -> BscSigner:
                return BscSigner(w3, key, kill_file=kill, max_gas_price_wei=0)

            writer = JobWriter(signer(ANVIL_KEY), CHAIN)
            by_provider = JobWriter(signer(PROVIDER_KEY), CHAIN)
            by_evaluator = JobWriter(signer(EVALUATOR_KEY), CHAIN)

            _step(steps, "approve", "client", lambda: writer.approve(BUDGET))
            created = _step(
                steps,
                "createJob",
                "client",
                lambda: writer.create_job(
                    provider=provider,
                    # The router, not a third wallet. `registerJob` reverts
                    # `RouterNotEvaluator()` for any other evaluator, so the
                    # address that settles and the address named as evaluator are
                    # the same one on this deployment. That is the finding this
                    # proof exists for — see `EVALUATOR_MUST_BE_THE_ROUTER`.
                    evaluator=addresses["router"],
                    expired_at=int(time.time()) + 30 * 24 * 3600,
                    description="Misquote fork proof: does the escrow accept a funded job",
                ),
            )
            job_id = created[0] if created else None

            escrowed = False
            settled = False
            window = None
            if job_id is not None:
                # setBudget before registerJob: `fund` reverts `ZeroBudget()`
                # without a budget and `PolicyNotSet()` without a registration,
                # so both precede it and neither substitutes for the other.
                _step(steps, "setBudget", "client", lambda: writer.set_budget(job_id, BUDGET))
                _step(
                    steps,
                    "registerJob",
                    "client",
                    lambda: writer.register_job(job_id, addresses["policy"]),
                )
                before = int(token.functions.balanceOf(client).call())
                _step(steps, "fund", "client", lambda: writer.fund(job_id, BUDGET))
                after = int(token.functions.balanceOf(client).call())
                escrowed = before - after == BUDGET

                _step(
                    steps,
                    "submit",
                    "provider",
                    lambda: by_provider.submit(job_id, Web3.keccak(text="deliverable")),
                )
                # Past the window the policy publishes, read rather than assumed.
                window = int(
                    w3.eth.contract(
                        address=Web3.to_checksum_address(addresses["policy"]), abi=POLICY_ABI
                    )
                    .functions.disputeWindow()
                    .call()
                )
                w3.provider.make_request("evm_increaseTime", [window + 60])
                w3.provider.make_request("evm_mine", [])
                paid_before = int(token.functions.balanceOf(provider).call())
                _step(steps, "settle", "client", lambda: writer.settle(job_id))
                settled = int(token.functions.balanceOf(provider).call()) > paid_before

            words = None
            if job_id is not None:
                try:
                    words = list(read_job(w3, CHAIN, job_id).words)
                except Exception:  # noqa: BLE001 — a read that fails is not the claim
                    words = None

            return {
                "ran": True,
                "network": "fork",
                "forked_from": "BSC mainnet",
                "chain_id": CHAIN,
                "forked_at_block": forked_at,
                "addresses": addresses,
                "token_owner": owner,
                "minted_to_client": minted,
                "budget": BUDGET,
                "client": client,
                "provider": provider,
                "evaluator": evaluator,
                "job_id": job_id,
                "job_words": words,
                "escrowed": escrowed,
                "settled": settled,
                "dispute_window_s": window,
                "transactions": steps,
                "gas_spent_wei": writer.gas_spent_wei
                + by_provider.gas_spent_wei
                + by_evaluator.gas_spent_wei,
                "escrowed_on_mainnet": False,
                "why_not_on_mainnet": (
                    "Nobody has decided to spend the money. The token is not out "
                    "of reach — it trades on PancakeSwap against USDT at about "
                    "0.9996 — so what is proven here is the flow, and what is "
                    "left is a funded wallet and the choice to use it."
                ),
                "success_criterion": (
                    "fund() moves the budget out of the client and settle() moves "
                    "it to the provider, against the mainnet deployment's own "
                    "bytecode at a forked block."
                ),
            }
        finally:
            os.environ["MISQUOTE_DRY_RUN"] = "1"
            for name, value in previous.items():
                if value is not None:
                    os.environ[name] = value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rpc", default=os.environ.get("BSC_ARCHIVE_RPC_URL") or "https://bsc-dataseed.bnbchain.org")
    ap.add_argument("--block", type=int, default=None)
    ap.add_argument("--out", type=Path, default=RECORD)
    args = ap.parse_args()

    import shutil

    if not shutil.which("anvil"):
        print("anvil not installed — nothing recorded", file=sys.stderr)
        return 2

    record = run(args.rpc, args.block)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")

    if record.get("ran"):
        print(f"  job          {record['job_id']}")
        print(f"  escrowed     {record['escrowed']}")
        print(f"  settled      {record['settled']}")
        for s in record["transactions"]:
            mark = "ok  " if s.get("ok") else "FAIL"
            print(f"  {mark} {s['call']:<12} {s.get('tx') or s.get('error','')[:90]}")
    else:
        print(f"  not run: {record.get('reason')}")
    print(f"  -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
