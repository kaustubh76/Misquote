"use client";

import Link from "next/link";
import { Band } from "@/components/Band";
import { EngineStamp } from "@/components/EngineStamp";
import { TapeSource } from "@/components/TapeSource";
import { AgentJournal } from "@/components/AgentJournal";
import { Card } from "@/components/Card";
import { Prose } from "@/components/Blocks";
import { CostBars } from "@/components/CostBars";
import { DataTable } from "@/components/DataTable";
import { Section } from "@/components/Heading";
import { SectionRail } from "@/components/SectionRail";
import {
  count,
  fraction,
  hours,
  money,
  pct,
  SIGN_CLASS,
  signed,
  signOf,
} from "@/lib/format";
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

  // "held N of M samples", or the reason zero is not "never measurable".
  //
  // `quotable_samples` had been on the artifact and on no surface, so a venue
  // Router measured on every sample and declined on size rendered identically
  // to one it could never read.
  const held = (v: (typeof data.venues)[number]) =>
    v.held_samples > 0
      ? `held ${count(v.held_samples)} of ${count(v.quotable_samples)} samples`
      : `quotable on ${count(v.quotable_samples)}, never entered`;

  // The price that reconciled the two numéraires, from whichever range carries
  // it. A24 says outright that it is published on the card, and until now it
  // was on the artifact and nowhere a reader could see — a sheet promising
  // something the page did not do.
  const bridged = data.venues.find((v) => v.kind === "pool");

  // The second replay. Always present on the artifact and zeroed when there was
  // no smaller size to try, so the section is drawn on `capital_quote` rather
  // than on the key existing.
  const scale = data.at_pool_scale ?? null;

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
    ...(scale && scale.capital_quote > 0
      ? [{ id: "at-scale", label: "At pool scale" }]
      : []),
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
                    note: `${count(q.windows)} windows × ${count(
                      q.perturbations
                    )} perturbations`,
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
              {
                label: "Best realized rate seen",
                value: rate(r.best_apr_seen),
              },
              {
                label: "Largest edge between venues",
                value: rate(r.max_edge_apr),
              },
              // `hurdle` is `/agent/router/`'s no-JS needle in
              // `scripts/check-pages.mjs`. This label is where it comes from.
              {
                label: "Round-trip hurdle (median)",
                value: rate(r.hurdle_apr_p50),
              },
              {
                label: "Commitment before entry repays a round trip",
                value: `${(r.breakeven_horizon_hours / 24).toFixed(1)} days`,
              },
              { label: "Decisions", value: count(r.samples) },
              {
                label: "Enter / switch / exit",
                value: `${count(r.entries)} / ${count(r.switches)} / ${count(
                  r.exits
                )}`,
              },
              {
                label: "Share of samples invested",
                value: fraction(r.invested_fraction),
              },
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
                {
                  label: "gross yield",
                  value: r.gross_yield_quote,
                  direction: "earned",
                },
                {
                  label: "switch costs",
                  value: r.costs_quote,
                  direction: "spent",
                },
              ]}
            />
          </div>
        </Card>
      </Section>

      {adv && (
        <Section
          id="advantage"
          title="Against doing it yourself"
          intro={adv.without_agent}
        >
          <Card>
            {/* The delta at the size the LP pages give it, with the two
                conditions a call needs beside it. `material` and `separated`
                were on this artifact and reached the page only folded inside
                the verdict sentence. */}
            <p className="m-0 text-md">
              <span
                className={`tabular font-semibold ${
                  SIGN_CLASS[signOf(adv.delta_pp)]
                }`}
              >
                {signed(adv.delta_pp, 2, "pp")}
              </span>{" "}
              <span className="text-dim">{adv.verdict}</span>
            </p>
            <p className="mt-1 mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs text-faint">
              <span>
                {adv.material ? "material" : "immaterial"} · bands{" "}
                {adv.separated ? "separated" : "overlapping"}
              </span>
              {/* And which tape. Router reads a rate tape rather than a swap
                  tape, which makes its disclosure more load-bearing than the
                  LP cards' rather than less: a reader comparing this delta
                  against one of theirs is already comparing two different
                  measurements, and the tape is the only thing on screen that
                  says so. */}
              <TapeSource source={data.source} />
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
                  value: `${count(adv.baseline.entries)} enter · ${count(
                    adv.baseline.switches
                  )} switch`,
                },
                {
                  label: "Baseline gross yield",
                  value: money(adv.baseline.gross_yield_quote, unit),
                },
                {
                  label: "Baseline costs",
                  value: money(adv.baseline.costs_quote, unit),
                },
                {
                  label: "Baseline net",
                  value: money(adv.baseline.net_quote, unit),
                },
              ]}
            />

            {/* The engine behind this delta. Router's card is written by `make
                router-card` and the advantage report by `make advantage`, so
                these two publish the same comparison from separate runs — and
                the day one is regenerated without the other, this line and the
                one on /advantage stop matching. */}
            <EngineStamp
              className="mt-4"
              sha={data.build?.git_sha}
              generatedAt={data.build?.generated_at}
              dirty={data.build?.git_dirty}
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
                  value: data.cost_model.derived
                    ? "yes"
                    : "no — a fallback is in use",
                },
              ]}
            />
            <p className="mt-3 mb-0 text-xs text-faint">
              {data.cost_model.basis}
            </p>
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
                    // Everything the venue was judged on, in the order it was
                    // judged: the tier it charges, the share of it the position
                    // keeps, what A1 let it take, and how often it was
                    // measurable at all.
                    //
                    // `quotable_samples` is the field that makes the ceiling
                    // mean something. Without it "held 0" reads as "never
                    // measurable", when what happened is that the rate was
                    // there on every sample and the size was not.
                    note:
                      `${pct(v.fee_pips / 1_000_000)} fee tier, LPs keep ${pct(
                        v.lp_fee_share
                      )}` +
                      ` · A1 ceiling ${money(v.a1_ceiling_quote, unit)}` +
                      ` · ${held(v)}`,
                  }
                : {
                    label: v.symbol,
                    value: `${count(v.supplied_base_at_tape_end)} supplied`,
                    note:
                      `reserve factor ${v.reserve_factor}` +
                      `${v.reserve_factor_recorded ? "" : " (not on tape)"}` +
                      ` · A1 ceiling ${money(v.a1_ceiling_quote, unit)}` +
                      ` · ${held(v)}`,
                  }
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

          {bridged && (
            <p className="mt-3 mb-0 text-xs text-faint">
              Sizes cross from the pool&rsquo;s quote token into this
              card&rsquo;s units at{" "}
              <span className="tabular text-dim">
                {money(bridged.quote_price_quote, unit)}
              </span>{" "}
              per {data.quote_symbol === "USD" ? "BNB" : "unit"}, read from the
              last swap on the verified pool — the same reading the cost model
              uses. A1&rsquo;s ceiling is one of the figures that crosses, which
              is why the rate is published beside it (A24).
            </p>
          )}

          {hasPool && (
            <p className="mt-4 text-sm leading-relaxed text-muted">
              A range is quoted <strong>net of its convexity cost</strong> —
              realized fees minus the adverse selection the same window booked —
              because the gross fee figure is the one every other venue quotes,
              and ranking it against a lending market&rsquo;s net supply rate
              would let it win on a subtraction it had not made. Even so the two
              are not the same risk. A supplied dollar earns a dollar rate and
              stays a dollar; a range earns a rate measured in the pool&rsquo;s
              own quote token and holds two assets whose value moves with the
              price. A higher number here is not simply a better one.
            </p>
          )}
        </Card>
      </Section>

      {scale && scale.capital_quote > 0 && (
        <Section
          id="at-scale"
          title="At a size the ranges can take"
          intro="The same policy over the same tape, with one input changed."
        >
          <Card>
            <p className="mt-0 mb-4 max-w-[72ch] text-sm text-dim">
              A1 caps a position at a fraction of the venue holding it, and at{" "}
              {money(data.capital_quote, unit)} that refuses every PancakeSwap
              range on this card. The refusal&rsquo;s own remedy is to quote for
              less capital, so this does: {money(scale.capital_quote, unit)},
              which is {scale.derived_from}.
            </p>

            <DataTable
              caption={`What Router did at ${money(scale.capital_quote, unit)}`}
              rows={[
                {
                  label: "Net return on supplied capital",
                  value: scale.quote.sufficient
                    ? `${pct(scale.quote.p25)} – ${pct(scale.quote.p75)}`
                    : "withheld",
                  note: scale.quote.sufficient
                    ? `median ${pct(scale.quote.p50)} · ${scale.quote.basis}`
                    : scale.quote.note,
                },
                {
                  label: "Samples inside a range",
                  value: `${count(scale.pool_held_samples)} of ${count(
                    scale.samples
                  )}`,
                  note:
                    scale.pool_held_samples > 0
                      ? "the agent using the venue it was built for, rather than only measuring it"
                      : "still none — the ranges were refused at this size too",
                },
                {
                  label: "Moves",
                  value: `${scale.entries} enter · ${scale.switches} switch · ${scale.exits} exit`,
                  note: `invested ${pct(scale.invested_fraction)} of the run`,
                },
                {
                  label: "Best rate it could take",
                  value: rate(scale.best_apr_seen),
                  note: `earned ${money(scale.net_quote, unit)} net`,
                },
              ]}
              notes="prose"
            />

            {scale.venues_held.length > 0 && (
              <p className="mt-4 mb-0 max-w-[72ch] text-sm">
                Held:{" "}
                {scale.venues_held
                  .map((v) =>
                    v.kind === "pool"
                      ? `${v.symbol} at ±${count(
                          v.reference_width_ticks
                        )} ticks`
                      : v.symbol
                  )
                  .join(", ")}
                .
              </p>
            )}

            {/* The thing this block is not. A smaller position earns less in
                absolute terms and the same rate is not more attainable for
                being demonstrated on less capital — what it shows is that the
                constraint was size and not yield, which is a different claim
                and the one A25 makes. */}
            <p className="mt-4 mb-0 max-w-[72ch] text-sm text-muted">
              This is not a better result, it is a smaller one. The rate is what
              a range of this width paid over this tape either way; what changes
              with the notional is whether A1 allows the position at all. A
              reader with more capital than the ceiling should read the refusal
              above, not this.
            </p>
          </Card>
        </Section>
      )}

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

      <Section title="Assumptions this rests on">
        <Card>
          <ul className="m-0 list-none space-y-3 p-0 text-sm text-dim">
            {data.caveats.map((c) => (
              // `Prose`, which is `WithCitations` plus the markdown the emitter
              // has always written. The citations came first: these carry A- and
              // P- ids and printed them as inert text, and `AgentDetail`
              // linkified the same field, so one caveat was a link on one
              // tearsheet and not on another. The half still missing was the
              // rest of the syntax — `make pools` and `pools.json` reached this
              // list inside literal backticks.
              <li key={c}>
                <Prose text={c} />
              </li>
            ))}
          </ul>
        </Card>
      </Section>

      {/* Live, so it renders nothing on the static export and needs no rail
          entry — see its own docstring. It is the last piece of evidence on the
          page and it is about a different run from everything above it. */}
      <AgentJournal agent="router" />

      {/* The same edge as `AgentDetail`'s, for the fourth card. Router is the
          one agent reachable only through the marketplace path, so leaving it
          out would break the journey on exactly the category the Agent Studio
          CLI deployment is about. */}
      <p className="mt-10 text-sm text-dim">
        <Link href="/activate">
          What hiring this agent would involve, and why there is no button →
        </Link>
      </p>
    </div>
  );
}
