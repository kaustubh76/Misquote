"""Differential-test the tick math against the real Solidity, and record vectors.

This is the check everything downstream rests on. Our Python must return the
*exact* integer the deployed libraries return — not a close one. A single wei of
disagreement in `getAmountsForLiquidity` becomes a mispriced position; a single
tick of disagreement in `getTickAtSqrtRatio` becomes a range on the wrong side of
the price; and a wrong `getFeeGrowthInside` becomes a fee number that is
confidently, plausibly false.

How it works: compile `vetting/forge/src/Exposer.sol` (which delegates to
upstream v3-core and v3-periphery at pinned commits), deploy it to a bare local
anvil, and ask it the same questions we ask ourselves. Every disagreement is a
failure; every agreement is written to `tests/core/vectors/*.json` so the offline
test suite can replay the same comparison with no chain at all.

No fork and no RPC: this is pure math, so the vectors are reproducible by anyone
with foundry installed and no network.

    uv run python scripts/gen_vectors.py            # fuzz + write vectors
    uv run python scripts/gen_vectors.py --check    # fuzz only, write nothing
    uv run python scripts/gen_vectors.py -n 20000   # more cases
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from web3 import Web3

REPO = Path(__file__).resolve().parents[1]
FORGE_DIR = REPO / "vetting" / "forge"
ARTIFACT = FORGE_DIR / "out" / "Exposer.sol" / "Exposer.json"
VECTOR_DIR = REPO / "tests" / "core" / "vectors"

MIN_TICK, MAX_TICK = -887272, 887272
MIN_SQRT_RATIO = 4295128739
MAX_SQRT_RATIO = 1461446703485210103287273052203988822378723970342
Q96 = 1 << 96
Q128 = 1 << 128
MASK256 = (1 << 256) - 1
UINT128_MAX = (1 << 128) - 1

# Anvil's first prefunded account.
DEPLOYER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"


# --- anvil -----------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Anvil:
    """A throwaway local chain. No fork, no network, no state worth keeping."""

    def __init__(self) -> None:
        self.port = _free_port()
        self.proc: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> Web3:
        if not shutil.which("anvil"):
            raise SystemExit("anvil not found — install foundry (https://getfoundry.sh)")
        self.proc = subprocess.Popen(
            ["anvil", "--port", str(self.port), "--silent", "--code-size-limit", "50000"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        w3 = Web3(
            Web3.HTTPProvider(f"http://127.0.0.1:{self.port}", request_kwargs={"timeout": 30})
        )
        for _ in range(100):
            try:
                if w3.is_connected():
                    return w3
            except Exception:
                pass
            time.sleep(0.1)
        raise SystemExit("anvil did not come up")

    def __exit__(self, *_exc: object) -> None:
        if self.proc is not None:
            self.proc.terminate()
            self.proc.wait(timeout=10)


def build_and_deploy(w3: Web3) -> Any:
    if not ARTIFACT.exists():
        print("building Exposer.sol ...")
        subprocess.run(["forge", "build"], cwd=FORGE_DIR, check=True)

    artifact = json.loads(ARTIFACT.read_text())
    abi = artifact["abi"]
    bytecode = artifact["bytecode"]["object"]

    acct = w3.eth.account.from_key(DEPLOYER_KEY)
    tx = (
        w3.eth.contract(abi=abi, bytecode=bytecode)
        .constructor()
        .build_transaction(
            {
                "from": acct.address,
                "nonce": w3.eth.get_transaction_count(acct.address),
                "gas": 10_000_000,
            }
        )
    )
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(raw))
    if receipt["status"] != 1:
        raise SystemExit("Exposer deployment reverted")
    return w3.eth.contract(address=receipt["contractAddress"], abi=abi)


# --- the comparison --------------------------------------------------------


def _encode(value: Any) -> Any:
    """JSON-safe encoding of a vector field.

    Integers become strings because uint256 values exceed what JSON numbers can
    carry losslessly. Booleans are checked *first*: `bool` subclasses `int` in
    Python, so the obvious ordering would serialise a rounding flag as the string
    "False" — which every reader then loads back as truthy.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    return value


