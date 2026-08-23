"""Venus Core Pool markets on BSC, every one read off chain rather than copied.

Regenerate and re-check with:

    uv run python scripts/verify_venus.py --chain 56 --out
    uv run python scripts/verify_venus.py --chain 56 --scan   # walk all 52 markets

`addresses.py` does this for PancakeSwap and the reasoning transfers unchanged:
an address taken from documentation is an unverified claim. Each market here is
checked three ways — bytecode present, its interface answers, and its answers
agree with the other contracts' (every market names the same Unitroller, that
Unitroller's `getAllMarkets()` contains the market, and the market's
`underlying()` is a token `addresses.py` already records).

Verified 2026-08-21 against BSC mainnet at block 117,186,608.

## The check that matters most, and it was free

`vUSDT.underlying()` returns `0x55d398326f99059fF775485246999027B3197955`, which
is byte-identical to `USDT_MAINNET` in `addresses.py` — an address this
repository verified independently, from the other direction, as token0 of the
flagship PancakeSwap pool. Two verifications that started in different places
landing on the same twenty bytes is a different quality of evidence from one
verification repeated, and it is the same argument `registry/aacp.py` records
for the ERC-8004 identity registry.

## Dollar markets only, and the reason is not caution

`vBNB` is a live market with a real supply rate, and it is excluded. Its APR is
denominated in BNB and vUSDT's in dollars, so an argmax over both is not
choosing a yield — it is taking an FX position and reporting the yield. Over any
horizon a router cares about, the BNB/USD move dominates the rate difference by
an order of magnitude, so the number driving the decision would not be the
number on the card. A router that silently takes a currency bet while claiming
to pick a rate is precisely the misquote this project is named after.

## Two decoding traps, both met on the first read

- **`vBNB.underlying()` returns zero bytes, not `address(0)`.** The market holds
  native BNB and has no underlying ERC-20, and the getter does not exist on it.
  A decoder that treats empty returndata as a zero address maps vBNB to "unknown
  token" and carries on; `read_market` refuses instead. Same rule
  `pool_by_address` states: guessing produces a complete, plausible, wrong
  answer.
- **Several `uint256` getters return 96 bytes, not 32.** Measured on vUSDT:
  `getCash()`, `supplyRatePerBlock()` and `exchangeRateStored()` each returned
  three words where the ABI declares one, while `borrowIndex()`,
  `totalBorrows()` and `reserveFactorMantissa()` returned one. The value is
  word 0 in every case — cross-checked against the accrual logs, which carry
  `cashPrior` and `totalBorrows` in their own data. So decoders here assert
  `len % 32 == 0` and take word 0; asserting `len == 32` would refuse three live
  getters, and indexing by a position nobody checked is P-8 (`slot0[2]` read
  where `slot0[5]` was meant, returning a plausible small integer).

## The Comptroller is a diamond, so absence proves nothing

`supplyCaps(address)` reverts with `Diamond: Function does not exist`. The
Unitroller is EIP-2535, dispatching per facet, so "the call reverted" and "the
contract does not implement this" are different statements and the first does
not imply the second. Nothing here infers a capability from a revert.
"""

from __future__ import annotations

from dataclasses import dataclass

from .addresses import BSC_MAINNET

#: Venus Core Pool's Unitroller. Every market below names this, and it names
#: every market — the third of the three checks.
UNITROLLER: dict[int, str] = {
    BSC_MAINNET: "0xfD36E2c2a6789Db23113685031d7F16329158384",
}

#: BSC's USDC. Its sibling `USDT_MAINNET` lives in `addresses.py` because the
#: flagship pool needed it first; this one is recorded here because Venus is
#: the first thing in the repository to read it.
USDC_MAINNET = "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d"


