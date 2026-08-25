"use client";

import { useCallback, useRef, useState } from "react";
import { AnsweredBy } from "@/components/AnsweredBy";
import { Button } from "@/components/Button";
import { Pill } from "@/components/Pill";
import { Refusal } from "@/components/Refusal";
import { loadLive, RefusalError, type Source } from "@/lib/api";
import { count, pct } from "@/lib/format";

/** The subset of a survey row this control needs. The cards render the rest. */
export interface SearchableAgent {
  agent_id: number;
  name: string;
  description: string;
  endpoints: string[];
  resolvable: boolean;
  substantive: boolean;
  looks_like_a_placeholder: boolean;
}

interface Coverage {
  population: number;
  sampled: number;
  searched: number;
  matching: number;
  sampled_at_block?: number | null;
  share_of_population: number | null;
  complete: boolean;
  note: string;
}

interface Page {
  query: string;
  page: number;
  pages: number;
  total_matching: number;
  agents: SearchableAgent[];
  coverage: Coverage;
}

/**
 * Searching the survey the artifact only samples.
 *
 * `registry.json` publishes twenty-four agent cards out of four hundred it
 * surveyed — `identity.listings_shown` against `identity.sampled`, both of them
 * already in the file. The other three hundred and seventy-six were read, and
 * scored, and are reachable only through `/registry/agents`, which was
 * registered, tested, named in `api.json`'s own `routes` map, and called by
 * nothing.
 *
 * So `ListingCard` — with its docstring about why a third-party listing carries
 * no performance figure, and the 234px overflow bug its `break-words` fixes —
 * rendered at most twenty-four of the rows it was written for.
 *
 * ## Coverage travels with the answer
 *
 * The route returns `coverage` inside every response rather than from a route
 * of its own, "because a caller who never asks is exactly the caller who most
 * needs to be told". This renders it for the same reason. A search across four
 * hundred agents out of a population of two hundred and seventy-eight thousand
 * is a search across 0.1% of the registry, and a result list that did not say
 * so would read as the registry's answer rather than as the sample's.
 *
 * ## Why a form rather than search-as-you-type
 *
 * Every keystroke would be a request to a free-tier host that spins down when
 * idle, and the first one after an idle hour pays a cold start. A submitted
 * query is one request whose cost the reader chose.
 */
export function RegistrySearch({ published }: { published: number }) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState<
    | { phase: "idle" }
    | { phase: "searching" }
    | { phase: "done"; value: Page; source: Source }
    | { phase: "refused"; error: RefusalError }
    | { phase: "unavailable" }
  >({ phase: "idle" });

  // Held so paging re-asks the question that produced the current page rather
  // than whatever is in the input now — a reader who edits the box and then
  // presses "next" must not silently page through different results.
  const asked = useRef("");

  const run = useCallback(async (needle: string, page: number) => {
    setState({ phase: "searching" });
    asked.current = needle;
    // No fallback. The published twenty-four are a different question — they are
    // what this page already shows — and returning them for a search that
    // matched nothing would be a stale yes in place of a considered no.
    const got = await loadLive<Page>(
      `/registry/agents?q=${encodeURIComponent(needle)}&page=${page}&per_page=12`,
    );
    if (got.ok) return setState({ phase: "done", value: got.value, source: got.source });
    if (got.error instanceof RefusalError) return setState({ phase: "refused", error: got.error });
    setState({ phase: "unavailable" });
  }, []);

  return (
    <div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void run(query.trim(), 1);
        }}
        className="flex flex-wrap items-end gap-2"
      >
        <label className="min-w-0 flex-1 text-sm">
          <span className="text-dim">Search all surveyed agents</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="a name, an endpoint, or an id"
            className="mt-1 w-full rounded-sm border border-glass-line bg-glass px-2.5 py-1.5 text-sm text-ink transition-colors placeholder:text-faint focus:border-brand focus:shadow-[inset_3px_0_0_0_var(--brand)]"
          />
        </label>
        <Button type="submit" disabled={state.phase === "searching"}>
          {state.phase === "searching" ? "Searching…" : "Search"}
        </Button>
      </form>

      <p className="mt-2 mb-0 text-xs text-faint">
        This page publishes {count(published)} cards. The survey read more than that,
        and a live service can search all of it.
      </p>

      <div className="mt-4" aria-busy={state.phase === "searching"}>
        {state.phase === "refused" && (
          <Refusal
            title="The registry survey cannot be searched"
            reason={state.error.message}
            floor={state.error.remedy || undefined}
          />
        )}

        {state.phase === "unavailable" && (
          <Refusal
            title="No live service answered"
            reason="Searching the whole survey needs a running API; the cards below are what this export carries."
            floor="Start one with `make api` and publish its address with `make api-config`."
          />
        )}

        {state.phase === "done" && <Results page={state.value} source={state.source} onPage={run} />}
      </div>
    </div>
  );
}

