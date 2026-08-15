"use client";

import { Loadable } from "@/components/LoadingStatus";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Blocks, type Block } from "@/components/Blocks";
import { Card } from "@/components/Card";
import { ErrorNotice } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { load, type Loaded } from "@/lib/artifacts";

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

export default function AssumptionsPage() {
  const [state, setState] = useState<Loaded<AssumptionsArtifact> | null>(null);

  useEffect(() => {
    let live = true;
    load<AssumptionsArtifact>("assumptions.json").then((r) => {
      if (live) setState(r);
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

          <section className="mt-10">
            <h2 className="mb-5 text-lg font-semibold">
              Assumptions ({assumptions.length})
            </h2>
            <div className="grid gap-5">
              {assumptions.map((entry) => (
                <EntryCard key={entry.id} entry={entry} />
              ))}
            </div>
          </section>

          {Object.entries(d.sections).map(([key, blocks]) =>
            blocks.length === 0 ? null : (
              <section key={key} className="mt-10">
                <h2 className="mb-5 text-lg font-semibold capitalize">
                  {key.replace(/_/g, " ")}
                </h2>
                <Card>
                  <Blocks blocks={blocks} />
                </Card>
              </section>
            ),
          )}

          <section className="mt-10">
            <h2 className="mb-2 text-lg font-semibold">
              Deviations, defects and corrections ({others.length})
            </h2>
            <p className="mb-5 max-w-[68ch] text-sm text-dim">
              Cards cite these alongside the assumptions — the 34% protocol fee is{" "}
              <code className="font-mono text-xs">P-1</code>, and it lives in the
              requirements matrix rather than the assumption sheet. Both are published
              here so that no citation on any card resolves to nothing.
            </p>
            <div className="grid gap-5">
              {others.map((entry) => (
                <EntryCard key={entry.id} entry={entry} />
              ))}
            </div>
          </section>

          <p className="mt-10 text-sm text-faint">
            Generated from {d.sources.join(" and ")}.
          </p>
        </>
      )}
    </Loadable>
  );
}

function EntryCard({ entry }: { entry: Entry }) {
  return (
    <article
      id={entry.id}
      tabIndex={-1}
      // Anchored deep links land under a sticky header without this.
      className="scroll-mt-20 rounded-lg border border-line bg-panel p-6 target:border-accent"
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex flex-wrap items-baseline gap-3">
          <span className="rounded-sm border border-line bg-panel-2 px-2 py-0.5 font-mono text-xs text-warn">
            {entry.id}
          </span>
          <h3 className="m-0 text-md font-semibold">{entry.title}</h3>
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
                {name.endsWith(".json") && !name.startsWith("advantage") ? (
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