@dataclass(frozen=True, slots=True)
class MarketRef:
    """One Venus market we have actually read, not one we assume exists."""

    chain_id: int
    address: str
    symbol: str
    underlying: str
    #: The underlying's decimals. BSC's stablecoins are 18, not Ethereum's 6 —
    #: the same trap `badge.py` checks for on pool tokens.
    underlying_decimals: int
    #: The vToken's own decimals, which are 8 and are *not* the underlying's.
    #: `exchangeRateStored` is scaled by both, so conflating them misprices the
    #: position by ten orders of magnitude.
    v_decimals: int
    comptroller: str
    label: str

    @property
    def key(self) -> str:
        """Lowercased address — the id used in tapes, journals and artifacts."""
        return self.address.lower()


VUSDT = MarketRef(
    chain_id=BSC_MAINNET,
    address="0xfD5840Cd36d94D7229439859C0112a4185BC0255",
    symbol="vUSDT",
    underlying="0x55d398326f99059fF775485246999027B3197955",
    underlying_decimals=18,
    v_decimals=8,
    comptroller=UNITROLLER[BSC_MAINNET],
    label="Venus Core Pool USDT",
)

VUSDC = MarketRef(
    chain_id=BSC_MAINNET,
    address="0xecA88125a5ADbe82614ffC12D0DB554E2e2867C8",
    symbol="vUSDC",
    underlying=USDC_MAINNET,
    underlying_decimals=18,
    v_decimals=8,
    comptroller=UNITROLLER[BSC_MAINNET],
    label="Venus Core Pool USDC",
)

#: The whitelist. Two markets, both dollar-denominated, both verified three ways.
#:
#: Two is the floor rather than a target: a router with one venue has nothing to
#: choose between, and `scripts/verify_venus.py` exits non-zero below it. Adding
#: a third means running that script and recording what it prints — never
#: appending an address because a page listed it.
MARKETS: dict[int, tuple[MarketRef, ...]] = {
    BSC_MAINNET: (VUSDT, VUSDC),
}

#: Deliberately empty, and named so the absence is checkable.
#:
#: Lista Lending was the obvious second venue and is not here. Its candidate
#: Moolah address carries 134 bytes of code — proxy-shaped, with nothing
#: confirming the interface behind it — and `docs.bsc.lista.org`'s lending
#: contract page returns 404. It is also Morpho-Blue-shaped
#: (`market(bytes32)` / `idToMarketParams(bytes32)`), which is a second venue
#: model rather than a second address for this one. `registry/aacp.py`'s rule
#: applies: a real contract that has not been verified against the interface we
#: intend to use is not an entry, and a mapping whose name overstates its
#: contents is the misquote wearing our own logo.
UNVERIFIED_VENUES: dict[str, str] = {
    "lista-moolah": (
        "134 bytes of code at the candidate address, interface unconfirmed; "
        "docs.bsc.lista.org/lista-lending/smart-contract returns 404"
    ),
}

#: The event every rate reading in this repository is derived from.
#:
#: `AccrueInterest(cashPrior, interestAccumulated, borrowIndex, totalBorrows)`.
#: Both of the accumulator's inputs are inside the log, so a rate can be
#: recomputed from the tape alone without re-reading chain state — which is
#: what makes the tape replayable at all. See `estimators/apr.py`.
ACCRUE_INTEREST_SIGNATURE = "AccrueInterest(uint256,uint256,uint256,uint256)"
NEW_RESERVE_FACTOR_SIGNATURE = "NewReserveFactor(uint256,uint256)"


