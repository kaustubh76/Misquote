"""The quote: a P25-P75 range, and the assumptions that produced it.

This is the feature the product is named for. Other marketplaces answer "what
will this agent earn?" with one number, and a single number implies a precision
nobody has. Misquote answers with a range and shows its working.

The range comes from two sources of spread, both required by assumption A5:

**Sampling spread.** The history is cut into K >= 20 overlapping sub-windows and
the policy is replayed on each. A strategy that earned well in one particular
fortnight and badly in the next has a wide range, and it should — that width is
the honest statement about how much the single number depends on when you
started.

**Parameter spread.** Gamma and kappa are perturbed by +/-25%, because neither is
known precisely. Gamma is a user preference with three published settings; kappa
is a fitted parameter whose functional form is a documented approximation
(assumption A8). A quote that collapses under a quarter's wiggle in either was
never a quote.

The result carries the sample count, and below a floor it refuses to quote at
all rather than extrapolating from four windows. That refusal is ported in
spirit from Mission Control's `_verdict(min_n=30)`, which is the single most
important line in the tearsheet generator.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from misquote.core.types import Params, Policy, PoolMeta
from misquote.replay.driver import CostModel, ReplayDriver, ReplayResult


@dataclass(frozen=True, slots=True)
class Quote:
    """What a card shows, and everything needed to disbelieve it."""

    p25: float
    p50: float
    p75: float

    samples: int
    windows: int
    perturbations: int

    in_range_p50: float
    rebalances_p50: float
    hours_per_window: float

    sufficient: bool
    note: str
    annualised: bool = False
    basis: str = ""

    # How many of the usable replays actually finished in profit. This is the
    # honest numerator for "does it beat holding": one observation per replay,
    # `samples` of them. `showcase.emit` used to invent this denominator as
    # `result.samples // 100` — 44,802 decisions became "448 windows", all of
    # them agreeing, from a single replay. That manufactured exactly the sample
    # size `tearsheet.verdict(min_n=30)` exists to refuse.
    net_positive: int = 0

    # The individual window returns behind the percentiles, so a reader can see
    # the distribution rather than three order statistics of it.
    returns: tuple[float, ...] = ()

    @property
    def spread(self) -> float:
        return self.p75 - self.p25

    def render(self, unit: str = "%") -> str:
        if not self.sufficient:
            return f"not enough history to quote ({self.note})"
        return (
            f"{self.p25:.2f}{unit} to {self.p75:.2f}{unit} "
            f"(median {self.p50:.2f}{unit}, {self.basis})"
        )


# Assumption A5's floor. Below this the spread describes the sample, not the
# strategy.
MIN_SAMPLES = 20

# A window shorter than the policy's own horizon never completes a decision
# cycle, so replaying one measures startup rather than strategy. Twenty such
# windows are still twenty measurements of nothing.
MIN_WINDOW_HOURS = 24.0

# Annualising is a multiplication, and multiplying an eight-hour result by a
# thousand does not make it an annual one — it makes a fixed rebalance cost look
# like a catastrophe and a lucky afternoon look like a fortune. Below this the
# quote states the period it actually covers.
MIN_HOURS_TO_ANNUALISE = 7 * 24.0


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile, with no numpy dependency.

    Written out rather than imported because the whole point of this number is
    that a reader can reproduce it, and "we called a library" is a worse answer
    than four lines of arithmetic.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def rolling_windows(first_ts: int, last_ts: int, count: int) -> list[tuple[int, int]]:
    """`count` overlapping sub-windows spanning the history.

    Overlapping rather than disjoint because disjoint windows over a 30-day tape
    would each be a day and a half — too short for a 24-hour policy horizon to
    mean anything. Overlap trades independence for sample length, which is the
    right trade when the alternative is twenty windows that each contain one
    decision cycle.
    """
    span = last_ts - first_ts
    if span <= 0 or count < 1:
        return []

    width = max(1, int(span * 0.5))  # each window covers half the history
    if count == 1:
        return [(first_ts, first_ts + width)]

    stride = max(1, (span - width) // (count - 1))
    windows = []
    for i in range(count):
        # The last window is anchored to the end rather than extrapolated from
        # the stride: integer division truncates, so the accumulated remainder
        # would leave the most recent hours of history unquoted — the hours a
        # reader is most likely to care about.
        if i == count - 1:
            start = max(first_ts, last_ts - width)
        else:
            start = first_ts + i * stride
        end = min(start + width, last_ts)
        if end > start:
            windows.append((start, end))
    return windows


def perturbations(params: Params, fraction: float = 0.25) -> list[Params]:
    """Gamma and kappa at their nominal values and at +/- `fraction`.

    Assumption A5. Kappa is perturbed through the policy's consumed value rather
    than through the estimator, so the sensitivity being measured is the quote's,
    not the fit's.
    """
    out = []
    for gamma_scale in (1.0 - fraction, 1.0, 1.0 + fraction):
        out.append(dataclasses.replace(params, gamma=params.gamma * gamma_scale))
    return out


def quote_from_results(
    results: Sequence[ReplayResult],
    *,
    windows: int,
    perturbation_count: int,
    capital_quote: float = 1000.0,
    annualise: bool = True,
) -> Quote:
    """Turn a set of replays into a published range.

    The metric is net return on deployed capital, annualised — fees, minus the
    adverse-selection upper bound, minus every cost of having been there.
    """
    usable = [r for r in results if r.samples > 0 and r.hours >= MIN_WINDOW_HOURS]
    if len(usable) < MIN_SAMPLES:
        short = [r for r in results if 0 < r.hours < MIN_WINDOW_HOURS]
        detail = f"{len(usable)} usable replays, assumption A5 requires {MIN_SAMPLES}"
        if short:
            detail += (
                f"; {len(short)} window(s) were shorter than the "
                f"{MIN_WINDOW_HOURS:.0f}h policy horizon"
            )
        return Quote(
            p25=0.0,
            p50=0.0,
            p75=0.0,
            samples=len(usable),
            windows=windows,
            perturbations=perturbation_count,
            in_range_p50=0.0,
            rebalances_p50=0.0,
            hours_per_window=0.0,
            sufficient=False,
            note=detail,
            net_positive=0,
            returns=(),
        )

    median_hours = percentile([r.hours for r in usable], 0.5)
    do_annualise = annualise and median_hours >= MIN_HOURS_TO_ANNUALISE

    returns = []
    for r in usable:
        # A *return*, not an amount: net token1 over the capital that earned it.
        # Reporting the raw amount makes the quote depend on position size,
        # which is not a property of the strategy.
        fraction = r.net_quote / capital_quote if capital_quote > 0 else 0.0
        scale = (365 * 24 / r.hours) if do_annualise else 1.0
        returns.append(100.0 * fraction * scale)

    basis = (
        "annualised"
        if do_annualise
        else f"over {median_hours:.0f}h — too short to annualise honestly"
    )

    return Quote(
        p25=percentile(returns, 0.25),
        p50=percentile(returns, 0.50),
        p75=percentile(returns, 0.75),
        samples=len(usable),
        windows=windows,
        perturbations=perturbation_count,
        in_range_p50=percentile([r.in_range_fraction for r in usable], 0.5),
        rebalances_p50=percentile([float(r.rebalances) for r in usable], 0.5),
        hours_per_window=percentile([r.hours for r in usable], 0.5),
        sufficient=True,
        note="",
        annualised=do_annualise,
        basis=basis,
        # Counted on net_quote rather than on the annualised return so the count
        # cannot disagree with the driver about which replays made money: the
        # annualisation scale is strictly positive, but it is a transform, and
        # the fact being counted is "this window finished ahead".
        net_positive=sum(1 for r in usable if r.net_quote > 0),
        returns=tuple(returns),
    )


# Populated by `quote()` immediately before a pool is forked, and read by the
# worker in the child. It is never pickled, and that is the point: `policy` is a
# closure (`sentinel_policy` returns one, and so does `grid_policy`) and so is
# every `tape_factory` in this repository. Neither survives a pickle, so a
# spawn-based pool cannot carry them and passing them per-task is not an option.
# Fork hands the child the parent's memory instead, copy-on-write, and the only
# thing crossing the pipe is a pair of small integers.
_FORKED: dict[str, Any] = {}


def _replay_one(index: tuple[int, int]) -> ReplayResult:
    """One (window, perturbation) replay, reading the inherited `_FORKED`."""
    window_index, variant_index = index
    start, end = _FORKED["spans"][window_index]
    tape = _FORKED["tape_factory"](start, end)
    try:
        driver = ReplayDriver(
            _FORKED["meta"],
            params=_FORKED["variants"][variant_index],
            costs=_FORKED["costs"],
            capital_quote=_FORKED["capital_quote"],
            policy=_FORKED["policy"],
        )
        result = driver.run(tape)
    finally:
        tape.close()

    # Everything the quote reads is a scalar: samples, hours, in_range_fraction,
    # rebalances, net_quote. `decisions` and `timestamps` hold ~24,000 entries
    # per window and are read by nothing downstream — `quote()` passes `results`
    # to `quote_from_results` and nowhere else. Shipping them back would cost
    # more than the replay that produced them.
    result.decisions = []
    result.timestamps = []
    return result


def quote(
    meta: PoolMeta,
    tape_factory,
    *,
    params: Params | None = None,
    costs: CostModel | None = None,
    capital_quote: float = 1000.0,
    windows: int | None = None,
    perturbation_fraction: float = 0.25,
    policy: Policy | None = None,
    map_fn: Callable[[Callable[..., Any], Iterable[Any]], Iterator[Any]] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> Quote:
    """Replay across sub-windows and parameter perturbations, then quote.

    `tape_factory(start_ts, end_ts)` must return a *fresh* tape each call. A
    tape is stateful in its frontier and cannot be rewound — deliberately, since
    rewinding is how a replay quietly restarts its clock — so reusing one across
    windows would raise rather than silently produce a wrong answer.

    `map_fn` decides *where* the window x perturbation replays run; this function
    decides *what* runs. It defaults to the builtin `map`, so every existing
    caller and test is unaffected, and `misquote.ops.parallel.fork_map(n)` spreads
    them across processes. The capability lives there rather than here because
    `replay` is a pure layer and `tests/test_layering.py` bans it from importing
    `multiprocessing` — a rule that caught the first version of this code.

    The replays are independent by construction: each builds its own driver over
    its own tape and shares no state. So parallelising changes no arithmetic
    anywhere, which is the whole reason it is the right lever. Sigma's value
    feeds the policy and T1/L1 compare decisions bitwise, so making the estimator
    incremental would change summation order and therefore change bits; running
    the same arithmetic on eight cores cannot.

    Measured on the 30-day WBNB/USDT tape: 1,839 events/s, 60 replays of ~125,700
    events each, 4.6 hours for the four agents the showcase runs. 86% of that is
    the sigma estimator recomputing its whole ~841-bar window on every event.
    """
    base = params or Params()
    window_count = windows or base.replay_windows
    variants = perturbations(base, perturbation_fraction)

    probe = tape_factory(None, None)
    first_ts, last_ts = probe.first_ts, probe.last_ts
    probe.close()
    if first_ts is None or last_ts is None:
        return quote_from_results(
            [],
            windows=window_count,
            perturbation_count=len(variants),
            capital_quote=capital_quote,
        )

    spans = rolling_windows(first_ts, last_ts, window_count)
    plan = [(w, v) for w in range(len(spans)) for v in range(len(variants))]

    _FORKED.update(
        meta=meta,
        spans=spans,
        variants=variants,
        tape_factory=tape_factory,
        costs=costs,
        capital_quote=capital_quote,
        policy=policy,
    )
    try:
        # `_FORKED` is populated *before* the first result is pulled, because a
        # forking `map_fn` creates its pool lazily on the first `next()` and the
        # children inherit whatever is here at that moment.
        #
        # Both maps yield in submission order, so `results` is assembled exactly
        # as a plain loop would assemble it — which is what keeps `returns` and
        # `net_positive` identical rather than merely equivalent.
        runner = map_fn or map
        results = []
        for done, result in enumerate(runner(_replay_one, plan), start=1):
            results.append(result)
            if on_progress:
                on_progress(done, len(plan))
    finally:
        _FORKED.clear()

    return quote_from_results(
        results,
        windows=window_count,
        perturbation_count=len(variants),
        # Forwarded, which it was not. `quote_from_results` divides net token1 by
        # this to turn an amount into a return, and its default is 1000.0 — so a
        # caller passing `capital_quote=5000` replayed with 5,000 of capital and
        # had the result divided by 1,000, reporting a return five times too
        # high. The early-return path above passed it; this one did not, and the
        # two disagreed in silence. Both CLIs default to 1000.0, which is why it
        # never showed.
        capital_quote=capital_quote,
    )
