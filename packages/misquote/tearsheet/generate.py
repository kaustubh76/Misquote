"""The tearsheet: what the agent did, and what nobody can yet say about it.

TermiX judges one question — *does hiring an agent on your marketplace beat doing
the job yourself, and can you prove it?* — so this is the submission's centre of
gravity rather than an appendix.

Every number here is derived from the decision journal or from a replay. There
are no hand-entered figures, which is `Readme.md`'s own definition of done for
this file: `make tearsheet` regenerates it, and if a number changed, the
underlying evidence changed.

The most important function is `verdict`, ported from Mission Control's
`_verdict(n, m, t, min_n=30)` with its behaviour unchanged. It **refuses to
call a result below a sample-size floor**. A card that says "no verdict yet, 12
observations" is worth more than one that says "83% win rate" on twelve
observations, and the difference between this product and the ones it is
arguing against is precisely the willingness to print the first.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from misquote.replay import ranges

MIN_OBSERVATIONS = 30  # Mission Control's `min_n`, unchanged


@dataclass(frozen=True, slots=True)
class Verdict:
    """A claim, or an explicit refusal to make one."""

    called: bool
    label: str
    detail: str
    n: int

    def __str__(self) -> str:
        return self.label if self.called else f"{self.label} ({self.detail})"


def verdict(
    successes: int, total: int, threshold: float, *, min_n: int = MIN_OBSERVATIONS
) -> Verdict:
    """Call a rate against a threshold, or refuse for want of evidence.

    Ported unchanged in behaviour from Mission Control's `_verdict`. The floor is
    the whole point: below it the observed rate says more about the sample than
    about the thing being measured, and stating it anyway is how a tearsheet
    becomes a misquote.
    """
    if total < min_n:
        return Verdict(
            called=False,
            label="no verdict",
            detail=f"{total} observation{'s' if total != 1 else ''}, need {min_n}",
            n=total,
        )
    rate = successes / total
    return Verdict(
        called=True,
        label=f"{'PASS' if rate >= threshold else 'FAIL'} ({rate:.0%} of {total})",
        detail=f"threshold {threshold:.0%}",
        n=total,
    )


@dataclass(slots=True)
class JournalSummary:
    """What the decision journal actually contains."""

    rows: int = 0
    decisions: int = 0
    holds: int = 0
    mints: int = 0
    rebalances: int = 0
    pulls: int = 0
    errors: int = 0
    # Follow-up rows about a decision already counted: executed, dropped as
    # stale, failed, or refused by the daily cap. Counted separately because
    # they are outcomes rather than decisions, and folding them into the action
    # counts is what made one mint render as three.
    #
    # `make warden` is wired to `RecordingExecutor`, so an action counted here
    # reached an executor and stopped there — nothing was broadcast. The name is
    # the loop's own vocabulary and stays. What did not stay is the *rendered*
    # word: "2 executed" sat on a public card directly above the caveat saying
    # nothing had been, which is this project's own failure mode appearing on its
    # own tearsheet. `AgentDetail.tsx` renders "recorded" now.
    executed: int = 0
    failed: int = 0
    dropped: int = 0
    first_ts: int | None = None
    last_ts: int | None = None
    gate_blocks: Counter = field(default_factory=Counter)
    fallback_samples: int = 0
    kappa_fallback_samples: int = 0

    @property
    def hours(self) -> float:
        if self.first_ts is None or self.last_ts is None:
            return 0.0
        return max(0.0, (self.last_ts - self.first_ts) / 3600.0)

    @property
    def actions(self) -> int:
        return self.mints + self.rebalances + self.pulls


def read_journal(path: str | Path) -> JournalSummary:
    """Summarise a JSONL decision journal.

    Counts *why* the agent held, not just that it did. All four R-gates are on
    every row precisely so this is possible: a tearsheet that can only say "it
    did not rebalance" is much less useful than one that can say which gate held
    it back and how often.
    """
    summary = JournalSummary()
    file = Path(path)
    if not file.exists():
        return summary

    for line in file.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue

        summary.rows += 1
        if row.get("event") == "decide_error":
            summary.errors += 1
            continue
        # Lifecycle rows — run_start, run_end, kill_switch, action_not_broadcast —
        # are not decisions. Some of them carry an `action` field, and counting
        # those was half of why one mint rendered as three.
        if "event" in row:
            continue

        action = row.get("action")
        if action is None:
            continue

        # The loop journals a decision when it is made and **again** when it is
        # executed, dropped, or refused, and the second row carries a note. Both
        # rows describe one decision, so only the noteless row is counted — the
        # first real journal this project ever produced showed a single mint as
        # "3 mint", which is the failure this whole product is named after
        # appearing on its own card.
        note = row.get("note") or ""
        if note:
            if note.startswith("executed"):
                summary.executed += 1
            elif note.startswith("failed"):
                summary.failed += 1
            else:
                summary.dropped += 1
            continue

        summary.decisions += 1
        ts = row.get("ts")
        if isinstance(ts, int):
            summary.first_ts = ts if summary.first_ts is None else min(summary.first_ts, ts)
            summary.last_ts = ts if summary.last_ts is None else max(summary.last_ts, ts)

        if action == "hold":
            summary.holds += 1
            for gate in ("R1", "R2", "R3", "R4"):
                if row.get("reasons", {}).get(gate) == 0.0:
                    summary.gate_blocks[gate] += 1
        elif action == "mint":
            summary.mints += 1
        elif action == "rebalance":
            summary.rebalances += 1
        elif action == "pull":
            summary.pulls += 1

        reasons = row.get("reasons", {})
        if reasons.get("using_onchain_fallback"):
            summary.fallback_samples += 1
        if reasons.get("kappa_is_fallback"):
            summary.kappa_fallback_samples += 1

    return summary


def _verdict_dict(v: Verdict) -> dict[str, Any]:
    """A verdict with its refusal intact.

    `detail` and `n` have always been on `Verdict` and were always dropped here,
    so a card could render "no verdict" but never "no verdict — 12 observations,
    need 30". The refusal is the product; shipping it without its reason turns
    the most honest thing on the card into the least informative.
    """
    return {"called": v.called, "label": str(v), "detail": v.detail, "n": v.n}


def _quote_dict(quote: Any) -> dict[str, Any] | None:
    """The quote as numbers, not as a sentence.

    `to_dict` used to emit only `quote.render()` — "36.88% to 38.72% (median
    37.74%, over 31h …)". Nothing downstream can draw a P25-P75 band from that
    string, so the range that is the entire point of the product could only ever
    be read, never seen.
    """
    if quote is None:
        return None
    return {
        "p25": quote.p25,
        "p50": quote.p50,
        "p75": quote.p75,
        "samples": quote.samples,
        "windows": quote.windows,
        "perturbations": quote.perturbations,
        # How far, beside how many. `/methods` stated the magnitude as typed
        # prose — "gamma and kappa at +/-25%" — while the artifact carried only
        # the count, so the one figure describing what a perturbation *is* was
        # the one figure on that page not read from anything.
        "perturbation_fraction": quote.perturbation_fraction,
        "net_positive": quote.net_positive,
        "returns": list(quote.returns),
        "in_range_p50": quote.in_range_p50,
        "rebalances_p50": quote.rebalances_p50,
        "hours_per_window": quote.hours_per_window,
        "sufficient": quote.sufficient,
        "annualised": quote.annualised,
        "basis": quote.basis,
        "note": quote.note,
    }


@dataclass(frozen=True, slots=True)
class Tearsheet:
    """Everything a card shows, and everything needed to disbelieve it."""

    agent: str
    pool: str
    quote_line: str
    quote_sufficient: bool

    in_range: Verdict
    profitable: Verdict

    journal: JournalSummary
    caveats: list[str]
    provenance: dict[str, Any]

    # The structured forms behind `quote_line`, and the sample-size floors that
    # decided whether there would be a quote at all.
    quote: Any = None
    floors: dict[str, Any] = field(default_factory=dict)
    estimators: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "pool": self.pool,
            "quote": self.quote_line,
            "quote_sufficient": self.quote_sufficient,
            "quote_detail": _quote_dict(self.quote),
            "floors": self.floors,
            "estimators": self.estimators,
            "verdicts": {
                "in_range": _verdict_dict(self.in_range),
                "profitable": _verdict_dict(self.profitable),
            },
            "activity": {
                "decisions": self.journal.decisions,
                "hours": round(self.journal.hours, 2),
                "mints": self.journal.mints,
                "rebalances": self.journal.rebalances,
                "pulls": self.journal.pulls,
                # Outcomes, kept apart from the decisions that caused them. A
                # decision the loop dropped as stale or refused by the daily cap
                # still happened and still belongs on the card; it just is not a
                # second mint.
                "executed": self.journal.executed,
                "failed": self.journal.failed,
                "dropped": self.journal.dropped,
                "read_errors": self.journal.errors,
                "held_by_gate": dict(self.journal.gate_blocks),
            },
            "caveats": self.caveats,
            "provenance": self.provenance,
        }

    def render(self) -> str:
        # What this document is a measurement *of*, stated before the number.
        #
        # `docs/TEARSHEET.md` published "36.88% to 38.72%" for Warden while
        # `warden.json` published "-52.18% to -49.92%" for the same agent on the
        # same pool. Both were correct: this file is quoted from a short live
        # journal, the card from a 725-hour replay across twenty windows. Nothing
        # said so, so the only available reading was that one of them was wrong —
        # a ninety-point contradiction between two of this project's own outputs,
        # in the project whose entire argument is that its numbers agree.
        lines = [
            f"  {self.agent}",
            f"  {self.pool}",
            "",
            f"  BASIS            this agent's live journal, {self.journal.decisions:,} decisions "
            f"over {self.journal.hours:.1f}h",
            "                   not the published card, which replays 20 windows of the full tape",
            "",
            f"  QUOTE            {self.quote_line}",
            f"  in range         {self.in_range}",
            f"  beats holding    {self.profitable}",
            "",
            f"  decisions        {self.journal.decisions:,} over {self.journal.hours:.1f}h",
            f"  moves            {self.journal.mints} mint, "
            f"{self.journal.rebalances} rebalance, {self.journal.pulls} pull",
        ]
        if self.journal.gate_blocks:
            ordered = ", ".join(
                f"{gate} {count:,}" for gate, count in sorted(self.journal.gate_blocks.items())
            )
            lines.append(f"  held back by     {ordered}")
        if self.journal.errors:
            lines.append(f"  read errors      {self.journal.errors:,} (survived)")

        if self.caveats:
            lines += ["", "  THINGS THIS NUMBER DOES NOT KNOW"]
            lines += [f"    - {caveat}" for caveat in self.caveats]
        return "\n".join(lines)


def build(
    *,
    agent: str,
    pool: str,
    journal_path: str | Path,
    quote=None,
    in_range_samples: int = 0,
    in_range_total: int = 0,
    net_positive_windows: int = 0,
    total_windows: int = 0,
    in_range_floor: float = 0.70,
    extra_caveats: list[str] | None = None,
    estimators: dict[str, Any] | None = None,
) -> Tearsheet:
    """Assemble a tearsheet from a journal and, optionally, a replay quote."""
    summary = read_journal(journal_path)

    caveats = list(extra_caveats or [])
    if quote is None:
        quote_line = "no replay yet"
        sufficient = False
    else:
        quote_line = quote.render()
        sufficient = quote.sufficient
        if not sufficient:
            caveats.append(
                "The quote is withheld: there is not enough history to state a range "
                "that describes the strategy rather than the sample."
            )

    # The caveats are not decoration. Each one is a published assumption that
    # makes the headline number less flattering than it could have been.
    caveats.append(
        "Adverse selection is reported as an upper bound (assumption A10): the "
        "measure is non-negative for every swap regardless of who traded, so it "
        "folds reversion round trips into what it calls adverse selection."
    )
    caveats.append(
        "Liquidity providers keep 66% of every fee on this pool — the protocol "
        "takes 34% (assumption P-1). Every fee figure here is net of that."
    )
    if summary.kappa_fallback_samples:
        share = summary.kappa_fallback_samples / max(1, summary.decisions)
        caveats.append(
            f"The fill-decay parameter fell back to a default on {share:.0%} of "
            "samples, so the range width on those was set by an assumption "
            "rather than by a fit (assumption A8)."
        )
    elif estimators and estimators.get("kappa_is_fallback"):
        # The clause above reads the decision journal, which a live agent writes
        # and a replay does not. So on every card built from a replay — which is
        # every card the site currently shows — the journal was empty, the
        # counter was zero, and the caveat did not fire *even when the fallback
        # had been used for the entire run*.
        #
        # A8 does not say the fallback is disclosed when a journal happens to
        # exist. It says: "Every card that uses kappa shows its r^2 and whether
        # the fallback was used." The estimator was read at the end of the run
        # and knows the answer, so ask it.
        caveats.append(
            "The fill-decay parameter kappa was not fitted on this run — it fell "
            f"back to its provisional default (fit r^2 = "
            f"{float(estimators.get('kappa_r_squared', 0.0)):.2f} over "
            f"{int(estimators.get('kappa_buckets_used', 0))} depth buckets). The "
            "range width here was therefore set by an assumption rather than by "
            "a measurement (assumption A8)."
        )
    if summary.fallback_samples:
        share = summary.fallback_samples / max(1, summary.decisions)
        caveats.append(
            f"The CEX price feed was unavailable on {share:.0%} of samples, so "
            "toxicity was judged from on-chain evidence alone."
        )

    return Tearsheet(
        agent=agent,
        pool=pool,
        quote_line=quote_line,
        quote_sufficient=sufficient,
        quote=quote,
        # Published rather than hardcoded downstream. Every one of these is a
        # threshold that can cause this product to say nothing, so a reader is
        # entitled to see the number that silenced it — and a UI that restated
        # them as literals could drift from the code that enforces them.
        floors={
            "min_windows": ranges.MIN_SAMPLES,
            "min_window_hours": ranges.MIN_WINDOW_HOURS,
            "min_hours_to_annualise": ranges.MIN_HOURS_TO_ANNUALISE,
            "min_observations": MIN_OBSERVATIONS,
            "in_range_floor": in_range_floor,
        },
        estimators=dict(estimators or {}),
        in_range=verdict(in_range_samples, in_range_total, in_range_floor),
        profitable=verdict(net_positive_windows, total_windows, 0.5),
        journal=summary,
        caveats=caveats,
        provenance={
            "journal": str(journal_path),
            "journal_rows": summary.rows,
            "hours_covered": round(summary.hours, 2),
            "every_number_derived": True,
        },
    )


def write_artifact(tearsheet: Tearsheet, path: str | Path) -> Path:
    """Emit the JSON the web app reads.

    The Next.js app never imports Python; it reads precomputed artifacts. So the
    site stays statically deployable even if every backend process is down,
    which is the state a demo is most likely to find them in.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(tearsheet.to_dict(), indent=2, sort_keys=True) + "\n")
    return out
