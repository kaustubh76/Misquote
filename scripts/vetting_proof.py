"""Run a badge's proof-of-concepts against a forked chain.

    uv run python scripts/vetting_proof.py --pool 0x36696169...
    make vet-prove

## What this closes

`Readme.md` §1: *"findings ship a PoC that executes on a mainnet fork — they
flag, we prove."* The flagging half has been built since Step 12. The proving
half was a ledger entry whose evidence was `vetting/forge/script/ — no
Badge.s.sol`, and whose stated premise was wrong in a way worth recording: the
ledger called `vetting/forge` a **fork lab**, and `scripts/gen_vectors.py`'s own
docstring says *"No fork and no RPC: this is pure math"*.

The forking machinery lived in pytest (`tests/chain/conftest.py`, `anvil
--fork-url`) and had never met foundry. This is the join.

## It proves the published finding, not a fresh one

The inputs come from `vetting/badges/<pool>.json` — the badge that was
*published* — rather than from a new chain read. A proof that re-read the pool
would be a second badge wearing a fork's clothes: it could pass while the
published finding was wrong, which is the one outcome that would make this worse
than nothing.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from misquote.vetting import proof as vp

RUN_DIR = vp.RUN_DIR


def _free_port() -> int:
    with contextlib.closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Anvil:
    """A forked chain for the length of one proof.

    The same invocation `tests/chain/conftest.py` uses, deliberately: one way of
    forking in this repository, so a proof and a test cannot disagree about what
    "a fork" means.
    """

    def __init__(self, url: str, block: int | None) -> None:
        self.url = url
        self.block = block
        self.port = _free_port()
        self.proc: subprocess.Popen | None = None

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> Anvil:
        cmd = ["anvil", "--fork-url", self.url, "--port", str(self.port), "--silent"]
        if self.block:
            cmd += ["--fork-block-number", str(self.block)]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with contextlib.closing(socket.create_connection(("127.0.0.1", self.port), 1)):
                    return self
            except OSError:
                time.sleep(0.2)
        self.__exit__(None, None, None)
        raise vp.ForgeMissing("anvil did not come up within 60s")

    def __exit__(self, *_exc: object) -> None:
        if self.proc is not None:
            self.proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(timeout=10)


#: anvil's first account, which every fork in this repository uses. It is a
#: published test key and is only ever pointed at a local fork.
ANVIL_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

#: Binance 8, the same address `tests/chain/conftest.py` impersonates for USDT.
#: One whale across the repository, so a fork and a test cannot disagree about
#: where testnet dollars come from.
USDT_WHALE = "0xF977814e90dA44bFA03b6295A0616a897441aceC"


#: How much of each token to hand the prover for the mint.
#:
#: Generous on purpose. The claim under test is "the pool accepts a range", not
#: "this size is optimal", and a mint that fails for want of one wei would be
#: recorded as the finding being false. Assumption A1's 1%-of-pool ceiling governs
#: what the *agent* may hold; it does not govern a fork.
MINT_AMOUNT = 5 * 10**18

#: Gas for the mint prover. See `record`: an estimate here measures the caught
#: path and starves the very call under test.
MINT_GAS = 1_500_000


def published_bounds(readings: dict) -> tuple[int, int] | None:
    """The tick bounds **the badge published**, parsed from its own detail line.

    `"w_min=40, [-65380, -65300]"`. Two provers need these now, and they must be
    the same two numbers: re-deriving them here would prove something about a
    range this repository never published, which is a different claim and a
    weaker one.
    """
    detail = (readings.get("mintable-range") or {}).get("detail", "")
    inside = detail[detail.find("[") + 1 : detail.find("]")]
    try:
        lower, upper = (int(part.strip()) for part in inside.split(","))
    except ValueError:
        return None
    return lower, upper


def fund(w3, target: str, pool_meta: dict) -> dict[str, int]:
    """Put both of the pool's tokens on `target`, on the fork.

    Two strategies, and the mix is deliberate — it is exactly what
    `tests/chain/conftest.py` does, for the reason stated there: neither depends
    on the pool's own balance, which the mint is about to trade against.

    - **WBNB by wrapping.** `deposit()` with value, from an account anvil funded.
    - **USDT by impersonation.** `anvil_impersonateAccount` on a whale and a
      plain `transfer`. There is no ERC-20 `deal` here: forge-std's `deal` is
      `stdStorage` on top of cheatcodes and is 0.8-only, and hand-locating a
      `balanceOf` slot silently deals zero when the slot is wrong.
    """
    from web3 import Web3

    funding_abi = json.loads(
        '[{"name":"transfer","type":"function","stateMutability":"nonpayable",'
        '"inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],'
        '"outputs":[{"type":"bool"}]},'
        '{"name":"deposit","type":"function","stateMutability":"payable","inputs":[],"outputs":[]},'
        '{"name":"balanceOf","type":"function","stateMutability":"view",'
        '"inputs":[{"name":"a","type":"address"}],"outputs":[{"type":"uint256"}]}]'
    )
    account = w3.eth.account.from_key(ANVIL_KEY)
    target = Web3.to_checksum_address(target)
    w3.provider.make_request("anvil_setBalance", [account.address, hex(20_000 * 10**18)])

    wbnb = Web3.to_checksum_address(pool_meta["wbnb"])
    usdt = Web3.to_checksum_address(pool_meta["usdt"])
    whale = Web3.to_checksum_address(pool_meta["whale"])

    def send(call, sender, **kwargs):
        tx = call.build_transaction(
            {"from": sender, "nonce": w3.eth.get_transaction_count(sender), **kwargs}
        )
        signed = account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        return w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(raw), timeout=120)

    # WBNB: wrap, then move it to the prover.
    token = w3.eth.contract(address=wbnb, abi=funding_abi)
    send(token.functions.deposit(), account.address, value=MINT_AMOUNT * 2)
    send(token.functions.transfer(target, MINT_AMOUNT), account.address)

    # USDT: impersonate the whale. Unsigned `eth_sendTransaction`, which anvil
    # accepts for an impersonated account precisely because we hold no key.
    w3.provider.make_request("anvil_impersonateAccount", [whale])
    w3.provider.make_request("anvil_setBalance", [whale, hex(10**18)])
    usdt_contract = w3.eth.contract(address=usdt, abi=funding_abi)
    tx_hash = usdt_contract.functions.transfer(target, MINT_AMOUNT).transact({"from": whale})
    w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    w3.provider.make_request("anvil_stopImpersonatingAccount", [whale])

    return {
        "wbnb": int(
            w3.eth.contract(address=wbnb, abi=funding_abi).functions.balanceOf(target).call()
        ),
        "usdt": int(usdt_contract.functions.balanceOf(target).call()),
    }


def deploy_and_prove(endpoint: str, badge: dict[str, Any]) -> list[vp.Proof]:
    """Deploy `BadgeProof` on the fork and run every provable check."""
    from web3 import Web3
    from web3.middleware import ExtraDataToPOAMiddleware

    artifact = vp.FORGE_DIR / "out" / "Badge.s.sol" / "BadgeProof.json"
    if not artifact.is_file():
        raise vp.ForgeMissing(f"{artifact} is missing — `forge build` did not produce it")
    compiled = json.loads(artifact.read_text())

    w3 = Web3(Web3.HTTPProvider(endpoint, request_kwargs={"timeout": 60}))
    # BSC is proof-of-authority and its `extraData` is 280 bytes; anvil forwards
    # the forked header shape unchanged, so the fork needs the same middleware
    # every other BSC reader in this repository installs.
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    account = w3.eth.account.from_key(ANVIL_KEY)

    contract = w3.eth.contract(abi=compiled["abi"], bytecode=compiled["bytecode"]["object"])
    tx = contract.constructor().build_transaction(
        {"from": account.address, "nonce": w3.eth.get_transaction_count(account.address)}
    )
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(raw), timeout=120)
    prover = w3.eth.contract(address=receipt.contractAddress, abi=compiled["abi"])

    pool = Web3.to_checksum_address(badge["pool"])
    readings = {c["id"]: c for c in badge["checks"] if "id" in c}
    block = int(w3.eth.block_number)
    out: list[vp.Proof] = []

    def record(check_id: str, call, *, gas: int | None = None) -> None:
        """Send it, then read the event. A `call()` would prove nothing: the
        whole claim is that this *executes*, and a view call is a reading.

        `gas` is explicit for anything wrapping a `try/catch`, and that is not a
        tuning knob — it is a correctness fix.

        `estimate_gas` measures the path the EVM actually takes, and for a
        `try/catch` around a failing inner call that is the **cheap, caught**
        path. Sending with that estimate gives the inner call 63/64 of almost
        nothing, so it runs out of gas, so the catch fires — and the failure is
        self-fulfilling and perfectly stable. It also reverts with **empty return
        data**, which is indistinguishable from a bare `revert()`, so the honest
        report is "no reason given" and the real reason is the estimate.
        """
        sent = call.build_transaction(
            {
                "from": account.address,
                "nonce": w3.eth.get_transaction_count(account.address),
                **({"gas": gas} if gas else {}),
            }
        )
        signed_call = account.sign_transaction(sent)
        raw_call = getattr(signed_call, "raw_transaction", None) or signed_call.rawTransaction
        rcpt = w3.eth.wait_for_transaction_receipt(
            w3.eth.send_raw_transaction(raw_call), timeout=120
        )
        events = prover.events.Proved().process_receipt(rcpt)
        held = bool(events and events[0]["args"]["held"])
        detail = events[0]["args"]["detail"] if events else "no event emitted"
        out.append(vp.Proof(check_id=check_id, held=held, detail=detail, block=block, pool=pool))
        print(f"  [{'ok  ' if held else 'FAIL'}] {check_id:<22} {detail}")

    if "factory" in readings:
        record("factory", prover.functions.proveFactory(pool))

    bounds = published_bounds(readings)

    if "tick-spacing" in readings:
        if bounds is None:
            print("  [ ?? ] tick-spacing           no bounds in the badge to prove")
        else:
            record("tick-spacing", prover.functions.proveTickSpacing(pool, *bounds))

    if "liquidity-depth" in readings:
        from misquote.vetting.badge import MIN_LIQUIDITY_FOR_EPS

        record("liquidity-depth", prover.functions.proveLiquidity(pool, MIN_LIQUIDITY_FOR_EPS))

    # Last, because it is the only one that changes state: it funds the prover
    # and sends a mint. Running it first would leave every reading after it taken
    # against a pool this script had just traded into.
    if "mintable-range" in readings:
        if bounds is None:
            print("  [ ?? ] mintable-range         no bounds in the badge to mint at")
        else:
            from misquote.chain.addresses import USDT_MAINNET, WBNB_MAINNET, deployment_for

            balances = fund(
                w3,
                prover.address,
                {"wbnb": WBNB_MAINNET, "usdt": USDT_MAINNET, "whale": USDT_WHALE},
            )
            print(
                f"  funded prover      {balances['usdt'] / 1e18:.1f} USDT, {balances['wbnb'] / 1e18:.1f} WBNB"
            )
            nfpm = deployment_for(badge["chain_id"]).position_manager
            record(
                "mintable-range",
                prover.functions.proveMintable(
                    Web3.to_checksum_address(nfpm), pool, *bounds, MINT_AMOUNT, MINT_AMOUNT
                ),
                # Measured: the same mint from an EOA estimates ~397k. The two
                # approvals and the try/catch frame sit on top. Generous, because
                # an under-estimate here does not fail loudly — it reports the
                # finding as false.
                gas=MINT_GAS,
            )

    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pool", required=True)
    ap.add_argument("--block", type=int, default=None, help="fork at a block, for reproducibility")
    ap.add_argument("--out", nargs="?", const=str(RUN_DIR / "proof-{pool}.json"))
    args = ap.parse_args(argv)

    badge = vp.badge_for(args.pool)
    cover = vp.coverage(badge)
    print(f"pool     {badge['pool']}  (chain {badge['chain_id']}, badge {badge['verdict']})")
    print(f"provable {len(cover['provable'])} of {cover['checks']}: {', '.join(cover['provable'])}")
    for check_id, why in cover["not_provable"].items():
        print(f"  not proven  {check_id:<22} {why[:96]}")

    url = os.environ.get("BSC_ARCHIVE_RPC_URL") or os.environ.get("BSC_RPC_URL")
    if not url:
        print(
            "\nno fork url — set BSC_ARCHIVE_RPC_URL or BSC_RPC_URL. The coverage "
            "above needed no chain; the proofs do."
        )
        return 1

    try:
        vp.build()
    except (vp.ForgeMissing, subprocess.CalledProcessError) as error:
        print(f"\nforge build failed: {error}")
        return 1

    print(f"\nforking {url.split('//')[-1][:40]}...")
    with Anvil(url, args.block) as anvil:
        proofs = deploy_and_prove(anvil.endpoint, badge)

    held = sum(1 for p in proofs if p.held)
    print(f"\n{held} of {len(proofs)} finding(s) held on the fork")

    if args.out:
        out = Path(args.out.replace("{pool}", badge["pool"].lower()))
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pool": badge["pool"],
            "chain_id": badge["chain_id"],
            "verdict": badge["verdict"],
            "coverage": cover,
            "proofs": [p.to_dict() for p in proofs],
        }
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"recorded -> {out}")

    return 0 if held == len(proofs) else 1


if __name__ == "__main__":
    sys.exit(main())
