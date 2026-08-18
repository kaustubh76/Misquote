"""Pool due diligence: nine checks, each one a defect this project actually hit.

`Readme.md` §1 promises that "every pool a listed agent touches gets a
due-diligence badge". This is that badge, and its design principle is narrow
enough to state in a sentence: **every check here exists because something went
wrong.**

That matters because the alternative — a plausible checklist assembled from what
sounds prudent — produces a badge that passes everything and catches nothing. Each
check below cites the matrix item that paid for it, and a reader can go and see
the arithmetic.

| Check | Paid for by |
|---|---|
| The factory resolves this address | **P-6** — Pancake deploys pools from a separate `PancakeV3PoolDeployer` with a different init-code hash, so Uniswap's `computeAddress` constants return **wrong addresses** that look perfectly well-formed. |
| `feeProtocol` was read, not assumed | **P-1, P-8** — 3400 on WBNB/USDT, **3200** on TSLAx/USDT. Same DEX, and no constant right for both. Hardcoding Uniswap's zero overstates LP earnings by 1.52× on one and 1.47× on the other. (This table said **0** for the equity pool for a long time. That was P-8's original reading, taken from `slot0[2]` — `observationIndex` — instead of `slot0[5]`. Index 2 happened to hold 0 there and 101 on the flagship: small plausible integers that neither reverted nor looked absurd, and 0 was the value that made the better story. `tests/chain/test_equity_pool.py` asserts 3200.) |
| Decimals were read, not assumed | BSC's USDT and USDC are **18** decimals, not the 6 they use on Ethereum. Assuming 6 misprices every position by twelve orders of magnitude. |
| Tick spacing matches the fee tier | **P-6** — 100→1, 500→10, 2500→50, 10000→200, and **no** 3000→60. A mismatch means the address is not the pool you think it is. |
| The pool is initialised and not pinned at an extreme | Chapel's own WBNB/USDT pool exists, was initialised at `MAX_TICK`, and never seeded: a real address, a real contract, zero liquidity, and a price at the top of the range. |
| A mintable range exists at `w_min` | **V-10** — `MIN_TICK % 10 == 2`, so clamping to the extreme yields ticks the pool *rejects*. The mint reverts, having cost gas. |
| Liquidity supports a position without being the pool | **A1** — a replayed position large enough to have moved the price it is replayed against is fiction, not a backtest. |
| Both tokens are contracts | An "ERC-20" with no code is an address someone typed. |

## It refuses rather than guesses

A check whose reading could not be obtained is `UNKNOWN`, never `PASS`. A badge
that silently downgrades a failed read to a pass is worse than no badge, because
it launders an absence of evidence into evidence of absence — which is the exact
move this project is named after.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PASS, WARN, FAIL, UNKNOWN = "PASS", "WARN", "FAIL", "UNKNOWN"

# Pancake's factory constructor, verified against the deployed bytecode (P-6).
# Note the absence of 3000 -> 60: Uniswap has that tier and Pancake does not, so
# a pool claiming it is not a Pancake v3 pool.
FEE_TIER_SPACING: dict[int, int] = {100: 1, 500: 10, 2500: 50, 10000: 200}

# v3's representable tick range. `MIN_TICK % 10 == 2`, which is why clamping a
# range to the extreme produces ticks the pool refuses (V-10).
MIN_TICK, MAX_TICK = -887272, 887272

# How close to the edge of the tick range counts as "pinned". A pool initialised
# at MAX_TICK and never seeded is a real contract at a real address that cannot
# be provided to, and chapel's WBNB/USDT is exactly that.
PINNED_TICKS_FROM_EDGE = 100

# Assumption A1's share, and the floor beneath which a position sized to it is
# dust. Below this the pool exists on paper.
MIN_LIQUIDITY_FOR_EPS = 10**15


@dataclass(frozen=True, slots=True)
class Check:
    """One finding, with the reading that produced it and where it came from."""

    name: str
    status: str
    detail: str
    provenance: str

    @property
    def blocking(self) -> bool:
        return self.status in (FAIL, UNKNOWN)


@dataclass(slots=True)
class Badge:
    """A pool's due diligence, as data rather than a picture."""

    pool: str
    chain_id: int
    label: str = ""
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str, provenance: str) -> None:
        self.checks.append(Check(name, status, detail, provenance))

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def unknowns(self) -> list[Check]:
        return [c for c in self.checks if c.status == UNKNOWN]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.status == WARN]

    @property
    def verdict(self) -> str:
        """`FAIL` beats `UNKNOWN` beats `WARN` beats `PASS`.

        An unknown is deliberately not a pass. The whole point of the badge is
        that "we could not check" and "we checked and it was fine" are different
        claims, and only one of them is evidence.
        """
        if self.failures:
            return FAIL
        if self.unknowns:
            return UNKNOWN
        if self.warnings:
            return WARN
        return PASS

    @property
    def safe_to_provide(self) -> bool:
        return self.verdict in (PASS, WARN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool": self.pool,
            "chain_id": self.chain_id,
            "label": self.label,
            "verdict": self.verdict,
            "safe_to_provide": self.safe_to_provide,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "detail": c.detail,
                    "provenance": c.provenance,
                }
                for c in self.checks
            ],
        }

    def render(self) -> str:
        lines = [f"  {self.label or self.pool}", f"  {self.pool}  (chain {self.chain_id})", ""]
        for c in self.checks:
            lines.append(f"  [{c.status:^7}] {c.name:<34} {c.detail}")
        lines += ["", f"  VERDICT: {self.verdict}"]
        if self.failures:
            lines.append("  Do not provide liquidity here.")
        elif self.unknowns:
            lines.append("  Not cleared: something could not be read, which is not the same")
            lines.append("  as something being fine.")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class PoolReadings:
    """Everything the badge needs, already read from chain.

    Separated from the reading so the judgement is pure and testable without a
    network: every check below is a function of these fields, and
    `vetting/read.py` is the only part that needs an endpoint. `None` means the
    read failed, and that is what produces `UNKNOWN` rather than a silent pass.
    """

    address: str
    chain_id: int
    # What `chain/addresses.py` claims about this pool, when it claims anything.
    # Supplied so the badge can compare the repo's constants against the chain
    # rather than merely reporting the chain and trusting the constants.
    recorded: dict[str, int] | None = None
    resolved_by_factory: str | None = None
    fee_pips: int | None = None
    tick_spacing: int | None = None
    fee_protocol: int | None = None
    tick: int | None = None
    sqrt_price_x96: int | None = None
    liquidity: int | None = None
    token0: str | None = None
    token1: str | None = None
    dec0: int | None = None
    dec1: int | None = None
    token0_code_size: int | None = None
    token1_code_size: int | None = None
    label: str = ""


