"""Signed swap-volume imbalance (spec section 3.4, second arm).

Spec section 3.4 defines toxicity as two conditions joined by `or`:

    TOXIC iff  |g_t| > fee_tier + arb_cost_bps  for m consecutive samples,
           or  imb_t > z_pull

The first arm needs a CEX feed. The second needs only the pool, which makes it
the arm that works when the feed is down — and it was the arm that had never
run. `Engine._observe` passed a literal `0.0` for `swap_imbalance_z`, so
`z_pull = 2.5` and `M = 50` were parameters that traced to nothing, the policy's
imbalance branch was unreachable, and half of section 3.4 was decoration. The
unit test for that branch passed the whole time, because it handed the policy a
z-score directly; nothing tested that anything ever computed one.

It surfaced while building Sentinel, whose entire strategy is threshold de-risk.
Warden only consults this arm as one gate among four and Grid ignores it, so
neither agent could tell the difference between a quiet signal and a dead one.

## The statistic

One swap's signed quote volume is just `amount1`, decimal-adjusted. The sign
falls out of the event's own convention rather than being reconstructed: amounts
are signed from the pool's perspective, so `amount1 > 0` means the pool received
token1 — a buy of token0, pushing price up — and `amount1 < 0` means it paid
token1 out. No direction inference, no microprice, nothing to get backwards.

Over the trailing M swaps:

    z = sum(s_i) / sqrt(sum(s_i^2))

which is the standardised statistic under the null that each swap's *direction*
is an independent fair coin with its magnitude held as observed. Under that null
`E[sum s] = 0` and `Var[sum s] = sum s^2`, so z is the sum in units of its own
standard deviation.

That null is conditional — a permutation null on the signs, not an assumption
that volumes are normal — so z is not N(0,1) in small samples. It is bounded:

    |z| <= sqrt(M)

with equality when every swap in the window is the same size and the same
direction. At M = 50 that ceiling is 7.07, which is what makes `z_pull = 2.5`
a threshold the rule can actually reach. A `z_pull` at or above `sqrt(M)` would
be unreachable by construction — a gate wired to nothing in a second, subtler
way — so `Params` now refuses that combination rather than letting it look
configured.

Two properties worth stating because they are the reason for this form rather
than a simpler one:

- **One whale is not toxic flow.** A single swap far larger than the rest drives
  numerator and denominator equally, so z tends to 1 — well under any sane
  threshold. Persistent one-way flow is what moves it, which is the thing the
  rule is actually about.
- **Balanced churn is not toxic flow.** Heavy two-way volume cancels in the
  numerator and accumulates in the denominator, pushing z toward zero. A busy
  pool does not read as an unsafe one.

Amounts are gross of fee, which biases each magnitude by the fee tier — 0.05%
here, in the same direction for both terms of the ratio. It is far below the
resolution of a threshold set at 2.5, and correcting it would mean reconstructing
per-swap fees for a statistic that is scale-free by construction.

## Why the threshold is calibrated rather than constant

Because the paragraph above is true — this is not N(0,1) — a threshold chosen as
though it were is not a threshold at all. Spec section 8 sets `z_pull = 2.5`,
which reads like a two-and-a-half-sigma event and is not one. Measured over
252,874 samples of the flagship pool the median |z| is **2.179**, so the spec's
rule fires on **41.94%** of samples, and it fires on 42.8% of a pool eighty-four
times shallower (P-19, P-23). A screen that fires on two samples in five is not
selecting; it is describing BSC.

That is a mis-specification of the same kind as V-1, where kappa's per-tick and
per-log-price readings differed by 10,000x: a number correct for a quantity that
is not the one it is applied to. The fix is the same shape too — apply the
threshold in the units the statistic actually has. Here that means a quantile of
the statistic's own trailing distribution, measured on the same pool by the same
estimator, rather than a constant transplanted from a distribution it does not
have.

`z_pull` survives as the fallback for the first `MIN_CALIBRATION_SAMPLES`
readings, so the spec's number still traces to something and the rule is defined
from the first sample. Published as assumption A16.

**This is not tuning.** The quantile is of the *input* distribution and is blind
to whether the resulting pull earned or lost anything: it never sees fees, gas,
LVR, or the position. Calibrating a threshold against outcomes would be the thing
P-23 refuses, and it would look nothing like this.
"""

