"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Section } from "@/components/Heading";
import { Badge } from "@/components/Badge";
import { Band } from "@/components/Band";
import { Card, CardHeader } from "@/components/Card";
import { WithCitations } from "@/components/Cite";
import { DataTable } from "@/components/DataTable";
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
      <Section title="Verdicts">
        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader
              title="Stayed in range"
              aside={<Pill tone={verdictTone(d.verdicts.in_range)} />}
            />
            <p className="m-0 font-mono text-sm">{d.verdicts.in_range.label}</p>
            <p className="mt-2 mb-0 text-xs text-faint">
              {d.verdicts.in_range.detail} · n = {count(d.verdicts.in_range.n)}
            </p>
          </Card>

          <Card>
            <CardHeader
              title="Beat holding"
              aside={<Pill tone={verdictTone(d.verdicts.profitable)} />}
            />
            <p className="m-0 font-mono text-sm">{d.verdicts.profitable.label}</p>
            <p className="mt-2 mb-0 text-xs text-faint">
              {d.verdicts.profitable.detail} · n = {count(d.verdicts.profitable.n)}, floor{" "}
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
            <DataTable
              caption="Agent against baseline"
              columns={["Metric", d.agent, adv.without_agent]}
              hideCaption={false}
              rows={[
                {
                  label: "median return",
                  value: pct(q?.p50),
                  note: pct(adv.baseline.p50),
                },
                {
                  label: "P25 – P75",
                  value: `${pct(q?.p25)} – ${pct(q?.p75)}`,
                  note: `${pct(adv.baseline.p25)} – ${pct(adv.baseline.p75)}`,
                },
                {
                  label: "in range",
                  value: fraction(r.in_range_fraction),
                  note: fraction(adv.baseline.in_range_fraction),
                },
                {
                  label: "fees",
                  value: amount(r.fees_quote),
                  note: amount(adv.baseline.fees_quote),
                },
                {
                  // Present on /advantage since it was written, absent here.
                  // Two hand-built copies of one comparison drifted, and the
                  // half that went missing is the cost side — the figure that
                  // makes the agent look worse. The value was already on this
                  // page, thirty lines below, in the replay table.
                  label: "adverse selection (upper bound)",
                  value: amount(r.lvr_quote_upper_bound),
                  note: amount(adv.baseline.lvr_quote_upper_bound),
                },
                {
                  label: "costs",
                  value: amount(r.costs_quote),
                  note: amount(adv.baseline.costs_quote),
                },
                {
                  label: "moves",
                  value: count(r.mints + r.rebalances + r.pulls),
                  note: count(adv.baseline.moves),
                },
              ]}
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
      <Section title="What it actually did">
        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader title="Replay" />
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
            <CardHeader title="Why it held" />
            {/* The `activity` block was in the artifact all along and the card
                page dropped it entirely — including this histogram, which is
                the reason all four gates are journalled on every row. */}
            <GateHistogram blocks={d.activity.held_by_gate} />
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
