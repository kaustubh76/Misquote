"""Gather what the badge judges. The only part of vetting that needs a chain.

    uv run python -m misquote.vetting                    # both known pools
    uv run python -m misquote.vetting --pool 0x... --fee 500

Every read here is a single `eth_call` or `eth_getCode`, which is the cheap end
of what a free endpoint will serve — the thing they refuse is sustained
`eth_getLogs`, measured at roughly four requests in eleven seconds (D-9). A badge
for one pool is about a dozen calls and is comfortably inside that.

A failed read becomes `None`, and `badge.evaluate` turns `None` into `UNKNOWN`
rather than a pass. That is the whole reason the reader and the judgement are
separate files: a reader that quietly substituted a default would make the badge
certify a pool nobody had looked at.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from web3 import Web3
from web3.exceptions import Web3Exception

from misquote.chain.addresses import DEPLOYMENTS, EQUITY_POOL, POOLS
from misquote.vetting.badge import Badge, PoolReadings, evaluate

REPO = Path(__file__).resolve().parents[3]

RPCS: dict[int, tuple[str, ...]] = {
    56: (
        "https://bsc-rpc.publicnode.com",
        "https://bsc-dataseed.bnbchain.org",
        "https://bsc-dataseed1.defibit.io",
    ),
    97: (
        "https://bsc-testnet-rpc.publicnode.com",
        "https://data-seed-prebsc-1-s1.bnbchain.org:8545",
    ),
}

POOL_ABI = [
    {"name": n, "type": "function", "stateMutability": "view", "inputs": [], "outputs": o}
    for n, o in (
        (
            "slot0",
            [
                {"type": "uint160"},
                {"type": "int24"},
                {"type": "uint16"},
                {"type": "uint16"},
                {"type": "uint16"},
                {"type": "uint32"},
                {"type": "bool"},
            ],
        ),
        ("liquidity", [{"type": "uint128"}]),
        ("token0", [{"type": "address"}]),
        ("token1", [{"type": "address"}]),
        ("fee", [{"type": "uint24"}]),
        ("tickSpacing", [{"type": "int24"}]),
    )
]

ERC20_ABI = [
    {
        "name": "decimals",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint8"}],
    }
]

FACTORY_ABI = [
    {
        "name": "getPool",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint24"}],
        "outputs": [{"type": "address"}],
    }
]


def connect(chain_id: int) -> Web3 | None:
    for url in RPCS.get(chain_id, ()):
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 15}))
            if w3.eth.chain_id == chain_id:
                return w3
        except (Web3Exception, ValueError, OSError):
            continue
    return None


def _try(fn, default=None):
    """Read, or record that we could not. Never substitute a plausible value."""
    try:
        return fn()
    except (Web3Exception, ValueError, OverflowError, TypeError):
        return default


def recorded_for(address: str) -> dict[str, int] | None:
    """What `chain/addresses.py` claims about this pool, if it claims anything.

    Handed to the badge so it can compare the repo against the chain. The
    alternative — printing the chain and trusting the constants — is how a
    wrong `fee_protocol` survived being published.
    """
    for pool in (*POOLS.values(), EQUITY_POOL):
        if pool.address.lower() == address.lower():
            return {
                "fee_pips": pool.fee_pips,
                "tick_spacing": pool.tick_spacing,
                "fee_protocol": pool.fee_protocol,
                "dec0": pool.dec0,
                "dec1": pool.dec1,
            }
    return None


def read_pool(w3: Web3, address: str, chain_id: int, *, label: str = "") -> PoolReadings:
    """One pool, read as far as the endpoint will let us."""
    pool = w3.eth.contract(address=Web3.to_checksum_address(address), abi=POOL_ABI)

    slot0 = _try(lambda: pool.functions.slot0().call())
    token0 = _try(lambda: pool.functions.token0().call())
    token1 = _try(lambda: pool.functions.token1().call())
    fee = _try(lambda: pool.functions.fee().call())

    resolved = None
    deployment = DEPLOYMENTS.get(chain_id)
    if deployment is not None and token0 and token1 and fee is not None:
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(deployment.factory), abi=FACTORY_ABI
        )
        resolved = _try(lambda: factory.functions.getPool(token0, token1, fee).call())

    def decimals(token):
        if not token:
            return None
        contract = w3.eth.contract(address=Web3.to_checksum_address(token), abi=ERC20_ABI)
        return _try(lambda: contract.functions.decimals().call())

    def code_size(token):
        if not token:
            return None
        raw = _try(lambda: w3.eth.get_code(Web3.to_checksum_address(token)))
        return None if raw is None else len(raw)

    return PoolReadings(
        address=address,
        chain_id=chain_id,
        recorded=recorded_for(address),
        resolved_by_factory=resolved,
        fee_pips=fee,
        tick_spacing=_try(lambda: pool.functions.tickSpacing().call()),
        # Index **5**. Index 2 is observationIndex, and reading that is how P-8
        # came to claim a pool took no protocol fee at all. Pancake packs
        # feeProtocol as fee0 | (fee1 << 16), both uint16.
        fee_protocol=(slot0[5] & 0xFFFF) if slot0 else None,
        tick=slot0[1] if slot0 else None,
        sqrt_price_x96=slot0[0] if slot0 else None,
        liquidity=_try(lambda: pool.functions.liquidity().call()),
        token0=token0,
        token1=token1,
        dec0=decimals(token0),
        dec1=decimals(token1),
        token0_code_size=code_size(token0),
        token1_code_size=code_size(token1),
        label=label,
    )


def badge_for(w3: Web3, address: str, chain_id: int, *, label: str = "") -> Badge:
    return evaluate(read_pool(w3, address, chain_id, label=label))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", type=int, default=56, choices=(56, 97))
    parser.add_argument("--pool", help="one address instead of the known pools")
    parser.add_argument("--label", default="")
    parser.add_argument("--out", default=str(REPO / "vetting" / "badges"))
    args = parser.parse_args(argv)

    w3 = connect(args.chain)
    if w3 is None:
        print(f"  no reachable RPC for chain {args.chain}")
        return 1

    if args.pool:
        targets = [(args.pool, args.label or args.pool)]
    else:
        targets = [(p.address, p.label) for p in _known_pools(args.chain)]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    worst = "PASS"
    order = {"PASS": 0, "WARN": 1, "UNKNOWN": 2, "FAIL": 3}
    for address, label in targets:
        badge = badge_for(w3, address, args.chain, label=label)
        print(badge.render())
        print()
        path = out / f"{address.lower()}.json"
        path.write_text(json.dumps(badge.to_dict(), indent=2, sort_keys=True) + "\n")
        print(f"  -> {path.relative_to(REPO) if path.is_relative_to(REPO) else path}\n")
        if order[badge.verdict] > order[worst]:
            worst = badge.verdict

    print(f"  worst verdict across {len(targets)} pool(s): {worst}")
    return 0 if worst in ("PASS", "WARN") else 2


def _known_pools(chain_id: int):
    pools = [POOLS[chain_id]] if chain_id in POOLS else []
    if chain_id == EQUITY_POOL.chain_id:
        pools.append(EQUITY_POOL)
    return pools


if __name__ == "__main__":
    sys.exit(main())