def evaluate(r: PoolReadings, *, eps: float = 0.01) -> Badge:
    """Judge a pool from readings alone. Pure, so a test needs no chain."""
    badge = Badge(pool=r.address, chain_id=r.chain_id, label=r.label)

    _check_factory(badge, r)
    _check_fee_tier(badge, r)
    _check_fee_protocol(badge, r)
    _check_decimals(badge, r)
    _check_initialised(badge, r)
    _check_mintable(badge, r)
    _check_liquidity(badge, r, eps)
    _check_tokens_are_contracts(badge, r)
    _check_recorded_matches_chain(badge, r)
    return badge


def _check_recorded_matches_chain(badge: Badge, r: PoolReadings) -> None:
    """Does what `chain/addresses.py` records still match what the chain says?

    This check exists because of a specific failure. `EQUITY_POOL.fee_protocol`
    was recorded as **0** — read from `slot0[2]`, which is `observationIndex`,
    rather than `slot0[5]`, which is `feeProtocol`. Index 2 held a small,
    plausible integer on both pools, so nothing reverted and nothing looked
    wrong, and the mistake was published as a finding claiming LPs kept the whole
    fee on that venue. They keep 68%.

    What eventually exposed it was a *disagreement between two numbers in the
    same repository* — the badge printed 100 for a pool `addresses.py` recorded
    as 3400. So the badge now makes that comparison itself instead of leaving it
    to whoever happens to read both. A constant nobody re-reads is a constant
    that rots, and this is the cheapest possible place to notice.
    """
    provenance = "P-8: fee_protocol was recorded as 0 by reading slot0[2], not slot0[5]"
    if not r.recorded:
        badge.add(
            "recorded values match chain",
            WARN,
            "nothing recorded for this pool to check against",
            provenance,
        )
        return

    live = {
        "fee_pips": r.fee_pips,
        "tick_spacing": r.tick_spacing,
        "fee_protocol": r.fee_protocol,
        "dec0": r.dec0,
        "dec1": r.dec1,
    }
    unread = [name for name in r.recorded if live.get(name) is None]
    if unread:
        badge.add(
            "recorded values match chain",
            UNKNOWN,
            f"could not read {', '.join(sorted(unread))}",
            provenance,
        )
        return

    drifted = [
        f"{name}: recorded {want}, chain says {live[name]}"
        for name, want in r.recorded.items()
        if live.get(name) != want
    ]
    if drifted:
        badge.add("recorded values match chain", FAIL, "; ".join(drifted), provenance)
    else:
        badge.add(
            "recorded values match chain",
            PASS,
            f"{len(r.recorded)} recorded value(s) still agree",
            provenance,
        )


