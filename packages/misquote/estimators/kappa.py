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

# Spec section 5.2: "Refit daily." Not on every decision — that would make the
# range width jitter every block, and it was half of all replay runtime.
REFIT_INTERVAL_S = 24 * 3600

# One tick, expressed in log-price. This is the conversion the whole units
# problem turns on, so it is named once and used everywhere.
TICK_IN_LOGPRICE = math.log(1.0001)

# PROVISIONAL, and labelled as such on every card that uses it.
#
# Spec section 5.2 says "fall back to kappa_default and label it" but the
# section 8 parameter table has no kappa row at all — the value was never
# given. An unpublished number that sets the range width is exactly what
# Readme rule 6 forbids, so this is a placeholder with a stated basis rather
# than an invented constant: 500 per log-price is the order of magnitude a real
# 0.05% pool fit produces (a per-tick decay near 0.05), and it yields a
# half-width in the tens of ticks rather than the tens of thousands.
#
# Step 8 backfills 30 days of the target pool and replaces this with the
# measured value, published as gap item G-4 alongside the r-squared that
# produced it. A default derived from the pool it will be used on is defensible
# in a way a round number never is.
PROVISIONAL_KAPPA_PER_LOGPRICE = 500.0
PROVISIONAL_KAPPA_PER_TICK = PROVISIONAL_KAPPA_PER_LOGPRICE * TICK_IN_LOGPRICE


@dataclass(frozen=True, slots=True)
class KappaFit:
    """A fit, and everything needed to judge whether to believe it.

    Carries **both unit conventions**, because the spec uses two and never
    reconciles them. Section 5.2 fits `ln(rate) = ln A - kappa*delta` with delta
    "in ticks beyond mid", so the fitted parameter is per tick. Equation (2)
    evaluates `ln(1 + gamma/kappa)`, which is only meaningful if `gamma/kappa`
    is dimensionless — and gamma is per log-price, because `(2/gamma)` has to
    come out in the same units as the half-width it contributes to.

    The two differ by a factor of 10,000. Feeding the per-tick value into
    equation (2) makes `gamma/kappa` about 16 instead of 0.0016, which turns the
    fill term from a small correction into the entire answer and produces a
    half-width of ~35,000 ticks: a range spanning 33x in price, effectively
    full-range, earning nothing while claiming to be concentrated liquidity. It
    is a positive, finite, plausible-looking number that mints without
    reverting, which is why it survived a green test suite.

    So both live here, one conversion between them, and the policy consumes
    `kappa_per_logprice` exclusively. The tearsheet appendix publishes the
    per-tick figure, since that is the one section 5.2 describes measuring.
    """

    kappa_per_tick: float
    ln_a: float
    r_squared: float
    buckets_used: int
    swaps_used: int
    is_fallback: bool

    @property
    def kappa_per_logprice(self) -> float:
        """What equation (2) consumes. The only place the conversion happens."""
        return self.kappa_per_tick / TICK_IN_LOGPRICE

    @property
    def label(self) -> str:
        per_tick = f"{self.kappa_per_tick:.4f}/tick"
        if self.is_fallback:
            return f"kappa = {per_tick} (provisional default; fit r^2 = {self.r_squared:.2f})"
        return f"kappa = {per_tick} (fitted, r^2 = {self.r_squared:.2f}, {self.swaps_used} swaps)"


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
    kappa_default_per_tick: float = PROVISIONAL_KAPPA_PER_TICK,
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
        return KappaFit(kappa_default_per_tick, 0.0, 0.0, 0, len(depths_and_times), True)

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
        return KappaFit(kappa_default_per_tick, 0.0, 0.0, len(xs), len(depths_and_times), True)

    slope, intercept, r_squared = least_squares(xs, ys)
    kappa = -slope  # intensity decays, so the slope is negative

    # A non-positive kappa would mean deep swaps are *more* common than shallow
    # ones, which is not a market — it is a broken window.
    if kappa <= 0.0 or r_squared < r2_floor:
        return KappaFit(
            kappa_default_per_tick, intercept, r_squared, len(xs), len(depths_and_times), True
        )

    return KappaFit(kappa, intercept, r_squared, len(xs), len(depths_and_times), False)


class KappaEstimator(TrailingEstimator):
    """Rolling seven-day fit of the fill-intensity decay."""

    __slots__ = ("_swaps", "_last_tick", "_kappa_default", "_window", "_cache", "_cache_at")

    def __init__(
        self,
        *,
        window_seconds: int = TRAILING_SECONDS,
        kappa_default_per_tick: float = PROVISIONAL_KAPPA_PER_TICK,
        max_swaps: int = 500_000,
    ) -> None:
        super().__init__()
        self._swaps: deque[tuple[int, int]] = deque(maxlen=max_swaps)
        self._last_tick: int | None = None
        self._kappa_default = kappa_default_per_tick
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
                # Deliberately does NOT clear the cache: the refit cadence is
            # daily and driven by the clock, so new data waits its turn.
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
        """The current fit, refitting at most once a day.

        Spec section 5.2 says "refit daily", and this used to refit on every
        decision — every five seconds. That is a deviation in two directions at
        once. Behaviourally, a continuously refitted kappa lets the range width
        jitter every block, where a daily refit gives the piecewise-constant
        parameter the spec describes. And it was 49% of replay runtime, which is
        what makes a thirty-day quote infeasible rather than merely slow.

        Refitting on a fixed cadence rather than "whenever the data changed" also
        makes the result reproducible: the fit depends on the decision clock, not
        on how a caller happened to batch its ingests.
        """
        due = self._cache is None or (self._t - self._cache_at) >= REFIT_INTERVAL_S
        if not due:
            return self._cache

        self._cache = fit_kappa(
            list(self._swaps),
            window_seconds=self._window,
            kappa_default_per_tick=self._kappa_default,
        )
        self._cache_at = self._t
        return self._cache

    def value(self) -> float:
        """The unit equation (2) consumes. Never the per-tick figure."""
        return self.fit().kappa_per_logprice
