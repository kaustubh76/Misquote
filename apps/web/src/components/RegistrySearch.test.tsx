import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RegistrySearch } from "@/components/RegistrySearch";

/**
 * The control that reaches the 376 agents the artifact does not publish.
 *
 * Driven through `window.__MISQUOTE_API__` for the reason `quote/view.test.tsx`
 * records: `apiBase()` checks it before its module-scope memo, so this exercises
 * the same seam a deployment uses rather than going around it.
 */
const BASE = "https://api.example.test";

beforeEach(() => vi.stubGlobal("__MISQUOTE_API__", BASE));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const agent = (id: number, over: Record<string, unknown> = {}) => ({
  agent_id: id,
  name: `Agent ${id}`,
  description: "does a thing",
  endpoints: [],
  resolvable: true,
  substantive: true,
  looks_like_a_placeholder: false,
  ...over,
});

const page = (over: Record<string, unknown> = {}) => ({
  query: "trading",
  page: 1,
  pages: 3,
  total_matching: 181,
  agents: [agent(1), agent(2)],
  coverage: {
    population: 280_287,
    sampled: 400,
    searched: 400,
    matching: 181,
    sampled_at_block: 117_075_046,
    share_of_population: 0.0014271,
    complete: false,
    note: "Text search covers the sampled agents only.",
  },
  ...over,
});

function serve(reply: (url: string) => Response) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      calls.push(String(input));
      return reply(String(input));
    }),
  );
  return calls;
}

describe("RegistrySearch", () => {
  it("reports the coverage the answer had, not just the count", async () => {
    serve(() => json(page()));
    render(<RegistrySearch published={24} />);

    await userEvent.type(screen.getByLabelText(/Search all surveyed agents/), "trading");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(screen.getByText(/181/)).toBeInTheDocument());
    // The share, spelled out. A result count with no denominator reads as the
    // registry's answer rather than as the sample's.
    expect(screen.getByText(/Searched 400 of 280,287 registered agents/)).toBeInTheDocument();
  });

  it("carries the no-quote sentence on every row, not once above the list", async () => {
    serve(() => json(page()));
    render(<RegistrySearch published={24} />);
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(screen.getAllByText(/No quote/)).toHaveLength(2));
  });

  it("pages the query that produced the current page, not what is in the box now", async () => {
    const calls = serve(() => json(page()));
    render(<RegistrySearch published={24} />);

    const box = screen.getByLabelText(/Search all surveyed agents/);
    await userEvent.type(box, "trading");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Next" })).toBeEnabled());

    // The reader edits the box and then pages, without searching again.
    await userEvent.clear(box);
    await userEvent.type(box, "something else");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]).toContain("q=trading");
    expect(calls[1]).toContain("page=2");
  });

  it("shows a refusal as a refusal, with the remedy the service named", async () => {
    // 409, not 503, and the distinction is the backend's own. `api/errors.py`
    // assigns 409 to "the request is well-formed and the evidence cannot
    // support it — not a failure, an answer" and 503 to "transient; retry is
    // the correct response". `loadLive` implements exactly that split, so a 503
    // is deliberately *not* a refusal to a client and the case below covers it.
    serve(() =>
      json(
        {
          detail: {
            error: "the survey covers 400 agents and this query needs the population",
            remedy: "make registry-survey SAMPLE=400",
          },
        },
        409,
      ),
    );
    render(<RegistrySearch published={24} />);
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(screen.getByText(/the survey covers 400 agents/)).toBeInTheDocument());
    expect(screen.getByText(/make registry-survey SAMPLE=400/)).toBeInTheDocument();
  });

  it("treats a transient 503 as nothing having answered, and still shows no cards", async () => {
    serve(() => json({ detail: { error: "an emitter is mid-write", remedy: "retry" } }, 503));
    render(<RegistrySearch published={24} />);
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(screen.getByText(/No live service answered/)).toBeInTheDocument());
    // The published cards are a different question and are never substituted
    // for a search result, whichever way the request failed.
    expect(screen.queryByText(/No quote/)).not.toBeInTheDocument();
  });

  it("says nothing matched rather than showing an empty grid", async () => {
    serve(() => json(page({ agents: [], total_matching: 0, pages: 1 })));
    render(<RegistrySearch published={24} />);
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() =>
      expect(screen.getByText(/Nothing in the sample matches/)).toBeInTheDocument(),
    );
  });
});
