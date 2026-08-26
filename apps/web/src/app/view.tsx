"use client";

import { BuildStamp } from "@/components/BuildStamp";
import { EvidenceRail, type EvidenceEntry } from "@/components/EvidenceRail";
import { TickRule } from "@/components/TickRule";
import { Button } from "@/components/Button";
import { count } from "@/lib/format";
import { Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import Link from "next/link";
import { useEffect, useState } from "react";
import { AgentCard } from "@/components/AgentCard";
import { RouterCard } from "@/components/RouterCard";
import { AgentComparison } from "@/components/AgentComparison";
import { Integrations } from "@/components/Integrations";
import { NotBuiltCard } from "@/components/Ledger";
import { ErrorNotice } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { SourceBanner } from "@/components/SourceBanner";
import { StaleNotice, type BehindEntry } from "@/components/StaleNotice";
import {
  load,
  loadAgents,
  type AgentArtifact,
  type BuildArtifact,
  type IndexArtifact,
  type Loaded,
  type RouterArtifact,
} from "@/lib/artifacts";

type AgentSlot = {
  slug: string;
  name: string;
  result: Loaded<AgentArtifact>;
};

/** Only the fields the router reads. The two pages themselves own the rest. */
interface VenueSummary {
  venue: { name: string };
  divergences: unknown[];
}

interface StatusSummary {
  checks: { name: string; status: string; detail: string }[];
}

/** The gate the TermiX track turns on, by the name `go_no_go.py` gives it. */
const DELIVERABLE_GATE = "agent advantage report";

export function OverviewView({
  initialIndex,
  initialBuild,
  evidence,
  behind = [],
}: {
  /** Artifacts generated before the engine changed. See `lib/stale`. */
  behind?: BehindEntry[];
  /**
   * Read from disk at build time by `app/page.tsx`, so the landing page is not
   * a heading and a spinner in the exported HTML.
   *
   * Only these two. They are what the page needs to render the source banner,
   * the ledger of what is not built, and the build stamp — the parts that are
   * prose and structure rather than a replayed figure. The agent cards stay
   * client-only on purpose: `loadAgents` fans out over the index at runtime and
   * baking three more artifacts into every build to save one round trip is a
   * worse trade than the round trip.
   *
   * Undefined when the file could not be read. That is not an error here — the
   * client's own load runs regardless and owns the failure path, which is where
   * the remedy text and the tests already are.
   */
  initialIndex?: IndexArtifact;
  initialBuild?: BuildArtifact;
  /**
   * One figure per evidence route, counted from its own artifact at build time
   * by `app/page.tsx`. Numbers rather than artifacts, because everything this
   * component receives is serialised into the flight payload and
   * `assumptions.json` is 130KB of it.
   */
  evidence: Record<string, EvidenceEntry | null>;
}) {
  const [index, setIndex] = useState<Loaded<IndexArtifact> | null>(
    initialIndex ? { ok: true, value: initialIndex } : null
  );
  const [build, setBuild] = useState<Loaded<BuildArtifact> | null>(
    initialBuild ? { ok: true, value: initialBuild } : null
  );
  const [agents, setAgents] = useState<AgentSlot[] | null>(null);
  const [venue, setVenue] = useState<Loaded<VenueSummary> | null>(null);
  const [status, setStatus] = useState<Loaded<StatusSummary> | null>(null);

  useEffect(() => {
    let live = true;

    (async () => {
      // The two router artifacts are fetched alongside, not after: neither
      // gates the skeletons below, so a slow one must not hold up the cards.
      const [idx, bld, ven, sts] = await Promise.all([
        load<IndexArtifact>("index.json"),
        load<BuildArtifact>("build.json"),
        load<VenueSummary>("venue.json"),
        load<StatusSummary>("status.json"),
      ]);
      if (!live) return;
      setIndex(idx);
      setBuild(bld);
      setVenue(ven);
      setStatus(sts);

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
          if (!ref || !slot.result.ok) return [];
          // Allocation agents are excluded, with the reason rendered below the
          // table rather than left to inference. Their return is not
          // commensurable with an LP's: there is no in-range fraction and no
          // LVR, and a zero in either column would read as "never out of range,
          // lost nothing to adverse selection" — the same argument that keeps a
          // 404'd card out of this table instead of drawing it as a zero.
          if (
            (slot.result.value as unknown as { kind?: string }).kind ===
            "allocation"
          )
            return [];
          return [{ ref, data: slot.result.value }];
        })
      : [];

  // Read from the artifact, never typed — it is the threshold the in-range
  // verdict is called against, and `/methods` publishes it as one of the floors.
  const inRangeFloor = compared[0]?.data.floors?.in_range_floor;

  // Agents kept off the comparison because their returns are not commensurable
  // with an LP's. Named on the page rather than silently absent: a reader who
  // counts four cards and three rows deserves to be told which one is missing
  // and why, and "it is not on the table" is a claim that has to be defended.
  const notCompared =
    agents && index?.ok
      ? agents.flatMap((slot) => {
          const ref = index.value.agents.find((a) => a.slug === slot.slug);
          if (!ref || !slot.result.ok) return [];
          return (slot.result.value as unknown as { kind?: string }).kind ===
            "allocation"
            ? [ref.name]
            : [];
        })
      : [];

  const venueSummary = venue?.ok ? venue.value : null;
  // Found by name rather than by index. `go_no_go.py` orders its checks and
  // that order is not a contract; a positional read would silently start
  // reporting a different gate's verdict the day one is inserted above it.
  const deliverableGate = status?.ok
    ? status.value.checks.find((c) => c.name === DELIVERABLE_GATE)
    : undefined;

  return (
    <Loadable loading={loading} what="agent cards">
      {/* The hero.
          This was an h1, a paragraph and a bordered grey box with a blue link
          in it — visually indistinguishable from the cards below, on the one
          screen that has to say what the product is before anything is read.
          Then it was a flat `bg-brand-bg/40` slab with a hard border, which
          fixed the hierarchy and, once `.tape` existed behind it, became a lid
          on the field.

          It has no fill now. The wash fades to nothing, so the tape reads
          through the headline and the region is defined by the light behind it
          rather than by a box drawn around it. `--glass-2` and not `--glass`
          because nothing on this strip is body copy — that distinction is in
          the token and it is the reason there are two.

          The border is gone too, replaced by the band: `--line` to P25, brand
          across the interquartile range, `--line` to P75, with the median tick
          at the centre. The product's own figure doing a divider's job, at page
          width, immediately under the sentence that promises ranges. */}
      <div className="-mx-5 mb-10 bg-gradient-to-b from-glass-2 to-transparent px-5 pt-4 pb-10">
        <p className="rise-1 mb-3 font-mono text-xs tracking-widest text-brand uppercase">
          Agent marketplace · BNB Chain
        </p>
        {/* `--text-4xl` existed in the scale and was used by nothing. The
            scale's own note says 3xl and 4xl were added because "a hero and a
            section heading had to be the same thing" — and the hero was still
            at 3xl, which is the size every other page's h1 uses. */}
        <h1 className="rise-2 max-w-[16ch] text-4xl leading-[1.05] font-semibold tracking-[-0.022em] text-balance">
          Every marketplace misquotes you.
        </h1>
        {/* 48 words carrying four claims, three of which the page demonstrates
            below: the ranges are drawn, the withheld quotes say so themselves,
            and every figure links to its assumption. What only prose can say is
            what the alternative does — so that is what is left. */}
        <p className="rise-3 mt-4 max-w-[60ch] text-md text-dim">
          Others rank agents by star ratings. Every number here traces to chain
          state or a <Link href="/assumptions">published assumption</Link>, and
          where the evidence is thin it{" "}
          <strong className="text-ink">says nothing instead</strong>.
        </p>

        <div className="rise-4 mt-6 flex flex-wrap gap-3">
          <Button href="/advantage">
            Does hiring an agent beat doing it yourself?
          </Button>
          <Button href="/methods" tone="secondary">
            How a quote is made
          </Button>
        </div>

        <TickRule className="mt-10" />
      </div>

      <div className="mt-10">
        {index?.ok && (
          <SourceBanner
            source={index.value.source}
            badge={index.value.badge}
            pool={index.value.pool}
          />
        )}

        {/* Every card below is drawn from one of these four. `index.json` and
            `build.json` carry no commit of their own and are stamped by proxy,
            which `go_no_go.py` reports separately as unstamped rather than as
            stale — so naming them here is what makes the notice cover the
            agent cards the landing page actually renders. */}
        <StaleNotice
          behind={behind}
          artifacts={[
            "index.json",
            "build.json",
            "warden.json",
            "grid.json",
            "sentinel.json",
            "router.json",
          ]}
          className="mb-8"
        />

        {index && !index.ok && (
          <ErrorNotice
            title="No artifacts to render"
            detail={index.error.message}
            remedy={
              index.error.kind === "http" ? (
                <>
                  Nothing has generated the cards yet. Run{" "}
                  <code className="font-mono text-xs">make showcase-demo</code>{" "}
                  for a labelled synthetic tape, or{" "}
                  <code className="font-mono text-xs">make showcase</code>{" "}
                  against an indexed one.
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

        {/* Which of the two integrations is yours, before any scrolling.
            The venue is the substrate every number below sits on; the track is
            a requirement with one judged deliverable. Both read from artifacts
            — the gate's verdict is `status.json`'s own string, so this cannot
            advertise green while the checklist says amber. */}
        {(venueSummary || deliverableGate) && (
          <div className="mb-8">
            <Integrations
              venue={venueSummary?.venue.name}
              divergences={venueSummary?.divergences.length}
              gate={deliverableGate}
            />
          </div>
        )}

        {/* The answer before the detail.
            This page was a heading, a paragraph, a link and three stacked
            cards, so "which of these works" took three screens and a memory for
            numbers. The cards are still the detail; this is the answer. */}
        {compared.length > 0 && (
          <div className="mb-8">
            <AgentComparison agents={compared} inRangeFloor={inRangeFloor} />
            {/* Why the fourth agent is off the table, stated accurately.

                  This read "it supplies to a lending market rather than
                  providing liquidity, so there is no in-range fraction and no
                  adverse-selection cost to compare". The first clause is no
                  longer the whole truth and the second is simply wrong: Router
                  evaluates PancakeSwap ranges as venues and derives a convexity
                  cost for every one of them — that subtraction is the reason its
                  pool figures are net rather than gross.

                  The real reason it cannot join this table is narrower and does
                  not change: it holds no range of its own, so there is nothing
                  to be in or out of, and the columns here measure a position
                  this agent does not take. */}
            {notCompared.length > 0 && (
              <p className="mt-3 mb-0 text-xs text-faint">
                {notCompared.join(", ")}{" "}
                {notCompared.length === 1 ? "is" : "are"} not on this table.{" "}
                {notCompared.length === 1 ? "It holds" : "They hold"} no range
                of its own — it chooses which venue to put capital in, so there
                is no in-range fraction to report and a zero in that column
                would read as a claim rather than an absence. It does price
                adverse selection: every PancakeSwap range it considers is
                quoted net of the convexity cost measured over the same window.
              </p>
            )}
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
              if (!slot.result.ok) {
                return (
                  <ErrorNotice
                    key={slot.slug}
                    title={`${slot.name} card could not be loaded`}
                    detail={slot.result.error.message}
                    remedy="The other cards on this page are unaffected."
                  />
                );
              }

              // Allocation agents get their own card. Dispatching on the
              // artifact's own `kind` rather than on the slug keeps the list of
              // which agents are which in one place — the emitter — instead of
              // two that have to agree.
              if (
                (slot.result.value as unknown as { kind?: string }).kind ===
                "allocation"
              ) {
                return (
                  <RouterCard
                    key={slot.slug}
                    ref_={ref_}
                    data={slot.result.value as unknown as RouterArtifact}
                  />
                );
              }

              return (
                <AgentCard
                  key={slot.slug}
                  ref_={ref_}
                  data={slot.result.value}
                  baseline={index.value.baseline}
                />
              );
            })}
          </div>
        )}

        {index?.ok && index.value.not_built.length > 0 && (
          <Section
            title="Advertised, and not built"
            className="mt-12"
            headingClassName="text-lg font-semibold"
          >
            {/* Sentences 2-3 restated the heading directly above and the
                "Not built" badge on every card below. And "four" was typed
                against a `not_built` list of five — a hardcoded count of the
                artifact it introduces. The count is read now, or omitted. */}
            <p className="mt-2 mb-5 max-w-[64ch] text-sm text-dim">
              {count(index.value.not_built.length)} capabilities the README
              advertises and this repository does not contain.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              {index.value.not_built.map((entry) => (
                <NotBuiltCard key={entry.name} entry={entry} />
              ))}
            </div>
          </Section>
        )}

        {/* The map of the argument.
            This page used to end at the ledger, so the half of the site that
            exists to be checked — seven pages of tick math, venue divergences,
            pool badges, assumptions and gates — was reachable only through a
            nav band a first-time reader has no reason to look at. A page whose
            headline is that other marketplaces cannot be checked should say
            what there is to check here, and say it in figures.

            Every number is read from its own artifact at build time, so this
            renders in the exported HTML with JavaScript off, along with the
            rest of the page. */}
        <Section
          title="What there is to check"
          className="mt-12"
          headingClassName="mb-4 text-lg font-semibold"
          intro="Seven pages, each generated from an artifact this repository can regenerate. The figures below are counted from those files, not typed."
        >
          <EvidenceRail entries={evidence} />
        </Section>
      </div>

      <footer className="mt-16 border-t border-glass-line pt-6 text-sm text-faint">
        {/* The unique claim here is the static export, which appears nowhere
            else on the site. The path is already in the build stamp below. */}
        <p className="m-0">
          A static export reading precomputed JSON — no backend to be down.
        </p>
        {build?.ok && (
          <BuildStamp
            className="mt-2"
            build={build.value}
            extra={`${build.value.events.toLocaleString("en-US")} events over ${
              build.value.span_hours
            }h`}
          />
        )}
      </footer>
    </Loadable>
  );
}
