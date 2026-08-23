"""The Venus market checks, against a chain that answers however the test says.

`vetting/venus.py`'s `survey()` takes a `Reader` protocol rather than a `Web3`
for the reason `test_address_checks.py` gives: every judgement is exercised
without a node, including the ones that only happen when a contract lies.

Named `test_venus_checks` and not `test_venus` on purpose. `tests/` is not a
package, so pytest derives a module name from the basename alone —
`tests/indexer/test_venus.py` already exists, and a second file with that
basename produces the same module name and fails collection, **taking the whole
suite with it**. The neighbouring `test_address_checks.py` docstring records the
same trap and the same fix.
"""

from __future__ import annotations

from typing import Any

from misquote.chain.venus import MARKETS, UNITROLLER, VUSDC, VUSDT
from misquote.vetting import venus
from misquote.vetting.badge import FAIL, PASS, UNKNOWN

CHAIN = 56
ALL_MARKETS = [m.key for m in MARKETS[CHAIN]]


class FakeChain:
    """A chain that agrees with `chain/venus.py` unless told otherwise.

    `overrides` is keyed by function name and may hold a value or an exception
    to raise. `per_market` overrides a single market's answer, which is what
    lets one market fail while its sibling passes.
    """

    def __init__(self, *, overrides: dict[str, Any] | None = None, per_market=None) -> None:
        self.overrides = overrides or {}
        self.per_market = per_market or {}
        self.empty: set[str] = set()
        self.reverts: set[str] = set()

    def code_size(self, address: str) -> int:
        if address in self.reverts:
            raise RuntimeError("connection reset")
        return 0 if address in self.empty else 4_744

    def call(self, address: str, signature: str, *args: Any) -> Any:
        name = signature.split("(")[0]
        key = (address.lower(), name)
        if key in self.per_market:
            value = self.per_market[key]
            if isinstance(value, Exception):
                raise value
            return value
        if name in self.overrides:
            value = self.overrides[name]
            if isinstance(value, Exception):
                raise value
            return value

        if name == "getAllMarkets":
            return ALL_MARKETS
        market = next((m for m in MARKETS[CHAIN] if m.key == address.lower()), None)
        if market is None:
            raise RuntimeError(f"no such market {address}")
        return {
            "comptroller": market.comptroller,
            "underlying": market.underlying,
            "symbol": market.symbol,
            "decimals": market.v_decimals,
            "borrowIndex": 1_501_211_336_155_601_162,
            "getCash": 80_226_884 * 10**18,
        }[name]


def statuses(report) -> dict[str, str]:
    return {c.name: c.status for c in report.checks}


# --- the clean case, so every failure below means something ------------------


def test_a_chain_that_agrees_with_the_config_passes_every_check() -> None:
    report = venus.survey(FakeChain(), CHAIN)
    assert report.verdict == PASS
    assert report.markets_passing == len(MARKETS[CHAIN])
    assert all(c.status == PASS for c in report.checks)


def test_every_check_names_the_market_it_is_about() -> None:
    """`markets_passing` splits on the symbol prefix, so the naming is load-bearing."""
    report = venus.survey(FakeChain(), CHAIN)
    per_market = [c for c in report.checks if c.name.startswith("v")]
    assert {c.name.split(" ")[0] for c in per_market} == {VUSDT.symbol, VUSDC.symbol}


# --- a read that fails is UNKNOWN, never PASS --------------------------------


def test_a_read_that_raises_is_unknown_and_blocking() -> None:
    chain = FakeChain()
    chain.per_market[(VUSDT.key, "comptroller")] = RuntimeError("node refused")
    report = venus.survey(chain, CHAIN)
    assert statuses(report)[f"{VUSDT.symbol} names the comptroller"] == UNKNOWN
    assert report.verdict == UNKNOWN


def test_an_unreadable_comptroller_makes_membership_unknown_not_false() -> None:
    """If `getAllMarkets()` did not answer, nothing can be said about membership.

    Reporting "not listed" would be a claim the chain never supported.
    """
    report = venus.survey(FakeChain(overrides={"getAllMarkets": RuntimeError("no")}), CHAIN)
    s = statuses(report)
    assert s["comptroller lists its markets"] == UNKNOWN
    assert s[f"{VUSDT.symbol} is listed by the comptroller"] == UNKNOWN
    assert report.verdict == UNKNOWN


def test_unreadable_bytecode_is_unknown() -> None:
    chain = FakeChain()
    chain.reverts.add(UNITROLLER[CHAIN])
    report = venus.survey(chain, CHAIN)
    assert statuses(report)["comptroller has code"] == UNKNOWN


# --- disagreement is FAIL, and FAIL beats UNKNOWN ---------------------------