function Results({
  page,
  source,
  onPage,
}: {
  page: Page;
  source: Source;
  onPage: (needle: string, page: number) => void;
}) {
  const { coverage } = page;

  return (
    <>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="m-0 text-sm text-dim">
          <strong className="text-ink">{count(page.total_matching)}</strong> of{" "}
          {count(coverage.searched)} surveyed agents match
          {page.query ? (
            <>
              {" "}
              <span className="font-mono text-xs">{page.query}</span>
            </>
          ) : null}
          .
        </p>
        <AnsweredBy source={source} />
      </div>

      {/* The magnitude the count alone hides. Four hundred agents out of a
          registry of hundreds of thousands is a fraction of a percent, and the
          route says so in every response precisely so a caller cannot report
          the sample's answer as the registry's. */}
      <p className="mt-1 mb-4 text-xs text-faint">
        Searched {count(coverage.sampled)} of {count(coverage.population)} registered
        agents
        {coverage.share_of_population !== null && (
          <> — {pct(coverage.share_of_population * 100)} of the registry</>
        )}
        {coverage.sampled_at_block ? <>, sampled at block {count(coverage.sampled_at_block)}</> : null}
        . {coverage.note}
      </p>

      {page.agents.length === 0 ? (
        <Refusal
          title="Nothing in the sample matches"
          reason="No surveyed agent carries that text in its name, description, notes or endpoints."
          floor="Text search covers the sample; lookup by id reaches every registered agent."
        />
      ) : (
        <ul className="m-0 grid list-none gap-2 p-0 sm:grid-cols-2">
          {page.agents.map((agent) => (
            <li
              key={agent.agent_id}
              className="surface min-w-0 rounded-md border border-glass-line bg-glass p-3"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate text-sm font-medium text-ink">
                  {agent.name?.trim() || `Agent #${agent.agent_id}`}
                </span>
                <span className="shrink-0 font-mono text-[11px] text-faint">
                  #{agent.agent_id}
                </span>
              </div>
              {/* `break-words` for the reason `ListingCard` records: one agent in
                  the first real survey describes itself as sixty digits with no
                  space in them, which set a card's min-content width to 599px. */}
              {agent.description?.trim() && (
                <p className="mt-1 mb-0 text-xs break-words text-dim line-clamp-2">
                  {agent.description}
                </p>
              )}
              <ul className="mt-2 flex flex-wrap gap-1.5">
                <Pill tone={agent.resolvable ? "pass" : "fail"}>
                  {agent.resolvable ? "card resolves" : "does not resolve"}
                </Pill>
                {agent.looks_like_a_placeholder && <Pill tone="fail">placeholder</Pill>}
              </ul>
              {/* The same sentence every published card carries, for the same
                  reason: the absence of a number is the claim, so it appears on
                  the row rather than once above the list. */}
              <p className="mt-2 mb-0 text-[11px] text-faint">
                No quote — we cannot replay a policy we do not have.
              </p>
            </li>
          ))}
        </ul>
      )}

      {page.pages > 1 && (
        <div className="mt-4 flex items-center justify-between gap-3">
          <Button
            type="button"
            disabled={page.page <= 1}
            onClick={() => onPage(page.query, page.page - 1)}
          >
            Previous
          </Button>
          <span className="tabular text-xs text-faint">
            page {count(page.page)} of {count(page.pages)}
          </span>
          <Button
            type="button"
            disabled={page.page >= page.pages}
            onClick={() => onPage(page.query, page.page + 1)}
          >
            Next
          </Button>
        </div>
      )}
    </>
  );
}

