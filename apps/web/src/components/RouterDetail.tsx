"use client";

import Link from "next/link";
import { Band } from "@/components/Band";
import { AgentJournal } from "@/components/AgentJournal";
import { BuildStamp } from "@/components/BuildStamp";
import { Card } from "@/components/Card";
import { WithCitations } from "@/components/Cite";
import { CostBars } from "@/components/CostBars";
import { DataTable } from "@/components/DataTable";
import { Section } from "@/components/Heading";
import { SectionRail } from "@/components/SectionRail";
import { SourceBanner } from "@/components/SourceBanner";
import { count, fraction, hours, money, pct, SIGN_CLASS, signed, signOf } from "@/lib/format";
import type { RouterArtifact } from "@/lib/artifacts";

/**
 * Router's page. A sibling of `AgentDetail`, for the reason `RouterArtifact` is
 * a sibling of `AgentArtifact`: this agent has no range, no fees and no LVR, and
 * the LP page's columns would have to be filled with zeros that read as claims.
 *
 * The card's job here is unusual and worth stating: on the tape this repository
 * holds, Router **never moved**. A page that rendered that as an empty activity
 * table would look broken. So the finding is the headline, and the numbers that
 * support it — the best rate the venues actually offered, the hurdle it was
 * measured against, and how long capital would have to be committed before the
 * two crossed — are the body.
 *
 * ## Why this file is `"use client"`
 *
 * Being a sibling of `AgentDetail` turned into being left behind by it. This
 * page had no `<h1>` at all — the built `/agent/router/` carried eight `<h2>`
 * and no document title, against warden's 1/7/4 — because it opened with a
 * `CardHeader`, and a card header is a `Heading` at whatever level it finds.
 *
 * `Section` is what supplies that level, and it cannot supply it across a
 * server boundary: it provides through React context, and a server-rendered
 * child arrives as an already-rendered prop with no access to it. So the
 * directive is not a preference. Without it every `Section` on this page would
 * render its own title correctly and leave every card inside it at the same
 * depth, which is the state this file was already in.
 */
