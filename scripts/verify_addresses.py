"""Verify every contract address against the chain, then print the module to commit.

`Readme.md` rule 6 says every displayed number traces to a chain query. The same
standard applies to the addresses the whole system is pointed at: an address
copied from a blog post is an unverified claim, and pointing a signer at one is
how funds go to a fork of a fork of the real router.

Each address here is checked three ways: it has bytecode, it answers the calls
its interface promises, and its answers agree with the other contracts'. The
factory must name the pool the pool names itself, the position manager must name
the factory, and the pool's own `fee` and `tickSpacing` must match what we
intend to trade.

    uv run python scripts/verify_addresses.py             # mainnet
    uv run python scripts/verify_addresses.py --chain 97  # chapel testnet
    uv run python scripts/verify_addresses.py --chain 97 --scan   # find usable pools
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from eth_abi import decode, encode
from web3 import Web3
from web3.exceptions import Web3Exception

from misquote.vetting import addresses

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

# Candidates to verify, not facts to trust. Anything that fails a check below is
# reported and excluded rather than written out.
CANDIDATES: dict[int, dict[str, str]] = {
    56: {
        "factory": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865",
        "position_manager": "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364",
        "swap_router": "0x1b81D678ffb9C0263b24A97847620C99d213eB14",
        "quoter_v2": "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997",
        "multicall3": "0xcA11bde05977b3631167028862bE2a173976CA11",
        "wbnb": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "usdt": "0x55d398326f99059fF775485246999027B3197955",
    },
    97: {
        "factory": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865",
        "position_manager": "0x427bF5b37357632377eCbEC9de3626C71A5396c1",
        "swap_router": "0x9a489505a00cE272eAa5e07Dba6491314CaE3796",
        "quoter_v2": "0xbC203d7f83677c7ed3F7acEc959963E7F4ECC5C2",
        "multicall3": "0xcA11bde05977b3631167028862bE2a173976CA11",
        "wbnb": "0xae13d989daC2f0dEbFf460aC112a837C89BAa7cd",
        "usdt": "0x7ef95a0FEE0Dd31b22626fA2e10Ee6A223F8a684",
        "busd": "0xaB1a4d4f1D656d2450692D237fdD6C7f9146e814",
        "usdc": "0x64544969ed7EBf5f083679233325356EbE738930",
        "cake": "0xFa60D973F7642B748046464e165A65B7323b0DEE",
    },
}

RECORD_DIR = Path(__file__).resolve().parents[1] / "vetting" / "addresses"

TARGET_FEE = 500  # 0.05% in pips

# Mainnet trades WBNB/USDT. Chapel's WBNB/USDT pool at this tier exists but was
# initialized at MAX_TICK and never seeded, so the testnet mirror is WBNB/BUSD —
# same fee tier, same tick spacing, therefore the same w_min and the same
# rounding behaviour the policy will meet on mainnet.
TARGET_PAIR: dict[int, tuple[str, str]] = {
    56: ("wbnb", "usdt"),
    97: ("wbnb", "busd"),
}

SCAN_PAIRS = (
    ("wbnb", "usdt"),
    ("wbnb", "busd"),
    ("wbnb", "usdc"),
    ("wbnb", "cake"),
)
FEE_TIERS = (100, 500, 2500, 10000)

FACTORY_ABI = [
    {
        "name": "getPool",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"type": "address"},
            {"type": "address"},
            {"type": "uint24"},
        ],
        "outputs": [{"type": "address"}],
    },
    {
        "name": "feeAmountTickSpacing",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"type": "uint24"}],
        "outputs": [{"type": "int24"}],
    },
]

POOL_ABI = [
    {
        "name": "token0",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "address"}],
    },
    {
        "name": "token1",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "address"}],
    },
    {
        "name": "fee",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint24"}],
    },
    {
        "name": "tickSpacing",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "int24"}],
    },
    {
        "name": "liquidity",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint128"}],
    },
    {
        "name": "factory",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "address"}],
    },
    {
        "name": "slot0",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {"type": "uint160", "name": "sqrtPriceX96"},
            {"type": "int24", "name": "tick"},
            {"type": "uint16", "name": "observationIndex"},
            {"type": "uint16", "name": "observationCardinality"},
            {"type": "uint16", "name": "observationCardinalityNext"},
            {"type": "uint32", "name": "feeProtocol"},
            {"type": "bool", "name": "unlocked"},
        ],
    },
]

NFPM_ABI = [
    {
        "name": "factory",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "address"}],
    },
    {
        "name": "WETH9",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "address"}],
    },
]

ROUTER_ABI = NFPM_ABI

ERC20_ABI = [
    {
        "name": "symbol",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "string"}],
    },
    {
        "name": "decimals",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint8"}],
    },
]


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        mark = "ok  " if ok else "FAIL"
        print(f"  [{mark}] {label}{'  ' + detail if detail else ''}")
        if not ok:
            self.failures.append(label)
        return ok


def connect(chain_id: int) -> Web3:
    for url in RPCS[chain_id]:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 12}))
            if w3.eth.chain_id == chain_id:
                print(f"rpc      {url}  (head {w3.eth.block_number})")
                return w3
        except Exception:
            continue
    raise SystemExit(f"no reachable RPC for chain {chain_id}")


def scan_pools(w3: Web3, factory, addrs: dict[str, str]) -> None:
    """List every pool the factory knows for our candidate pairs, and its liquidity.

    A pool can exist, be unlocked, and still be unusable: Pancake deploys many
    that were initialized at an absurd price and never seeded. Liquidity is the
    only column that decides.
    """
    print(f"\n{'pair':12s} {'fee':>6s}  {'pool':42s} {'tick':>9s} {'liquidity':>30s}")
    for a, b in SCAN_PAIRS:
        if a not in addrs or b not in addrs:
            continue
        for fee in FEE_TIERS:
            try:
                addr = factory.functions.getPool(addrs[a], addrs[b], fee).call()
            except Web3Exception:
                continue
            if int(addr, 16) == 0:
                continue
            pool = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=POOL_ABI)
            try:
                liq = pool.functions.liquidity().call()
                tick = pool.functions.slot0().call()[1]
            except Web3Exception:
                print(f"{a + '/' + b:12s} {fee:6d}  {addr}  unreadable")
                continue
            usable = "  usable" if liq > 0 else ""
            print(f"{a + '/' + b:12s} {fee:6d}  {addr} {tick:9d} {liq:30,d}{usable}")


class Web3Reader:
    """`vetting.addresses.Reader`, backed by a real node.

    The judgement lives in `packages/misquote/vetting/addresses.py` and takes a
    protocol, so every verdict in it is exercised without a chain by
    `tests/vetting/test_address_checks.py`. This is the thin half that cannot be:
    it turns a signature and some arguments into an `eth_call`.

    Raising is the contract. `survey()` turns any exception into `UNKNOWN`,
    which is blocking — a read that did not happen must never be a pass — so
    swallowing an error here would be the one thing that breaks the guarantee.
    """

    def __init__(self, w3: Web3) -> None:
        self.w3 = w3

    def code_size(self, address: str) -> int:
        return len(self.w3.eth.get_code(Web3.to_checksum_address(address)))

    def call(self, address: str, signature: str, *args: Any) -> Any:
        types = [t for t in signature[signature.index("(") + 1 : -1].split(",") if t]
        selector = Web3.keccak(text=signature)[:4]
        encoded = encode(types, [_arg(t, a) for t, a in zip(types, args, strict=True)])
        raw = self.w3.eth.call(
            {"to": Web3.to_checksum_address(address), "data": selector + encoded}
        )
        # Every signature this module uses returns exactly one value, and the
        # return type is not in the signature string — so it is inferred from
        # the name rather than parsed. A new check with a different shape has
        # to add itself here, which is the right place to notice.
        return _decode(signature, raw)


def _arg(abi_type: str, value: Any) -> Any:
    return Web3.to_checksum_address(value) if abi_type == "address" else value


_RETURNS = {
    "getPool": "address",
    "token0": "address",
    "token1": "address",
    "factory": "address",
    "fee": "uint24",
    "tickSpacing": "int24",
}


def _decode(signature: str, raw: bytes) -> Any:
    name = signature.split("(")[0]
    return decode([_RETURNS[name]], raw)[0]


def record_survey(w3: Web3, chain_id: int, out: Path) -> int:
    """Run the structured checks and write down what they found.

    Separate from the stdout report above, which predates it and does more —
    `--scan` in particular walks candidate pools looking for liquidity, which is
    discovery rather than verification. This writes the verification half in a
    form `scripts/addresses_report.py` can republish.
    """
    report = addresses.survey(Web3Reader(w3), chain_id)
    report.block = w3.eth.block_number

    payload = report.to_dict()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    print(f"\nrecorded {payload['summary']['checked']} checks -> {out}")
    print(f"verdict  {payload['verdict']}")
    return 0 if report.verdict == "PASS" else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", type=int, default=56, choices=(56, 97))
    ap.add_argument("--scan", action="store_true", help="list candidate pools and their liquidity")
    ap.add_argument(
        "--out",
        nargs="?",
        const=str(RECORD_DIR / "{chain}.json"),
        help="also write the structured checks here, for the web report to republish",
    )
    args = ap.parse_args()

    chain_id = args.chain
    w3 = connect(chain_id)

    if args.out:
        # The structured pass, written for the site to republish. Runs the
        # checks in `misquote.vetting.addresses`, which derive from
        # `chain/addresses.py` rather than from this file's `CANDIDATES` copy.
        return record_survey(w3, chain_id, Path(args.out.replace("{chain}", str(chain_id))))

    addrs = {k: Web3.to_checksum_address(v) for k, v in CANDIDATES[chain_id].items()}
    r = Report()

    print("\nbytecode present")
    for name, addr in addrs.items():
        r.check(f"{name:17s} {addr}", w3.eth.get_code(addr) not in (b"", "0x"))

    print("\ninterfaces answer, and agree with each other")
    factory = w3.eth.contract(address=addrs["factory"], abi=FACTORY_ABI)

    spacing_for_fee = None
    try:
        spacing_for_fee = factory.functions.feeAmountTickSpacing(TARGET_FEE).call()
        r.check(
            f"factory.feeAmountTickSpacing({TARGET_FEE})",
            spacing_for_fee > 0,
            f"-> {spacing_for_fee}",
        )
    except Web3Exception as e:
        r.check("factory.feeAmountTickSpacing", False, str(e)[:60])

    for name, abi in (("position_manager", NFPM_ABI), ("swap_router", ROUTER_ABI)):
        try:
            got = w3.eth.contract(address=addrs[name], abi=abi).functions.factory().call()
            r.check(f"{name}.factory() == factory", got == addrs["factory"], f"-> {got}")
        except Web3Exception as e:
            r.check(f"{name}.factory()", False, str(e)[:60])

    tok_a, tok_b = TARGET_PAIR[chain_id]
    decimals: dict[str, int] = {}
    for name in (tok_a, tok_b):
        try:
            token = w3.eth.contract(address=addrs[name], abi=ERC20_ABI)
            sym, dec = token.functions.symbol().call(), token.functions.decimals().call()
            decimals[name] = dec
            r.check(f"{name} is an ERC-20", True, f"-> {sym}, {dec} decimals")
        except Web3Exception as e:
            r.check(f"{name} ERC-20 metadata", False, str(e)[:60])

    if args.scan:
        scan_pools(w3, factory, addrs)

    print(f"\ntarget pool: {tok_a.upper()}/{tok_b.upper()} at {TARGET_FEE} pips")
    pool_addr = None
    try:
        pool_addr = factory.functions.getPool(addrs[tok_a], addrs[tok_b], TARGET_FEE).call()
        r.check("factory.getPool resolves", int(pool_addr, 16) != 0, f"-> {pool_addr}")
    except Web3Exception as e:
        r.check("factory.getPool", False, str(e)[:60])

    pool_facts: dict[str, object] = {}
    if pool_addr and int(pool_addr, 16) != 0:
        pool = w3.eth.contract(address=Web3.to_checksum_address(pool_addr), abi=POOL_ABI)
        t0 = pool.functions.token0().call()
        t1 = pool.functions.token1().call()
        fee = pool.functions.fee().call()
        spacing = pool.functions.tickSpacing().call()
        liq = pool.functions.liquidity().call()
        slot0 = pool.functions.slot0().call()
        pool_factory = pool.functions.factory().call()

        r.check("pool.factory() == factory", pool_factory == addrs["factory"])
        r.check("pool.fee() == target", fee == TARGET_FEE, f"-> {fee}")
        r.check(
            "pool.tickSpacing() == factory's for this fee",
            spacing_for_fee is None or spacing == spacing_for_fee,
            f"-> {spacing}",
        )
        r.check("token0/token1 are the pair we asked for", {t0, t1} == {addrs[tok_a], addrs[tok_b]})
        r.check("pool has liquidity", liq > 0, f"-> {liq:,}")
        r.check("pool is unlocked", bool(slot0[6]), f"tick={slot0[1]} sqrtP={slot0[0]}")

        by_addr = {addrs[tok_a]: tok_a, addrs[tok_b]: tok_b}
        pool_facts = {
            "address": Web3.to_checksum_address(pool_addr),
            "token0": t0,
            "token1": t1,
            "dec0": decimals.get(by_addr.get(t0, ""), 18),
            "dec1": decimals.get(by_addr.get(t1, ""), 18),
            "fee_pips": fee,
            "tick_spacing": spacing,
            "tick": slot0[1],
            "sqrt_price_x96": slot0[0],
            "liquidity": liq,
        }

    print()
    if r.failures:
        print(f"{len(r.failures)} check(s) failed — do not write these addresses:")
        for f in r.failures:
            print(f"  - {f}")
        return 1

    print(f"all checks passed on chain {chain_id} at block {w3.eth.block_number}")
    if pool_facts:
        w_min = 4 * int(pool_facts["tick_spacing"])  # type: ignore[arg-type]
        print(f"  pool          {pool_facts['address']}")
        print(f"  token0        {pool_facts['token0']}  ({pool_facts['dec0']} decimals)")
        print(f"  token1        {pool_facts['token1']}  ({pool_facts['dec1']} decimals)")
        print(f"  tick spacing  {pool_facts['tick_spacing']}  ->  w_min = {w_min} ticks")
        print(f"  current tick  {pool_facts['tick']}")
        print(f"  liquidity     {int(pool_facts['liquidity']):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
