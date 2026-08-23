"""Do the Venus markets we point a router at agree with each other?

`addresses.py` asks this of the PancakeSwap deployment. This asks it of the
lending venue, and the three questions are the same ones in the same order:

1. **Is there code there?** An address with no bytecode is a typo.
2. **Does it answer?** A market that reverts on `comptroller()` is not a market.
3. **Do the answers agree with each other?** The market must name the Unitroller
   that names the market, and the market's `underlying()` must be a token
   `chain/addresses.py` verified independently. Any single reading can be made
   to look right by pointing at a plausible contract; making three agree
   requires actually being the deployment.

The third check is the strong one and it is worth being precise about why. This
repository verified `USDT_MAINNET` from the PancakeSwap side, as token0 of the
flagship pool, months before it read Venus at all. When `vUSDT.underlying()`
returns those same twenty bytes, two independent chains of reasoning have
converged, and that is evidence one chain repeated twice cannot produce.

## A read that fails is UNKNOWN, never PASS

Same rule as everywhere else here: a call that raises produces `UNKNOWN`, which
is blocking. An address nobody could check and an address checked clean must not
render the same, and the shape of the data enforces it rather than the shape of
the page.

## `getAllMarkets()` containing the market is a check, not a formality

Venus's Comptroller is an EIP-2535 diamond that dispatches per facet, so a
revert proves nothing about what it implements — `supplyCaps(address)` reverts
with `Diamond: Function does not exist` on a contract that plainly has supply
caps. Membership in `getAllMarkets()` is therefore the only *positive* statement
available about whether the Unitroller considers a market to be one of its own,
and it is asked here rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..chain.venus import MARKETS, UNITROLLER
from .badge import FAIL, PASS, UNKNOWN, Check


class Reader(Protocol):
    """The chain, narrowed to what this module needs.

    A protocol rather than a `Web3`, so every verdict below is exercised without
    a node — the same split `vetting/addresses.py` makes.
    """

    def code_size(self, address: str) -> int: ...

    def call(self, address: str, signature: str, *args: Any) -> Any: ...


@dataclass(slots=True)
class VenusReport:
    chain_id: int
    checks: list[Check] = field(default_factory=list)
    #: Set when nothing could be read at all. An empty list of checks and a
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

    @property
    def markets_passing(self) -> int:
        """How many markets cleared every check that names them.

        The router's floor is two: one venue is not a choice. This counts
        markets rather than checks so a market failing three ways costs one,
        not three.
        """
        by_market: dict[str, bool] = {}
        for check in self.checks:
            market = check.name.split(" ")[0]
            if not market.startswith("v"):
                continue
            by_market[market] = by_market.get(market, True) and check.status == PASS
        return sum(1 for ok in by_market.values() if ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "surveyed": self.surveyed,
            "reason": self.reason,
            "block": self.block,
            "verdict": self.verdict,
            "markets_passing": self.markets_passing,
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


def survey(reader: Reader, chain_id: int) -> VenusReport:
    """Every check, in order, against one chain's verified markets."""
    report = VenusReport(chain_id=chain_id)
    markets = MARKETS.get(chain_id, ())
    unitroller = UNITROLLER.get(chain_id)

    if not markets or not unitroller:
        report.surveyed = False
        report.reason = f"no Venus markets are recorded for chain {chain_id}"
        return report

    # 1. Bytecode on the Unitroller. Every market's third check compares against
    #    it, so a Unitroller that is not a contract invalidates all of them.
    try:
        size = reader.code_size(unitroller)
        report.add(
            "comptroller has code",
            PASS if size > 0 else FAIL,
            f"{size:,} bytes at {unitroller}" if size else f"no code at {unitroller}",
            "A1",
        )
    except Exception as error:  # noqa: BLE001 — any read failure is UNKNOWN
        report.add(
            "comptroller has code", UNKNOWN, f"could not read code at {unitroller}: {error}", "A1"
        )

    # The Unitroller's own list, read once and compared against by every market.
    listed: set[str] | None
    try:
        listed = {str(a).lower() for a in reader.call(unitroller, "getAllMarkets()")}
        report.add(
            "comptroller lists its markets",
            PASS if listed else FAIL,
            f"getAllMarkets() returns {len(listed)} markets",
            "V-14",
        )
    except Exception as error:  # noqa: BLE001
        listed = None
        report.add(
            "comptroller lists its markets", UNKNOWN, f"getAllMarkets() failed: {error}", "V-14"
        )

    for market in markets:
        _survey_market(reader, report, market, listed)

    return report


