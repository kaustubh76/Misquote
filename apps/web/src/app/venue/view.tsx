"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card } from "@/components/Card";
import { Prose } from "@/components/Blocks";
import { WithCitations } from "@/components/Cite";
import { DataTable } from "@/components/DataTable";
import { Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import { PoolLookup } from "@/components/PoolLookup";
import { ErrorNotice } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { WidthLadder, type LadderBand } from "@/components/WidthLadder";
import { load, type Loaded } from "@/lib/artifacts";
import { count, fixed, fraction, isNum, money, shortAddress } from "@/lib/format";

interface Divergence {
  what: string;
  uniswap: string;
  pancake: string;
  costs: string;
  provenance: string;
  /** The module the divergence is handled in, and the test that holds it. */
  where: string;
  caught_by: string;
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
    /**
     * Whether the fork actually left the libraries alone.
     *
     * Null until `make fork-parity` has run, and that is the honest state for a
     * clean checkout: the check reads GitHub, the emitter reads no network, so
     * the artifact carries whatever was last recorded and nothing when nothing
     * was. Rendered as an absence, never as a pass.
     */
    parity: {
      outcome: string;
      libraries: number;
      identical: number;
      commit: string;
      pinned: string;
      repo: string;
      checked_at: string;
    } | null;
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
/**
 * One rung is `LadderBand`, declared beside the component that draws it.
 *
 * This file used to redeclare the seven fields itself. Two declarations of one
 * emitter's shape is one too many — `indistinguishable_from` was added to the
 * artifact and to `components/WidthLadder.tsx`, and a second copy here would
 * have typechecked all the way to a ladder that silently offered no comparison.
 */
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
  ladder: LadderBand[];
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
  /**
   * `checks` is declared only so this page can count them.
   *
   * `/vetting` renders each reading; this page needs to say how many a badge
   * is, and said "nine" in three places rather than measure the array that is
   * right here. Typed as `unknown[]` because nothing on this page looks inside
   * a check — declaring the shape would be declaring an interface it does not
   * read, which `lib/artifacts.ts` sets the rule against: only what is
   * rendered is declared.
   */
  pools: { pool?: string; badged?: boolean; checks?: unknown[] }[];
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

  // How many readings a badge is, counted off a badge rather than typed.
  //
  // Three places on this page said "nine" — two in prose and one in a table
  // cell — and `vetting/view.tsx` said it a fourth time. It is
  // `badges.pools[].checks.length`, it is the same nine for every pool, and it
  // has no business being a word. Undefined when no badge was read, and the
  // sentences below say "the checks" rather than inventing a number.
  const perPoolChecks = badges?.pools?.find((p) => Array.isArray(p.checks))?.checks?.length;

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

              {/* The step every one of those cases depends on, and which this
                  page asserted for months.

                  The corpus is generated against the table above — *Uniswap's*
                  Solidity, at Uniswap's commits. It says nothing about
                  PancakeSwap unless the fork left those libraries alone, and
                  that clause was carried by a comment in `ops/forge_deps.txt`
                  and another in `scripts/venue_report.py`. Both were right.
                  Neither was checked, on the page whose entire argument is that
                  a plausible sentence is not a reading.

                  `make fork-parity` reads PancakeSwap's own copies at a pinned
                  commit and compares the token streams, so a reflowed ternary
                  and a different licence header pass and a changed constant
                  does not. */}
              {d.shared_math.parity ? (
                <p className="mt-3 mb-0 border-t border-line pt-3 text-xs text-faint">
                  And the step that makes any of it a claim about this venue:{" "}
                  <strong
                    className={
                      d.shared_math.parity.outcome === "PASS"
                        ? "text-good"
                        : "text-warn"
                    }
                  >
                    {count(d.shared_math.parity.identical)} of{" "}
                    {count(d.shared_math.parity.libraries)}
                  </strong>{" "}
                  of those libraries are token-identical to{" "}
                  {d.venue.name}&rsquo;s own copies —{" "}
                  <a
                    href={`https://github.com/${d.shared_math.parity.repo}/tree/${d.shared_math.parity.commit}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {d.shared_math.parity.repo}
                  </a>{" "}
                  at{" "}
                  <code className="font-mono">
                    {d.shared_math.parity.commit.slice(0, 12)}
                  </code>
                  , pinned {d.shared_math.parity.pinned}. Same licence header
                  changed, same lines rewrapped, same arithmetic.
                </p>
              ) : (
                <p className="mt-3 mb-0 border-t border-line pt-3 text-xs text-faint">
                  Whether the fork left those libraries alone has not been
                  checked here. Run{" "}
                  <code className="font-mono">make fork-parity</code> — it reads{" "}
                  {d.venue.name}&rsquo;s repository and compares the token
                  streams. Until it has, the corpus above is a comparison
                  against {d.venue.fork_of} and nothing more.
                </p>
              )}
            </Card>
          </Section>

          {/* ------------------------------------------ the divergences -- */}
          <Section
            title="Where it is not"
            intro="Each row cost something before it was written down. The last column is what catches it now."
          >
            {/* The one place a PancakeSwap reader will look, linking the one
                document written for them. It had lived in the repository,
                referenced from a single line of a single file, which is a
                findings list that finds nobody. */}
            {/* The one transaction this project has sent to PancakeSwap.
                It is a v2 swap, not a position — and saying so is the point:
                every other mainnet claim here carries a hash, and the one on
                the venue the whole project is built around did not, because
                nobody wrote it down. */}
            <p className="mt-0 mb-3 max-w-[70ch] text-sm text-dim">
              We have sent exactly one transaction to PancakeSwap:{" "}
              <a
                href="https://bscscan.com/tx/0x63a1b95c219806110e3970794df9a537e677272a1b9ed8992fa82d0dbe0878f2"
                target="_blank"
                rel="noreferrer"
              >
                a v2 swap
              </a>{" "}
              that bought the ERC-8183 payment token this project had recorded as
              unobtainable. Not a liquidity position &mdash; nothing here has
              minted one on mainnet, and that is on the ledger rather than in a
              footnote.
            </p>
            <p className="mt-0 mb-5 max-w-[70ch] text-sm text-dim">
              These are written up as{" "}
              <a
                href="https://github.com/kaustubh76/Misquote/blob/main/docs/PANCAKESWAP_FINDINGS.md"
                target="_blank"
                rel="noreferrer"
              >
                six findings to file upstream
              </a>{" "}
              &mdash; each with what it costs to get wrong, and opening on the
              one we got wrong ourselves.
            </p>
            <div className="grid gap-4">
              {d.divergences.map((row) => (
                <Card key={row.what} className="!p-5">
                  <p className="m-0 text-sm font-semibold text-ink">
                    <Prose text={row.what} />
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

                  {/* The section above promises "the last column is what
                      catches it now", and for the life of this page the last
                      column was the assumption ids.
                      `where` and `caught_by` have been on every row of
                      `venue.json` since it was written — the module that
                      handles the divergence and the test that holds it — and
                      the comment that used to sit here described rendering
                      them while the markup rendered neither. A claim that six
                      defects are each caught by something that runs is worth
                      exactly the name of the thing that runs, and a reader had
                      to take it on faith.

                      `caught_by` is rendered verbatim rather than parsed: two
                      of the six carry a clause naming the check inside the
                      module — "badge.py — check 'factory resolves it'" — and
                      the file alone would drop the half that says which of the
                      nine. */}
                  <p className="mt-3 mb-0 border-t border-line pt-2 text-xs text-faint">
                    <span className="text-dim">caught by</span>{" "}
                    <code className="font-mono">{row.caught_by}</code>
                    <br />
                    <span className="text-dim">handled in</span>{" "}
                    <code className="font-mono">{row.where}</code>
                  </p>
                  <p className="mt-1 mb-0 text-xs text-faint">
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
                columns={["Pool", "Fee · spacing · smallest range", "LPs keep · checked"]}
                rows={d.pools.map((pool) => ({
                  label: pool.label,
                  // `w_min_ticks` was emitted on every one of these rows and
                  // rendered on no page. It is the anti-dust floor — the
                  // smallest half-width the pool will accept — and it is the
                  // reason `/simulate` refuses +/-40, +/-80 and +/-130 on the
                  // 0.25% pool while allowing all three on the flagship. So the
                  // number lived here, was shown nowhere, and was re-derived in
                  // Python for the other page. This table already carried the
                  // spacing and stopped one column short of what the spacing
                  // costs.
                  value: `${pool.fee_pips} · ${pool.tick_spacing} · ±${pool.w_min_ticks}`,
                  // The badge verdict sits with the constants it vouches for.
                  // `feeProtocol 3400` and "nobody has checked that on chain"
                  // are one fact, and this page's argument does not survive
                  // splitting them into two places.
                  note: `${fraction(pool.lp_fee_share)} — feeProtocol ${
                    pool.fee_protocol
                  } · ${
                    checked.has(pool.address.toLowerCase())
                      ? perPoolChecks === undefined
                        ? "checked"
                        : `${perPoolChecks} checks passed`
                      : badges?.chain_id
                        ? `not checked — /vetting reads chain ${badges.chain_id}`
                        : // No chain id, so no chain id is named. This read
                          // `badges?.chain_id ?? "56"`, which invented one on
                          // the exact branch where the badge file was the thing
                          // that could not be read — the sentence asserting
                          // which chain /vetting reads was fabricated precisely
                          // when nothing had been read from any chain.
                          "not checked — no badge file was read"
                  }`,
                }))}
                notes="prose"
              />

              <p className="mt-4 mb-0 text-xs text-faint">
                {/* What the floor above costs, on the page that enforces it. */}
                A range narrower than a pool&rsquo;s floor cannot be minted there
                &mdash; <Link href="/simulate">which widths that rules out →</Link>
                <br />
                {d.pools.map((pool) => shortAddress(pool.address)).join(" · ")}{" "}
                ·{" "}
                {/* Counted, not claimed. This read "The nine checks each of them
                    passed" over a table containing a pool on another chain that
                    no check has ever touched. */}
                <Link href="/vetting">
                  {count(checked.size)} of {count(d.pools.length)} through the{" "}
                  {perPoolChecks === undefined ? "" : `${perPoolChecks} `}checks →
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
            {/* The question this section answers is which width. The question a
                reader arrives with is what it would have paid them, and that is
                a different page — same windows, same engine, an amount instead
                of a percentile. It is linked here because this is where someone
                has just finished choosing a width. */}
            <p className="mt-0 mb-4 max-w-[70ch] text-sm text-dim">
              These are rates. To see what one of them would have paid on an
              amount you pick, over a window you pick,{" "}
              <Link href="/simulate">simulate the position &rarr;</Link>
            </p>
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
                      // The size, not "per unit of capital". `capital_quote`
                      // was in the artifact and read by nothing while both
                      // places that needed it said "unit" — the same sentence
                      // with the number left out, on the page whose argument is
                      // that a figure names what it is denominated in.
                      note: `±${count(pools.width_ladder[0])} to ±${count(
                        pools.width_ladder[pools.width_ladder.length - 1]
                      )} ticks, per ${money(pools.capital_quote, pools.pools[0]?.quote_symbol)}`,
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
                      {/* `WidthLadder` rather than `DataTable`, and the rows
                          are the same rows: same widths, same figures, same
                          order. What the table could not do is the comparison
                          this section is about. Seven ranges printed as text
                          leave "is ±80 actually better than ±200" to a reader
                          holding fourteen numbers in their head, which is the
                          arithmetic this project keeps saying nobody does. */}
                      <WidthLadder
                        caption={`Fee APR by width, net of the convexity cost, per ${money(
                          pools.capital_quote,
                          pool.quote_symbol
                        )}`}
                        bands={usable}
                        bestWidth={pool.best_width_ticks}
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
                          A P25 below −100% is an annualised rate, not a realized
                          loss — one bad day scaled to a year lands in the hundreds.
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
                    {/* The other half of the answer, which is on the other
                        page. Thin depth is why a pool pays well per unit and is
                        also why it can absorb almost nothing, and a reader
                        given only the ratio is given the opportunity without
                        the constraint. No figure here on purpose: the ceilings
                        are measured in `simulation.json`, this view already
                        joins three artifacts, and a fourth would make it the
                        worst offender for the collision `LEAF_COLLISIONS`
                        exists to record. */}
                    <p className="mt-0 mb-4 max-w-[72ch] text-sm text-dim">
                      A ratio is half of it. The same thinness that pays each
                      unit well is what caps how much can be put in —{" "}
                      <Link href="/simulate">
                        how much each pool can actually take &rarr;
                      </Link>
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
                Hold a position in a pool that is not listed? Ask directly — the
                answer tells you whether it was unverified or simply unrankable.
              </p>
              {/* The set the route can answer, handed to the control that asks.
                  `pools.json`'s own rows, so the chips cannot name a pool the
                  published report does not carry. */}
              <PoolLookup
                known={(pools?.pools ?? []).map((pool) => ({
                  label: pool.label,
                  address: pool.address,
                }))}
              />
            </Card>
          </Section>
        </>
      )}
    </Loadable>
  );
}
