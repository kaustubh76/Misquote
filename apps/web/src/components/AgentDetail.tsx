"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Section } from "@/components/Heading";
import { Badge } from "@/components/Badge";
import { Band } from "@/components/Band";
import { Card, CardHeader } from "@/components/Card";
import { WithCitations } from "@/components/Cite";
import { DataTable } from "@/components/DataTable";
import { ComparisonTable } from "@/components/ComparisonTable";
import { GateHistogram } from "@/components/GateHistogram";
import { Pill, verdictTone } from "@/components/Pill";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { load, type AgentArtifact, type Loaded } from "@/lib/artifacts";
import {
  amount,
  count,
  fraction,
  hours,
  pct,
  shortAddress,
  signed,
  SIGN_CLASS,
  signOf,
} from "@/lib/format";

/**
 * Name what an `n` counts, but only where the artifact says so.
 *
 * `verdicts.*.n` is a bare integer. The emitter knows what it counted —
 * `verdict(in_range_samples, in_range_total, …)` against
 * `verdict(net_positive_windows, total_windows, …)` — and publishes neither
 * unit, so the page is left with two numbers three orders of magnitude apart
 * and no way to say why.
 *
 * Writing the words in unconditionally would be the thing this project argues
 * against: a label asserted by the view, correct today, silently wrong the
 * first time the emitter changes what it counts. So the unit is claimed only
 * when the count is *identically* the quantity it is supposed to be — the
 * replay's decision count, the quote's sample count. If those ever diverge the
 * page falls back to the bare `n`, which says less and stays true.
 *
 * Adding the unit to the artifact would be better still, and is the right move
 * next time it is regenerated: `test_artifact_contract.py` asserts field-set
 * equality in both directions, so a new key means a half-hour `make artifacts`
 * in the same commit.
 */
function unitFor(n: number, expected: number | undefined, unit: string) {
  return expected !== undefined && n === expected ? ` ${unit}` : "";
}

