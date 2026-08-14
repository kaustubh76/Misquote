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
"""

from __future__ import annotations

import math
from collections import deque

from misquote.core.types import Event
from misquote.estimators.base import TrailingEstimator

# Spec section 3.4's M, published as gap item G-1. Long enough for the sign
# pattern to mean something, short enough to react within minutes on a busy pool.
DEFAULT_WINDOW_SWAPS = 50


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

    __slots__ = ("_volumes", "_window", "_dec1")

    def __init__(self, *, dec1: int, window_swaps: int = DEFAULT_WINDOW_SWAPS) -> None:
        super().__init__()
        if window_swaps < 2:
            raise ValueError("a z-score over fewer than two swaps is not a z-score")
        self._window = window_swaps
        self._dec1 = dec1
        self._volumes: deque[float] = deque(maxlen=window_swaps)

    def _absorb(self, event: Event) -> None:
        if event.kind != "swap":
            return
        # Signed quote volume, straight from the event's own sign convention.
        self._volumes.append(event.amount1 / 10.0**self._dec1)

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
        return imbalance_z(list(self._volumes))
