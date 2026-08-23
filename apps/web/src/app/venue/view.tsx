"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BuildStamp, type Build } from "@/components/BuildStamp";
import { Card } from "@/components/Card";
import { WithCitations } from "@/components/Cite";
import { DataTable } from "@/components/DataTable";
import { Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import { ErrorNotice } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { load, type Loaded } from "@/lib/artifacts";
import { count, fraction, shortAddress } from "@/lib/format";

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
  shared_math: { cases: number; groups: number; pins: { name: string; commit: string; pinned: string }[] };
  fee_tiers: { fee_pips: number; tick_spacing: number }[];
  uniswap_only_tier: number;
  fee_overstatement: number;
  unmintable_remainder: number;
  divergences: Divergence[];
  pools: VenuePool[];
  build?: Build;
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
/** Only what this page needs of `vetting.json`: which pools carry a badge. */
export interface BadgeSurvey {
  chain_id: number;
  pools: { pool?: string; badged?: boolean }[];
}

export function VenueView({ initial, initialBadges }: {
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
   * Derived rather than asserted, for the reason `SourceBanner`'s docstring was
   * wrong twice: which pools are covered is data, and a view that hardcodes it
   * is correct only until somebody runs `make vet --chain 97`.
   */
  initialBadges?: BadgeSurvey;
}) {
  const [state, setState] = useState<Loaded<VenueArtifact> | null>(
    initial ? { ok: true, value: initial } : null,
  );
  const [badges, setBadges] = useState<BadgeSurvey | undefined>(initialBadges);

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
    return () => {
      live = false;
    };
  }, []);

  // Lowercased, because one file writes checksummed addresses and the other
  // writes them folded.
  const checked = new Set(
    (badges?.pools ?? [])
      .filter((p) => p.badged && typeof p.pool === "string")
      .map((p) => (p.pool as string).toLowerCase()),
  );

  const d = state?.ok ? state.value : null;

  return (
    <Loadable loading={state === null} what="the venue report" className="max-w-3xl">
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">
        Where PancakeSwap is not Uniswap
      </h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        The cores are the same source. Everything below is a place they diverge, and
        each one is a defect this project hit before it was a paragraph.
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
                Run <code className="font-mono text-xs">make venue</code>. It reads no
                chain — every field is a projection of a constant in this repository.
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
                {d.venue.name} forks {d.venue.fork_of}, so the tick and liquidity
                libraries are the same source. That is what makes a{" "}
                <strong className="text-ink">differential corpus</strong> meaningful
                rather than circular.
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
                {count(d.shared_math.groups)} functions, replayed at exact integer
                equality — no tolerance anywhere.{" "}
                <Link href="/vectors">What was recorded, and whether it still holds →</Link>
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
                  <p className="m-0 text-sm font-semibold text-ink">{row.what}</p>

                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    <div className="rounded-sm border border-line bg-panel-2 px-3 py-2">
                      <p className="m-0 font-mono text-[0.6875rem] tracking-wide text-faint uppercase">
                        {d.venue.fork_of}
                      </p>
                      <p className="mt-1 mb-0 text-xs text-dim">{row.uniswap}</p>
                    </div>
                    <div className="rounded-sm border border-warn-line bg-warn-bg/40 px-3 py-2">
                      <p className="m-0 font-mono text-[0.6875rem] tracking-wide text-faint uppercase">
                        {d.venue.name}
                      </p>
                      <p className="mt-1 mb-0 text-xs text-dim">{row.pancake}</p>
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
                  note: `${fraction(pool.lp_fee_share)} — feeProtocol ${pool.fee_protocol} · ${
                    checked.has(pool.address.toLowerCase())
                      ? "nine checks passed"
                      : `not checked — /vetting reads chain ${badges?.chain_id ?? "56"}`
                  }`,
                }))}
                notes="prose"
              />

              <p className="mt-4 mb-0 text-xs text-faint">
                {d.pools.map((pool) => shortAddress(pool.address)).join(" · ")} ·{" "}
                {/* Counted, not claimed. This read "The nine checks each of them
                    passed" over a table containing a pool on another chain that
                    no check has ever touched. */}
                <Link href="/vetting">
                  {count(checked.size)} of {count(d.pools.length)} through the nine checks →
                </Link>
              </p>
            </Card>

            <Card className="mt-4">
              <p className="m-0 max-w-[72ch] text-sm text-dim">
                {/* The tier table, rendered rather than described. The absent
                    tier is the claim, so it is drawn as an absence beside the
                    ones that exist rather than asserted in a sentence. */}
                Fee tiers here are{" "}
                {d.fee_tiers.map((tier, i) => (
                  <span key={tier.fee_pips}>
                    {i > 0 && ", "}
                    <span className="font-mono text-xs text-ink">
                      {tier.fee_pips}→{tier.tick_spacing}
                    </span>
                  </span>
                ))}
                . There is no{" "}
                <span className="font-mono text-xs text-warn">
                  {d.uniswap_only_tier}→60
                </span>
                , which is {d.venue.fork_of}&rsquo;s most-used tier.
              </p>
            </Card>
          </Section>

          {d.build && <BuildStamp className="mt-10" build={d.build} />}
        </>
      )}
    </Loadable>
  );
}