export function RouterDetail({ data }: { data: RouterArtifact }) {
  const q = data.quote;
  const r = data.replay;
  const adv = data.advantage;
  const unit = data.quote_symbol;

  // An APR at three decimals, because the edge and the hurdle differ in the
  // third. Named for what it is now that `pct` is imported and means percent.
  const rate = (x: number) => `${(100 * x).toFixed(3)}%`;

  // Whether any venue on this card is a concentrated-liquidity range. Drives
  // the prose beside the table, which would be noise on a Venus-only card and
  // is load-bearing the moment a range appears next to a lending market.
  const hasPool = data.venues.some((v) => v.kind === "pool");

  // Built from what renders. `advantage`, `cost_model` and `provenance` are all
  // optional on this artifact, and a pill pointing at a section a withheld run
  // never drew is a dead anchor — the defect `AgentDetail` had, found in the
  // same pass.
  const rail = [
    { id: "quote", label: "Quote" },
    { id: "boundary", label: "Boundary" },
    ...(adv ? [{ id: "advantage", label: "vs DIY" }] : []),
    ...(data.cost_model ? [{ id: "costs", label: "Costs" }] : []),
    { id: "venues", label: "Venues" },
    // Rendered, anchored, and omitted from this list for one commit — which is
    // the *other* half of the bug the comment above claims credit for fixing.
    // `AgentDetail` listed four of six and skipped the middle of its own page;
    // this listed five of seven and did the same thing, three lines under a
    // note about not doing it. A rail built from a hand-written list is a rail
    // that drifts from its page; both are now written beside the condition that
    // draws the section.
    ...(Object.keys(data.params).length > 0
      ? [{ id: "parameters", label: "Parameters" }]
      : []),
    ...(data.provenance ? [{ id: "provenance", label: "Provenance" }] : []),
  ];

  return (
    <div>
      <p className="mb-3 text-sm">
        <Link href="/" className="text-dim">
          ← All agents
        </Link>
      </p>

      <h1 className="m-0 text-2xl font-semibold">{data.agent}</h1>
      <p className="mt-1 mb-0 font-mono text-xs text-faint">
        {data.category} · {data.venue}
      </p>

      <SectionRail label="On this tearsheet" items={rail} />

      {/* The badge was a bare `<Badge>` under the title, which is the
          qualification without the thing it qualifies. "This position was not
          held" and "this is the tape it was replayed over" are two halves of
          one sentence, and `/`, `/advantage` and the three LP tearsheets all
          state them together. This page made the most specific claim on the
          site — "the edge cleared, and only just" — and never said which tape
          it read. */}
      <SourceBanner
        source={data.source}
        badge={data.badge}
        pool={data.venue}
        span={r.hours > 0 ? hours(r.hours) : undefined}
      />

      <Section id="quote" title="What it would have earned">
        <Card>
          <p className="mt-0 mb-4 text-sm text-dim">{q.basis}</p>

          {/* The range, drawn.
              A5 says a quote is a range and never a point estimate, and this
              page honoured that in a sentence — `1.89% – 1.93% (median 1.91%)`
              — on the one site whose reusable mark is a drawn interval. Worse,
              a sentence cannot show what Router's actual finding is: the range
              *overlaps its own baseline*. `ranges_overlap` is true and
              `delta_pp` is +0.00, so "indistinguishable" is the result, and it
              is exactly the thing two numbers side by side cannot say.

              Two series, not one: Router publishes a park-policy baseline in
              the same shape the LP cards do, so this is `Band`'s ordinary case.
              `overlap` and `deltaPp` are passed rather than derived, for the
              reason `Band` states about `ranges_overlap` — the engine computed
              them, and a second implementation one screen-inch away could be
              made to disagree.

              No `floor` prop: `RouterArtifact` carries no `floors` block, and a
              gauge drawn from a threshold this file invented would be a
              fabricated number underneath a refusal. */}
          <Band
            sufficient={q.sufficient}
            note={q.note}
            returns={q.returns}
            caption={`${data.agent} net return on supplied capital`}
            overlap={adv?.quotable ? adv.ranges_overlap : undefined}
            deltaPp={adv?.quotable ? adv.delta_pp : undefined}
            series={
              q.sufficient
                ? [
                    {
                      label: data.agent,
                      p25: q.p25,
                      p50: q.p50,
                      p75: q.p75,
                      tone: "agent" as const,
                    },
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

          {/* The median in text, and this is not redundancy. `Band` writes
              P25–P75 in its label row and puts the median only in the
              container's `aria-label` — and an aria-label contributes no
              `innerText`, which is what `scripts/check-pages.mjs` measures with
              JavaScript off. Drawing the range must not cost the page the
              number. */}
          {q.sufficient && (
            <div className="mt-5">
              <DataTable
                caption="How the quote was constructed"
                rows={[
                  { label: "median", value: pct(q.p50) },
                  {
                    label: "observations",
                    value: count(q.samples),
                    note: `${count(q.windows)} windows × ${count(q.perturbations)} perturbations`,
                  },
                  {
                    label: "each window covers",
                    value: hours(q.hours_per_window),
                    note: `tape is ${hours(r.hours)}`,
                  },
                  {
                    label: "observations finishing in profit",
                    value: `${count(q.net_positive)} of ${count(q.samples)}`,
                  },
                  { label: "basis", value: q.basis },
                ]}
              />
            </div>
          )}
        </Card>
      </Section>

      <Section
        id="boundary"
        title="Why it did what it did"
        intro="The boundary, and how far the market was from crossing it."
      >
        {data.finding && (
          <Card className="mb-4">
            <p className="m-0 text-sm leading-relaxed">{data.finding}</p>
          </Card>
        )}
        <Card>
          <DataTable
            caption="Router's switching boundary and the rates it was measured against"
            rows={[
              { label: "Best realized rate seen", value: rate(r.best_apr_seen) },
              { label: "Largest edge between venues", value: rate(r.max_edge_apr) },
              // `hurdle` is `/agent/router/`'s no-JS needle in
              // `scripts/check-pages.mjs`. This label is where it comes from.
              { label: "Round-trip hurdle (median)", value: rate(r.hurdle_apr_p50) },
              {
                label: "Commitment before entry repays a round trip",
                value: `${(r.breakeven_horizon_hours / 24).toFixed(1)} days`,
              },
              { label: "Decisions", value: count(r.samples) },
              {
                label: "Enter / switch / exit",
                value: `${count(r.entries)} / ${count(r.switches)} / ${count(r.exits)}`,
              },
              { label: "Share of samples invested", value: fraction(r.invested_fraction) },
              {
                label: "Share of samples on the best venue",
                value: fraction(r.best_venue_fraction),
              },
            ]}
          />

          {/* Where the yield went, drawn. The artifact has carried the
              gross/costs/net identity all along and the page showed none of
              it — which on this agent is the whole story, because a router
              that never moved earned its gross and spent almost nothing. */}
          <div className="mt-5">
            <CostBars
              caption={`${data.agent}: where the yield went`}
              net={r.net_quote}
              unit={unit}
              rows={[
                { label: "gross yield", value: r.gross_yield_quote, direction: "earned" },
                { label: "switch costs", value: r.costs_quote, direction: "spent" },
              ]}
            />
          </div>
        </Card>
      </Section>

      {adv && (
        <Section id="advantage" title="Against doing it yourself" intro={adv.without_agent}>
          <Card>
            {/* The delta at the size the LP pages give it, with the two
                conditions a call needs beside it. `material` and `separated`
                were on this artifact and reached the page only folded inside
                the verdict sentence. */}
            <p className="m-0 text-md">
              <span className={`tabular font-semibold ${SIGN_CLASS[signOf(adv.delta_pp)]}`}>
                {signed(adv.delta_pp, 2, "pp")}
              </span>{" "}
              <span className="text-dim">{adv.verdict}</span>
            </p>
            <p className="mt-1 mb-4 font-mono text-xs text-faint">
              {adv.material ? "material" : "immaterial"} · bands{" "}
              {adv.separated ? "separated" : "overlapping"}
            </p>

            <DataTable
              caption="The baseline's own figures, from the same driver and the same tape"
              rows={[
                {
                  label: "Baseline net return P25–P75",
                  value: `${pct(adv.baseline.p25)} – ${pct(adv.baseline.p75)}`,
                  note: `median ${pct(adv.baseline.p50)}`,
                },
                {
                  label: "Baseline moves",
                  value: `${count(adv.baseline.entries)} enter · ${count(adv.baseline.switches)} switch`,
                },
                {
                  label: "Baseline gross yield",
                  value: money(adv.baseline.gross_yield_quote, unit),
                },
                { label: "Baseline costs", value: money(adv.baseline.costs_quote, unit) },
                { label: "Baseline net", value: money(adv.baseline.net_quote, unit) },
              ]}
            />
          </Card>
        </Section>
      )}

      {data.cost_model && (
        <Section
          id="costs"
          title="What a move costs"
          intro="Every input is a reading, or says it is not."
        >
          <Card>
            <DataTable
              caption="The cost inputs behind the hurdle, and where each came from"
              rows={[
                {
                  label: "Swap fee",
                  value: `${count(data.cost_model.slippage_bps)} bps`,
                  note: "the verified pool's own fee tier",
                },
                {
                  label: "Gas per transaction",
                  value: money(data.cost_model.gas_quote, unit, 6),
                  note: "gas units × gas price × native price",
                },
                {
                  label: "Derived from readings",
                  value: data.cost_model.derived ? "yes" : "no — a fallback is in use",
                },
              ]}
            />
            <p className="mt-3 mb-0 text-xs text-faint">{data.cost_model.basis}</p>
          </Card>
        </Section>
      )}

      <Section
        id="venues"
        title="Venues"
        intro={
          hasPool
            ? "Two kinds of venue, verified the same way — and not the same risk."
            : "Verified three ways; sizes are as at the end of the tape."
        }
      >
        <Card>
          <DataTable
            caption="The venues Router is allowed to choose between"
            rows={data.venues.map((v) =>
              v.kind === "pool"
                ? {
                    label: v.symbol,
                    // The width, on the row, because there is no width-free fee
                    // APR: two LPs in this pool at this moment earn differently
                    // because they chose differently (A21).
                    value: `range at ±${count(v.reference_width_ticks)} ticks`,
                    note: `${pct(v.fee_pips / 1_000_000)} fee tier, LPs keep ${pct(
                      v.lp_fee_share,
                    )}`,
                  }
                : {
                    label: v.symbol,
                    value: `${count(v.supplied_base_at_tape_end)} supplied`,
                    note: `reserve factor ${v.reserve_factor}${
                      v.reserve_factor_recorded ? "" : " (not on tape)"
                    }`,
                  },
            )}
          />
          {/* The asymmetry, in words, beside the numbers rather than left for a
              reader to infer. Every figure on this page is one net rate ranked
              against another, and ranking them is only honest if it is also
              said that they are not the same product: a supplied dollar keeps
              its principal in dollars, and a range does not. Nothing here is a
              number, so nothing here can drift from the artifact. */}
          {/* What happened to the ranges, above the standing caveat about how
              they are quoted. This is a result of *this* run; the paragraph
              below is true of every run, and putting the general statement
              first would bury the specific one. */}
          {data.pool_finding && (
            <p className="mt-4 text-sm leading-relaxed">{data.pool_finding}</p>
          )}

          {hasPool && (
            <p className="mt-4 text-sm leading-relaxed text-muted">
              A range is quoted <strong>net of its convexity cost</strong> — realized
              fees minus the adverse selection the same window booked — because the
              gross fee figure is the one every other venue quotes, and ranking it
              against a lending market&rsquo;s net supply rate would let it win on a
              subtraction it had not made. Even so the two are not the same risk. A
              supplied dollar earns a dollar rate and stays a dollar; a range earns a
              rate measured in the pool&rsquo;s own quote token and holds two assets
              whose value moves with the price. A higher number here is not simply a
              better one.
            </p>
          )}
        </Card>
      </Section>

      {/* The policy behind every number above. `params` has been on this
          artifact since the agent was written and reached no surface at all,
          while `AgentDetail` gives the same block its own section — so the one
          agent whose entire finding is "the boundary was not crossed" never
          published the constants that define the boundary. */}
      {Object.keys(data.params).length > 0 && (
        <Section
          id="parameters"
          title="The parameters behind the boundary"
          intro="Read from the policy, not restated here — a constant a page could get wrong is not a constant."
        >
          <Card>
            <DataTable
              caption="Router's policy parameters"
              rows={Object.entries(data.params).map(([name, value]) => ({
                label: <span className="font-mono text-xs">{name}</span>,
                value: count(value),
              }))}
            />
          </Card>
        </Section>
      )}

      {data.provenance && (
        <Section
          id="provenance"
          title="Where these numbers came from"
          intro="The journal the agent wrote, published beside the replay that quoted it."
        >
          <Card>
            <DataTable
              caption="The decision journal behind this card"
              rows={[
                { label: "Journal", value: data.provenance.journal },
                {
                  label: "Rows",
                  value: count(data.provenance.journal_rows),
                  note: `${hours(data.provenance.hours_covered)} covered`,
                },
                {
                  label: "Every number derived",
                  value: data.provenance.every_number_derived ? "yes" : "no",
                },
              ]}
            />
          </Card>
        </Section>
      )}

      <Section title="Assumptions this rests on">
        <Card>
          <ul className="m-0 list-none space-y-3 p-0 text-sm text-dim">
            {data.caveats.map((c) => (
              // `WithCitations`, because these carry A- and P- ids and printed
              // them as inert text. `AgentDetail` linkifies the same field, so
              // the same caveat was a link on one tearsheet and not on another.
              <li key={c}>
                <WithCitations text={c} />
              </li>
            ))}
          </ul>
        </Card>
      </Section>

      {/* Live, so it renders nothing on the static export and needs no rail
          entry — see its own docstring. Placed after the replay sections and
          before the stamp: it is the last piece of evidence on the page and it
          is about a different run from everything above it. */}
      <AgentJournal agent="router" />

      {data.build && <BuildStamp className="mt-10" build={data.build} />}
    </div>
  );
}
