"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card } from "@/components/Card";
import { WithCitations } from "@/components/Cite";
import { DataTable } from "@/components/DataTable";
import { Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import { PoolLookup } from "@/components/PoolLookup";
import { ErrorNotice } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { load, type Loaded } from "@/lib/artifacts";
import { count, fixed, fraction, isNum, shortAddress } from "@/lib/format";

interface Divergence {
  what: string;
  uniswap: string;
  pancake: string;
  costs: string;
  where: string;
  caught_by: string;
  provenance: string;
}

interface VenuePool {
  role: string;
  label: string;
  address: string;
  chain_id: number;
  fee_pips: number;
  tick_spacing: number;
  fee_protocol: number;
  lp_fee_share: number;
  w_min_ticks: number;
  quote_symbol: string;
}

export interface VenueArtifact {
  venue: { name: string; fork_of: string; chain_id: number };
  shared_math: {
    cases: number;
    groups: number;
    pins: { name: string; commit: string; pinned: string }[];
  };
  fee_tiers: { fee_pips: number; tick_spacing: number }[];
  uniswap_only_tier: number;
  fee_overstatement: number;
  unmintable_remainder: number;
  divergences: Divergence[];
  pools: VenuePool[];
}

/**
 * The venue as an integration, which the site had nowhere to say.
 *
 * Every other page here is about *method* — how a quote is made, what it refuses
 * to claim. The substrate all of it runs on reached a reader only as a label
 * inside a provenance banner, so "we built on PancakeSwap" was something the
 * site demonstrated and never said.
 *
 * The order is the argument. **The math is Uniswap's** goes first because it is
 * the larger and less obvious half: the cores are the same source, which is what
 * makes a differential corpus meaningful at all. **Where it is not** goes second
 * because that is the part that costs money. Putting the divergences first would
 * read as a list of grievances against a fork rather than as the reason a
 * replay built from Uniswap's documentation would be quietly wrong here.
 *
 * Nothing on this page is typed. `venue.json` is a projection of the constants
 * that implement each divergence, re-derived in full by
 * `tests/web/test_artifact_projections.py` — so a page arguing that the details
 * were got right cannot itself carry a figure that drifted from the code.
 */
/**
 * `pools.json`, as this page reads it.
 *
 * Emitted by `make pools`, served by `GET /pools`, and for a while read by
 * nothing at all — the width ladder existed, was tested and was reachable over
 * HTTP, and no page rendered it. A benefit nobody can see has not been
 * delivered, and this is the page it belongs on: everything else here is about
 * the venue, and this is the only thing here an LP can act on.
 */
export interface WidthBand {
  width_ticks: number;
  p25: number;
  p50: number;
  p75: number;
  observations: number;
  sufficient: boolean;
  note: string;
}

export interface PoolLadder {
  address: string;
  label: string;
  fee_pips: number;
  quote_symbol: string;
  badged: boolean;
  /** Null when no width cleared the evidence floor. Then the verdict says so. */
  best_width_ticks: number | null;
  /** The engine's own sentence, rendered verbatim. Never re-derived here. */
  verdict: string;
  ladder: WidthBand[];
  demand: {
    swaps: number;
    volume_quote: number;
    tick_crossings: number;
    median_liquidity: number;
    /** What an LP's return is actually proportional to. See `tearsheet/pools.py`. */
    fee_per_unit_liquidity: number;
  };
}

export interface PoolsArtifact {
  chain_id: number;
  capital_quote: number;
  /** Every width the ladder was run at, so its span is stated not inferred. */
  width_ladder: number[];
  /** How many pools were looked at, badged, ranked, and refused. */
  summary: { pools: number; badged: number; quotable: number; refused: number };
  pools: PoolLadder[];
}

/** Only what this page needs of `vetting.json`: which pools carry a badge. */
export interface BadgeSurvey {
  chain_id: number;
  pools: { pool?: string; badged?: boolean }[];
}

export function VenueView({
  initial,
  initialBadges,
  initialPools,
}: {
  /** Read from disk at build time by `page.tsx`. See `lib/build-artifact`. */
  initial?: VenueArtifact;
  /**
   * What `/vetting` has actually checked.
   *
   * This page listed four pools under a link reading "The nine checks each of
   * them passed" — and `/vetting` runs against one chain. The chapel mirror is
   * on 97 and has never been through a single check, so the sentence was an
   * overstatement about a quarter of its own table, on the page whose whole
   * argument is that these details were read rather than assumed.
   *
   * Derived rather than asserted: which pools are covered is data, and a view
   * that hardcodes it is correct only until somebody runs `make vet --chain 97`.
   */
  initialBadges?: BadgeSurvey;
  /**
   * The width ladder, when `make pools` has been run.
   *
   * Optional on purpose. `make artifacts` does not build `pools` — the ladder
   * replays the accountant across the whole tape at seven widths and takes
   * minutes — so a clean checkout genuinely will not have this file, and the
   * page has to be complete without it rather than broken.
   */
  initialPools?: PoolsArtifact;
}) {
  const [state, setState] = useState<Loaded<VenueArtifact> | null>(
    initial ? { ok: true, value: initial } : null
  );
  const [badges, setBadges] = useState<BadgeSurvey | undefined>(initialBadges);
  const [pools, setPools] = useState<PoolsArtifact | undefined>(initialPools);

  useEffect(() => {
    let live = true;
    load<VenueArtifact>("venue.json").then((r) => {
      if (live) setState(r);
    });
    // Refreshed on the same terms as the table it annotates. Only a successful
    // read replaces it: a missing `vetting.json` means nothing has been badged,
    // and the honest surface for that is every row reading "not checked".
    load<BadgeSurvey>("vetting.json").then((r) => {
      if (live && r.ok) setBadges(r.value);
    });
    // Same terms, same reason: an absent ladder means it has not been measured,
    // and the honest surface for that is a section that says so.
    load<PoolsArtifact>("pools.json").then((r) => {
      if (live && r.ok) setPools(r.value);
    });
    return () => {
      live = false;
    };
  }, []);

  // Lowercased, because one file writes checksummed addresses and the other
  // writes them folded.
  const checked = new Set(
    (badges?.pools ?? [])
      .filter((p) => p.badged && typeof p.pool === "string")
      .map((p) => (p.pool as string).toLowerCase())
  );

  const d = state?.ok ? state.value : null;

  return (
    <Loadable
      loading={state === null}
      what="the venue report"
      className="max-w-3xl"
    >
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">
        Where PancakeSwap is not Uniswap
      </h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        The cores are the same source. Everything below is a place they diverge,
        and each one is a defect this project hit before it was a paragraph.
      </p>

      {state === null && (
        <div className="mt-10">
          <CardSkeleton />
        </div>
      )}

      {state && !state.ok && (
        <div className="mt-10">
          <ErrorNotice
            title="No venue report has been generated"
            detail={state.error.message}
            remedy={
              <>
                Run <code className="font-mono text-xs">make venue</code>. It
                reads no chain — every field is a projection of a constant in
                this repository.
              </>
            }
          />
        </div>
      )}

      {d && (
        <>
          {/* ------------------------------------------- the shared half -- */}
          <Section title="The math is Uniswap's">
            <Card>
              <p className="mt-0 mb-4 max-w-[72ch] text-sm text-dim">
                {d.venue.name} forks {d.venue.fork_of}, so the tick and
                liquidity libraries are the same source. That is what makes a{" "}
                <strong className="text-ink">differential corpus</strong>{" "}
                meaningful rather than circular.
              </p>

              <DataTable
                caption="Upstream libraries, at the commits they were recorded from"
                hideCaption={false}
                columns={["Library", "Commit", "Pinned"]}
                rows={d.shared_math.pins.map((pin) => ({
                  label: pin.name,
                  value: pin.commit.slice(0, 12),
                  note: pin.pinned,
                }))}
              />

              <p className="mt-4 mb-0 text-xs text-faint">
                {count(d.shared_math.cases)} recorded answers across{" "}
                {count(d.shared_math.groups)} functions, replayed at exact
                integer equality — no tolerance anywhere.{" "}
                <Link href="/vectors">
                  What was recorded, and whether it still holds →
                </Link>
              </p>
            </Card>
          </Section>

          {/* ------------------------------------------ the divergences -- */}
          <Section
            title="Where it is not"
            intro="Each row cost something before it was written down. The last column is what catches it now."
          >
            <div className="grid gap-4">
              {d.divergences.map((row) => (
                <Card key={row.what} className="!p-5">
                  <p className="m-0 text-sm font-semibold text-ink">
                    {row.what}
                  </p>

                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    <div className="rounded-sm border border-glass-line bg-panel-2/50 px-3 py-2">
                      <p className="m-0 font-mono text-[0.6875rem] tracking-wide text-faint uppercase">
                        {d.venue.fork_of}
                      </p>
                      <p className="mt-1 mb-0 text-xs text-dim">
                        {row.uniswap}
                      </p>
                    </div>
                    <div className="rounded-sm border border-warn-line bg-warn-bg/40 px-3 py-2">
                      <p className="m-0 font-mono text-[0.6875rem] tracking-wide text-faint uppercase">
                        {d.venue.name}
                      </p>
                      <p className="mt-1 mb-0 text-xs text-dim">
                        {row.pancake}
                      </p>
                    </div>
                  </div>

                  {/* The row's reason to exist. Not styled as a warning: it is
                      not a caveat about the venue, it is what the integration
                      had to get right, and it is stated in full rather than
                      summarised because the amount is the point. */}
                  <p className="mt-3 mb-0 max-w-[72ch] text-sm">{row.costs}</p>

                  <p className="mt-3 mb-0 border-t border-line pt-2 font-mono text-xs break-words text-faint">
                    {row.where} · caught by {row.caught_by} ·{" "}
                    {/* The provenance carries P- and V- ids, and `WithCitations`
                        linkifies them out of the artifact string — so the same
                        text stays byte-identical in the JSON and in the page. */}
                    <WithCitations text={row.provenance} />
                  </p>
                </Card>
              ))}
            </div>

            {/* What the first divergence costs, as a figure.

                `fee_overstatement` has been in the artifact as long as the
                report has, and the page argued about it in prose and never
                showed it. It is 1 / `lp_fee_share` for the flagship pool: a
                replay that reconstructs LP fees from swap volume — which is
                what every integration written from the fork parent's
                documentation does — counts the whole fee, and the position is
                only paid part of it.

                Its own card rather than attached to a divergence row. Selecting
                that row would mean keying off an index or matching its `where`
                string, and both are the kind of brittle join that survives
                until an emitter reorders a list.

                One bar, split, rather than two bars: it is one fee, and the
                question is who receives it. The protocol's share is hatched
                because the hatch means "there is deliberately nothing here",
                and that is exactly what it is to the LP — fees a reconstruction
                counts and the position never sees. */}
            {(() => {
              const flagship = d.pools.find((pool) => pool.role === "flagship");
              if (!flagship || !isNum(flagship.lp_fee_share)) return null;
              const lp = flagship.lp_fee_share;
              return (
                <Card className="mt-4">
                  <p className="mt-0 mb-4 max-w-[72ch] text-sm text-dim">
                    The pool charges one fee. The LP is not paid all of it, and
                    a replay written from {d.venue.fork_of}&rsquo;s
                    documentation has no reason to know that.
                  </p>

                  <div
                    className="hatched relative h-6 overflow-hidden rounded-sm border border-glass-line"
                    role="img"
                    aria-label={`Of every fee this pool charges, the liquidity provider receives ${fraction(
                      lp
                    )} and the protocol takes the rest.`}
                  >
                    <div
                      className="absolute inset-y-0 left-0 bg-brand/35"
                      style={{ width: `${lp * 100}%` }}
                    />
                    <span
                      className="absolute inset-y-0 left-0 border-r border-brand"
                      style={{ width: `${lp * 100}%` }}
                    />
                  </div>

                  <div className="mt-2 flex flex-wrap justify-between gap-x-4 text-xs">
                    <span className="text-dim">
                      the LP receives{" "}
                      <span className="tabular text-ink">{fraction(lp)}</span> —
                      feeProtocol {count(flagship.fee_protocol)}
                    </span>
                    <span className="text-faint">
                      the protocol takes{" "}
                      <span className="tabular">{fraction(1 - lp)}</span>
                    </span>
                  </div>

                  <p className="mt-4 mb-0 border-t border-line pt-3 text-sm">
                    <span className="tabular font-semibold text-warn">
                      {fixed(d.fee_overstatement, 3)}&times;
                    </span>{" "}
                    <span className="text-dim">
                      — how much a replay that reconstructs fees from swap
                      volume overstates what a position earned, and it lands on
                      the headline return.
                    </span>
                  </p>
                </Card>
              );
            })()}
          </Section>

          {/* ------------------------------------------------- the pools -- */}
          <Section
            title="The pools we actually read"
            intro="One DEX, and no constant is right for all of them — which is why every field below is read rather than defaulted."
          >
            <Card>
              <DataTable
                caption="Every pool this project has read, and where they differ"
                hideCaption={false}
                columns={["Pool", "Fee tier · spacing", "LPs keep · checked"]}
                rows={d.pools.map((pool) => ({
                  label: pool.label,
                  value: `${pool.fee_pips} · ${pool.tick_spacing}`,
                  // The badge verdict sits with the constants it vouches for.
                  // `feeProtocol 3400` and "nobody has checked that on chain"
                  // are one fact, and this page's argument does not survive
                  // splitting them into two places.
                  note: `${fraction(pool.lp_fee_share)} — feeProtocol ${
                    pool.fee_protocol
                  } · ${
                    checked.has(pool.address.toLowerCase())
                      ? "nine checks passed"
                      : `not checked — /vetting reads chain ${
                          badges?.chain_id ?? "56"
                        }`
                  }`,
                }))}
                notes="prose"
              />

              <p className="mt-4 mb-0 text-xs text-faint">
                {d.pools.map((pool) => shortAddress(pool.address)).join(" · ")}{" "}
                ·{" "}
                {/* Counted, not claimed. This read "The nine checks each of them
                    passed" over a table containing a pool on another chain that
                    no check has ever touched. */}
                <Link href="/vetting">
                  {count(checked.size)} of {count(d.pools.length)} through the
                  nine checks →
                </Link>
              </p>
            </Card>

            <Card className="mt-4">
              {/* The comment here used to say the absent tier "is drawn as an
                  absence beside the ones that exist rather than asserted in a
                  sentence", and then asserted it in a sentence. It is drawn
                  now: the tiers that exist are solid chips and the one that
                  does not is a dashed, hatched chip in the same row — the
                  site's texture for "there is deliberately nothing here",
                  which is what a missing fee tier is.

                  The absent chip's `<span>` holds exactly `3000→60` and its
                  `<li>` holds no direct text of its own, which is what keeps
                  `pages.test.tsx`'s singular `getByText` on that string
                  matching one element. */}
              <p className="mt-0 mb-3 max-w-[72ch] text-sm text-dim">
                Fee tiers here, and the one that is not.
              </p>

              <ul className="m-0 flex list-none flex-wrap items-center gap-2 p-0">
                {d.fee_tiers.map((tier) => (
                  <li key={tier.fee_pips}>
                    <span className="inline-block rounded-sm border border-glass-line bg-panel-2/50 px-2.5 py-1 font-mono text-xs text-ink">
                      {tier.fee_pips}&rarr;{tier.tick_spacing}
                    </span>
                  </li>
                ))}
                <li>
                  <span className="hatched inline-block rounded-sm border border-dashed border-warn-line px-2.5 py-1 font-mono text-xs text-warn [--hatch-tone:var(--hatch-warn)]">
                    {d.uniswap_only_tier}&rarr;60
                  </span>
                </li>
              </ul>

              <p className="mt-3 mb-0 max-w-[72ch] text-sm text-dim">
                The dashed one is {d.venue.fork_of}&rsquo;s most-used tier, and
                it does not exist here. A position sized for it has{" "}
                <span className="tabular text-ink">
                  {count(d.unmintable_remainder)}
                </span>{" "}
                ticks of remainder that cannot be minted at any spacing this
                venue offers.
              </p>
            </Card>
          </Section>

          {/* --------------------------------- which pool, and how wide -- */}
          {/* The only section on this page an LP can act on.

              Everything above is about the venue as an integration — what the
              fork changed and what that cost to get right. This is the question
              somebody with capital actually has: which of these pools, at what
              width, and what would that have earned. `pools.json` has answered
              it since `make pools` existed and no page asked.

              Bands, never a leaderboard. Every figure is a P25-P75 range over
              rolling windows with its observation count, and the engine's own
              verdict sentence is rendered verbatim rather than re-derived —
              because the load-bearing half of it is the clause saying the lead
              is *not separated at this sample size*, and a page that recomputed
              a winner would drop exactly that. */}
          <Section
            title="Which pool, and how wide"
            intro="Measured over the indexed tape, as ranges rather than a ranking — two widths whose bands overlap have not been shown to differ."
          >
            {!pools && (
              <Card>
                <p className="mt-0 mb-0 max-w-[72ch] text-sm text-dim">
                  No width ladder has been measured. Run{" "}
                  <code className="font-mono text-xs">make pools</code> — it
                  reads the indexed tape and writes no chain. It is not part of{" "}
                  <code className="font-mono text-xs">make artifacts</code>{" "}
                  because it replays the fee and LVR accounting at every width
                  on the ladder, which takes minutes rather than seconds.
                </p>
              </Card>
            )}

            {/* What the ladder covered, before the per-pool detail.

                `summary` and `width_ladder` were both in the artifact and on no
                surface, so the section opened straight into the first pool and a
                reader had to count rows to learn how many pools had been looked
                at or how wide the sweep went. The counts are the honest headline
                for a measurement whose whole argument is about evidence: three
                pools examined, and one of them refused. */}
            {pools && (
              <Card>
                <DataTable
                  caption="What the ladder covered"
                  hideCaption={false}
                  rows={[
                    {
                      label: "Pools examined",
                      value: count(pools.summary.pools),
                      note: `${count(
                        pools.summary.badged
                      )} carry a due-diligence badge`,
                    },
                    {
                      label: "Ranked",
                      value: count(pools.summary.quotable),
                      note:
                        pools.summary.refused > 0
                          ? `${count(
                              pools.summary.refused
                            )} refused for want of evidence`
                          : "every badged pool cleared the evidence floor",
                    },
                    {
                      label: "Widths measured",
                      value: count(pools.width_ladder.length),
                      note: `±${count(pools.width_ladder[0])} to ±${count(
                        pools.width_ladder[pools.width_ladder.length - 1]
                      )} ticks, per unit of capital`,
                    },
                  ]}
                  notes="prose"
                />
              </Card>
            )}

            {pools?.pools.map((pool) => {
              const usable = pool.ladder.filter((band) => band.sufficient);
              return (
                <Card key={pool.address} className="mt-4">
                  <p className="mt-0 mb-1 text-sm font-semibold text-ink">
                    {pool.label}
                  </p>
                  {/* Verbatim from the engine. See the comment above. */}
                  <p className="mt-0 mb-4 max-w-[72ch] text-sm text-dim">
                    {pool.verdict}
                  </p>

                  {usable.length > 0 ? (
                    <>
                      <DataTable
                        caption={`Fee APR by width, net of the convexity cost, per unit of capital in ${pool.quote_symbol}`}
                        hideCaption={false}
                        columns={["Width", "P25 – P75", "Median · windows"]}
                        rows={usable.map((band) => ({
                          label: `±${count(band.width_ticks)} ticks`,
                          value: `${fraction(band.p25)} – ${fraction(
                            band.p75
                          )}`,
                          note: `${fraction(band.p50)} · ${count(
                            band.observations
                          )} windows${
                            band.width_ticks === pool.best_width_ticks
                              ? " · leads"
                              : ""
                          }`,
                        }))}
                        notes="prose"
                      />
                      {/* Why a P25 can sit far below −100%.

                          The figure is net of the realized convexity cost, and
                          A10 publishes that cost as an *upper bound* on adverse
                          selection — so the subtraction is a lower bound, not a
                          middle. Annualising a bad day multiplies it by three
                          hundred and sixty-five: a range giving up under a
                          percent of its capital to arbitrage in a day shows as
                          a rate in the hundreds. It is arithmetic about a rate,
                          not a loss anyone realized, and clipping it at −100%
                          would be the tidier lie. */}
                      {usable.some((band) => band.p25 < -1) && (
                        <p className="mt-3 mb-0 max-w-[72ch] text-xs text-faint">
                          A P25 below −100% is an annualised rate, not a
                          realized loss: the convexity cost is an upper bound on
                          adverse selection, and a single bad day scaled to a
                          year lands in the hundreds. The worst quarter of
                          windows on this pool is where its depth is thinnest.
                        </p>
                      )}
                    </>
                  ) : (
                    <p className="mt-0 mb-0 max-w-[72ch] text-sm text-dim">
                      No width on the ladder cleared the evidence floor on this
                      pool, so there is no answer here rather than a small
                      number. It saw{" "}
                      <span className="tabular text-ink">
                        {count(pool.demand.swaps)}
                      </span>{" "}
                      swaps across the whole tape.
                    </p>
                  )}
                </Card>
              );
            })}

            {/* The demand finding, which is the other half of the question and
                the one volume alone gets wrong.

                Volume says a pool is busy. Busy is not underserved. What an LP's
                return is proportional to is fee income per unit of the liquidity
                already there, so that is what is ranked — and the ratio is taken
                against the busiest pool rather than printed raw, because the raw
                figure is a number with twenty-odd zeros in front of it and
                nobody can read it. Both come from the artifact; the division
                happens here because the comparison is between rows. */}
            {pools &&
              pools.pools.length > 1 &&
              (() => {
                const busiest = pools.pools.reduce((a, b) =>
                  b.demand.volume_quote > a.demand.volume_quote ? b : a
                );
                const base = busiest.demand.fee_per_unit_liquidity;
                if (!isNum(base) || base <= 0) return null;
                return (
                  <Card className="mt-4">
                    <p className="mt-0 mb-4 max-w-[72ch] text-sm text-dim">
                      Where the depth already there is being paid thinly — which
                      is where adding liquidity would improve the venue rather
                      than dilute it.
                    </p>
                    <DataTable
                      caption="Fee income per unit of liquidity, against the pool that saw the most volume"
                      hideCaption={false}
                      columns={[
                        "Pool",
                        "Per unit of liquidity",
                        "Depth · flow",
                      ]}
                      rows={pools.pools.map((pool) => ({
                        label: pool.label,
                        value:
                          pool.address === busiest.address
                            ? "the busiest pool"
                            : `${fixed(
                                pool.demand.fee_per_unit_liquidity / base,
                                1
                              )}× it`,
                        // The denominator, beside the ratio built from it.
                        // Publishing "3.4× the flagship" while hiding the depth
                        // that produced it is half the argument: the whole claim
                        // is that the same flow over less liquidity pays each
                        // unit more, and the liquidity is the half a reader
                        // cannot check without.
                        note: `median depth ${count(
                          pool.demand.median_liquidity
                        )} · ${count(pool.demand.volume_quote)} ${
                          pool.quote_symbol
                        } over ${count(pool.demand.swaps)} swaps, ${count(
                          pool.demand.tick_crossings
                        )} of which moved the tick`,
                      }))}
                      notes="prose"
                    />
                  </Card>
                );
              })()}

            {/* The question the list cannot answer: what about *my* pool.

                `/pools/{address}` was built for exactly that and had no caller —
                registered, tested, served, and reachable only by someone who
                already knew it existed. Mounted here as `BadgeLookup` is mounted
                on `/vetting`, and needing a live API is why it sits below the
                published ladders rather than above them. */}
            <Card className="mt-4">
              <p className="mt-0 mb-3 max-w-[72ch] text-sm text-dim">
                The ladders above are every pool this repository measured. If
                you hold a position in one, ask about it directly — the answer
                distinguishes a pool nobody verified from one that was verified
                and could not be ranked.
              </p>
              <PoolLookup />
            </Card>
          </Section>
        </>
      )}
    </Loadable>
  );
}