class Differ:
    """Runs one comparison, records the vector, and remembers what disagreed."""

    def __init__(self) -> None:
        self.vectors: dict[str, list[dict[str, Any]]] = {}
        self.mismatches: list[str] = []
        self.compared = 0

    def check(self, group: str, args: dict[str, Any], ours: Any, theirs: Any) -> bool:
        self.compared += 1
        if ours != theirs:
            self.mismatches.append(f"{group}{args}: ours={ours} solidity={theirs}")
            return False
        self.vectors.setdefault(group, []).append(
            {
                **{k: _encode(v) for k, v in args.items()},
                "expected": [_encode(x) for x in theirs]
                if isinstance(theirs, list | tuple)
                else _encode(theirs),
            }
        )
        return True


def run(exposer: Any, n: int, seed: int) -> Differ:
    from misquote.core import fees, liquidity, tickmath

    rng = random.Random(seed)
    d = Differ()

    # --- constants agree ---------------------------------------------------
    d.check(
        "constants", {"name": "MIN_TICK"}, tickmath.MIN_TICK, exposer.functions.minTick().call()
    )
    d.check(
        "constants", {"name": "MAX_TICK"}, tickmath.MAX_TICK, exposer.functions.maxTick().call()
    )
    d.check(
        "constants",
        {"name": "MIN_SQRT_RATIO"},
        tickmath.MIN_SQRT_RATIO,
        exposer.functions.minSqrtRatio().call(),
    )
    d.check(
        "constants",
        {"name": "MAX_SQRT_RATIO"},
        tickmath.MAX_SQRT_RATIO,
        exposer.functions.maxSqrtRatio().call(),
    )

    # --- ticks -------------------------------------------------------------
    # Boundaries first: the interesting failures live at the edges, not in the
    # middle, and a uniform sample almost never lands on them.
    edge_ticks = [
        MIN_TICK,
        MIN_TICK + 1,
        MAX_TICK,
        MAX_TICK - 1,
        0,
        1,
        -1,
        -64183,
        -64180,
        -64190,  # the live pool and its usable neighbours
    ]
    ticks = edge_ticks + [rng.randint(MIN_TICK, MAX_TICK) for _ in range(n)]

    print(f"  tick -> sqrt ratio          ({len(ticks)} cases)")
    for tick in ticks:
        d.check(
            "get_sqrt_ratio_at_tick",
            {"tick": tick},
            tickmath.get_sqrt_ratio_at_tick(tick),
            exposer.functions.getSqrtRatioAtTick(tick).call(),
        )

    edge_ratios = [MIN_SQRT_RATIO, MIN_SQRT_RATIO + 1, MAX_SQRT_RATIO - 1, Q96]
    ratios = edge_ratios + [rng.randint(MIN_SQRT_RATIO, MAX_SQRT_RATIO - 1) for _ in range(n)]

    print(f"  sqrt ratio -> tick          ({len(ratios)} cases)")
    for ratio in ratios:
        d.check(
            "get_tick_at_sqrt_ratio",
            {"sqrt_price_x96": ratio},
            tickmath.get_tick_at_sqrt_ratio(ratio),
            exposer.functions.getTickAtSqrtRatio(ratio).call(),
        )

    # --- amounts -----------------------------------------------------------
    def sample_range() -> tuple[int, int, int]:
        """A range and a price, biased toward the boundary cases that break things."""
        lower = rng.randint(MIN_TICK + 1, MAX_TICK - 2)
        upper = min(lower + rng.choice([10, 40, 200, 1000, 20000, 400000]), MAX_TICK - 1)
        where = rng.choice(["below", "at_lower", "inside", "at_upper", "above"])
        if where == "below":
            price_tick = max(MIN_TICK, lower - rng.randint(1, 500))
        elif where == "at_lower":
            price_tick = lower
        elif where == "at_upper":
            price_tick = upper
        elif where == "above":
            price_tick = min(MAX_TICK - 1, upper + rng.randint(1, 500))
        else:
            price_tick = rng.randint(lower, upper)
        return lower, upper, price_tick

    cases = [sample_range() for _ in range(n)]
    liq_samples = [1, 2, 10**6, 10**12, 10**18, 10**24, UINT128_MAX]

    print(f"  amount deltas, both roundings ({len(cases)} cases)")
    for lower, upper, _ in cases:
        sa = tickmath.get_sqrt_ratio_at_tick(lower)
        sb = tickmath.get_sqrt_ratio_at_tick(upper)
        liq = rng.choice(liq_samples)
        for round_up in (True, False):
            d.check(
                "get_amount0_delta",
                {"sqrt_a": sa, "sqrt_b": sb, "liquidity": liq, "round_up": round_up},
                liquidity.get_amount0_delta(sa, sb, liq, round_up),
                exposer.functions.getAmount0Delta(sa, sb, liq, round_up).call(),
            )
            d.check(
                "get_amount1_delta",
                {"sqrt_a": sa, "sqrt_b": sb, "liquidity": liq, "round_up": round_up},
                liquidity.get_amount1_delta(sa, sb, liq, round_up),
                exposer.functions.getAmount1Delta(sa, sb, liq, round_up).call(),
            )

    print(f"  liquidity <-> amounts        ({len(cases)} cases)")
    for lower, upper, price_tick in cases:
        sa = tickmath.get_sqrt_ratio_at_tick(lower)
        sb = tickmath.get_sqrt_ratio_at_tick(upper)
        sp = tickmath.get_sqrt_ratio_at_tick(price_tick)
        liq = rng.choice(liq_samples[:-1])

        d.check(
            "get_amounts_for_liquidity",
            {"sqrt_price": sp, "sqrt_a": sa, "sqrt_b": sb, "liquidity": liq},
            list(liquidity.get_amounts_for_liquidity(sp, sa, sb, liq)),
            list(exposer.functions.getAmountsForLiquidity(sp, sa, sb, liq).call()),
        )

        amount0, amount1 = liquidity.get_amounts_for_liquidity(sp, sa, sb, liq)
        if (amount0 or amount1) and sa != sb:
            d.check(
                "get_liquidity_for_amounts",
                {
                    "sqrt_price": sp,
                    "sqrt_a": sa,
                    "sqrt_b": sb,
                    "amount0": amount0,
                    "amount1": amount1,
                },
                liquidity.get_liquidity_for_amounts(sp, sa, sb, amount0, amount1),
                exposer.functions.getLiquidityForAmounts(sp, sa, sb, amount0, amount1).call(),
            )

    # --- fee growth, including wrapped accumulators ------------------------
    #
    # The tick's `feeGrowthOutside` values live in storage, so each distinct pair
    # costs two transactions. The globals and the current tick are call
    # arguments and cost nothing, so one seeded pair is reused across many of
    # them — same coverage, a fraction of the chain traffic. Every value spans
    # the whole word, so the unchecked subtraction is exercised across its
    # wrapping range rather than only its comfortable middle.
    configs = max(1, n // 8)
    print(f"  fee growth inside            ({configs} tick states x 8 probes)")
    sender = exposer.w3.eth.accounts[0]  # type: ignore[attr-defined]
    seeded: set[tuple[int, int]] = set()

    for _ in range(configs):
        lower, upper, _ = sample_range()
        if (lower, upper) in seeded:
            continue
        seeded.add((lower, upper))

        lo0, lo1 = rng.randint(0, MASK256), rng.randint(0, MASK256)
        up0, up1 = rng.randint(0, MASK256), rng.randint(0, MASK256)

        # Wait for the receipt rather than just the hash. `transact` returns as
        # soon as the node accepts the transaction, so an immediate `call` can
        # read pre-transaction state and see a tick's fee growth as zero. That
        # race produces phantom mismatches — and, worse, could produce phantom
        # agreements — which is fatal in a test whose only job is to be exact.
        w3 = exposer.w3  # type: ignore[attr-defined]
        w3.eth.wait_for_transaction_receipt(
            exposer.functions.setTick(lower, lo0, lo1).transact({"from": sender})
        )
        receipt = w3.eth.wait_for_transaction_receipt(
            exposer.functions.setTick(upper, up0, up1).transact({"from": sender})
        )
        if receipt["status"] != 1:
            raise SystemExit(f"setTick reverted for ticks {lower}/{upper}")

        # Probe both sides of both boundaries, plus the interior, so every branch
        # of getFeeGrowthInside is taken for this state.
        probes = [
            max(MIN_TICK, lower - 1),
            lower,
            lower + 1,
            (lower + upper) // 2,
            upper - 1,
            upper,
            min(MAX_TICK, upper + 1),
            rng.randint(MIN_TICK, MAX_TICK),
        ]
        for price_tick in probes:
            g0, g1 = rng.randint(0, MASK256), rng.randint(0, MASK256)
            d.check(
                "fee_growth_inside",
                {
                    "global0": g0,
                    "global1": g1,
                    "lower_outside0": lo0,
                    "lower_outside1": lo1,
                    "upper_outside0": up0,
                    "upper_outside1": up1,
                    "tick_current": price_tick,
                    "tick_lower": lower,
                    "tick_upper": upper,
                },
                list(fees.fee_growth_inside(g0, g1, lo0, lo1, up0, up1, price_tick, lower, upper)),
                list(exposer.functions.getFeeGrowthInside(lower, upper, price_tick, g0, g1).call()),
            )

    print(f"  tokens owed (wrapping)       ({n} cases)")
    for i in range(n):
        # Wrapping has to be aimed at, not hoped for. A uniformly-drawn `last`
        # plus a realistic growth delta overflows with probability around
        # 1e-38, so half the cases start deliberately near the top of the word —
        # which is the only region where the unchecked subtraction differs from
        # a naive one, and therefore the only region worth testing.
        delta = rng.choice([0, 1, rng.randint(0, Q128), rng.randint(0, 10**30)])
        if i % 2 == 0 and delta > 0:
            last = MASK256 - rng.randint(0, min(delta, MASK256))
        else:
            last = rng.randint(0, MASK256)
        now = (last + delta) & MASK256
        liq = rng.choice([1, 10**12, 10**18, 10**24])
        ours = fees.tokens_owed(last, now, liq)
        if ours > UINT128_MAX:
            continue  # Solidity's uint128 cast would truncate; not a real position
        d.check(
            "tokens_owed",
            {"last": last, "now": now, "liquidity": liq},
            ours,
            exposer.functions.tokensOwed(last, now, liq).call(),
        )

    return d


#: Where `--check` leaves what it observed, beside the replay's own receipt.
DIFFERENTIAL_RECEIPT = REPO / "vetting" / "runs" / "vectors-differential.json"


def write_receipt(args: argparse.Namespace, differ: Differ) -> None:
    """Record what the differential actually compared, for `/vectors` to publish.

    ## Why this did not exist

    `vectors_report.py` hardcoded `differential: {"recorded": False}` under a
    comment reading "No differential receipt is written by anything yet", and
    the same file notes that `docs/FOR_JUDGES.md` row 1 *quotes the
    differential's headline*. So the claim that makes a fork comparison
    meaningful at all — this Python reproduces Uniswap's own libraries — was
    asserted in a document and refused on the page, while the run that would
    settle it printed its result and exited.

    ## What this receipt claims, and what it must not

    `--check` **fuzzes fresh cases against the deployed Solidity**. It does not
    replay `tests/core/vectors/`. Those are two different assurances and the
    stronger sentence — "the committed vectors were verified against Solidity" —
    belongs to `vectors_verify.py`, which watches a replay of exactly those
    files. Writing it here would be this project's own failure mode: a true
    claim about one thing, printed where a reader takes it for another.

    So `summary_line` says *fuzzed*, and `cases_covered` is
    `differ.compared` — the comparisons this run actually made — never the
    corpus's 19,546.

    ## The digests are still the corpus's

    Deliberately, and it is the same mechanism `read_receipt` applies to the
    replay: they record *what the corpus looked like when the two
    implementations were last shown to agree*. Regenerate the vectors and this
    receipt stops describing them, `corpus_matches` goes false at publish time,
    and the page says so. A receipt cannot vouch for itself.
    """
    from misquote.tearsheet import provenance, vectors

    corpus = vectors.corpus()
    ok = not differ.mismatches
    receipt = {
        "command": f"python scripts/gen_vectors.py -n {args.n} --seed {args.seed} --check",
        "exit_code": 0 if ok else 1,
        "outcome": "PASS" if ok else "FAIL",
        "cases_covered": differ.compared,
        "mismatches": len(differ.mismatches),
        "groups_compared": sorted(differ.vectors),
        "seed": args.seed,
        "cases_per_group": args.n,
        "summary_line": (
            f"{differ.compared:,} fresh cases fuzzed against the deployed Solidity "
            f"across {len(differ.vectors)} groups, {len(differ.mismatches)} mismatches"
        ),
        "digests": {g["group"]: g["sha256"] for g in corpus["groups"]},
        **provenance.build_stamp(
            f"python scripts/gen_vectors.py -n {args.n} --check",
            source="Uniswap v3 Solidity, redeployed to a local anvil",
        ),
    }

    DIFFERENTIAL_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    DIFFERENTIAL_RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"  -> {DIFFERENTIAL_RECEIPT.relative_to(REPO)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=3000, help="random cases per group")
    ap.add_argument("--seed", type=int, default=20260813)
    ap.add_argument("--check", action="store_true", help="compare only, do not write vectors")
    args = ap.parse_args()

    print(f"differential test against real v3 Solidity (seed {args.seed}, n {args.n})")
    with Anvil() as w3:
        exposer = build_and_deploy(w3)
        exposer.w3 = w3  # type: ignore[attr-defined]
        print(f"  Exposer deployed at {exposer.address}\n")
        d = run(exposer, args.n, args.seed)

    print(f"\n{d.compared:,} comparisons, {len(d.mismatches)} mismatches")

    # Before the mismatch branch, not after it. Written the other way round
    # first, and it had the asymmetry exactly backwards: a passing run recorded
    # itself and a failing one exited at `return 1` having recorded nothing, so
    # `/vectors` could show a green differential and never a red one. A page
    # that can only publish agreement is not evidence of agreement.
    if args.check:
        write_receipt(args, d)

    if d.mismatches:
        for line in d.mismatches[:20]:
            print(f"  {line}")
        if len(d.mismatches) > 20:
            print(f"  ... and {len(d.mismatches) - 20} more")
        return 1

    if args.check:
        print("--check: vectors not written")
        return 0

    VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    for group, rows in sorted(d.vectors.items()):
        path = VECTOR_DIR / f"{group}.json"
        path.write_text(
            json.dumps(
                {
                    "source": "Uniswap v3-core / v3-periphery, commits in ops/forge_deps.txt",
                    "generated_by": "scripts/gen_vectors.py",
                    "seed": args.seed,
                    "cases": rows,
                },
                indent=1,
            )
            + "\n"
        )
        print(f"  wrote {len(rows):6,} cases -> tests/core/vectors/{group}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