def test_a_market_naming_a_different_comptroller_fails() -> None:
    chain = FakeChain()
    chain.per_market[(VUSDT.key, "comptroller")] = "0x" + "11" * 20
    report = venus.survey(chain, CHAIN)
    assert statuses(report)[f"{VUSDT.symbol} names the comptroller"] == FAIL
    assert report.verdict == FAIL


def test_a_market_the_comptroller_does_not_list_fails() -> None:
    """The one positive statement available about ownership.

    The Unitroller is an EIP-2535 diamond, so a revert proves nothing about what
    it implements — membership in `getAllMarkets()` is the only affirmative
    check there is.
    """
    report = venus.survey(FakeChain(overrides={"getAllMarkets": [VUSDC.key]}), CHAIN)
    s = statuses(report)
    assert s[f"{VUSDT.symbol} is listed by the comptroller"] == FAIL
    assert s[f"{VUSDC.symbol} is listed by the comptroller"] == PASS


def test_an_underlying_that_disagrees_with_addresses_py_fails() -> None:
    """The strongest check: two verifications from different directions.

    `chain/addresses.py` verified USDT independently, as token0 of the flagship
    PancakeSwap pool. A Venus market claiming a different underlying breaks that
    agreement, and agreement is the evidence.
    """
    chain = FakeChain()
    chain.per_market[(VUSDT.key, "underlying")] = "0x" + "22" * 20
    report = venus.survey(chain, CHAIN)
    assert statuses(report)[f"{VUSDT.symbol} underlying agrees with addresses.py"] == FAIL


def test_the_vtoken_decimals_check_reads_the_vtoken_not_the_underlying() -> None:
    """8 and 18 differ by ten orders of magnitude in `exchangeRateStored`."""
    chain = FakeChain()
    chain.per_market[(VUSDT.key, "decimals")] = VUSDT.underlying_decimals
    report = venus.survey(chain, CHAIN)
    assert statuses(report)[f"{VUSDT.symbol} vToken decimals agree"] == FAIL


def test_a_market_that_has_never_accrued_fails() -> None:
    chain = FakeChain()
    chain.per_market[(VUSDT.key, "borrowIndex")] = 0
    report = venus.survey(chain, CHAIN)
    assert statuses(report)[f"{VUSDT.symbol} has accrued interest"] == FAIL


def test_a_market_with_no_cash_fails() -> None:
    chain = FakeChain()
    chain.per_market[(VUSDT.key, "getCash")] = 0
    report = venus.survey(chain, CHAIN)
    assert statuses(report)[f"{VUSDT.symbol} has cash to supply into"] == FAIL


def test_no_code_at_a_market_fails() -> None:
    chain = FakeChain()
    chain.empty.add(VUSDT.address)
    report = venus.survey(chain, CHAIN)
    assert statuses(report)[f"{VUSDT.symbol} has code"] == FAIL


def test_fail_outranks_unknown() -> None:
    """Same ordering as a pool badge."""
    chain = FakeChain()
    chain.per_market[(VUSDT.key, "borrowIndex")] = 0  # FAIL
    chain.per_market[(VUSDC.key, "getCash")] = RuntimeError("no")  # UNKNOWN
    assert venus.survey(chain, CHAIN).verdict == FAIL


# --- the router's floor is counted in markets, not checks --------------------


def test_markets_passing_counts_markets_not_checks() -> None:
    """A market failing three ways costs one, not three — the floor is a count
    of venues the router could actually choose between."""
    chain = FakeChain()
    for name, value in (("borrowIndex", 0), ("getCash", 0), ("decimals", 18)):
        chain.per_market[(VUSDT.key, name)] = value
    report = venus.survey(chain, CHAIN)
    assert report.markets_passing == 1


def test_an_unconfigured_chain_is_not_surveyed_and_says_why() -> None:
    """An empty list of checks and a clean list of checks are not the same sentence."""
    report = venus.survey(FakeChain(), 97)
    assert report.surveyed is False
    assert report.verdict == UNKNOWN
    assert "no Venus markets are recorded" in report.reason
    assert report.checks == []


# --- the serialised shape the report script republishes ---------------------


def test_the_dict_carries_the_verdict_and_the_counts() -> None:
    chain = FakeChain()
    chain.per_market[(VUSDT.key, "borrowIndex")] = 0
    payload = venus.survey(chain, CHAIN).to_dict()
    assert payload["verdict"] == FAIL
    assert payload["markets_passing"] == 1
    assert payload["summary"]["failed"] == 1
    assert payload["summary"]["checked"] == len(payload["checks"])
    assert all({"name", "status", "detail", "provenance"} <= set(c) for c in payload["checks"])
