"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AgentCard } from "@/components/AgentCard";
import type { HireTerms } from "@/components/HirePrice";
import { Card, CardHeader } from "@/components/Card";
import { CategoryGlyph } from "@/components/CategoryGlyph";
import { Heading, Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import { NotBuiltCard } from "@/components/Ledger";
import { Pill } from "@/components/Pill";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { RouterCard } from "@/components/RouterCard";
import { ScanCategoryAgents } from "@/components/ScanAgents";
import type { ScanCategory, ScanFeedback } from "@/components/ScanAgents";
import {
  load,
  loadAgents,
  type AdvantageArtifact,
  type AgentArtifact,
  type IndexArtifact,
  type Loaded,
  type RouterArtifact,
} from "@/lib/artifacts";
import { categoryBySlug } from "@/lib/categories";
import { counterpartTask } from "@/lib/counterpart";

/**
 * One category: what it measures, what it is measured against, and who serves it.
 *
 * The card itself is the same component the Overview renders, deliberately —
 * duplicating an agent card here with a different layout would give a reader
 * two renderings of one artifact to reconcile. What this page adds is the
 * frame: the DIY baseline the whole category is judged against, the metric
 * sentence when the report has one, and the advantage task when the report
 * covers this agent at all.
 *
 * **It often does not.** The report has four tasks against four agents and they
 * do not correspond: Grid appears in none of them. `counterpartTask` returns
 * `undefined` and its docstring is explicit that the caller must render nothing
 * rather than an empty box — so this page says the report does not cover this
 * agent, which is a fact, instead of drawing a comparison card with dashes in
 * it, which would look like a measurement that came out empty.
 */
/**
 * Only the two blocks a category page draws.
 *
 * Declared here rather than imported from `registry/view.tsx`, which types the
 * whole artifact for a page that renders the whole artifact. This page needs
 * the categories and the per-agent feedback to join them against, and
 * `artifacts.ts`'s own header makes the rule: only what is rendered is
 * declared.
 */
export interface ScanArtifact {
  categories?: Record<string, ScanCategory>;
  feedback_graph?: { by_agent?: Record<string, ScanFeedback> };
}

export function CategoryView({
  slug,
  initialIndex,
  initialAdvantage,
  initialCards,
  initialScan,
  hire,
}: {
  slug: string;
  /** What hiring costs, read at build time. See `readHireTerms`. */
  hire?: HireTerms;
  initialIndex?: IndexArtifact;
  initialAdvantage?: AdvantageArtifact;
  /** Read from disk by `page.tsx`, so the card is in the prerendered HTML. */
  initialCards?: Record<string, AgentArtifact>;
  /**
   * 8004scan's per-category reading, baked in at build time.
   *
   * Server-side like `initialCards` and for the same reason its comment gives:
   * a reader with JavaScript off would otherwise get a heading and a paragraph
   * where the third-party agents should be. There is one artifact per page
   * here, so the trade goes this way.
   */
  initialScan?: ScanArtifact;
}) {
  const [index, setIndex] = useState<Loaded<IndexArtifact> | null>(
    initialIndex ? { ok: true, value: initialIndex } : null,
  );
  const [advantage, setAdvantage] = useState<AdvantageArtifact | undefined>(initialAdvantage);
  const scan = initialScan;
  const [cards, setCards] = useState<{ slug: string; result: Loaded<AgentArtifact> }[] | null>(
    initialCards && Object.keys(initialCards).length > 0
      ? Object.entries(initialCards).map(([slug, value]) => ({
          slug,
          result: { ok: true, value },
        }))
      : null,
  );

  useEffect(() => {
    let live = true;
    (async () => {
      const [idx, adv] = await Promise.all([
        load<IndexArtifact>("index.json"),
        load<AdvantageArtifact>("advantage.json"),
      ]);
      if (!live) return;
      setIndex(idx);
      if (adv.ok) setAdvantage(adv.value);

      if (idx.ok) {
        const category = categoryBySlug(slug, idx.value.agents);
        const loaded = await loadAgents(category?.agents ?? []);
        if (live) setCards(loaded);
      } else {
        setCards([]);
      }
    })();
    return () => {
      live = false;
    };
  }, [slug]);

  const artifact = index?.ok ? index.value : undefined;
  const category = categoryBySlug(slug, artifact?.agents);
  const loading = index === null || cards === null;

  // The not-built ledger carries its own category vocabulary, overlapping this
  // one on `Yield` alone. Matched on the display name rather than the slug,
  // because the ledger's values are prose the emitter writes and were never
  // slugs.
  const notBuilt = (artifact?.not_built ?? []).filter(
    (entry) => entry.category?.toLowerCase() === category?.name.toLowerCase(),
  );

  return (
    <Loadable loading={loading} what="the category" className="max-w-5xl">
      <p className="mb-2 font-mono text-xs tracking-widest text-brand uppercase">
        <Link href="/category" className="text-brand no-underline hover:underline">
          ← All categories
        </Link>
      </p>
      <h1 className="flex flex-wrap items-center gap-3 text-3xl leading-[1.15] font-semibold text-balance">
        {/* The glyph is `aria-hidden` and renders no text, so the accessible
            name of this heading is the category name and nothing else. */}
        <CategoryGlyph slug={slug} />
        {category?.name ?? slug}
      </h1>

      {index && !index.ok && (
        <ErrorNotice
          title="No index to read"
          detail={index.error.message}
          remedy="Run `make showcase-demo`."
        />
      )}

      {index?.ok && !category && (
        <div className="mt-6">
          <Refusal
            title="No such category"
            reason={`The agent index publishes no category with the slug "${slug}".`}
            floor="The categories that exist are listed on /category."
          />
        </div>
      )}

      {category && (
        <>
          <div className="mt-8 grid min-w-0 gap-6">
            {(cards ?? []).map((slot) => {
              const ref = category.agents.find((a) => a.slug === slot.slug);
              if (!ref) return null;

              if (!slot.result.ok) {
                return (
                  <ErrorNotice
                    key={slot.slug}
                    title={`${ref.name} could not be loaded`}
                    detail={slot.result.error.message}
                  />
                );
              }

              const data = slot.result.value;
              const kind = (data as unknown as { kind?: string }).kind;

              return (
                // `min-w-0`, because a grid item's default `min-width: auto`
                // refuses to shrink below its content the same way a flex
                // item's does — and the content here includes a pool address
                // and a baseline sentence. Without it this pushed the document
                // 27px past a 390px viewport.
                <div key={slot.slug} className="min-w-0">
                  <Basis data={data} advantage={advantage} agent={ref.name} />
                  {kind === "allocation" ? (
                    <RouterCard ref_={ref} data={data as unknown as RouterArtifact} />
                  ) : (
                    <AgentCard ref_={ref} data={data} baseline={artifact?.baseline} hire={hire} />
                  )}
                </div>
              );
            })}
          </div>

          {notBuilt.length > 0 && (
            <Section
              title="Advertised in this category, and not built"
              className="mt-12"
              headingClassName="text-lg font-semibold"
            >
              <div className="mt-3 grid gap-4">
                {notBuilt.map((entry) => (
                  <NotBuiltCard key={entry.name} entry={entry} />
                ))}
              </div>
            </Section>
          )}

          <Heading className="mt-12 mb-2 text-md font-semibold">
            Who else is in this category
          </Heading>
          {/* This paragraph used to say "Nobody", and the reason it gave was
              right: ERC-8004 declares no category anywhere in the standard, so
              placing a stranger's agent here is *our* classification of *their*
              free text. That has not changed and is not fixed by having a
              better index.

              What changed is that the classification can now be shown instead
              of asserted. Every row below carries `matched_on` — the word its
              description had to contain to land here — so a reader can see the
              judgement being made rather than being handed its output. The
              search that produced them matches stems rather than substrings,
              which is why each row is re-checked against its own needle and
              the rejects are counted on the card.

              The objection survives in one place and is stated there: none of
              these agents gets a quote, because we do not have its policy. */}
          <p className="m-0 max-w-[62ch] text-sm text-dim">
            Agents from{" "}
            <Link href="/registry">a third-party index</Link> whose own descriptions
            place them here &mdash; our reading of their free text, so every row says
            which word it matched on. None carries a quote: we do not have their
            policies.
          </p>
          <div className="mt-4">
            <ScanCategoryAgents
              category={scan?.categories?.[category.name]}
              by_agent={scan?.feedback_graph?.by_agent}
            />
          </div>
        </>
      )}
    </Loadable>
  );
}

/**
 * What the comparison on this page measures, and against what.
 *
 * The baseline comes from the agent's own artifact — it describes the tape
 * rather than the policy, which is what makes it a category-level fact. The
 * metric sentence comes from the advantage report and is frequently absent,
 * because the report covers three of the four agents.
 */
function Basis({
  data,
  advantage,
  agent,
}: {
  data: AgentArtifact;
  advantage?: AdvantageArtifact;
  agent: string;
}) {
  const baseline = data.advantage?.without_agent;
  const counterpart = counterpartTask(agent, advantage);
  const metric = counterpart?.task.metric;

  if (!baseline && !metric) return null;

  return (
    <Card className="mb-4">
      <CardHeader title="What this category is judged on" eyebrow="the comparison" />
      <dl className="m-0 grid gap-3 text-sm sm:grid-cols-2">
        {baseline && (
          <div className="min-w-0 rounded-sm border border-glass-line bg-panel-2/50 p-3">
            <dt className="m-0 text-xs text-faint uppercase">Doing it yourself</dt>
            <dd className="m-0 mt-1 text-dim [overflow-wrap:anywhere]">{baseline}</dd>
          </div>
        )}
        {metric ? (
          <div className="min-w-0 rounded-sm border border-glass-line bg-panel-2/50 p-3">
            <dt className="m-0 text-xs text-faint uppercase">Measured as</dt>
            <dd className="m-0 mt-1 text-dim [overflow-wrap:anywhere]">{metric}</dd>
          </div>
        ) : (
          <div className="min-w-0 rounded-sm border border-glass-line bg-panel-2/50 p-3">
            <dt className="m-0 text-xs text-faint uppercase">Measured as</dt>
            <dd className="m-0 mt-1 text-dim">
              <Pill tone="none">Not in the advantage report</Pill>
              <span className="mt-2 block">
                The report runs a fixed set of tasks and does not cover this
                agent, so there is no cross-run figure to quote here — only the
                card&rsquo;s own replay below.
              </span>
            </dd>
          </div>
        )}
      </dl>
    </Card>
  );
}
