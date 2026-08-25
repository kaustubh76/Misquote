import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { serveArtifacts } from "@/test/harness";
import type { AdvantageArtifact, AdvantageTask } from "@/lib/artifacts";
import { AdvantageView } from "./view";

/**
 * The two chart-honesty rules, driven by fixtures rather than by the artifact.
 *
 * `pages.test.tsx` renders `<AdvantagePage />` against the real
 * `advantage.json`, which is the right way round for everything it asserts —
 * an emitter change should break a page test. It cannot cover these two,
 * because `same_run` and `returns` only appear in a report generated after the
 * emitter learned to publish them, and that is a four-hour replay away.
 */
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const side = (over: Partial<AdvantageTask["agent"]> = {}) => ({
  p25: 1.0,
  p50: 2.0,
  p75: 3.0,
  in_range: 0.9,
  fees: 1.5,
  lvr_upper_bound: 0.25,
  costs: 0.75,
  moves: 6,
  ...over,
});

const task = (over: Partial<AdvantageTask> = {}): AdvantageTask =>
  ({
    task: "Choose — which pool to provide liquidity to",
    category: "security",
    venue: "two venues",
    metric: "net return on capital",
    without_agent: "pick the deepest pool",
    with_agent: "pick the pool whose flow is not one-way",
    quotable: true,
    note: "annualised",
    baseline: side(),
    agent: side(),
    delta_pp: 0,
    ranges_overlap: true,
    material: false,
    separated: false,
    verdict: "indistinguishable",
    replay_days: 31,
    ...over,
  }) as AdvantageTask;

const report = (t: AdvantageTask): AdvantageArtifact =>
  ({
    report: "r",
    question: "q",
    counterfactual: "c",
    badge: "COUNTERFACTUAL",
    source: "chain",
    quote_symbol: "WBNB",
    capital_quote: 1,
    summary: { tasks: 1, quotable: 1, withheld: 0 },
    overall: { called: false, label: "no verdict" },
    tasks: [t],
  }) as unknown as AdvantageArtifact;

const bands = () => document.querySelectorAll(".band-draw");

/**
 * Serve the fixture, do not merely seed it.
 *
 * `AdvantageView` keeps its `useEffect` and refetches `advantage.json` — the
 * property `lib/build-artifact` exists to preserve, so that editing a JSON and
 * reloading still works. Passing a fixture only as `initialMain` therefore
 * renders it for one frame and then replaces it with the real artifact on disk,
 * which is how the first draft of this file asserted against the committed
 * report while believing it was reading a fixture.
 */
function serve(t: AdvantageTask) {
  serveArtifacts({ overrides: { "advantage.json": report(t) } });
  return report(t);
}

describe("a task where both columns are the same replay", () => {
  it("draws one band, not two identical ones", async () => {
    const fixture = serve(task({ same_run: true }));
    render(<AdvantageView initialMain={fixture} />);
    await screen.findByRole("heading", { name: /Choose/ });
    await waitFor(() => expect(bands()).toHaveLength(1));
  });

  it("says why there is only one", async () => {
    const fixture = serve(task({ same_run: true }));
    render(<AdvantageView initialMain={fixture} />);
    expect(await screen.findByText(/One band, because one thing was measured/)).toBeInTheDocument();
    expect(screen.getByText(/exactly zero by construction rather than by measurement/)).toBeInTheDocument();
  });

  it("still draws two when two runs merely tied", async () => {
    // `same_run` absent, delta zero. Two separate replays are allowed to agree,
    // and collapsing that would erase the finding that they did.
    const fixture = serve(task({ delta_pp: 0 }));
    render(<AdvantageView initialMain={fixture} />);
    await screen.findByRole("heading", { name: /Choose/ });
    await waitFor(() => expect(bands()).toHaveLength(2));
    expect(screen.queryByText(/One band, because one thing was measured/)).not.toBeInTheDocument();
  });
});

describe("a task on a venue that has no liquidity-provision metrics", () => {
  it("explains the em dashes instead of leaving them bare", async () => {
    const lending = task({
      task: "Route — which lending venue to supply to",
      agent: side({ in_range: undefined, fees: undefined, lvr_upper_bound: undefined }),
      baseline: side({ in_range: undefined, fees: undefined, lvr_upper_bound: undefined }),
    });
    const fixture = serve(lending);
    render(<AdvantageView initialMain={fixture} />);
    expect(
      await screen.findByText(/quantities this venue does not have — not measurements of zero/),
    ).toBeInTheDocument();
  });

  it("says nothing of the sort on a liquidity task", async () => {
    const fixture = serve(task());
    render(<AdvantageView initialMain={fixture} />);
    await screen.findByRole("heading", { name: /Choose/ });
    expect(screen.queryByText(/quantities this venue does not have/)).not.toBeInTheDocument();
  });
});
