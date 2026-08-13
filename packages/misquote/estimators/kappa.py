"""Fee-capture intensity decay (spec section 5.2).

In Avellaneda-Stoikov, the rate at which a quote gets filled falls off with its
distance from the mid:

    lambda(delta) = A * exp(-kappa * delta)

The v3 analogue is the rate at which swaps reach a given tick depth. Swaps that
travel far from the current tick are rarer than swaps that stay near it, and how
much rarer is exactly `kappa`. A large `kappa` means fee flow is concentrated at
the mid, so equation (2) tightens the range to sit in it.

Fitting is a least-squares line through `ln(rate) = ln A - kappa * delta` over
depth buckets from a trailing seven days, refit daily. Nothing on this machine
did this before — PolyLambda hand-sets the equivalent constant and never
estimates it — so this is written from the spec rather than ported.

When the fit is poor the spec sanctions falling back to a default, provided the
fallback is labelled. That labelling is not decoration: a range computed from a
guessed parameter is a different claim from one computed from data, and the card
has to say which it is.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from misquote.core.types import Event
from misquote.estimators.base import TrailingEstimator

TRAILING_DAYS = 7
TRAILING_SECONDS = TRAILING_DAYS * 24 * 3600

# Depth buckets in ticks. Geometric rather than uniform because swap depth is
# heavy-tailed: uniform buckets would put almost every swap in the first one and
# leave the rest too sparse to fit a line through.
DEFAULT_BUCKET_EDGES: tuple[int, ...] = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000)

MIN_BUCKETS = 4  # a line through three points is not evidence
MIN_SWAPS = 200
R2_FLOOR = 0.5  # spec section 5.2
KAPPA_DEFAULT = 50.0


@dataclass(frozen=True, slots=True)
class KappaFit:
    """A fit, and everything needed to judge whether to believe it.

    Published in the tearsheet appendix, so a reader can disagree with the
    number rather than having to take it on faith.
    """

    kappa: float
    ln_a: float
    r_squared: float
    buckets_used: int
    swaps_used: int
    is_fallback: bool

    @property
    def label(self) -> str:
        if self.is_fallback:
            return f"kappa = {self.kappa:.1f} (default; fit r^2 = {self.r_squared:.2f})"
        return f"kappa = {self.kappa:.1f} (fitted, r^2 = {self.r_squared:.2f}, {self.swaps_used} swaps)"


def least_squares(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Fit y = intercept + slope*x. Returns (slope, intercept, r_squared).

    r_squared is 0.0 when y has no variance to explain, rather than the 1.0 a
    naive `1 - ss_res/ss_tot` would produce from a zero denominator. Reporting a
    perfect fit for a flat line is how a meaningless kappa gets believed.
    """
    n = len(xs)
    if n < 2:
        return 0.0, 0.0, 0.0

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0.0:
        return 0.0, mean_y, 0.0

    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x

    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    if ss_tot <= 0.0:
        return slope, intercept, 0.0
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys, strict=True))
    return slope, intercept, max(0.0, 1.0 - ss_res / ss_tot)


def fit_kappa(
    depths_and_times: list[tuple[int, int]],
    *,
    window_seconds: int = TRAILING_SECONDS,
    bucket_edges: tuple[int, ...] = DEFAULT_BUCKET_EDGES,
    kappa_default: float = KAPPA_DEFAULT,
    r2_floor: float = R2_FLOOR,
) -> KappaFit:
    """Fit `ln(rate) = ln A - kappa * delta` over depth buckets.

    `depths_and_times` is one `(tick_depth, timestamp)` pair per swap, where
    depth is how far the swap moved from the pre-swap tick.

    A bucket's rate is its count divided by the window length, so buckets with
    no swaps are dropped rather than contributing `ln(0)`. Dropping them biases
    the fit slightly toward shallower depths, which understates kappa, which
    widens the range — the safe direction.
    """
    if len(depths_and_times) < MIN_SWAPS:
        return KappaFit(kappa_default, 0.0, 0.0, 0, len(depths_and_times), True)

    hours = window_seconds / 3600.0
    counts = dict.fromkeys(bucket_edges, 0)
    for depth, _ts in depths_and_times:
        for edge in bucket_edges:
            if depth >= edge:
                counts[edge] += 1

    xs: list[float] = []
    ys: list[float] = []
    for edge in bucket_edges:
        if counts[edge] > 0:
            xs.append(float(edge))
            ys.append(math.log(counts[edge] / hours))

    if len(xs) < MIN_BUCKETS:
        return KappaFit(kappa_default, 0.0, 0.0, len(xs), len(depths_and_times), True)

    slope, intercept, r_squared = least_squares(xs, ys)
    kappa = -slope  # intensity decays, so the slope is negative

    # A non-positive kappa would mean deep swaps are *more* common than shallow
    # ones, which is not a market — it is a broken window.
    if kappa <= 0.0 or r_squared < r2_floor:
        return KappaFit(kappa_default, intercept, r_squared, len(xs), len(depths_and_times), True)

    return KappaFit(kappa, intercept, r_squared, len(xs), len(depths_and_times), False)


class KappaEstimator(TrailingEstimator):
    """Rolling seven-day fit of the fill-intensity decay."""

    __slots__ = ("_swaps", "_last_tick", "_kappa_default", "_window", "_cache", "_cache_at")

    def __init__(
        self,
        *,
        window_seconds: int = TRAILING_SECONDS,
        kappa_default: float = KAPPA_DEFAULT,
        max_swaps: int = 500_000,
    ) -> None:
        super().__init__()
        self._swaps: deque[tuple[int, int]] = deque(maxlen=max_swaps)
        self._last_tick: int | None = None
        self._kappa_default = kappa_default
        self._window = window_seconds
        self._cache: KappaFit | None = None
        self._cache_at: int = -1

    def _absorb(self, event: Event) -> None:
        if event.kind != "swap":
            return
        if self._last_tick is not None:
            depth = abs(event.tick - self._last_tick)
            if depth > 0:
                self._swaps.append((depth, event.ts))
                self._cache = None
        self._last_tick = event.tick

    def _on_time_advanced(self) -> None:
        """Retire swaps that have fallen out of the trailing window."""
        cutoff = self._t - self._window
        while self._swaps and self._swaps[0][1] < cutoff:
            self._swaps.popleft()
            self._cache = None

    @property
    def ready(self) -> bool:
        return len(self._swaps) >= MIN_SWAPS

    def fit(self) -> KappaFit:
        """Refit if anything changed, otherwise reuse.

        The cache is keyed on the decision time as well as on the data, so a
        second call at the same instant cannot return a different answer — which
        would otherwise make a replay non-deterministic in a way that is very
        hard to see.
        """
        if self._cache is not None and self._cache_at == self._t:
            return self._cache
        self._cache = fit_kappa(
            list(self._swaps), window_seconds=self._window, kappa_default=self._kappa_default
        )
        self._cache_at = self._t
        return self._cache

    def value(self) -> float:
        return self.fit().kappa
