"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card } from "@/components/Card";
import { Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import { PoolSimulator, type SimulationArtifact } from "@/components/PoolSimulator";
import { ErrorNotice } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { load, type Loaded } from "@/lib/artifacts";
import { count } from "@/lib/format";

/**
 * The PancakeSwap deliverable, as something a reader does rather than reads.
 *
 * Its own route rather than a fifth section on `/venue`, and the reason is where
 * the two sit. `/venue` is in the evidence band and is a document about
 * `slot0` layout and init-code hashes — correct, and not where somebody asking
 * *should I provide liquidity here* is going to arrive. This is in the product
 * band beside `/quote`, because it is the same kind of thing: an answer about
 * money, for a person who has some.
 *
 * The page is thin on purpose. Everything it knows is in `simulation.json` and
 * every decision is `PoolSimulator`'s; this supplies the frame, the honest
 * account of what the simulation is and is not, and the link back to the
 * evidence for anyone who wants to check rather than click.
 */
export function SimulateView({ initial }: { initial?: SimulationArtifact }) {
  const [state, setState] = useState<Loaded<SimulationArtifact> | null>(
    initial ? { ok: true, value: initial } : null
  );

  useEffect(() => {
    let live = true;
    load<SimulationArtifact>("simulation.json").then((r) => {
      if (live) setState(r);
    });
    return () => {
      live = false;
    };
  }, []);

  const d = state?.ok ? state.value : null;

  return (
    <Loadable loading={state === null} what="the simulation" className="max-w-3xl">
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">
        What a position on PancakeSwap would have earned you
      </h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        Pick a pool, a range width and an amount. Every figure is a replay of
        swaps that happened, so this signs nothing, holds nothing, and cannot
        cost anybody anything.
      </p>

      {state === null && (
        <div className="mt-10">
          <CardSkeleton />
        </div>
      )}

      {state && !state.ok && (
        <div className="mt-10">
          <ErrorNotice
            title="No simulation has been generated"
            detail={state.error.message}
            remedy={
              <>
                Run <code className="font-mono text-xs">make simulate</code>. It
                reads the indexed tape and no chain, and takes minutes rather
                than seconds — it replays the fee and adverse-selection
                accounting at every width on the ladder.
              </>
            }
          />
        </div>
      )}

      {d && (
        <>
          <Section
            title="Set up a position"
            intro="Nothing here is interpolated. Each combination below was replayed with the same engine that produces the published bands, and one that was never replayed refuses instead of guessing."
          >
            <PoolSimulator data={d} />
          </Section>

          <Section title="What this is, and what it is not">
            <Card>
              <ul className="m-0 flex list-none flex-col gap-3 p-0 text-sm text-dim">
                {/* First, because it is the caveat that changes what the
                    number means rather than how much to trust it. The list
                    opened on "not a forecast", which every replay on this site
                    could say; the one specific to this page — that nothing is
                    managing the position — was absent from it entirely. */}
                <li>
                  <strong className="text-ink">
                    Nothing is managing the position.
                  </strong>{" "}
                  It is minted once at the width you chose and held to the end of
                  the window. On a marketplace that sells agents, that is worth
                  saying plainly: these figures are the do-it-yourself arm, and{" "}
                  <Link href="/advantage">
                    the report measures an agent against exactly this policy
                  </Link>
                  .
                </li>
                <li>
                  <strong className="text-ink">It is a replay, not a forecast.</strong>{" "}
                  Every number is what a position of that size, at that width,
                  opened on that date, would have collected from swaps already on
                  chain. Nothing here predicts the next window.
                </li>
                <li>
                  <strong className="text-ink">
                    Adverse selection is subtracted, as an upper bound.
                  </strong>{" "}
                  Assumption A10 publishes the convexity cost as a ceiling on
                  what arbitrage took, so the net figure is a floor on what the
                  position kept. Every other venue quotes the gross number.
                </li>
                <li>
                  <strong className="text-ink">
                    The protocol&rsquo;s cut is taken from each swap, not modelled.
                  </strong>{" "}
                  PancakeSwap&rsquo;s protocol fee is on by default and differs
                  between tiers of the same pair, so it is read per swap from the
                  event&rsquo;s own fields.{" "}
                  <Link href="/venue">Why that matters, and what it costs &rarr;</Link>
                </li>
                <li>
                  <strong className="text-ink">Only badged pools appear.</strong>{" "}
                  {count(d.summary.badged)} of {count(d.summary.pools)} pools carry
                  a due-diligence badge, and{" "}
                  {count(d.summary.simulable)} have enough tape to simulate at all.{" "}
                  <Link href="/vetting">What each was checked for &rarr;</Link>
                </li>
              </ul>

              <p className="mt-4 mb-0 border-t border-line pt-3 text-xs text-faint">
                {count(d.summary.cells)} replayed windows across{" "}
                {count(d.width_ladder.length)} widths, from ±
                {count(d.width_ladder[0])} to ±
                {count(d.width_ladder[d.width_ladder.length - 1])} ticks.{" "}
                <Link href="/venue">Which width the evidence can separate &rarr;</Link>
              </p>
            </Card>
          </Section>
        </>
      )}
    </Loadable>
  );
}