@dataclass(frozen=True, slots=True)
class SwapVenueRef:
    """The pool a router swaps one underlying into the other through.

    Recorded here rather than in `addresses.py`'s `KNOWN_POOLS` because it is
    not a pool this project provides liquidity to: nothing replays a position on
    it, and `PoolRef`'s `fee_protocol` and `quote_symbol` carry LP semantics
    that would be asserted and never used. What matters here is the fee a
    *taker* pays and the depth behind it.

    Verified 22 Aug 2026 against BSC mainnet, three ways: 22,962 bytes of
    bytecode; `token0`/`token1`/`fee`/`tickSpacing` answered; and its `factory()`
    equals `DEPLOYMENTS[56].factory` — the same PancakeSwap factory
    `addresses.py` verified independently, which is the agreement that makes the
    reading evidence rather than a lookup.
    """

    chain_id: int
    address: str
    token0: str
    token1: str
    decimals: int
    #: Hundredths of a basis point, as the pool reports it. 100 = 0.01% = 1 bp.
    fee_pips: int
    tick_spacing: int
    label: str

    @property
    def taker_fee_bps(self) -> float:
        """What a swap costs, in basis points, gross of nothing.

        This is the **full** tier, not the LP's share of it. A router paying to
        move between underlyings pays the protocol's cut too — P-1 in a mirror,
        and using `lp_fee_share` here would understate every switch.
        """
        return self.fee_pips / 100.0


#: The stablecoin pair, and the number that decides whether Router ever moves.
#:
#: Router's `SwitchCost.slippage_bps` was **5.0** — a literal copied from the
#: LP `CostModel`, which estimates slippage for a *WBNB/USDT* recentre. There
#: was no USDT/USDC pool anywhere in this repository, so no fee tier was ever
#: consulted; the constant simply wore the argument that the router pays the
#: full pool fee.
#:
#: PancakeSwap runs this pair at the **0.01% tier** with roughly ten times the
#: depth of its 0.05% pool. One basis point, not five. At five the round-trip
#: hurdle was 5.84% against a best observed rate of 2.50% and Router never
#: supplied; the published card, its 16-day break-even and its 3.90pp advantage
#: over parking all followed from that. See P-25.
STABLE_SWAP_VENUE = SwapVenueRef(
    chain_id=BSC_MAINNET,
    address="0x92b7807bF19b7Dddf89b706143896d05228f3121",
    token0="0x55d398326f99059fF775485246999027B3197955",  # USDT
    token1=USDC_MAINNET,
    decimals=18,
    fee_pips=100,
    tick_spacing=1,
    label="PancakeSwap v3 USDT/USDC 0.01%",
)

#: Gas a Venus supply or redeem costs, in units.
#:
#: The sibling of `chain/live_source.py`'s `REBALANCE_GAS_UNITS = 600_000`, and
#: deliberately not that number: a Compound-fork `mint`/`redeem` writes far less
#: state than a v3 burn-collect-mint. 250,000 is the conservative end of what
#: these calls cost on BSC.
#:
#: Stated rather than measured, and named so, because measuring it needs a
#: transaction and nothing here signs. It is an input to a published figure, so
#: it is published too — see `docs/ASSUMPTIONS.md`.
VENUS_SWITCH_GAS_UNITS = 250_000


def markets_on(chain_id: int) -> tuple[MarketRef, ...]:
    """Every verified market for a chain, or an empty tuple."""
    return MARKETS.get(chain_id, ())


def market_by_address(address: str) -> MarketRef:
    """The verified reference for a market address, or a refusal.

    Refusing is the point, and the reason is sharper here than for pools: a
    market's `underlying_decimals` and `v_decimals` decide what its accumulator
    readings *mean*, and the two differ by ten. An unverified address produces a
    complete, plausible, wrongly-scaled rate.
    """
    wanted = address.lower()
    for chain_markets in MARKETS.values():
        for ref in chain_markets:
            if ref.key == wanted:
                return ref
    known = "\n  ".join(f"{r.address}  {r.label}" for chain in MARKETS.values() for r in chain)
    raise ValueError(
        f"{address} is not a Venus market this repository has verified on chain.\n"
        f"Its decimals decide what its accumulator readings mean, and guessing "
        f"them produces a rate that looks right and is not.\n"
        f"Verified markets:\n  {known}\n"
        f"To add one: resolve it with scripts/verify_venus.py and record it here."
    )
