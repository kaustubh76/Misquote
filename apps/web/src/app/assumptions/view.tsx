"use client";

import { Heading, Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Blocks, type Block } from "@/components/Blocks";
import { Card } from "@/components/Card";
import { ErrorNotice } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { load, type IndexArtifact, type Loaded } from "@/lib/artifacts";

interface Entry {
  id: string;
  title: string;
  kind: string;
  source: string;
  line: number;
  blocks: Block[];
  cited_by: string[];
}

interface AssumptionsArtifact {
  entries: Entry[];
  sections: Record<string, Block[]>;
  sources: string[];
  unresolved_citations: string[];
}

const KIND_LABEL: Record<string, string> = {
  assumption: "Assumption",
  deviation: "Accepted deviation",
  defect: "Defect found and fixed",
  correction: "Correction",
  erratum: "Erratum",
  gap: "Gap",
  note: "Note",
};

export function AssumptionsView() {
  const [state, setState] = useState<Loaded<AssumptionsArtifact> | null>(null);
  const [index, setIndex] = useState<Loaded<IndexArtifact> | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([
      load<AssumptionsArtifact>("assumptions.json"),
      load<IndexArtifact>("index.json"),
    ]).then(([sheet, idx]) => {
      if (!live) return;
      setState(sheet);
      setIndex(idx);
    });
    return () => {
      live = false;
    };
  }, []);

  // Deep links arrive as /assumptions#A6. The content is fetched after mount,
  // so the browser's own anchor scroll has already run against a page that did
  // not yet contain the target.
  useEffect(() => {
    if (!state?.ok) return;
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (!id) return;
    const target = document.getElementById(id);
    if (target) {
      target.scrollIntoView({ block: "start" });
      target.focus({ preventScroll: true });
    }
  }, [state]);

  const d = state?.ok ? state.value : null;
  const agentSlugs = new Set(index?.ok ? index.value.agents.map((a) => a.slug) : []);
  const assumptions = d?.entries.filter((e) => e.kind === "assumption") ?? [];
  const others = d?.entries.filter((e) => e.kind !== "assumption") ?? [];

  return (
    <Loadable loading={state === null} what="the assumption sheet">
      <h1 className="text-2xl font-semibold">The assumption sheet</h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        Read this the way you would read the footnotes of a fund factsheet — except these
        footnotes are the point. Every number this site displays must trace to a chain
        query or to an entry below. If it cannot, it does not render.
      </p>

      {state === null && (
        <div className="mt-10">
          <CardSkeleton />
        </div>
      )}

      {state && !state.ok && (
        <div className="mt-10">
          <ErrorNotice
            title="The assumption sheet has not been generated"
            detail={state.error.message}
            remedy={
              <>
                Run <code className="font-mono text-xs">make assumptions</code>. The source
                documents are <code className="font-mono text-xs">docs/ASSUMPTIONS.md</code>{" "}
                and <code className="font-mono text-xs">docs/REQUIREMENTS_MATRIX.md</code>.
              </>
            }
          />
        </div>
      )}

      {d && (
        <>
          {d.unresolved_citations.length > 0 && (
            <div className="mt-8 rounded-md border border-bad-line bg-bad-bg/40 p-4">
              <p className="m-0 text-sm text-bad">
                <strong>Dead citations:</strong> {d.unresolved_citations.join(", ")} are
                referenced by a published artifact but appear in neither source document.
              </p>
            </div>
          )}

          {/* Index, so a reader can find the entry a card sent them to. */}
          <nav aria-label="Assumptions index" className="mt-8">
            <ul className="flex list-none flex-wrap gap-1.5 p-0">
              {d.entries.map((e) => (
                <li key={e.id}>
                  <a
                    href={`#${e.id}`}
                    className="block rounded-sm border border-line bg-panel px-2 py-1 font-mono text-xs text-dim no-underline hover:border-accent hover:text-accent"
                  >
                    {e.id}
                  </a>
                </li>
              ))}
            </ul>
          </nav>

          <Section title={<>Assumptions ({assumptions.length})</>} className="mt-10" headingClassName="mb-5 text-lg font-semibold">
            <div className="grid gap-5">
              {assumptions.map((entry) => (
                <EntryCard key={entry.id} entry={entry} agentSlugs={agentSlugs} />
              ))}
            </div>
          </Section>

          {Object.entries(d.sections).map(([key, blocks]) =>
            blocks.length === 0 ? null : (
              <Section
                key={key}
                className="mt-10"
                headingClassName="mb-5 text-lg font-semibold capitalize"
                title={key.replace(/_/g, " ")}
              >
                <Card>
                  <Blocks blocks={blocks} />
                </Card>
              </Section>
            ),
          )}

          <Section title={<>Deviations, defects and corrections ({others.length})</>} className="mt-10" headingClassName="mb-2 text-lg font-semibold">
            <p className="mb-5 max-w-[68ch] text-sm text-dim">
              Cards cite these alongside the assumptions — the 34% protocol fee is{" "}
              <code className="font-mono text-xs">P-1</code>, and it lives in the
              requirements matrix rather than the assumption sheet. Both are published
              here so that no citation on any card resolves to nothing.
            </p>
            <div className="grid gap-5">
              {others.map((entry) => (
                <EntryCard key={entry.id} entry={entry} agentSlugs={agentSlugs} />
              ))}
            </div>
          </Section>

          <p className="mt-10 text-sm text-faint">
            Generated from {d.sources.join(" and ")}.
          </p>
        </>
      )}
    </Loadable>
  );
}

function EntryCard({ entry, agentSlugs }: { entry: Entry; agentSlugs: Set<string> }) {
  return (
    <article
      id={entry.id}
      tabIndex={-1}
      // Anchored deep links land under a sticky header without this.
      // `min-w-0`: a grid item defaults to `min-width: auto`, so it refuses to
      // shrink below its own min-content width. One long token inside — a code
      // span, a table cell — then pushes the whole card wider than its column
      // and the document scrolls sideways at 390px.
      className="min-w-0 scroll-mt-20 rounded-lg border border-line bg-panel p-6 target:border-accent"
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex flex-wrap items-baseline gap-3">
          <span className="rounded-sm border border-line bg-panel-2 px-2 py-0.5 font-mono text-xs text-warn">
            {entry.id}
          </span>
          <Heading className="m-0 min-w-0 text-md font-semibold break-words">{entry.title}</Heading>
        </div>
        <span className="font-mono text-xs text-faint">
          {KIND_LABEL[entry.kind] ?? entry.kind}
        </span>
      </div>

      <Blocks blocks={entry.blocks} />

      <p className="mt-4 mb-0 border-t border-line pt-3 font-mono text-xs text-faint">
        {entry.source}:{entry.line}
        {entry.cited_by.length > 0 && (
          <>
            {" · cited by "}
            {entry.cited_by.map((name, i) => (
              <span key={name}>
                {i > 0 && ", "}
                {/* Only the agent artifacts have a route. This used to linkify
                    any *.json that was not the advantage report, so the moment
                    vetting.json started citing assumptions it produced a link
                    to /agent/vetting — a page that does not exist. The agent
                    slugs are the ones with pages, and index.json is the
                    authority on what they are. */}
                {agentSlugs.has(name.replace(".json", "")) ? (
                  <Link href={`/agent/${name.replace(".json", "")}`}>{name}</Link>
                ) : (
                  name
                )}
              </span>
            ))}
          </>
        )}
      </p>
    </article>
  );
}
