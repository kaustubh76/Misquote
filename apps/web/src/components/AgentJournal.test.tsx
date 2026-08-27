import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentJournal } from "@/components/AgentJournal";

const BASE = "https://api.example.test";

beforeEach(() => vi.stubGlobal("__MISQUOTE_API__", BASE));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const serve = (body: unknown, status = 200) =>
  vi.stubGlobal("fetch", vi.fn(async () => json(body, status)));

const decision = (ts: number, action = "hold") => ({
  ts,
  action,
  reasons: { reason_hold: 1, reason_no_quotable_venue: 1, hurdle_apr: 0.0105 },
});

/**
 * The row shape that took `/agent/warden` down in all three viewports.
 *
 * Four of the warden's 181 lines are lifecycle events with no `ts` and no
 * `action`. `new Date(undefined * 1000).toISOString()` throws `RangeError`, and
 * this component renders inside the page rather than beside it.
 */
const lifecycle = {
  event: "run_start",
  chain_id: 56,
  head_block: 116_046_434,
  poll_seconds: 90,
};

const body = (over: Record<string, unknown> = {}) => ({
  agent: "warden",
  total_rows: 4,
  unparsed_rows: 0,
  returned: 4,
  summary: {
    rows: 4,
    decisions: 3,
    holds: 3,
    mints: 0,
    rebalances: 0,
    pulls: 0,
    errors: 0,
    executed: 0,
    first_ts: 1_786_781_591,
    last_ts: 1_786_868_000,
  },
  rows: [lifecycle, decision(1_786_781_591), decision(1_786_785_191), decision(1_786_868_000)],
  ...over,
});

describe("AgentJournal", () => {
  it("survives a row with no timestamp and no action", async () => {
    serve(body());
    render(<AgentJournal agent="warden" />);

    await waitFor(() => expect(screen.getByText(/What it did when it ran/)).toBeInTheDocument());
    // Three decisions listed, not four rows.
    expect(screen.getAllByText("hold", { selector: "span" })).toHaveLength(3);
  });

  it("counts decisions rather than lines, and says what the rest are", async () => {
    serve(body());
    render(<AgentJournal agent="warden" />);

    await waitFor(() => expect(screen.getByText(/3 of 3 recorded decisions/)).toBeInTheDocument());
    expect(screen.getByText(/1 lifecycle row\(s\), which are not decisions/)).toBeInTheDocument();
  });

  it("reports holds as a share, because a bare count is not about the policy", async () => {
    serve(body());
    render(<AgentJournal agent="warden" />);
    await waitFor(() => expect(screen.getByText(/3 · 100%/)).toBeInTheDocument());
  });

  /**
   * A refusal and an absence used to be one branch, and both of these asserted
   * the same empty DOM.
   *
   * They also both passed vacuously: `waitFor` retries until its callback
   * succeeds, and `toBeEmptyDOMElement()` succeeds on the very first tick —
   * before the effect that fetches has resolved anything at all. Either test
   * would have gone on passing whatever the component did afterwards, which is
   * how a section that silently disappeared stayed described as deliberate.
   *
   * They are split, and each now waits for something to be *there*.
   */
  it("renders the refusal when the service says why there is no journal", async () => {
    // The API does not 404 blankly here. It names the remedy and the agents
    // that do have journals, and says "Both are absences and neither is an
    // empty journal" — and all of that used to be thrown away.
    serve(
      {
        detail: {
          error: "no journal for 'grid'",
          remedy: "make warden ENV=testnet, or make router",
          available: ["router", "warden"],
        },
      },
      404
    );
    render(<AgentJournal agent="grid" />);

    expect(
      await screen.findByText(/This agent has written no journal/)
    ).toBeInTheDocument();
    expect(screen.getByText(/no journal for 'grid'/)).toBeInTheDocument();
    expect(screen.getByText(/make warden ENV=testnet/)).toBeInTheDocument();
  });

  it("falls back to the recorded summary when nothing answers", async () => {
    // The case that matters on the exported site: no API, or one asleep. The
    // section used to vanish on all four agents, with nothing said.
    const recorded = { agents: { warden: body({ total_rows: 181 }) } };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.includes("/artifacts/journal.json")
          ? json(recorded)
          : Promise.reject(new TypeError("network down"))
      )
    );
    render(<AgentJournal agent="warden" />);

    expect(await screen.findByText(/What it did when it ran/)).toBeInTheDocument();
    // And it says which of the two answered, rather than presenting a snapshot
    // as a live reading.
    expect(screen.getByText("recorded earlier")).toBeInTheDocument();
  });

  it("renders nothing when the recorded summary has no entry for this agent either", async () => {
    // An artifact holding no entry for an agent is the same fact the API states
    // when it refuses — but nothing said it here, so there is nothing to
    // render, and a section reading zero would be worse than none.
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.includes("/artifacts/journal.json")
          ? json({ agents: {} })
          : Promise.reject(new TypeError("network down"))
      )
    );
    const { container } = render(<AgentJournal agent="grid" />);

    // Waits for the effect to have run rather than passing on the first tick.
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("says when lines could not be parsed, so a short total is not silent", async () => {
    serve(body({ unparsed_rows: 2 }));
    render(<AgentJournal agent="warden" />);
    await waitFor(() =>
      expect(screen.getByText(/2 line\(s\) in this journal could not be parsed/)).toBeInTheDocument(),
    );
  });
});
