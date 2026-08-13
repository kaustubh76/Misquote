"""Volatility of the pool price (spec section 5.1).

EWMA of one-minute log returns with a six-hour half-life, scaled to per
sqrt-hour, which is the unit equations (1) and (2) expect.

Ported from PolyLambda's `estimators/sigma.py`, with its logit returns swapped
for log returns: that project works in log-odds because a probability must stay
inside (0, 1), while a pool price has no such ceiling and log-price is the
natural coordinate. The EWMA recursion, the winsorising, and the shrinkage
toward a prior are unchanged, because they were doing the right thing already.
"""

from __future__ import annotations

import math
from collections import deque

from misquote.core.tickmath import Q96
from misquote.core.types import Event
from misquote.estimators.base import TrailingEstimator

SECONDS_PER_HOUR = 3600.0
BAR_SECONDS = 60.0  # one-minute bars, per spec section 5.1
HALF_LIFE_HOURS = 6.0

# EWMA decay for a six-hour half-life sampled every minute: after 360 bars the
# weight must have halved.
DEFAULT_DECAY = 0.5 ** (1.0 / (HALF_LIFE_HOURS * SECONDS_PER_HOUR / BAR_SECONDS))

# Enough bars for the estimate to mean something. Below this the estimator is
# not `ready` and the caller must label whatever it publishes.
MIN_BARS = 30

# A thin pool can print a single swap that moves price several percent and then
# immediately reverts. Left alone that one bar dominates a six-hour EWMA and the
# policy widens its range for the rest of the day on the strength of one trade.
WINSOR_K = 5.0


def log_returns(prices: list[float]) -> list[float]:
    """Consecutive log price changes. Non-positive prices are dropped, not
    tolerated: a zero price is a data defect, and `log(0)` would poison the
    whole window."""
    out: list[float] = []
    for previous, current in zip(prices, prices[1:], strict=False):
        if previous > 0.0 and current > 0.0:
            out.append(math.log(current / previous))
    return out


def ewma_variance(returns: list[float], decay: float) -> float:
    """v_t = decay * v_{t-1} + (1 - decay) * r_t^2, seeded from the first return."""
    if not returns:
        return 0.0
    variance = returns[0] ** 2
    for r in returns[1:]:
        variance = decay * variance + (1.0 - decay) * r * r
    return variance


def winsorise(returns: list[float], k: float = WINSOR_K) -> list[float]:
    """Clamp returns at k times the median absolute return.

    Median-based rather than standard-deviation-based on purpose: the outlier we
    are trying to contain would itself inflate a standard deviation, so the
    threshold would move to accommodate the very bar it should be clipping.
    """
    if not returns:
        return []
    magnitudes = sorted(abs(r) for r in returns)
    median = magnitudes[len(magnitudes) // 2]
    if median <= 0.0:
        return list(returns)
    limit = k * median
    return [max(-limit, min(limit, r)) for r in returns]


def shrink(sigma: float, prior: float, n_obs: int, strength: float = 20.0) -> float:
    """Pull a thin-sample estimate toward a prior, James-Stein style.

    Weight on the sample is n / (n + strength), so a fresh window barely moves
    the prior and a long one almost ignores it. This keeps the first hour after
    a restart from producing a confidently wrong volatility.
    """
    if n_obs <= 0:
        return prior
    weight = n_obs / (n_obs + strength)
    return weight * sigma + (1.0 - weight) * prior


def price_from_sqrt_ratio(sqrt_price_x96: int) -> float:
    """Raw pool price (token1 per token0) from the Q64.96 sqrt ratio.

    Decimals are deliberately not applied: volatility of a log return is
    invariant to a constant scale factor, so converting here would cost
    precision and buy nothing.
    """
    return (sqrt_price_x96 / Q96) ** 2


class SigmaEstimator(TrailingEstimator):
    """Per sqrt-hour volatility of the pool's log price.

    Swaps arrive irregularly, so prices are bucketed into fixed one-minute bars
    and the last price in each bar is used. Using raw swap-to-swap returns
    instead would make the estimate depend on trading frequency rather than on
    volatility — a busy hour would look more volatile than a quiet one at the
    same price range.
    """

    __slots__ = ("_decay", "_prior", "_bars", "_bar_index", "_bar_price", "_max_bars")

    def __init__(
        self,
        *,
        decay: float = DEFAULT_DECAY,
        prior_sigma: float = 0.02,
        max_bars: int = 24 * 60,
    ) -> None:
        super().__init__()
        if not 0.0 < decay < 1.0:
            raise ValueError(f"decay must be in (0, 1), got {decay}")
        self._decay = decay
        self._prior = prior_sigma
        self._max_bars = max_bars
        self._bars: deque[float] = deque(maxlen=max_bars)
        self._bar_index: int | None = None
        self._bar_price: float | None = None

    def _absorb(self, event: Event) -> None:
        if event.kind != "swap" or event.sqrt_price_x96 <= 0:
            return

        index = event.ts // int(BAR_SECONDS)
        price = price_from_sqrt_ratio(event.sqrt_price_x96)

        if self._bar_index is None:
            self._bar_index, self._bar_price = index, price
            return

        if index == self._bar_index:
            self._bar_price = price  # last price wins within a bar
            return

        # A new bar started, so the previous one is final. Gaps are left as gaps
        # rather than forward-filled: a pool with no trades for an hour was not
        # volatile during it, and inventing bars would say otherwise.
        if self._bar_price is not None:
            self._bars.append(self._bar_price)
        self._bar_index, self._bar_price = index, price

    @property
    def bars(self) -> int:
        return len(self._bars)

    @property
    def ready(self) -> bool:
        return len(self._bars) >= MIN_BARS

    def value(self) -> float:
        """Volatility per sqrt-hour.

        The EWMA is computed over one-minute bars, so its square root is a
        per-minute figure; multiplying by sqrt(60) rescales it to the per
        sqrt-hour unit that equations (1) and (2) are written in.
        """
        prices = list(self._bars)
        if self._bar_price is not None:
            prices.append(self._bar_price)  # include the bar in progress

        returns = winsorise(log_returns(prices))
        if not returns:
            return self._prior

        per_minute = math.sqrt(ewma_variance(returns, self._decay))
        per_sqrt_hour = per_minute * math.sqrt(SECONDS_PER_HOUR / BAR_SECONDS)
        return shrink(per_sqrt_hour, self._prior, len(returns))