from __future__ import annotations

import math
from collections import deque

from misquote.core.types import Event
from misquote.estimators.base import TrailingEstimator

# Spec section 3.4's M, published as gap item G-1. Long enough for the sign
# pattern to mean something, short enough to react within minutes on a busy pool.
DEFAULT_WINDOW_SWAPS = 50

# How many trailing samples the threshold is calibrated over, and how often that
# calibration is redone. A day of 5-second samples, recalibrated hourly.
#
# The stride exists for cost, not for semantics: the quantile is exact when it is
# computed, and between computations it is up to an hour stale. An hour-old
# quantile of a day-long window differs from a fresh one in its last decimals,
# and paying a sort per 5-second sample to chase that would multiply the replay's
# cost for no change in any decision.
DEFAULT_CALIBRATION_SAMPLES = 17_280
DEFAULT_CALIBRATION_STRIDE = 720

# Below this many readings the empirical quantile is not a quantile — it is the
# largest of a handful of numbers. The caller is told `threshold_ready` is false
# and falls back to the published constant rather than acting on it.
MIN_CALIBRATION_SAMPLES = 2_000


def imbalance_z(signed_volumes: list[float]) -> float:
    """`sum(s) / sqrt(sum(s^2))`, or 0.0 when there is nothing to standardise.

    Pure, so the test suite can check the statistic against hand arithmetic
    without constructing events or an estimator.
    """
    if not signed_volumes:
        return 0.0
    total = math.fsum(signed_volumes)
    sum_squares = math.fsum(v * v for v in signed_volumes)
    if sum_squares <= 0.0:
        # Every swap in the window moved zero quote volume. There is no
        # direction to detect, and dividing would produce a NaN that makes every
        # downstream Decision unequal to itself — the exact failure that made
        # test T1 unpassable on the feed-down path.
        return 0.0
    return total / math.sqrt(sum_squares)