def _check_factory(badge: Badge, r: PoolReadings) -> None:
    provenance = "P-6: Pancake's pool deployer has a different init-code hash"
    if r.resolved_by_factory is None:
        badge.add("factory resolves it", UNKNOWN, "could not call getPool()", provenance)
    elif r.resolved_by_factory.lower() != r.address.lower():
        badge.add(
            "factory resolves it",
            FAIL,
            f"factory returns {r.resolved_by_factory} for these tokens and this tier",
            provenance,
        )
    else:
        badge.add("factory resolves it", PASS, "getPool() agrees with the address", provenance)


def _check_fee_tier(badge: Badge, r: PoolReadings) -> None:
    provenance = "P-6: 100/500/2500/10000 -> 1/10/50/200, and no 3000 tier"
    if r.fee_pips is None or r.tick_spacing is None:
        badge.add("tick spacing matches tier", UNKNOWN, "could not read the tier", provenance)
        return
    expected = FEE_TIER_SPACING.get(r.fee_pips)
    if expected is None:
        badge.add(
            "tick spacing matches tier",
            FAIL,
            f"fee tier {r.fee_pips} is not one PancakeSwap v3 deploys",
            provenance,
        )
    elif expected != r.tick_spacing:
        badge.add(
            "tick spacing matches tier",
            FAIL,
            f"tier {r.fee_pips} implies spacing {expected}, pool reports {r.tick_spacing}",
            provenance,
        )
    else:
        badge.add(
            "tick spacing matches tier",
            PASS,
            f"{r.fee_pips / 10_000:.2f}% -> spacing {r.tick_spacing}",
            provenance,
        )


def _check_fee_protocol(badge: Badge, r: PoolReadings) -> None:
    provenance = "P-1, P-8: 3400 on WBNB/USDT, 3200 on TSLAx/USDT — no constant is right"
    if r.fee_protocol is None:
        badge.add("protocol fee read", UNKNOWN, "could not read slot0.feeProtocol", provenance)
        return
    if not 0 <= r.fee_protocol <= 10_000:
        badge.add(
            "protocol fee read",
            FAIL,
            f"feeProtocol {r.fee_protocol} is outside 0..10000",
            provenance,
        )
        return
    lp_share = 1.0 - r.fee_protocol / 10_000.0
    effective = (r.fee_pips or 0) / 100.0 * lp_share
    badge.add(
        "protocol fee read",
        PASS,
        f"feeProtocol {r.fee_protocol} — LPs keep {lp_share:.0%}, effective {effective:.3f}bps",
        provenance,
    )


