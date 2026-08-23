"""A lending market's supply rate, derived from an accumulator rather than quoted.

## The finding this module exists because of

Venus exposes `supplyRatePerBlock()`, a per-block mantissa. Turning it into an
APR needs a blocks-per-year constant, and **that constant is not readable from
chain**: the market's own `interestRateModel()` reverts on `blocksPerYear()`,
`getBlocksPerYear()`, `blocksOrSecondsPerYear()` and `isTimeBased()` alike, and
the Comptroller is an EIP-2535 diamond that reverts `supplyCaps(address)` with
`Diamond: Function does not exist` — so a revert there proves nothing either.

Measured on vUSDT, 21 Aug 2026, mantissa 308,220,494:

| assumed blocks/year | implied supply APR |
|---|---|
| 10,512,000 — Venus's documented 3-second blocks | **0.324%** |
| 31,536,000 — one second | 0.972% |
| 42,048,000 — 0.75 s | 1.296% |
| 70,080,000 — 0.45 s | **2.160%** |

A **6.67x** spread, entirely from a constant nobody can read, landing directly
on the headline number a yield router sorts by.

## So this differences the accumulator instead, and needs no constant

`borrowIndex` is a monotone accumulator. Between two accruals:

    growth      = borrowIndex_1 / borrowIndex_0 - 1
    utilisation = totalBorrowsPrior / (cashPrior + totalBorrowsPrior)
    supply_apr  = growth * utilisation * (1 - reserveFactor) * SECONDS_PER_YEAR / dt

Every input except the reserve factor is inside the `AccrueInterest` log itself
(`totalBorrowsPrior = totalBorrows - interestAccumulated`), so a rate can be
recomputed from the tape alone, with no chain state re-read and no constant.
`dt` is a difference of two block timestamps, which the indexer already fetches.

**The two methods agree, and that is the check.** Measured over four window
widths on vUSDT at head 117,187,116:

| window | accruals | blocks | seconds | s/block | realized supply APR |
|---|---|---|---|---|---|
| 500 | 82 | 475 | 214 | 0.451 | 2.1583% |
| 2,000 | 296 | 1,957 | 881 | 0.450 | 2.1599% |
| 4,000 | 550 | 3,970 | 1,787 | 0.450 | 2.1594% |
| 4,999 | 638 | 4,969 | 2,237 | 0.450 | 2.1590% |

Stable to within 0.002pp across a tenfold change in window, and BSC measures a
consistent **0.450 s/block** — which is the constant Venus's own documentation
does not use. The realized 2.159% and the quoted-at-0.45s 2.160% agree to three
decimal places. Two independent routes to the same number is what makes either
one trustworthy, and it is the same argument `chain/venus.py` makes about
`vUSDT.underlying()` matching an address verified from the PancakeSwap side.

The realized figure is therefore not merely "an alternative"; it is the one that
does not silently depend on a stale documented block time. Published as an
assumption rather than asserted here — see `docs/ASSUMPTIONS.md`.

## A sparse market is not an undersampled market

vUSDC accrues roughly twice per 5,000 blocks against vUSDT's several hundred.
Sampling a *rate* twice in forty minutes would be a thin, badly conditioned
estimate. Sampling an *accumulator* twice is exact — `borrowIndex` is literally
constant between accruals, so a market that did not accrue has not been
undersampled, it has not moved. The estimate over a window is identical whether
it is computed from its two endpoints or from every accrual inside it, and
`tests/estimators/test_apr.py` asserts precisely that.

The opposite intuition is the natural one, which is why it is written here.

## What "not ready" means, and why it is not zero

A window containing fewer than two accruals cannot produce a growth figure at
all — one point is not a difference. That is `ready == False` and a `stale`
flag, never `apr == 0.0`. A market yielding nothing and a market nobody could
measure are different claims, and the router refuses to route into the second
rather than ranking it last.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..core.types import DEFAULT_RESERVE_FACTOR, SECONDS_PER_YEAR
from .base import TrailingEstimator

#: Seconds in a 365-day year. The only constant here, and it is a definition
#: rather than a measurement — which is the entire point of the module.


#: Below two accruals there is no difference to take.
MIN_ACCRUALS = 2


@dataclass(frozen=True, slots=True)
class RateEvent:
    """One `AccrueInterest` log, decoded.

    Satisfies `estimators.base.Timed` — `ts` and `key` — so it goes through the
    same look-ahead firewall as a pool swap without that firewall needing a
    second implementation.

    The four data words are carried as written. `total_borrows` is the value
    *after* this accrual and `interest_accumulated` is what was just added, so
    the prior is their difference — which is what utilisation needs and why the
    log is self-sufficient.
    """

    market: str
    block: int
    log_index: int
    ts: int
    cash_prior: int
    interest_accumulated: int
    borrow_index: int
    total_borrows: int

    @property
    def key(self) -> tuple[int, int]:
        return (self.block, self.log_index)

    @property
    def total_borrows_prior(self) -> int:
        """Borrows before this accrual — `w3 - w1`, both from this log."""
        return self.total_borrows - self.interest_accumulated

    @property
    def utilisation(self) -> float:
        """Borrowed fraction of the pool at the moment of this accrual.

        Zero when the market is empty rather than a division error: a pool with
        no cash and no borrows is idle, and idle is a real state.
        """
        prior = self.total_borrows_prior
        supplied = self.cash_prior + prior
        return prior / supplied if supplied > 0 else 0.0


@dataclass(frozen=True, slots=True)
class AprFit:
    """What the estimator found, and how much it rests on.

    `label` is the estimator's own sentence about itself, so a card cannot
    describe the fit in terms the fit would not use — the same contract
    `kappa.fit()` has.
    """

    supply_apr: float
    borrow_apr: float
    utilisation: float
    reserve_factor: float
    accruals: int
    span_seconds: int
    is_stale: bool
    label: str


class TrailingAprEstimator(TrailingEstimator):
    """Realized supply APR for one market over a trailing window.

    Inherits `ingest`, and with it both guards — an event after the decision
    time raises `LookAheadError`, an event out of chain order raises
    `OutOfOrderError`. Neither is reimplemented here, which is the reason
    `base.Timed` was widened instead of a second base class being written.
    """

    __slots__ = ("_window_s", "_reserve_factor", "_events")

    def __init__(self, window_seconds: int, reserve_factor: float = DEFAULT_RESERVE_FACTOR) -> None:
        super().__init__()
        if window_seconds <= 0:
            raise ValueError("a trailing window with no width is not a window")
        if not 0.0 <= reserve_factor < 1.0:
            raise ValueError(
                f"reserve_factor={reserve_factor} is outside [0, 1) — a market that "
                f"reserves all of its interest pays suppliers nothing, and a negative "
                f"reserve pays them interest that was never earned"
            )
        self._window_s = window_seconds
        self._reserve_factor = reserve_factor
        self._events: deque[RateEvent] = deque()

    def _absorb(self, event: RateEvent) -> None:  # type: ignore[override]
        self._events.append(event)
        self._evict()

    def _on_time_advanced(self) -> None:
        # Eviction on the clock as well as on arrival: a market that stops
        # accruing must age out of its own window and become stale, and
        # discovering that only when someone asks for the number is how a stale
        # estimate gets published as a fresh one. `base.py` says so.
        self._evict()

    def _evict(self) -> None:
        cutoff = self.decision_time - self._window_s
        while self._events and self._events[0].ts < cutoff:
            self._events.popleft()

    @property
    def ready(self) -> bool:
        return len(self._events) >= MIN_ACCRUALS and self._span() > 0

    def _span(self) -> int:
        if len(self._events) < MIN_ACCRUALS:
            return 0
        return self._events[-1].ts - self._events[0].ts

    def value(self) -> float:
        """The trailing realized supply APR, as a fraction per year."""
        return self.fit().supply_apr

    def fit(self) -> AprFit:
        """The estimate with its own provenance attached."""
        n = len(self._events)
        span = self._span()
        if n < MIN_ACCRUALS or span <= 0:
            return AprFit(
                supply_apr=0.0,
                borrow_apr=0.0,
                utilisation=0.0,
                reserve_factor=self._reserve_factor,
                accruals=n,
                span_seconds=span,
                is_stale=True,
                # Named as unmeasured, not as zero. The router refuses a stale
                # venue rather than ranking it last.
                label=(
                    f"stale: {n} accrual(s) in the trailing {self._window_s}s — "
                    f"a rate needs two points to difference"
                ),
            )

        first, last = self._events[0], self._events[-1]
        growth = last.borrow_index / first.borrow_index - 1.0
        # Utilisation at the *end* of the window. The growth already integrates
        # whatever utilisation held while it accrued; this is the figure the
        # next interval will be earned at, which is what a forward-looking
        # decision is about.
        util = last.utilisation
        borrow_apr = growth * SECONDS_PER_YEAR / span
        supply_apr = borrow_apr * util * (1.0 - self._reserve_factor)
        return AprFit(
            supply_apr=supply_apr,
            borrow_apr=borrow_apr,
            utilisation=util,
            reserve_factor=self._reserve_factor,
            accruals=n,
            span_seconds=span,
            is_stale=False,
            label=(
                f"realized from borrowIndex over {span:,}s and {n:,} accruals "
                f"(no blocks-per-year constant)"
            ),
        )
