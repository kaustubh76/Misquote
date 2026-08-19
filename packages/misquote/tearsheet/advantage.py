"""Agent advantage: hiring the agent, against doing the job yourself.

This is the one question the TermiX track judges — *"does hiring an agent on your
marketplace beat doing the job yourself, and can you prove it?"* — and until now
we answered it in a unit test and threw the answer away.

`core/policy.py:passive_policy` has existed since Step 7 and was used **only** by
`tests/`. `Tearsheet` had no comparison field, and `scripts/showcase.py` never ran
the baseline. The machinery to answer the judged question was built, tested, and
never once shown to a user.

This used to cite `replay/driver.py:passive_result` alongside it. That function was
called by nothing at all — not here, not the showcase, not a test — and counted
`in_range_samples` per swap event where the live driver counts per decision sample.
Being named here is most of why it survived. It is deleted.

## The claim this module is allowed to make, and why it is credible

**The baseline is not a different program.** "Doing it yourself" runs through
`ReplayDriver` with `policy=passive_policy` — the same engine, the same tape, the
same cost model, the same LVR accountant, the same quote machinery. The only
thing that differs between the two columns is the function that returns a
`Decision`.

That matters more than it sounds. The usual way to make an agent look good is to
compare it against a baseline implemented separately, charged differently, and
measured on a kinder tape. Here that is not possible: swap `policy=` and
everything else is held fixed by construction. The Step 20 policy seam is what
made this a one-line change rather than a second program.

## What "advantage" means here

Net return on deployed capital: fees, minus the realized convexity cost (our
upper bound on LVR, assumption A10), minus every cost of having been there. The
same figure the cards already quote, so the advantage number and the advertised
number cannot disagree.

Two deliberate refusals, both inherited rather than reinvented:

- **A quote below the sample floor is withheld**, not estimated (`replay/ranges`
  requires 20 usable sub-windows, each at least as long as the policy horizon).
- **A verdict below 30 observations is refused** (`tearsheet.verdict`, ported
  from Mission Control's `_verdict(min_n=30)`).

So a task can legitimately come back saying *nobody can yet tell*, and that is a
result rather than a failure. An advantage report that always produces a number
is not measuring anything.

## Sign convention

`delta` is agent minus baseline, in percentage points of return on capital. It is
**allowed to be negative**, and on at least one tape it already is: a driftless
random walk with a tight range pays gas for nothing, and the honest answer is
that hiring the agent lost money. Publishing that is the entire point of the
project, so nothing here clamps, hides, or reorders on sign.
"""

from __future__ import annotations

from dataclasses import dataclass

from misquote.tearsheet.generate import MIN_OBSERVATIONS, Verdict, verdict

# Below this many percentage points, an advantage is noise dressed as a result.
# A tenth of a point of annualised return on a thousand dollars is ten cents, and
# claiming an edge from it would be the misquote in miniature.
MATERIAL_PP = 0.10


@dataclass(frozen=True, slots=True)
class Comparison:
    """One task, done both ways, with everything needed to disbelieve it."""

    task: str
    category: str  # "trading" | "security"
    venue: str
    metric: str

    without_agent: str  # what "doing it yourself" concretely was
    with_agent: str

    baseline_p50: float
    agent_p50: float
    baseline_p25: float
    agent_p25: float
    baseline_p75: float
    agent_p75: float

    quotable: bool  # both sides cleared the sample floor
    note: str
    windows: int

    # Where this task's tape came from — "chain" or "synthetic" — per task
    # rather than per report.
    #
    # One report-level flag was not enough. Task 3 compares two venues, and it
    # was possible for tasks 1 and 2 to run on real swaps while task 3 ran on
    # two constructed tapes, under a report stamped `source: chain`. The gate in
    # `go_no_go` read that one flag and passed. The track asks for three *real*
    # tasks, so provenance has to travel with the task that has it.
    source: str = "synthetic"

    # Supporting detail, published because the headline alone is not auditable.
    baseline_in_range: float = 0.0
    agent_in_range: float = 0.0
    baseline_costs: float = 0.0
    agent_costs: float = 0.0
    baseline_fees: float = 0.0
    agent_fees: float = 0.0
    baseline_lvr: float = 0.0
    agent_lvr: float = 0.0
    baseline_moves: int = 0
    agent_moves: int = 0

    @property
    def delta(self) -> float:
        """Agent minus baseline, in percentage points. May be negative."""
        return self.agent_p50 - self.baseline_p50

    @property
    def ranges_overlap(self) -> bool:
        """Do the two P25-P75 bands overlap?

        If they do, the two strategies are not distinguishable at this sample
        size however far apart their medians sit — and a report that leads with
        the median difference while the bands overlap is quoting a difference it
        cannot support. This is the whole reason the product publishes ranges.
        """
        return self.agent_p25 <= self.baseline_p75 and self.baseline_p25 <= self.agent_p75

    @property
    def material(self) -> bool:
        return abs(self.delta) >= MATERIAL_PP

    @property
    def separated(self) -> bool:
        """Quotable, material, and the bands do not overlap."""
        return self.quotable and self.material and not self.ranges_overlap

    def verdict_line(self) -> str:
        """One sentence a judge can read, including the refusals."""
        if not self.quotable:
            return f"no verdict — {self.note}"
        direction = "beats" if self.delta > 0 else "loses to"
        if not self.material:
            return (
                f"indistinguishable: {self.delta:+.2f}pp is below the "
                f"{MATERIAL_PP:.2f}pp materiality floor"
            )
        if self.ranges_overlap:
            return (
                f"agent {direction} DIY by {abs(self.delta):.2f}pp at the median, "
                f"but the P25-P75 bands overlap — not separated at this sample size"
            )
        return f"agent {direction} DIY by {abs(self.delta):.2f}pp, bands do not overlap"