export function AgentDetail({ slug }: { slug: string }) {
  const [state, setState] = useState<Loaded<AgentArtifact> | null>(null);

  useEffect(() => {
    let live = true;
    load<AgentArtifact>(`${slug}.json`).then((r) => {
      if (live) setState(r);
    });
    return () => {
      live = false;
    };
  }, [slug]);

  if (state === null) {
    return (
      <div aria-busy="true">
        <h1 className="text-2xl font-semibold capitalize">{slug}</h1>
        <div className="mt-8">
          <CardSkeleton />
        </div>
      </div>
    );
  }

  if (!state.ok) {
    return (
      <>
        <h1 className="text-2xl font-semibold capitalize">{slug}</h1>
        <div className="mt-8">
          <ErrorNotice
            title={`No artifact for "${slug}"`}
            detail={state.error.message}
            remedy={
              <>
                Generate the cards with{" "}
                <code className="font-mono text-xs">make showcase-demo</code>, or return to
                the <Link href="/">overview</Link>.
              </>
            }
          />
        </div>
      </>
    );
  }

  const d = state.value;
  const q = d.quote_detail;
  const r = d.replay;
  const e = d.estimators;
  const adv = d.advantage;
  const [poolLabel, poolAddress] = d.pool.split(" · ");

  return (
    <div>
      <p className="mb-3 text-sm">
        <Link href="/" className="text-dim">
          ← All agents
        </Link>
      </p>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="m-0 text-2xl font-semibold">{d.agent}</h1>
          <p className="mt-1 mb-0 font-mono text-xs text-faint">
            {poolLabel}
            {poolAddress && <> · {shortAddress(poolAddress)}</>}
          </p>
        </div>
        <Badge tone="warn">{d.badge}</Badge>
      </div>

      {/* ---------------------------------------------------------- quote -- */}
      <Section title="What it would have earned">
        <Card>
          <Band
            sufficient={d.quote_sufficient && !!q}
            note={q?.note}
            returns={q?.returns}
            caption={`${d.agent} net return on capital`}
            overlap={adv?.quotable ? adv.ranges_overlap : undefined}
            deltaPp={adv?.quotable ? adv.delta_pp : undefined}
            series={
              q && q.sufficient
                ? [
                    { label: d.agent, p25: q.p25, p50: q.p50, p75: q.p75, tone: "agent" },
                    ...(adv?.quotable
                      ? [
                          {
                            label: adv.without_agent,
                            p25: adv.baseline.p25,
                            p50: adv.baseline.p50,
                            p75: adv.baseline.p75,
                            tone: "baseline" as const,
                          },
                        ]
                      : []),
                  ]
                : []
            }
          />

          {q?.sufficient && (
            <div className="mt-5">
              <DataTable
                caption="How the quote was constructed"
                rows={[
                  { label: "median", value: pct(q.p50) },
                  {
                    label: "observations",
                    value: `${count(q.samples)}`,
                    note: `${q.windows} windows × ${q.perturbations} perturbations`,
                  },
                  {
                    label: "each window covers",
                    value: hours(q.hours_per_window),
                    note: `tape is ${hours(r.hours)} — see Methods`,
                  },
                  {
                    label: "windows finishing in profit",
                    value: `${count(q.net_positive)} of ${count(q.samples)}`,
                  },
                  { label: "basis", value: q.basis },
                ]}
              />
              <p className="mt-3 mb-0 text-xs text-faint">
                A window is half the tape, so twenty of them overlap. Overlap trades
                independence for length — twenty windows of{" "}
                {hours(q.hours_per_window)} each say more about a{" "}
                {d.floors.min_window_hours}h policy horizon than twenty disjoint slivers
                would. <Link href="/methods">Full method →</Link>
              </p>
            </div>
          )}
        </Card>
      </Section>

      {/* ------------------------------------------------------- verdicts -- */}
      {/* The two n's differ by three orders of magnitude — 44,802 against 60 —
          because they count different things: one decision at a time across the
          replay, against one return per window of the quote. Side by side with
          nothing but "n =" on each, the smaller one reads as the weaker
          evidence, when it is the one built out of the quote this page exists to
          defend. `unitFor` names the unit only where the artifact proves it, so
          neither label is a guess. */}
      <Section
        title="Verdicts"
        intro="Two different populations, both from the same replay: one counts decisions, the other counts window returns."
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader
              title="Stayed in range"
              aside={<Pill tone={verdictTone(d.verdicts.in_range)} />}
            />
            <p className="m-0 font-mono text-sm">{d.verdicts.in_range.label}</p>
            <p className="mt-2 mb-0 text-xs text-faint">
              {d.verdicts.in_range.detail} · n = {count(d.verdicts.in_range.n)}
              {unitFor(d.verdicts.in_range.n, r.samples, "replay decisions")}
            </p>
          </Card>

          <Card>
            <CardHeader
              title="Beat holding"
              aside={<Pill tone={verdictTone(d.verdicts.profitable)} />}
            />
            <p className="m-0 font-mono text-sm">{d.verdicts.profitable.label}</p>
            <p className="mt-2 mb-0 text-xs text-faint">
              {d.verdicts.profitable.detail} · n = {count(d.verdicts.profitable.n)}
              {unitFor(d.verdicts.profitable.n, q?.samples, "window returns")}, floor{" "}
              {d.floors.min_observations}
            </p>
          </Card>
        </div>
      </Section>

      {/* ------------------------------------------------------ vs the DIY -- */}
      {adv && (
        <Section title="Against doing it yourself">
          <Card>
            <p className="mt-0 mb-4 text-sm text-dim">
              The baseline is not a different program. It runs through the same replay
              driver, the same tape, the same cost model and the same adverse-selection
              accountant; the only thing that differs is the function that returns a
              decision — here, <em>{adv.without_agent}</em>.
            </p>
            {/* The row list lives in ComparisonTable, because this table and
                the one on /advantage answer the same question from the same
                replay and had already drifted apart once. Only the mapping from
                this artifact's field names is local. */}
            <ComparisonTable
              caption="Agent against baseline"
              agentLabel={d.agent}
              baselineLabel={adv.without_agent}
              agent={{
                p25: q?.p25,
                p50: q?.p50,
                p75: q?.p75,
                inRange: r.in_range_fraction,
                fees: r.fees_quote,
                lvrUpperBound: r.lvr_quote_upper_bound,
                costs: r.costs_quote,
                // `advantage.json` publishes the baseline's moves as one figure;
                // the replay block breaks the agent's out by kind. Summed here
                // so the row compares like with like.
                moves: r.mints + r.rebalances + r.pulls,
              }}
              baseline={{
                p25: adv.baseline.p25,
                p50: adv.baseline.p50,
                p75: adv.baseline.p75,
                inRange: adv.baseline.in_range_fraction,
                fees: adv.baseline.fees_quote,
                lvrUpperBound: adv.baseline.lvr_quote_upper_bound,
                costs: adv.baseline.costs_quote,
                moves: adv.baseline.moves,
              }}
            />
            <p className="mt-4 mb-0 text-sm">
              <span
                className={`tabular text-md font-semibold ${SIGN_CLASS[signOf(adv.delta_pp)]}`}
              >
                {signed(adv.delta_pp, 2, "pp")}
              </span>{" "}
              <span className="text-dim">— {adv.verdict}</span>
            </p>
          </Card>
        </Section>
      )}

      {/* ------------------------------------------------------- activity -- */}
      {/* These two cards are not two views of one run. The left is the replay
          — 44,802 decisions over 62 hours of tape, none of which happened. The
          right is `activity`, read from the decision journal of a live loop
          that ran for a quarter of an hour. They sat side by side under one
          heading with no scale on either, so the gate histogram read as an
          account of the 44,802. Each card now states its own source and span,
          and the heading no longer calls a counterfactual "what it did". */}
      <Section
        title="What it did, and what it would have done"
        intro="Two different runs, kept apart. The replay never held a position; the journal is a loop that ran against a live chain and recorded rather than signed."
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader
              title="Replay"
              eyebrow={`${count(r.samples)} decisions · ${hours(r.hours)} of tape`}
              aside={<Badge tone="warn">Counterfactual</Badge>}
            />
            <DataTable
              caption="Replay activity"
              rows={[
                { label: "decisions", value: count(r.samples) },
                { label: "covering", value: hours(r.hours) },
                { label: "mints", value: count(r.mints) },
                { label: "recentres", value: count(r.rebalances) },
                { label: "pulls", value: count(r.pulls) },
                { label: "in range", value: fraction(r.in_range_fraction) },
                { label: "fees earned", value: amount(r.fees_quote) },
                {
                  label: "adverse selection (upper bound)",
                  value: amount(r.lvr_quote_upper_bound),
                },
                { label: "costs", value: amount(r.costs_quote) },
                {
                  label: "net",
                  value: amount(r.net_quote),
                  tone: SIGN_CLASS[signOf(r.net_quote)],
                },
              ]}
            />
          </Card>

          <Card>
            <CardHeader
              title="Why it held"
              eyebrow={`${count(d.activity.decisions)} decisions · ${hours(d.activity.hours)} journalled`}
              aside={<Badge tone="neutral">Live loop</Badge>}
            />
            {/* The `activity` block was in the artifact all along and the card
                page dropped it entirely — including this histogram, which is
                the reason all four gates are journalled on every row.
                `decisions` is the journal's own count, not the replay's: the
                two differ by three orders of magnitude, and passing the wrong
                one would put every gate at a fraction of a percent. */}
            <GateHistogram
              blocks={d.activity.held_by_gate}
              total={d.activity.decisions}
            />
            {/* Outcomes, kept apart from the decisions that caused them. A
                decision the loop dropped as stale or refused by the daily cap
                still happened; it is just not a second mint. Counting them
                together is what once rendered one mint as three. */}
            <p className="mt-4 mb-0 text-xs text-dim">
              {count(d.activity.executed)} executed · {count(d.activity.failed)} failed ·{" "}
              {count(d.activity.dropped)} dropped as stale or capped
            </p>
            {d.activity.read_errors > 0 && (
              <p className="mt-2 mb-0 text-xs text-warn">
                {count(d.activity.read_errors)} read errors, survived.
              </p>
            )}
          </Card>
        </div>
      </Section>

      {/* ----------------------------------------------------- estimators -- */}
      <Section title="The parameters behind the range">
        <Card>
          {e.kappa_is_fallback ? (
            <Refusal
              title="κ was not fitted on this run"
              reason={e.kappa_label}
              floor={`r² = ${e.kappa_r_squared.toFixed(2)} over ${count(e.kappa_buckets_used)} depth buckets from ${count(e.kappa_swaps_used)} swaps`}
              cite="A8"
            >
              <p className="mt-2 mb-0 text-sm text-dim">
                The half-width of every range above was therefore set by an assumption
                rather than by a measurement. The quote is still the quote — but this is
                the parameter you would attack first.
              </p>
            </Refusal>
          ) : (
            <p className="mt-0 mb-4 font-mono text-sm text-good">{e.kappa_label}</p>
          )}

          <div className="mt-5">
            <DataTable
              caption="Estimator state at the end of the replay"
              rows={[
                {
                  label: "σ (per √hour)",
                  value: e.sigma_per_sqrt_hour.toFixed(6),
                  note: e.sigma_ready ? "ready" : "below the bar threshold",
                },
                { label: "κ per tick", value: e.kappa_per_tick.toFixed(6) },
                {
                  label: "κ per log-price",
                  value: e.kappa_per_logprice.toFixed(2),
                  note: "what equation (2) consumes",
                },
                {
                  label: "κ fit r²",
                  value: e.kappa_r_squared.toFixed(4),
                  tone: e.kappa_is_fallback ? "text-warn" : undefined,
                },
                { label: "κ swaps used", value: count(e.kappa_swaps_used) },
                {
                  label: "swap-imbalance z",
                  value: e.imbalance_z.toFixed(4),
                  note: e.imbalance_ready ? "window full" : "no verdict yet",
                },
              ]}
            />
          </div>
        </Card>
      </Section>

      {/* ----------------------------------------------------- provenance -- */}
      <Section title="Provenance">
        <Card>
          <DataTable
            caption="Where these numbers came from"
            rows={[
              { label: "source", value: d.source },
              { label: "decision journal", value: d.provenance.journal },
              {
                label: "journal rows",
                value: count(d.provenance.journal_rows),
                note:
                  d.provenance.journal_rows === 0
                    ? "empty — no live run has been recorded"
                    : undefined,
              },
              { label: "hours covered by journal", value: hours(d.provenance.hours_covered) },
              {
                label: "every number derived",
                value: d.provenance.every_number_derived ? "yes" : "no",
              },
            ]}
          />
          {d.provenance.journal_rows === 0 && (
            <p className="mt-4 mb-0 text-sm text-warn">
              The journal backing this card&rsquo;s provenance has zero rows: nothing on
              this page comes from a live agent run. Every figure is a replay of the
              policy over recorded history.
            </p>
          )}
        </Card>
      </Section>

      {/* -------------------------------------------------------- caveats -- */}
      <Section title={<>Things this number does not know ({d.caveats.length})</>}>
        <Card>
          <ul className="m-0 list-none space-y-4 p-0">
            {d.caveats.map((c, i) => (
              <li key={i} className="border-l-2 border-warn-line pl-4 text-sm text-dim">
                <WithCitations text={c} />
              </li>
            ))}
          </ul>
        </Card>
      </Section>
    </div>
  );
}
