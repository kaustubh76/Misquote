"use client";

import { Heading, Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Blocks, type Block } from "@/components/Blocks";
import { Card } from "@/components/Card";
import { ChipGroup } from "@/components/ChipGroup";
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

export interface AssumptionsArtifact {
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

/** Short enough for a filter chip, where the full `KIND_LABEL` does not fit. */
const KIND_SHORT: Record<string, string> = {
  assumption: "Assumptions",
  deviation: "Deviations",
  defect: "Defects",
  correction: "Corrections",
  erratum: "Errata",
  gap: "Gaps",
  note: "Notes",
};

/**
 * The order kinds appear in, in the index and the filter.
 *
 * Not the artifact's order, which is by id — A, D, G, P, V — and not
 * alphabetical either. Assumptions first because they are what the sheet is
 * named for and what the cards cite most; then the things found and fixed;
 * then what is still open. A reader scanning the index is asking "what did
 * they assume" long before "what is still a gap".
 *
 * Kinds absent from this list still render: `kindsIn` appends anything it
 * finds, so a new series in the matrix appears at the end rather than
 * vanishing from a page whose whole claim is that nothing is omitted.
 */
const KIND_ORDER = ["assumption", "correction", "defect", "deviation", "gap"] as const;

function kindsIn(entries: Entry[]): string[] {
  const present = new Set(entries.map((e) => e.kind));
  const known = KIND_ORDER.filter((k) => present.has(k));
  const rest = [...present].filter((k) => !KIND_ORDER.includes(k as never)).sort();
  return [...known, ...rest];
}

/** Matches on id and title only — the body is 48,000 characters of prose. */
function matches(entry: Entry, query: string): boolean {
  if (!query) return true;
  const needle = query.trim().toLowerCase();
  return (
    entry.id.toLowerCase().includes(needle) || entry.title.toLowerCase().includes(needle)
  );
}

export function AssumptionsView({
  initialSheet,
  initialIndex,
}: {
  /** Read from disk at build time by `page.tsx`. See `lib/build-artifact`. */
  initialSheet?: AssumptionsArtifact;
  initialIndex?: IndexArtifact;
}) {
  const [state, setState] = useState<Loaded<AssumptionsArtifact> | null>(
    initialSheet ? { ok: true, value: initialSheet } : null,
  );
  const [index, setIndex] = useState<Loaded<IndexArtifact> | null>(
    initialIndex ? { ok: true, value: initialIndex } : null,
  );
  const [kind, setKind] = useState("all");
  const [query, setQuery] = useState("");
  const [landed, setLanded] = useState<string | null>(null);

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

    function reveal() {
      const id = decodeURIComponent(window.location.hash.slice(1));
      if (!id) return;

      // Clear the filter before looking for the target. A filter that can hide
      // the entry a citation points at turns "one click from every quote" into
      // a blank page, with nothing to tell the reader a filter is why.
      // Arriving by anchor is a request for one specific entry, so it outranks
      // whatever was being browsed.
      setKind("all");
      setQuery("");

      const target = document.getElementById(id);
      if (!target) return;

      // Mark before scrolling, not after. `scrollIntoView` is the one call here
      // an environment can be missing — jsdom has no layout and does not
      // implement it — and an exception thrown mid-effect takes everything
      // after it down. Ordered the other way, the marking silently depended on
      // the scroll succeeding, which is the weaker of the two: a reader who
      // cannot tell which entry they landed on is worse off than one who has
      // to scroll to it.
      //
      // The marking is itself the non-colour signal. `:target` alone is a
      // border tint, and the programmatic focus below does not reliably
      // satisfy `:focus-visible` for a reader who arrived by clicking — so a
      // mouse user got colour and nothing else, on the page every citation
      // points at. `Pill.tsx` states the rule that breaks: colour is the third
      // signal, never the only one.
      setLanded(id);
      target.focus({ preventScroll: true });
      target.scrollIntoView?.({ block: "start" });
    }

    reveal();

    // Also on `hashchange`, not only on load. Entry bodies are rendered through
    // `Blocks`, which linkifies citations — so the sheet cites itself, and
    // following `V-2` → `P-8` from inside an entry is a same-page hash change
    // that never remounts this component. Bound to load alone, the filter
    // stayed applied and the destination could be one of the entries it was
    // hiding. A mutation test caught this: removing the filter reset changed
    // nothing, because the only test exercising it remounted first.
    window.addEventListener("hashchange", reveal);
    return () => window.removeEventListener("hashchange", reveal);
  }, [state]);

  const d = state?.ok ? state.value : null;
  const agentSlugs = new Set(index?.ok ? index.value.agents.map((a) => a.slug) : []);

  const all = d?.entries ?? [];
  const shown = all.filter((e) => (kind === "all" || e.kind === kind) && matches(e, query));
  const filtering = kind !== "all" || query.trim() !== "";

  const kinds = kindsIn(all);
  const counts = new Map(kinds.map((k) => [k, all.filter((e) => e.kind === k).length]));
  const chips = [
    { value: "all", label: "All", meta: String(all.length) },
    ...kinds.map((k) => ({
      value: k,
      label: KIND_SHORT[k] ?? k,
      meta: String(counts.get(k) ?? 0),
    })),
  ];

  const assumptions = shown.filter((e) => e.kind === "assumption");
  const others = shown.filter((e) => e.kind !== "assumption");

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

          {/* The index, and the filter that makes 48 entries findable.
              This page renders about 19,000px — four times any other on the
              site — and it is where every citation lands. The index was 48
              chips reading "A1 A2 A3 …" in one undifferentiated run: no
              titles, so nothing to recognise; no grouping, though the page
              below splits by kind; and nothing to narrow it with. */}
          <div className="mt-8 rounded-lg border border-line bg-panel-2 p-5">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <ChipGroup label="Filter by kind" options={chips} value={kind} onChange={setKind} />
              <div className="min-w-0 flex-1 sm:max-w-xs">
                <label htmlFor="entry-filter" className="block text-xs text-faint">
                  Filter by id or title
                </label>
                <input
                  id="entry-filter"
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="e.g. P-1, or protocol fee"
                  className="mt-1 w-full rounded-sm border border-line bg-panel px-2.5 py-1.5 text-sm text-ink placeholder:text-faint"
                />
              </div>
            </div>

            {/* Announced, not merely rendered. Filtering removes cards from
                well below the fold, so a screen-reader user gets no signal
                that anything happened unless it is said. */}
            {/* Named, because `Loadable` already puts a `role="status"` on this
                page for the artifact load. Two unnamed status regions are two
                anonymous voices, and a test asking for "the status" gets
                whichever it finds first. */}
            <p role="status" aria-label="Filter result" className="mt-4 mb-0 text-xs text-faint">
              {filtering
                ? `Showing ${shown.length} of ${all.length} entries.`
                : `${all.length} entries, none filtered out.`}
            </p>

            {shown.length > 0 && (
              <nav aria-label="Assumptions index" className="mt-4 border-t border-line pt-4">
                {kinds
                  .filter((k) => shown.some((e) => e.kind === k))
                  .map((k) => (
                    <div key={k} className="mt-3 first:mt-0">
                      <p className="m-0 font-mono text-xs tracking-wide text-faint uppercase">
                        {KIND_SHORT[k] ?? k} ({shown.filter((e) => e.kind === k).length})
                      </p>
                      <ul className="mt-1.5 grid list-none gap-x-6 gap-y-1 p-0 sm:grid-cols-2">
                        {shown
                          .filter((e) => e.kind === k)
                          .map((e) => (
                            <li key={e.id} className="min-w-0">
                              <a
                                href={`#${e.id}`}
                                className="flex min-w-0 gap-2 py-0.5 text-sm text-dim no-underline hover:text-accent"
                              >
                                <span className="shrink-0 font-mono text-xs text-warn">
                                  {e.id}
                                </span>
                                <span className="truncate">{e.title}</span>
                              </a>
                            </li>
                          ))}
                      </ul>
                    </div>
                  ))}
              </nav>
            )}
          </div>

          {shown.length === 0 && (
            // A stated result, not a blank page. An empty list under a filter
            // is indistinguishable from an artifact that failed to load.
            <p className="mt-8 rounded-md border border-line bg-panel p-5 text-sm text-dim">
              No entry matches that filter. All {all.length} are still here —{" "}
              <button
                type="button"
                onClick={() => {
                  setKind("all");
                  setQuery("");
                }}
                className="cursor-pointer border-0 bg-transparent p-0 text-accent underline"
              >
                clear the filter
              </button>
              .
            </p>
          )}

          {assumptions.length > 0 && (
            <Section
              title={<>Assumptions ({assumptions.length}{filtering && ` of ${counts.get("assumption") ?? 0}`})</>}
              className="mt-10"
              headingClassName="mb-5 text-lg font-semibold"
            >
              <div className="grid gap-5">
                {assumptions.map((entry) => (
                  <EntryCard
                    key={entry.id}
                    entry={entry}
                    agentSlugs={agentSlugs}
                    landed={landed === entry.id}
                  />
                ))}
              </div>
            </Section>
          )}

          {/* The named sections carry no id in the artifact and had none here
              either, so they were the only content on the page unreachable by
              anchor — and absent from the index for the same reason. */}
          {Object.entries(d.sections).map(([key, blocks]) =>
            blocks.length === 0 ? null : (
              <Section
                key={key}
                className="mt-10"
                headingClassName="mb-5 text-lg font-semibold capitalize"
                title={key.replace(/_/g, " ")}
              >
                <Card>
                  <span id={key} className="block scroll-mt-20" />
                  <Blocks blocks={blocks} />
                </Card>
              </Section>
            ),
          )}

          {others.length > 0 && (
            <Section
              // "Deviations, defects and corrections" omitted the four gaps,
              // on a page whose argument is that nothing is left out.
              title={
                <>
                  Everything else on the record ({others.length}
                  {filtering && ` of ${all.length - (counts.get("assumption") ?? 0)}`})
                </>
              }
              className="mt-10"
              headingClassName="mb-2 text-lg font-semibold"
            >
              <p className="mb-5 max-w-[68ch] text-sm text-dim">
                {/* "the 34% protocol fee" was typed here, on the page whose own
                    thesis two screens up is that every number must trace. And
                    the entry it pointed at has since been superseded by another
                    entry rendered on this same page: P-8 concludes "it is 34%
                    against 32%, not 34% against nothing… no constant is right
                    for both", and /vetting shows the second pool at 68%. So the
                    example was not just untraced, it was the exact error P-8
                    exists to record. The pointer stays; the number goes. */}
                Deviations, defects, corrections and gaps. Cards cite these alongside the
                assumptions — the protocol fee this pool actually charges is{" "}
                <code className="font-mono text-xs">P-1</code>, and the reason no single
                figure covers both pools is <code className="font-mono text-xs">P-8</code>.
                Both live in the requirements matrix rather than the assumption sheet, and
                both are published here so that no citation on any card resolves to
                nothing.
              </p>
              <div className="grid gap-5">
                {others.map((entry) => (
                  <EntryCard
                    key={entry.id}
                    entry={entry}
                    agentSlugs={agentSlugs}
                    landed={landed === entry.id}
                  />
                ))}
              </div>
            </Section>
          )}

          <p className="mt-10 text-sm text-faint">
            Generated from {d.sources.join(" and ")}.
          </p>
        </>
      )}
    </Loadable>
  );
}