def _check_decimals(badge: Badge, r: PoolReadings) -> None:
    provenance = "BSC's USDT/USDC are 18 decimals, not Ethereum's 6"
    if r.dec0 is None or r.dec1 is None:
        badge.add("decimals read", UNKNOWN, "could not read decimals()", provenance)
    elif not (0 < r.dec0 <= 36 and 0 < r.dec1 <= 36):
        badge.add("decimals read", FAIL, f"implausible decimals {r.dec0}/{r.dec1}", provenance)
    else:
        badge.add("decimals read", PASS, f"token0 {r.dec0}, token1 {r.dec1}", provenance)


def _check_initialised(badge: Badge, r: PoolReadings) -> None:
    provenance = "chapel's WBNB/USDT: real address, initialised at MAX_TICK, never seeded"
    if r.sqrt_price_x96 is None or r.tick is None:
        badge.add("initialised and not pinned", UNKNOWN, "could not read slot0", provenance)
        return
    if r.sqrt_price_x96 == 0:
        badge.add("initialised and not pinned", FAIL, "sqrtPriceX96 is zero", provenance)
        return
    from_edge = min(r.tick - MIN_TICK, MAX_TICK - r.tick)
    if from_edge < PINNED_TICKS_FROM_EDGE:
        badge.add(
            "initialised and not pinned",
            FAIL,
            f"tick {r.tick} is {from_edge} ticks from the edge of the range",
            provenance,
        )
    else:
        badge.add("initialised and not pinned", PASS, f"tick {r.tick}", provenance)


def _check_mintable(badge: Badge, r: PoolReadings) -> None:
    provenance = "V-10: MIN_TICK % 10 == 2, so clamping yields ticks the pool rejects"
    if r.tick is None or r.tick_spacing is None:
        badge.add("a mintable range exists", UNKNOWN, "could not read tick or spacing", provenance)
        return
    w_min = 4 * r.tick_spacing  # spec section 3.2's anti-dust floor
    centre = (r.tick // r.tick_spacing) * r.tick_spacing
    lower, upper = centre - w_min, centre + w_min
    if lower <= MIN_TICK or upper >= MAX_TICK:
        badge.add(
            "a mintable range exists",
            FAIL,
            f"w_min={w_min} does not fit at tick {r.tick}",
            provenance,
        )
    elif lower % r.tick_spacing or upper % r.tick_spacing:
        badge.add(
            "a mintable range exists",
            FAIL,
            f"[{lower}, {upper}] is not on the {r.tick_spacing} grid",
            provenance,
        )
    else:
        badge.add("a mintable range exists", PASS, f"w_min={w_min}, [{lower}, {upper}]", provenance)


def _check_liquidity(badge: Badge, r: PoolReadings, eps: float) -> None:
    provenance = "A1: a position big enough to move the price it is replayed against is fiction"
    if r.liquidity is None:
        badge.add(
            "liquidity supports a position", UNKNOWN, "could not read liquidity()", provenance
        )
        return
    if r.liquidity <= 0:
        badge.add(
            "liquidity supports a position",
            FAIL,
            "the pool holds no liquidity — it exists on paper",
            provenance,
        )
        return
    share = int(r.liquidity * eps)
    if r.liquidity < MIN_LIQUIDITY_FOR_EPS:
        badge.add(
            "liquidity supports a position",
            WARN,
            f"{r.liquidity:,} — a {eps:.0%} share is {share:,}, thin enough that a "
            "quote would describe the pool rather than the strategy",
            provenance,
        )
    else:
        badge.add(
            "liquidity supports a position",
            PASS,
            f"{r.liquidity:,} — a {eps:.0%} share is {share:,}",
            provenance,
        )


def _check_tokens_are_contracts(badge: Badge, r: PoolReadings) -> None:
    provenance = 'an "ERC-20" with no code is an address somebody typed'
    sizes = (r.token0_code_size, r.token1_code_size)
    if any(size is None for size in sizes):
        badge.add("both tokens are contracts", UNKNOWN, "could not read code", provenance)
    elif any(size == 0 for size in sizes):
        which = "token0" if r.token0_code_size == 0 else "token1"
        badge.add("both tokens are contracts", FAIL, f"{which} has no code", provenance)
    else:
        badge.add(
            "both tokens are contracts",
            PASS,
            f"{r.token0_code_size:,} and {r.token1_code_size:,} bytes",
            provenance,
        )