def _survey_market(reader: Reader, report: VenusReport, market, listed: set[str] | None) -> None:
    """The eight checks that name one market.

    A module-level function rather than a closure inside the loop: bound-late
    closures over a loop variable are a real defect class, and the version of
    this that lived inline had it — every reader carried a `m=market` default to
    dodge it while the error path that formatted the name did not, so a market
    whose read raised would have been reported under the *last* market's symbol.
    """

    def _add(name: str, provenance: str, read) -> None:
        try:
            ok, detail = read()
        except Exception as error:  # noqa: BLE001 — any read failure is UNKNOWN
            report.add(f"{market.symbol} {name}", UNKNOWN, f"read failed: {error}", provenance)
            return
        report.add(f"{market.symbol} {name}", PASS if ok else FAIL, detail, provenance)

    def has_code():
        size = reader.code_size(market.address)
        return size > 0, (
            f"{size:,} bytes at {market.address}" if size else f"no code at {market.address}"
        )

    def names_the_comptroller():
        got = str(reader.call(market.address, "comptroller()"))
        return got.lower() == market.comptroller.lower(), (
            f"market says {got}, config says {market.comptroller}"
        )

    def is_listed():
        if listed is None:
            raise RuntimeError("getAllMarkets() did not answer, so membership is unknown")
        ok = market.key in listed
        return ok, (
            f"{market.symbol} is in getAllMarkets()"
            if ok
            else f"{market.symbol} is NOT in getAllMarkets() — the Unitroller does not own it"
        )

    def underlying_agrees():
        got = str(reader.call(market.address, "underlying()"))
        ok = got.lower() == market.underlying.lower()
        return ok, (
            f"underlying() returns {got}, which chain/addresses.py verified independently"
            if ok
            else f"underlying() returns {got}, config says {market.underlying}"
        )

    def symbol_agrees():
        got = str(reader.call(market.address, "symbol()"))
        return got == market.symbol, f"symbol() returns {got!r}, config says {market.symbol!r}"

    def vtoken_decimals_agree():
        got = int(reader.call(market.address, "decimals()"))
        return got == market.v_decimals, (
            f"decimals() returns {got}, config says {market.v_decimals} — "
            f"the vToken's own, not the underlying's {market.underlying_decimals}"
        )

    def accrues():
        index = int(reader.call(market.address, "borrowIndex()"))
        return index > 0, (
            f"borrowIndex() is {index:,}"
            if index > 0
            else "borrowIndex() is 0 — the market has never accrued"
        )

    def has_liquidity():
        cash = int(reader.call(market.address, "getCash()"))
        scale = 10**market.underlying_decimals
        return cash > 0, (
            f"getCash() is {cash / scale:,.0f} {market.symbol[1:]}"
            if cash > 0
            else "getCash() is 0 — nothing to supply into"
        )

    _add("has code", "A1", has_code)
    _add("names the comptroller", "V-14", names_the_comptroller)
    _add("is listed by the comptroller", "V-14", is_listed)
    _add("underlying agrees with addresses.py", "V-15", underlying_agrees)
    _add("symbol agrees", "V-14", symbol_agrees)
    _add("vToken decimals agree", "V-16", vtoken_decimals_agree)
    _add("has accrued interest", "V-17", accrues)
    _add("has cash to supply into", "V-17", has_liquidity)
