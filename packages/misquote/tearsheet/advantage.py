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
class PrimaryMetric:
    """The quantity a task is *named after*, and both sides' value for it.

    Every task here headlines net return, which is the right headline and is not
    always the thing the task asks about. Task 2 is called *"Protect — avoid
    being picked off by one-way flow"* and on exactly that quantity — realized
    convexity cost — the agent wins by a factor of seventeen. The report never
    showed it. A reader was given the number the tasks have in common and not
    the number the task is about.

    This does **not** displace the headline. The net-return figure and its
    verdict are unchanged, including where they are unflattering; this is an
    additional column, and its direction is carried so a cost and a return are
    not read the same way round.
    """

    name: str
    baseline: float
    agent: float
    #: True when smaller is better — a cost, a loss, an error.
    lower_is_better: bool
    unit: str = ""

    @property
    def delta(self) -> float:
        """Agent minus baseline, always. Sign is interpreted by `improved`."""
        return self.agent - self.baseline

    @property
    def improved(self) -> bool:
        return self.delta < 0 if self.lower_is_better else self.delta > 0

    @property
    def ratio(self) -> float | None:
        """How many times better or worse, when that is expressible.

        `None` when the baseline is zero: "seventeen times less" is a useful
        sentence and "infinitely times less" is not one.
        """
        if self.baseline == 0:
            return None
        return self.agent / self.baseline

    def render(self) -> str:
        arrow = "better" if self.improved else "worse"
        body = f"{self.name}: {self.agent:,.6g}{self.unit} vs {self.baseline:,.6g}{self.unit}"
        r = self.ratio
        if r is not None and r > 0:
            factor = (1 / r) if self.lower_is_better else r
            if factor >= 1.05:
                return f"{body} — {factor:.1f}x {arrow}"
        return f"{body} — {arrow}"


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

    #: The quantity this task is named after, when it is not net return.
    #: `None` for a task whose name and headline already agree.
    primary: PrimaryMetric | None = None

    # Where this task's tape came from — "chain" or "synthetic" — per task
    # rather than per report.
    #
    # One report-level flag was not enough. Task 3 compares two venues, and it
    # was possible for tasks 1 and 2 to run on real swaps while task 3 ran on
    # two constructed tapes, under a report stamped `source: chain`. The gate in
    # `go_no_go` read that one flag and passed. The track asks for three *real*
    # tasks, so provenance has to travel with the task that has it.
    source: str = "synthetic"

    # What this task actually ran at, which is not always the report's figure.
    #
    # Task 3 compares two venues, and A1's liquidity ceiling belongs to the
    # *pool*: on the 0.25% tier the report's default capital breached it on 564
    # mints, and A1 refuses such a quote rather than clamping it. So that task
    # runs at a capital derived from the shallower venue, and a report-level
    # `capital_quote` would describe it wrongly while looking authoritative. The
    # prose already said so; a machine reading the artifact could not.
    capital_quote: float = 0.0

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

    # `moves` decomposed. Published because the aggregate hides the mechanism:
    # 498 moves reads as a busy agent, and 249 mints beside 249 pulls and **zero
    # recentres** reads as an agent that spent its entire daily budget leaving
    # and coming back. Those are different findings, and only the second is what
    # the tape shows. See P-20.
    baseline_mints: int = 0
    agent_mints: int = 0
    baseline_pulls: int = 0
    agent_pulls: int = 0
    baseline_recentres: int = 0
    agent_recentres: int = 0

    # How many of the reported samples are actually distinct results.
    #
    # P-17 built this field and this report never published it. A5 counts each
    # window three times under a +/-25% perturbation of (gamma, kappa), so when
    # the anti-dust floor discards both parameters those three replays are one
    # replay — P-17 measured Warden at 23 distinct returns of 60 reported
    # samples. A P25-P75 band drawn from 20 results counted three times is
    # narrower than the evidence supports, and a reader cannot tell without
    # this number.
    baseline_distinct: int = 0
    agent_distinct: int = 0

    # UTC calendar days the replay touched — **not** its elapsed span.
    #
    # The distinction is the difference between a rate that can be compared to
    # `max_rebalances_per_day` and one that cannot. `core.position.
    # rebalances_today` resets on the UTC calendar day of the last move, and
    # says so: *"calendar days are what 'per day' means to the operator reading
    # the parameter."* Dividing 32 cycles by a 2.6-day *span* gives 12.3/day and
    # reads as an agent exceeding a cap of 8; dividing by the 4 calendar days it
    # actually touched gives 8.0, which is the cap being hit exactly.
    days: float = 0.0

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
    capital_quote: float = 0.0,
    primary: PrimaryMetric | None = None,
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
        primary=primary,
        source=source,
        capital_quote=capital_quote,
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
        baseline_mints=_count(baseline_result, "mints"),
        agent_mints=_count(agent_result, "mints"),
        baseline_pulls=_count(baseline_result, "pulls"),
        agent_pulls=_count(agent_result, "pulls"),
        baseline_recentres=_count(baseline_result, "rebalances"),
        agent_recentres=_count(agent_result, "rebalances"),
        baseline_distinct=int(getattr(baseline_quote, "distinct_returns", 0) or 0),
        agent_distinct=int(getattr(agent_quote, "distinct_returns", 0) or 0),
        days=_span_days(agent_result) or _span_days(baseline_result),
    )


def _of(result, name: str) -> float:
    return float(getattr(result, name, 0.0)) if result is not None else 0.0


def _count(result, name: str) -> int:
    return int(getattr(result, name, 0) or 0) if result is not None else 0


def _span_days(result) -> float:
    """UTC calendar days the replay touched, matching the budget's own window.

    Deliberately not the elapsed span. The daily rebalance budget resets on the
    UTC calendar day of the last move (`core.position.rebalances_today`), so a
    rate meant to be read against `max_rebalances_per_day` has to divide by the
    same thing the budget counts in. Elapsed span gives 12.3/day where the
    budget saw 8.0/day, and the report would appear to show the cap being
    breached.

    Returns 0.0 rather than guessing when the result carries no timestamps: a
    rate computed against an assumed window would be wrong in the direction that
    makes the agent look calmer.
    """
    if result is None:
        return 0.0
    first, last = getattr(result, "first_ts", None), getattr(result, "last_ts", None)
    if not first or not last or last < first:
        return 0.0
    return float(last // 86400 - first // 86400 + 1)


def _moves(result) -> int:
    """Every action that spent gas, whatever kind of agent produced it.

    An LP result decomposes into mints, recentres and pulls; an allocation
    result into entries, switches and exits and exposes their sum as `moves`.
    Preferring `moves` when it exists keeps this the one place that knows the
    difference — the sibling accessors above are already defensive, and this one
    reached straight for `result.mints` and raised on anything that was not a
    range replay.
    """
    if result is None:
        return 0
    own = getattr(result, "moves", None)
    if own is not None:
        return int(own)
    return int(_count(result, "mints") + _count(result, "rebalances") + _count(result, "pulls"))


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
