import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PoolLookup } from "@/components/PoolLookup";

const BASE = "https://api.example.test";

beforeEach(() => vi.stubGlobal("__MISQUOTE_API__", BASE));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

const serve = (body: unknown, status = 200) =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json(body, status))
  );

async function ask(address = "0xabc") {
  await userEvent.type(screen.getByLabelText(/Look up one pool/), address);
  await userEvent.click(screen.getByRole("button", { name: "Check" }));
}

const LADDER = {
  address: "0xabc",
  label: "PancakeSwap v3 WBNB/USDT 0.05%",
  quote_symbol: "WBNB",
  best_width_ticks: 80,
  verdict: "+/-80 ticks leads at the median, but its band overlaps +/-130",
  ladder: [
    {
      width_ticks: 80,
      p25: 0.12,
      p50: 0.17,
      p75: 0.28,
      observations: 20,
      sufficient: true,
    },
    {
      width_ticks: 40,
      p25: 0.08,
      p50: 0.15,
      p75: 0.3,
      observations: 4,
      sufficient: false,
    },
  ],
  demand: { swaps: 252923 },
};

/**
 * The route that was served and called by nothing.
 *
 * `/pools/{address}` answers what `/venue`'s list cannot — *what about the pool
 * I hold* — and until this component nothing in the app requested it. The three
 * answers it can give are pinned separately, because telling them apart is the
 * reason the route exists rather than a detail of it.
 */
describe("PoolLookup", () => {
  it("renders the engine's verdict verbatim", async () => {
    // The load-bearing half of that sentence is the clause about the lead not
    // being separated. A surface that re-derived a winner from the medians would
    // drop exactly that and publish the leaderboard this project is named
    // against.
    serve(LADDER);
    render(<PoolLookup />);
    await ask();

    expect(await screen.findByText(LADDER.verdict)).toBeInTheDocument();
  });

  it("shows only the widths that cleared the evidence floor", async () => {
    serve(LADDER);
    render(<PoolLookup />);
    await ask();

    expect(await screen.findByText("±80 ticks")).toBeInTheDocument();
    expect(screen.queryByText("±40 ticks")).not.toBeInTheDocument();
  });

  it("keeps the route's own refusal instead of rewriting it", async () => {
    // Two different 404s — never verified, versus verified and unranked — and
    // which one arrived is the answer. Collapsing them into one "not found"
    // would throw away the distinction the route was built to make.
    serve(
      {
        detail: {
          error: "0xdead is not a pool this deployment has verified",
          remedy: "GET /pools for the ones it has",
          note: "Addresses are not resolved dynamically.",
        },
      },
      404
    );
    render(<PoolLookup />);
    await ask("0xdead");

    expect(
      await screen.findByText(/not a pool this deployment has verified/)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/GET \/pools for the ones it has/)
    ).toBeInTheDocument();
  });

  it("says a pool with no ranking has none, rather than drawing a blank", async () => {
    serve({
      ...LADDER,
      best_width_ticks: null,
      verdict: "no width has enough evidence on this pool",
      ladder: [LADDER.ladder[1]],
      demand: { swaps: 85 },
    });
    render(<PoolLookup />);
    await ask();

    expect(
      await screen.findByText(/No width cleared the evidence floor/)
    ).toBeInTheDocument();
    expect(screen.getByText("85")).toBeInTheDocument();
  });

  it("refuses rather than pretending when no service answers", async () => {
    vi.stubGlobal("__MISQUOTE_API__", null);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ base: null, routes: {} }))
    );
    render(<PoolLookup />);
    await ask();

    expect(
      await screen.findByText(/No live service answered/)
    ).toBeInTheDocument();
  });
});
