"use client";

import { BuildStamp } from "@/components/BuildStamp";
import { count } from "@/lib/format";
import { Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import Link from "next/link";
import { useEffect, useState } from "react";
import { AgentCard } from "@/components/AgentCard";
import { AgentComparison } from "@/components/AgentComparison";
import { NotBuiltCard } from "@/components/Ledger";
import { ErrorNotice } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { SourceBanner } from "@/components/SourceBanner";
import {
  load,
  loadAgents,
  type AgentArtifact,
  type BuildArtifact,
  type IndexArtifact,
  type Loaded,
} from "@/lib/artifacts";

type AgentSlot = {
  slug: string;
  name: string;
  result: Loaded<AgentArtifact>;
};

export default function OverviewPage() {
  const [index, setIndex] = useState<Loaded<IndexArtifact> | null>(null);
  const [build, setBuild] = useState<Loaded<BuildArtifact> | null>(null);
  const [agents, setAgents] = useState<AgentSlot[] | null>(null);

  useEffect(() => {
    let live = true;

    (async () => {
      const [idx, bld] = await Promise.all([
        load<IndexArtifact>("index.json"),
        load<BuildArtifact>("build.json"),
      ]);
      if (!live) return;
      setIndex(idx);
      setBuild(bld);

      if (idx.ok) {
        const loaded = await loadAgents(idx.value.agents);
        if (live) setAgents(loaded);
      } else {
        setAgents([]);
      }
    })();

    return () => {
      live = false;
    };
  }, []);

  // Both rounds, not just the first.
  //
  // The agent cards are fetched only after index.json resolves, so gating on
  // `index === null` alone unmounted the skeletons one full round trip before
  // there was anything to put in their place: hero, source banner, and then a
  // bare gap where three cards would later appear, with a large layout shift
  // when they did. It was the worst loading moment on the site and it was on
  // the landing page.
  const loading = index === null || agents === null;

  // Only the agents that both loaded and are listed. A card that 404'd is
  // absent from the comparison rather than drawn as a zero, which would read
  // as an agent that lost nothing.
  const compared =
    agents && index?.ok
      ? agents.flatMap((slot) => {
          const ref = index.value.agents.find((a) => a.slug === slot.slug);
          return ref && slot.result.ok ? [{ ref, data: slot.result.value }] : [];
        })
      : [];

  // Read from the artifact, never typed — it is the threshold the in-range
  // verdict is called against, and `/methods` publishes it as one of the floors.
  const inRangeFloor = compared[0]?.data.floors?.in_range_floor;

  return (
    <Loadable loading={loading} what="agent cards">
      <h1 className="text-2xl font-semibold">Every marketplace misquotes you.</h1>
      {/* 48 words carrying four claims, three of which the page demonstrates
          below: the ranges are drawn, the withheld quotes say so themselves,
          and every figure links to its assumption. What only prose can say is
          what the alternative does — so that is what is left. */}
      <p className="mt-3 max-w-[64ch] text-dim">
        Others rank agents by star ratings. Every number here traces to chain state or a{" "}
        <Link href="/assumptions">published assumption</Link>, and where the evidence is
        thin it <strong className="text-ink">says nothing instead</strong>.
      </p>

      <p className="mt-4">
        <Link
          href="/advantage"
          className="inline-block rounded-md border border-line bg-panel px-4 py-2 text-sm font-medium text-ink no-underline hover:border-accent hover:text-accent"
        >
          Does hiring an agent beat doing it yourself? →
        </Link>
      </p>

      <div className="mt-10">
        {index?.ok && (
          <SourceBanner
            source={index.value.source}
            badge={index.value.badge}
            pool={index.value.pool}
          />
        )}

        {index && !index.ok && (
          <ErrorNotice
            title="No artifacts to render"
            detail={index.error.message}
            remedy={
              index.error.kind === "http" ? (
                <>
                  Nothing has generated the cards yet. Run{" "}
                  <code className="font-mono text-xs">make showcase-demo</code> for a
                  labelled synthetic tape, or{" "}
                  <code className="font-mono text-xs">make showcase</code> against an
                  indexed one.
                </>
              ) : undefined
            }
          />
        )}

        {loading && (
          <div className="grid gap-5">
            <CardSkeleton />
            <CardSkeleton />
          </div>
        )}

        {/* The answer before the detail.
            This page was a heading, a paragraph, a link and three stacked
            cards, so "which of these works" took three screens and a memory for
            numbers. The cards are still the detail; this is the answer. */}
        {compared.length > 0 && (
          <div className="mb-8">
            <AgentComparison agents={compared} inRangeFloor={inRangeFloor} />
          </div>
        )}

        {agents && agents.length > 0 && index?.ok && (
          <div className="grid gap-5">
            {agents.map((slot) => {
              const ref_ = index.value.agents.find((a) => a.slug === slot.slug);
              if (!ref_) return null;

              // Per-card failure. One missing artifact costs one card — the
              // page this replaces used Promise.all, so a single 404 erased
              // every card and blamed it on the pipeline never having run.
              return slot.result.ok ? (
                <AgentCard
                  key={slot.slug}
                  ref_={ref_}
                  data={slot.result.value}
                  baseline={index.value.baseline}
                />
              ) : (
                <ErrorNotice
                  key={slot.slug}
                  title={`${slot.name} card could not be loaded`}
                  detail={slot.result.error.message}
                  remedy="The other cards on this page are unaffected."
                />
              );
            })}
          </div>
        )}

        {index?.ok && index.value.not_built.length > 0 && (
          <Section title="Advertised, and not built" className="mt-12" headingClassName="text-lg font-semibold">
            {/* Sentences 2-3 restated the heading directly above and the
                "Not built" badge on every card below. And "four" was typed
                against a `not_built` list of five — a hardcoded count of the
                artifact it introduces. The count is read now, or omitted. */}
            <p className="mt-2 mb-5 max-w-[64ch] text-sm text-dim">
              {count(index.value.not_built.length)} capabilities the README advertises and
              this repository does not contain.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              {index.value.not_built.map((entry) => (
                <NotBuiltCard key={entry.name} entry={entry} />
              ))}
            </div>
          </Section>
        )}
      </div>

      <footer className="mt-16 border-t border-line pt-6 text-sm text-faint">
        {/* The unique claim here is the static export, which appears nowhere
            else on the site. The path is already in the build stamp below. */}
        <p className="m-0">
          A static export reading precomputed JSON — no backend to be down.
        </p>
        {build?.ok && (
          <BuildStamp
            className="mt-2"
            build={build.value}
            extra={`${build.value.events.toLocaleString("en-US")} events over ${build.value.span_hours}h`}
          />
        )}
      </footer>
    </Loadable>
  );
}
