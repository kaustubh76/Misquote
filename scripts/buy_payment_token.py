"""Buy the ERC-8183 deployment's payment token, so a job can be funded.

## Why this exists

The ledger recorded the escrow as not built because *"the payment token is
owner-minted with no faucet, so no wallet here can hold any"*. The first half is
true. The conclusion is not: the token has deep PancakeSwap liquidity — about
11M of it in one v3 pool against USDT, trading within a twentieth of a percent
of a dollar — so any wallet can hold it for the price of a swap.

`scripts/prove_escrow_fund.py` proved the flow on a fork by impersonating the
token's owner. That is the right move for a proof and not available to a real
wallet. This is what a real wallet does instead, and it is the last thing
between "settles on a fork" and "settled on mainnet".

## Why v2, and why a minimum

**v2 rather than v3**: BNB goes in directly with no wrapping step and no
fee-tier argument to get wrong. The v2 pair holds 81,162 tokens, so the sums
this script is for move nothing.

**`amountOutMin` is never zero.** A zero minimum accepts any price the mempool
cares to give, which on BSC means a sandwich. It is computed from a live
`getAmountsOut` less an explicit slippage bound, and the quote is printed before
anything is sent — a swap nobody priced is not cheaper, it is unpriced.

This is deliberately not a trading surface. One direction, one pair, one
purpose: acquire enough of one token to fund one job.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from web3 import Web3

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))

from misquote.chain.signer import BscSigner  # noqa: E402
from misquote.registry.erc8183 import PAYMENT_TOKEN  # noqa: E402

#: PancakeSwap v2. Checked to have code before use — a router address typed from
#: a docs page is exactly the class of thing `erc8183.py` refuses to trust.
ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"

ROUTER_ABI = json.loads(
    '[{"name":"getAmountsOut","type":"function","stateMutability":"view",'
    '"inputs":[{"type":"uint256"},{"type":"address[]"}],'
    '"outputs":[{"type":"uint256[]"}]},'
    '{"name":"swapExactETHForTokens","type":"function","stateMutability":"payable",'
    '"inputs":[{"type":"uint256"},{"type":"address[]"},{"type":"address"},'
    '{"type":"uint256"}],"outputs":[{"type":"uint256[]"}]}]'
)
ERC20_ABI = json.loads(
    '[{"name":"balanceOf","type":"function","stateMutability":"view",'
    '"inputs":[{"type":"address"}],"outputs":[{"type":"uint256"}]}]'
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bnb", type=float, default=0.0003, help="how much BNB to spend")
    ap.add_argument("--slippage", type=float, default=1.0, help="percent")
    ap.add_argument(
        "--rpc", default=os.environ.get("BSC_RPC_URL") or "https://bsc-dataseed.bnbchain.org"
    )
    args = ap.parse_args()

    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": 60}))
    if w3.eth.chain_id != 56:
        raise SystemExit(f"this buys on BSC mainnet; the RPC is chain {w3.eth.chain_id}")

    router_address = Web3.to_checksum_address(ROUTER)
    if len(w3.eth.get_code(router_address)) <= 2:
        raise SystemExit(f"no code at the router {ROUTER}; refusing to send BNB to it")

    token = Web3.to_checksum_address(PAYMENT_TOKEN[56])
    path = [Web3.to_checksum_address(WBNB), token]
    router = w3.eth.contract(address=router_address, abi=ROUTER_ABI)
    erc20 = w3.eth.contract(address=token, abi=ERC20_ABI)

    amount_in = int(args.bnb * 10**18)
    quoted = int(router.functions.getAmountsOut(amount_in, path).call()[-1])
    minimum = int(quoted * (1 - args.slippage / 100))

    signer = BscSigner(w3)
    held = int(erc20.functions.balanceOf(signer.address).call())
    gas_price = w3.eth.gas_price

    print(f"signer     {signer.address}")
    print(f"dry run    {signer.dry_run}")
    print(f"BNB        {w3.eth.get_balance(signer.address) / 1e18:.6f}")
    print(f"token      {held / 1e18:.6f} held now")
    print(f"spend      {args.bnb} BNB")
    print(f"quote      {quoted / 1e18:.6f} token")
    print(f"minimum    {minimum / 1e18:.6f} token  ({args.slippage}% slippage)")
    print(f"gas price  {gas_price / 1e9:.3f} gwei")

    call = router.functions.swapExactETHForTokens(
        minimum, path, signer.address, int(time.time()) + 600
    )
    # Estimated against the live router, not guessed. A swap whose gas is
    # unknown is a swap whose total cost is unknown.
    try:
        gas = w3.eth.estimate_gas(
            {
                "from": signer.address,
                "to": router_address,
                "value": amount_in,
                "data": call._encode_transaction_data(),
            }
        )
        print(f"gas        {gas:,} = {gas * gas_price / 1e18:.8f} BNB")
        print(f"TOTAL      {(amount_in + gas * gas_price) / 1e18:.8f} BNB")
    except Exception as error:  # noqa: BLE001 — an estimate that fails is a finding
        print(f"gas        estimate failed: {type(error).__name__}: {str(error)[:120]}")

    if signer.dry_run:
        print("\nMISQUOTE_DRY_RUN is set, so nothing was sent. That is the default.")
        print("Set MISQUOTE_DRY_RUN=0 to run it.")
        return 0

    sent = signer.send(signer.build(call, value=amount_in))
    now = int(erc20.functions.balanceOf(signer.address).call())
    print(f"\n  swap    {sent.tx_hash}")
    print(f"  token   {held / 1e18:.6f} -> {now / 1e18:.6f}  (+{(now - held) / 1e18:.6f})")
    if now <= held:
        raise SystemExit("the swap mined and the balance did not move — stopping")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