class ImbalanceEstimator(TrailingEstimator):
    """Rolling z-score of signed swap-volume imbalance over M swaps.

    Count-windowed rather than time-windowed, because section 3.4 says "trailing
    M swaps" and that is a count. The consequence is worth naming: if flow stops
    entirely, the window keeps its last M swaps however old they are, so the
    z-score goes stale rather than decaying to zero. Sigma handles its own gaps
    for exactly this reason, and this one deliberately does not, because adding a
    staleness horizon would mean inventing a parameter the spec never published.

    The bounded harm is what makes that acceptable: the rule's only consequence
    is withdrawing the range, and a range earns nothing during dead flow anyway.

    The window is recomputed rather than kept as a running sum. That is O(M) per
    read with M = 50, which is nothing, and it avoids the accumulated
    add-then-subtract drift that would make two runs over the same prefix differ
    in their last bits — and test T1 compares decisions bitwise.
    """

    __slots__ = (
        "_volumes",
        "_window",
        "_dec1",
        "_history",
        "_stride",
        "_since_calibration",
        "_cached_quantile",
        "_cached_at",
        "_last_z",
        "_z_dirty",
    )

    def __init__(
        self,
        *,
        dec1: int,
        window_swaps: int = DEFAULT_WINDOW_SWAPS,
        calibration_samples: int = DEFAULT_CALIBRATION_SAMPLES,
        calibration_stride: int = DEFAULT_CALIBRATION_STRIDE,
    ) -> None:
        super().__init__()
        if window_swaps < 2:
            raise ValueError("a z-score over fewer than two swaps is not a z-score")
        if calibration_samples < 2:
            raise ValueError("a quantile over fewer than two readings is not a quantile")
        if calibration_stride < 1:
            raise ValueError("calibration stride must be at least one sample")
        self._window = window_swaps
        self._dec1 = dec1
        self._volumes: deque[float] = deque(maxlen=window_swaps)
        # Trailing |z| readings, one per decision sample. See `_on_time_advanced`
        # for why recording them there is what makes this trailing-only.
        self._history: deque[float] = deque(maxlen=calibration_samples)
        self._stride = calibration_stride
        self._since_calibration = calibration_stride
        self._cached_quantile = 0.0
        self._cached_at = 0
        # The z-score as of the last `value()`, and whether a swap has arrived
        # since. `_on_time_advanced` wants exactly the number the previous
        # decision was shown, and recomputing it is a second `fsum` over the
        # window on every one of a 500,000-sample replay's steps.
        self._last_z = 0.0
        self._z_dirty = True

    @property
    def ceiling(self) -> float:
        """`sqrt(M)` — the largest |z| this statistic can produce.

        Published because it is the only principled upper bound on a threshold:
        `Params` refuses a `z_pull` at or above it, and a calibrated quantile is
        checked against it for the same reason.
        """
        return math.sqrt(self._window)

    def _on_time_advanced(self) -> None:
        """Record the previous sample's |z| into the calibration history.

        This runs from `set_decision_time`, which `Engine.step` calls *before*
        ingesting the events belonging to the new sample. So the reading captured
        here is the one the previous decision saw, and the history can only ever
        contain values that were already public when they were recorded. That
        ordering is the whole no-look-ahead argument for the calibrated threshold,
        and it is why this lives in the hook rather than in `value()`.

        Nothing is recorded before the swap window fills, because `value()`
        returns 0.0 as "no verdict" until then and a run of manufactured zeros
        would drag the quantile down exactly when the pool is quietest.
        """
        if not self.ready:
            return
        self._history.append(abs(self._current_z()))
        self._since_calibration += 1

    @property
    def threshold_ready(self) -> bool:
        """Whether the history is long enough to be read as a distribution."""
        return len(self._history) >= MIN_CALIBRATION_SAMPLES

    def threshold(self, quantile: float) -> float:
        """The empirical `quantile` of trailing |z|, recomputed every stride.

        Nearest-rank on the sorted window: with 17,280 readings the difference
        between interpolation methods is far below the resolution of the decision
        this feeds, and nearest-rank has the property that the value returned is
        one the pool actually produced rather than an average of two it did not.

        Cached between strides. The cache key is the number of readings taken,
        not a clock, so two runs over the same prefix recalibrate at the same
        samples and produce the same thresholds — which is what test T1 needs,
        since this number reaches `Decision.reasons`.
        """
        if not 0.0 < quantile < 1.0:
            raise ValueError(f"quantile must lie strictly in (0, 1), got {quantile}")
        if not self.threshold_ready:
            return 0.0
        if self._since_calibration >= self._stride or self._cached_at == 0:
            ordered = sorted(self._history)
            rank = min(len(ordered) - 1, int(math.ceil(quantile * len(ordered))) - 1)
            self._cached_quantile = ordered[max(0, rank)]
            self._cached_at = len(self._history)
            self._since_calibration = 0
        return self._cached_quantile

    def _current_z(self) -> float:
        """The z-score over the window as it stands, computed at most once.

        Recomputed only when a swap has arrived since the last read. The value is
        a pure function of `_volumes`, so caching it cannot change a result — and
        it must not, because test T1 compares decisions bitwise and this number
        reaches every one of them.
        """
        if self._z_dirty:
            self._last_z = imbalance_z(list(self._volumes))
            self._z_dirty = False
        return self._last_z

    def _absorb(self, event: Event) -> None:
        if event.kind != "swap":
            return
        # Signed quote volume, straight from the event's own sign convention.
        self._volumes.append(event.amount1 / 10.0**self._dec1)
        self._z_dirty = True

    @property
    def ready(self) -> bool:
        """A full window, or no verdict.

        The same sample-size discipline the LVR-versus-fees arm applies before it
        will call a pool toxic, and the tearsheet applies before it will call a
        result. A z-score computed from four swaps is a number, not evidence, and
        publishing it would let a quiet start read as an emergency.
        """
        return len(self._volumes) >= self._window

    def value(self) -> float:
        """The z-score, or 0.0 — meaning no verdict — before the window fills."""
        if not self.ready:
            return 0.0
        return self._current_z()