def compare(
    *,
    task: str,
    category: str,
    venue: str,
    metric: str,
    without_agent: str,
    with_agent: str,
    baseline_quote,
    agent_quote,
    baseline_result=None,
    agent_result=None,
    source: str = "synthetic",
) -> Comparison:
    """Build a `Comparison` from two quotes produced by the same engine.

    Takes `Quote` objects rather than raw numbers so the sample-size refusal
    travels with the data: if either side could not be quoted, the comparison
    inherits that and says so instead of subtracting two zeros and reporting a
    confident nil.
    """
    quotable = bool(baseline_quote.sufficient and agent_quote.sufficient)
    if not quotable:
        which = []
        if not baseline_quote.sufficient:
            which.append(f"baseline: {baseline_quote.note}")
        if not agent_quote.sufficient:
            which.append(f"agent: {agent_quote.note}")
        note = "; ".join(which)
    else:
        note = agent_quote.basis

    return Comparison(
        task=task,
        category=category,
        venue=venue,
        metric=metric,
        without_agent=without_agent,
        with_agent=with_agent,
        baseline_p50=baseline_quote.p50,
        agent_p50=agent_quote.p50,
        baseline_p25=baseline_quote.p25,
        agent_p25=agent_quote.p25,
        baseline_p75=baseline_quote.p75,
        agent_p75=agent_quote.p75,
        quotable=quotable,
        note=note,
        windows=agent_quote.windows,
        source=source,
        baseline_in_range=_of(baseline_result, "in_range_fraction"),
        agent_in_range=_of(agent_result, "in_range_fraction"),
        baseline_costs=_of(baseline_result, "total_costs"),
        agent_costs=_of(agent_result, "total_costs"),
        baseline_fees=_of(baseline_result, "total_fees"),
        agent_fees=_of(agent_result, "total_fees"),
        baseline_lvr=_of(baseline_result, "total_lvr"),
        agent_lvr=_of(agent_result, "total_lvr"),
        baseline_moves=_moves(baseline_result),
        agent_moves=_moves(agent_result),
    )


def _of(result, name: str) -> float:
    return float(getattr(result, name, 0.0)) if result is not None else 0.0


def _moves(result) -> int:
    if result is None:
        return 0
    return int(result.mints + result.rebalances + result.pulls)


def overall(comparisons: list[Comparison]) -> Verdict:
    """Across every task: how often did hiring the agent actually win?

    Uses the same `verdict(min_n=30)` the tearsheet uses, which means with three
    or six tasks it will **refuse to call it** — three observations are not
    evidence about a strategy, and a report claiming "the agent wins 3 of 3" from
    three tapes would be doing the thing this project argues against.

    The refusal is the honest headline. What carries the argument is each task's
    own quote, where the sample size is twenty sub-windows times three parameter
    perturbations rather than one.
    """
    quotable = [c for c in comparisons if c.quotable]
    wins = sum(1 for c in quotable if c.delta > 0 and c.material)
    return verdict(wins, len(quotable), 0.5, min_n=MIN_OBSERVATIONS)


def summarise(comparisons: list[Comparison]) -> dict:
    """Counts a reader can check against the table without re-adding it."""
    quotable = [c for c in comparisons if c.quotable]
    return {
        "tasks": len(comparisons),
        "quotable": len(quotable),
        "withheld": len(comparisons) - len(quotable),
        "agent_ahead": sum(1 for c in quotable if c.delta > 0 and c.material),
        "diy_ahead": sum(1 for c in quotable if c.delta < 0 and c.material),
        "indistinguishable": sum(1 for c in quotable if not c.material),
        "bands_overlap": sum(1 for c in quotable if c.ranges_overlap),
        "separated": sum(1 for c in quotable if c.separated),
        "categories": sorted({c.category for c in comparisons}),
        "venues": sorted({c.venue for c in comparisons}),
    }
