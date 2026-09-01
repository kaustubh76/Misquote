"use client";

import { Heading, Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import { useEffect, useState } from "react";
import { Blocks, Prose, type Block } from "@/components/Blocks";
import { Card } from "@/components/Card";
import { ChipGroup } from "@/components/ChipGroup";
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
}: {
  /** Read from disk at build time by `page.tsx`. See `lib/build-artifact`. */
  initialSheet?: AssumptionsArtifact;
}) {
  const [state, setState] = useState<Loaded<AssumptionsArtifact> | null>(
    initialSheet ? { ok: true, value: initialSheet } : null,
  );
  const [kind, setKind] = useState("all");
  const [query, setQuery] = useState("");
  const [landed, setLanded] = useState<string | null>(null);
  /** An id from the hash, waiting for the filter reset to land. */
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    load<AssumptionsArtifact>("assumptions.json").then((sheet) => {
      if (live) setState(sheet);
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

      // And then stop, because the entry is not in the DOM yet.
      //
      // React batches those two setters, so at this point the page is still
      // filtered and `getElementById` returns null for exactly the entry this
      // exists to reveal. The early return below then skipped the marking, the
      // focus and the scroll — leaving a reader who followed a citation from a
      // filtered page at whatever scroll position they were already at, with
      // nothing marked.
      //
      // **jsdom cannot see this.** The test covering this scenario passed
      // throughout, and a real browser fails it: filtered to Gaps, following a
      // citation to A5 clears the filter, renders no badge, and leaves the
      // entry 2,340px down the page. The guard that does see it is the
      // interaction pass in `scripts/check-pages.mjs`.
      //
      // So the DOM work moves to its own effect, which runs after the filter
      // has actually been applied.
      setPending(id);
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

  /**
   * The half of the reveal that needs the DOM, run once the filter has cleared.
   *
   * Keyed on `kind` and `query` as well as `pending`, so it fires on the render
   * *after* the setters above have been applied — which is the render in which
   * the target entry actually exists. Doing it inline was the defect: React
   * batches, so the element was never found and the reader was left unmarked
   * and unscrolled.
   */
  useEffect(() => {
    if (!pending) return;

    const target = document.getElementById(pending);
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
    setLanded(pending);
    target.focus({ preventScroll: true });
    target.scrollIntoView?.({ block: "start" });

    setPending(null);
  }, [pending, kind, query, state]);

  const d = state?.ok ? state.value : null;

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
    <Loadable loading={state === null} what="the assumption sheet" className="max-w-3xl">
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">The assumption sheet</h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        Footnotes, except these are the point: every number on this site traces to a
        chain query or to an entry below, or it does not render.
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
                Run <code className="font-mono text-xs">make assumptions</code>.
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
          <div className="surface mt-8 rounded-lg border border-glass-line bg-glass p-5">
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
                  className="mt-1 w-full rounded-sm border border-glass-line bg-glass px-2.5 py-1.5 text-sm text-ink transition-colors placeholder:text-faint focus:border-brand focus:shadow-[inset_3px_0_0_0_var(--brand)]"
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
                                className="flex min-w-0 gap-2 py-0.5 text-sm text-dim no-underline hover:text-brand"
                              >
                                <span className="shrink-0 font-mono text-xs text-warn">
                                  {e.id}
                                </span>
                                {/* Same string, same treatment — an index whose
                                    entries read differently from the headings
                                    they point at is a worse index. `truncate`
                                    still clips it; the marks inside are inline.

                                    `links={false}` because this whole row is
                                    already an `<a href="#id">`, and three titles
                                    name another assumption — "A1 is refused at
                                    the decision", "published as G-4". A `<Cite>`
                                    inside this anchor is an anchor inside an
                                    anchor: the parser hoists it out, and
                                    `/assumptions` threw React #418 on every
                                    load until this prop existed. The ids still
                                    read as text; they are links in the heading
                                    the row points at. */}
                                <span className="truncate">
                                  <Prose text={e.title} links={false} />
                                </span>
                              </a>
                            </li>
                          ))}
                      </ul>
                    </div>
                  ))}

                {/* The named sections, which this index omitted entirely.
                    They are the only blocks on the page that are not entries,
                    so iterating `shown` never reached them — a reader could
                    jump to any of seventy assumptions and to none of the five
                    sections that frame them. Kept visually apart from the
                    kind groups above, because they are a different kind of
                    destination, and not filtered: a verdict filter narrows
                    entries and these are not entries. */}
                {Object.entries(d.sections).some(([, b]) => b.length > 0) && (
                  <div className="mt-4 border-t border-line pt-3">
                    <p className="m-0 font-mono text-xs tracking-wide text-faint uppercase">
                      Sections
                    </p>
                    <ul className="mt-1.5 flex list-none flex-wrap gap-x-4 gap-y-1 p-0">
                      {Object.entries(d.sections)
                        .filter(([, blocks]) => blocks.length > 0)
                        .map(([key]) => (
                          <li key={key} className="min-w-0">
                            <a
                              href={`#${key}`}
                              className="text-sm text-dim capitalize no-underline hover:text-brand"
                            >
                              {key.replace(/_/g, " ")}
                            </a>
                          </li>
                        ))}
                    </ul>
                  </div>
                )}
              </nav>
            )}
          </div>

          {shown.length === 0 && (
            // A stated result, not a blank page. An empty list under a filter
            // is indistinguishable from an artifact that failed to load.
            <p className="surface mt-8 rounded-md border border-glass-line bg-glass p-5 text-sm text-dim">
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
                    landed={landed === entry.id}
                  />
                ))}
              </div>
            </Section>
          )}

          {/* The named sections carry no id in the artifact, so the id is the
              key and it goes on the `<section>` — via `Section`'s own `id`
              prop, which brings `.scroll-anchor` with it.

              It was a `<span id>` *inside* the Card, below the heading, so a
              deep link to one of these landed past the title of the thing it
              was linking to. The comment here used to say these sections were
              "the only content on the page unreachable by anchor — and absent
              from the index for the same reason", as though both halves had
              been fixed. Only the first had. The index below iterates the
              entries and never these, which is the second half, and it is
              fixed in the same pass. */}
          {Object.entries(d.sections).map(([key, blocks]) =>
            blocks.length === 0 ? null : (
              <Section
                key={key}
                id={key}
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
                    landed={landed === entry.id}
                  />
                ))}
              </div>
            </Section>
          )}

        </>
      )}
    </Loadable>
  );
}

function EntryCard({
  entry,
  landed = false,
}: {
  entry: Entry;
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
        "surface scroll-anchor min-w-0 rounded-lg border bg-glass p-6",
        landed ? "border-accent ring-1 ring-accent" : "border-glass-line target:border-accent",
      ].join(" ")}
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex flex-wrap items-baseline gap-3">
          <span className="rounded-sm border border-glass-line bg-panel-2/50 px-2 py-0.5 font-mono text-xs text-warn">
            {entry.id}
          </span>
          {/* `Prose`, because these titles are written in markdown too.
              Thirty-two of the eighty-two end in a dated suffix —
              "**fixed 17 Aug 2026**" — and every one of them printed its own
              asterisks, on the page that argues the sheet is a product surface
              rather than a note. The body two blocks down has rendered markdown
              since it was written; only the heading above it did not. */}
          <Heading className="m-0 min-w-0 text-md font-semibold break-words">
            <Prose text={entry.title} />
          </Heading>
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
    </article>
  );
}
