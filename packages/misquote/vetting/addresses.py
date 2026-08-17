"""Do the contracts at the addresses we point the signer at agree with each other?

`badge.py` vets *pools*. This vets the **addresses**, which is the one thing that
page did not cover — and the addresses are what a signer is aimed at. A pool can
pass every check in the world while the factory constant used to find it points
somewhere else entirely.

Three questions, in increasing strength:

1. **Is there code there?** An address with no bytecode is a typo that will
   accept a transfer and swallow it.
2. **Does it answer?** A contract that reverts on `factory()` is not the
   contract we think it is.
3. **Do the answers agree with each other?** This is the one that catches real
   mistakes. The factory must name the pool that the pool names itself; the
   position manager must name the factory; the pool's `fee` and `tickSpacing`
   must be the ones `PoolRef` records. Any single reading can be made to look
   right by pointing at a plausible contract. Making three of them agree
   requires actually being the deployment.

## Derived from `chain/addresses.py`, not copied beside it

`scripts/verify_addresses.py` carried its own `CANDIDATES` table — the same
addresses, typed a second time, with nothing asserting the two agreed. So the
script could report every check green while the module the signer actually
imports pointed somewhere else, which is the exact failure mode "verify the
addresses" exists to prevent. There is now one table, and this reads it.

## A read that fails is UNKNOWN, never PASS

`read.py` states the rule and this restates it by construction: a call that
raises produces `UNKNOWN`, which `Badge.verdict` treats as blocking. An address
nobody could check and an address checked clean must never render the same, and
the shape of the data is where that is enforced rather than the shape of the
page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..chain.addresses import DEPLOYMENTS, POOLS
from .badge import FAIL, PASS, UNKNOWN, Check


class Reader(Protocol):
    """The chain, narrowed to what this module needs.

    A protocol rather than a `Web3`, so the whole judgement layer is testable
    without a node — the same split `badge.py` makes against `read.py`.
    """

    def code_size(self, address: str) -> int: ...

    def call(self, address: str, signature: str, *args: Any) -> Any: ...


@dataclass(slots=True)
class AddressReport:
    chain_id: int
    checks: list[Check] = field(default_factory=list)
    #: Set when nothing could be read at all — an empty list of checks and a
    #: clean list of checks are not the same sentence.
    surveyed: bool = True
    reason: str = ""
    block: int | None = None

    def add(self, name: str, status: str, detail: str, provenance: str) -> None:
        self.checks.append(Check(name, status, detail, provenance))

    @property
    def verdict(self) -> str:
        """`FAIL` beats `UNKNOWN` beats `PASS`. Same ordering as a pool badge."""
        if not self.surveyed:
            return UNKNOWN
        if any(c.status == FAIL for c in self.checks):
            return FAIL
        if any(c.status == UNKNOWN for c in self.checks):
            return UNKNOWN
        return PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "surveyed": self.surveyed,
            "reason": self.reason,
            "block": self.block,
            "verdict": self.verdict,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "detail": c.detail,
                    "provenance": c.provenance,
                }
                for c in self.checks
            ],
            "summary": {
                "checked": len(self.checks),
                "failed": sum(1 for c in self.checks if c.status == FAIL),
                "unknown": sum(1 for c in self.checks if c.status == UNKNOWN),
            },
        }


def _named(chain_id: int) -> dict[str, str]:
    """Every address this chain's config points the signer at, by role.

    One place, read from `chain/addresses.py`. The verification script used to
    keep a second copy of this and nothing compared them.
    """
    deployment = DEPLOYMENTS[chain_id]
    found = {
        "factory": deployment.factory,
        "position_manager": deployment.position_manager,
        "swap_router": deployment.swap_router,
    }
    pool = POOLS.get(chain_id)
    if pool:
        found["pool"] = pool.address
        found["token0"] = pool.token0
        found["token1"] = pool.token1
    return found


def survey(reader: Reader, chain_id: int) -> AddressReport:
    """Every check, in order, against one chain."""
    report = AddressReport(chain_id=chain_id)
    named = _named(chain_id)
    pool = POOLS.get(chain_id)

    # 1. Bytecode. Cheapest, and it catches the whole class of "this address is
    #    a typo" — including an EOA, which accepts a transfer and keeps it.
    for role, address in named.items():
        try:
            size = reader.code_size(address)
        except Exception as error:  # noqa: BLE001 — any read failure is UNKNOWN
            report.add(
                f"{role} has code",
                UNKNOWN,
                f"could not read code at {address}: {error}",
                "A1",
            )
            continue
        report.add(
            f"{role} has code",
            PASS if size > 0 else FAIL,
            f"{size:,} bytes at {address}" if size else f"no code at {address}",
            "A1",
        )

    if not pool:
        return report

    # 2 and 3 together: each reading is only interesting because another
    #    reading has to agree with it.
    def agree(name: str, detail_ok: str, provenance: str, read) -> None:
        try:
            ok, detail = read()
        except Exception as error:  # noqa: BLE001
            report.add(name, UNKNOWN, f"read failed: {error}", provenance)
            return
        report.add(name, PASS if ok else FAIL, detail_ok if ok else detail, provenance)

    def factory_names_the_pool():
        got = reader.call(
            named["factory"],
            "getPool(address,address,uint24)",
            pool.token0,
            pool.token1,
            pool.fee_pips,
        )
        ok = str(got).lower() == pool.address.lower()
        return ok, f"factory returns {got}, config says {pool.address}"

    def pool_names_its_tokens():
        token0 = str(reader.call(pool.address, "token0()"))
        token1 = str(reader.call(pool.address, "token1()"))
        ok = token0.lower() == pool.token0.lower() and token1.lower() == pool.token1.lower()
        return ok, f"pool says {token0}/{token1}, config says {pool.token0}/{pool.token1}"

    def manager_names_the_factory():
        got = str(reader.call(named["position_manager"], "factory()"))
        ok = got.lower() == named["factory"].lower()
        return ok, f"position manager returns {got}, config says {named['factory']}"

    def fee_matches():
        got = int(reader.call(pool.address, "fee()"))
        return got == pool.fee_pips, f"pool says {got} pips, config says {pool.fee_pips}"

    def spacing_matches():
        got = int(reader.call(pool.address, "tickSpacing()"))
        return (
            got == pool.tick_spacing,
            f"pool says {got}, config says {pool.tick_spacing}",
        )

    agree(
        "the factory names this pool",
        f"getPool() returns {pool.address}",
        # P-6: Pancake deploys from its own PoolDeployer with a different
        # init-code hash, so Uniswap's computeAddress constants return
        # well-formed wrong addresses.
        "P-6",
        factory_names_the_pool,
    )
    agree(
        "the pool names these tokens",
        f"token0/token1 match {pool.token0}/{pool.token1}",
        "A1",
        pool_names_its_tokens,
    )
    agree(
        "the position manager names this factory",
        f"factory() returns {named['factory']}",
        "P-6",
        manager_names_the_factory,
    )
    agree(
        "the fee tier is the one recorded",
        f"{pool.fee_pips} pips",
        "P-8",
        fee_matches,
    )
    agree(
        "tick spacing is the one recorded",
        f"{pool.tick_spacing} ticks",
        # V-10: MIN_TICK % 10 == 2, so a wrong spacing yields ticks the pool
        # rejects and the mint reverts having cost gas.
        "V-10",
        spacing_matches,
    )
    return report


def not_surveyed(chain_id: int, reason: str) -> AddressReport:
    """No reading was taken, said as a sentence rather than as an empty list.

    `/registry` already publishes the equivalent — *"A count carried over from a
    previous run would be indistinguishable from a fresh one"* — and the reason
    is the same one: zero checks failing and zero checks run render identically
    unless something says which happened.
    """
    return AddressReport(chain_id=chain_id, surveyed=False, reason=reason)