function EntryCard({
  entry,
  agentSlugs,
  landed = false,
}: {
  entry: Entry;
  agentSlugs: Set<string>;
  /** True for the entry a citation link just sent the reader to. */
  landed?: boolean;
}) {
  return (
    <article
      id={entry.id}
      tabIndex={-1}
      // Anchored deep links land under a sticky header without this.
      // `min-w-0`: a grid item defaults to `min-width: auto`, so it refuses to
      // shrink below its own min-content width. One long token inside — a code
      // span, a table cell — then pushes the whole card wider than its column
      // and the document scrolls sideways at 390px.
      className={[
        "min-w-0 scroll-mt-20 rounded-lg border bg-panel p-6",
        landed ? "border-accent ring-1 ring-accent" : "border-line target:border-accent",
      ].join(" ")}
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex flex-wrap items-baseline gap-3">
          <span className="rounded-sm border border-line bg-panel-2 px-2 py-0.5 font-mono text-xs text-warn">
            {entry.id}
          </span>
          <Heading className="m-0 min-w-0 text-md font-semibold break-words">{entry.title}</Heading>
          {/* Words, not only a colour. `:target` gives a border tint and the
              programmatic focus does not reliably satisfy `:focus-visible` for
              a reader who arrived by clicking, so a mouse user landing here
              from a card's citation had colour and nothing else to pick this
              entry out of forty-eight. */}
          {landed && (
            <span className="rounded-sm border border-accent px-1.5 py-0.5 font-mono text-[11px] text-accent">
              ← you followed a citation here
            </span>
          )}
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
