"use client";

import { Loadable } from "@/components/LoadingStatus";
import Link from "next/link";
import { useEffect, useState } from "react";
import { AgentCard } from "@/components/AgentCard";
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
import { timestamp } from "@/lib/format";

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

  return (
    <Loadable loading={loading} what="agent cards">
      <h1 className="text-2xl font-semibold">Every marketplace misquotes you.</h1>
      <p className="mt-3 max-w-[64ch] text-dim">
        Agent marketplaces run on star ratings, user counts and unverifiable claims. Every
        number here traces to chain state or to a{" "}
        <Link href="/assumptions">published assumption</Link>, every quote is a P25–P75
        range rather than a point estimate, and where the evidence is too thin to say
        something, <strong className="text-ink">it says nothing instead</strong>.
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

        {agents && agents.length > 0 && index?.ok && (
          <div className="grid gap-5">
            {agents.map((slot) => {
              const ref_ = index.value.agents.find((a) => a.slug === slot.slug);
              if (!ref_) return null;

              // Per-card failure. One missing artifact costs one card — the
              // page this replaces used Promise.all, so a single 404 erased
              // every card and blamed it on the pipeline never having run.
              return slot.result.ok ? (
                <AgentCard key={slot.slug} ref_={ref_} data={slot.result.value} />
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
          <section className="mt-12">
            <h2 className="text-lg font-semibold">Advertised, and not built</h2>
            <p className="mt-2 mb-5 max-w-[64ch] text-sm text-dim">
              The README describes four agent categories and an activation path. These are
              the parts that do not exist. They are listed here rather than omitted,
              because a marketplace that quietly shows only what it finished is doing the
              thing this one is named after.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              {index.value.not_built.map((entry) => (
                <NotBuiltCard key={entry.name} entry={entry} />
              ))}
            </div>
          </section>
        )}
      </div>

      <footer className="mt-16 border-t border-line pt-6 text-sm text-faint">
        <p className="m-0">
          Cards render precomputed JSON from{" "}
          <code className="font-mono text-xs">public/artifacts/</code>. This site is a
          static export and calls no backend, so it renders identically when every server
          behind it is down.
        </p>
        {build?.ok && (
          <p className="mt-2 mb-0 font-mono text-xs">
            {build.value.command} · {timestamp(build.value.generated_at)} ·{" "}
            {build.value.git_sha ?? "no commit"}
            {build.value.git_dirty ? " (dirty tree)" : ""} ·{" "}
            {build.value.events.toLocaleString("en-US")} events over{" "}
            {build.value.span_hours}h
          </p>
        )}
      </footer>
    </Loadable>
  );
}
