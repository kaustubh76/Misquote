import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DemoView } from "./view";
import type { ScenarioSummary } from "@/lib/build-artifact";

vi.mock("next/navigation", () => ({ usePathname: () => "/demo" }));

afterEach(cleanup);

const happy: ScenarioSummary = {
  name: "demo-quote",
  label: "A quote the tape can support",
  why: "The flagship flow, recorded from a real job.",
  paths: ["/quote/eligibility/{address}", "POST /quote", "/quote/job/{id}"],
  route: "/quote/",
};

const refusal: ScenarioSummary = {
  name: "quote-thin-tape",
  label: "A quote the tape cannot support",
  why: "The engine refuses before it starts.",
  paths: ["POST /quote"],
  route: "/quote/",
};

describe("Demo: the way into a feature that had none", () => {
  it("links to every scenario it was given, carrying the parameter", () => {
    // The whole defect this page exists for: the simulation layer was complete,
    // tested, deployed — and reachable only by knowing `?scenario=` existed and
    // guessing a fixture name printed on no page.
    render(<DemoView scenarios={[happy, refusal]} />);

    // Without the trailing slash, which is what `next/link` renders even though
    // the fixture stores `/quote/` and `next.config.ts` sets `trailingSlash:
    // true`. Checked against the deployed site rather than assumed: a request to
    // `/quote?scenario=…` answers 308 to `/quote/?scenario=…` with the query
    // intact, so the link resolves either way and the parameter survives.
    const link = screen.getByRole("link", { name: /Open this state/ });
    expect(link).toHaveAttribute("href", "/quote?scenario=quote-thin-tape");
  });

  it("renders each scenario's own label and why, rather than a description of it", () => {
    // `scenario.ts` refuses a fixture without both, on the grounds that "a file
    // that does not describe itself is not a scenario". This page shows what the
    // fixture says about itself, so the two cannot drift into disagreeing.
    render(<DemoView scenarios={[happy, refusal]} />);

    expect(screen.getByText(refusal.label)).toBeInTheDocument();
    expect(screen.getByText(refusal.why)).toBeInTheDocument();
  });

  it("takes the list as data, so it cannot advertise a fixture that is gone", () => {
    // Read off `public/scenarios/` at build time by `readScenarios()`. A page
    // with the names written into it would keep offering a deleted state, and
    // keep silent about a new one.
    render(<DemoView scenarios={[]} />);

    expect(screen.queryByText(/Open this state/)).not.toBeInTheDocument();
    // The rules are the page's argument and survive an empty list.
    expect(screen.getByText(/never on by default and never sticky/)).toBeInTheDocument();
  });

  it("marks the guided run's last step real, because it is", () => {
    // `/activate` carries three mined chapel transactions. Simulating a grant
    // beside genuine receipts would be strictly worse evidence, so the walkthrough
    // walks to them instead — and has to say which steps are which.
    render(<DemoView scenarios={[happy, refusal]} />);

    const activate = screen.getByRole("link", { name: /See what hiring involves/ });
    const step = activate.closest("li");
    expect(step).not.toBeNull();
    expect(within(step!).getByText("Real")).toBeInTheDocument();
    expect(activate).toHaveAttribute("href", "/activate");
  });

  it("marks the quote step simulated, and carries an address so it lands on an answer", () => {
    // Two steps pointed at the same URL and the second told the reader to press
    // a button that only exists after a submit — so the interesting step landed
    // on an empty form. One step now, with an address in the link.
    render(<DemoView scenarios={[happy, refusal]} />);

    const run = screen.getByRole("link", { name: /Read the range, on a wallet you do not own/ });
    const href = run.getAttribute("href") ?? "";
    expect(href).toContain("/quote");
    expect(href).toContain("scenario=demo-quote");
    expect(href).toMatch(/address=0x[0-9a-fA-F]{40}/);
    expect(within(run.closest("li")!).getByText("Simulated")).toBeInTheDocument();
  });

  it("does not offer a guided run when the recorded quote is absent", () => {
    // The happy path is the one fixture that has to be *recorded* rather than
    // written, so a checkout without it must not advertise a walkthrough that
    // dead-ends on step two.
    render(<DemoView scenarios={[refusal]} />);

    expect(screen.queryByText("The guided run")).not.toBeInTheDocument();
    expect(screen.getByText(/Every recorded state/)).toBeInTheDocument();
  });

  it("says what is never simulated, and names Showcase Mode", () => {
    // `Readme.md` §1 calls Showcase Mode the default and §7 makes it never-cut,
    // and it has existed only as a COUNTERFACTUAL badge nobody was told the
    // meaning of.
    render(<DemoView scenarios={[happy]} />);

    expect(screen.getByText(/COUNTERFACTUAL/)).toBeInTheDocument();
    expect(screen.getByText(/Showcase Mode/)).toBeInTheDocument();
  });
});

describe("the recorded quote is a recording", () => {
  /**
   * The fixture is the one thing here that could have been invented, and the
   * plan said record rather than assemble. Doing so is what found P-32: the same
   * job, before the fix, answered `0.00% to 0.00%` with `distinct_returns: 1`
   * and the engine called it sufficient.
   *
   * So these assert the properties that distinguish a measurement from an
   * absence, on the file itself.
   */
  const fixture = JSON.parse(
    readFileSync(join(process.cwd(), "public", "scenarios", "demo-quote.json"), "utf8"),
  );

  it("carries a range that varies, rather than three copies of one number", () => {
    const result = fixture.responses["/quote/job/{id}"].body.result;
    expect(result.p25).toBeLessThan(result.p50);
    expect(result.p50).toBeLessThan(result.p75);
    // The tell that named the defect. One distinct return across every replay is
    // what a missing denominator looks like.
    expect(result.distinct_returns).toBeGreaterThan(1);
    expect(result.samples).toBe(24);
  });

  it("discloses that it ran on the reduced budget", () => {
    // Eight windows, not twenty — a published reduction (A15). Without this flag
    // a reader would compare it against an agent card, and the two are different
    // measurements of different policies.
    const result = fixture.responses["/quote/job/{id}"].body.result;
    expect(result.interactive_budget).toBe(true);
    expect(result.windows).toBe(8);
  });

  it("offers exactly one quotable holding, so no button leads nowhere", () => {
    // Two would render a second "Replay this pool" whose POST this fixture does
    // not answer — a dead button on step three of the guided run.
    const body = fixture.responses["/quote/eligibility/{address}"].body;
    expect(body.holdings.filter((h: { quotable: boolean }) => h.quotable)).toHaveLength(1);
    expect(body.holdings).toHaveLength(1);
  });

  it("keeps no per-deployment liveness in a recording", () => {
    // A worker heartbeat from the day this was captured is not a fact about a
    // demo opened months later.
    const body = fixture.responses["POST /quote"].body;
    expect(body).not.toHaveProperty("worker_last_seen");
    expect(body).not.toHaveProperty("workers_alive");
    expect(body.job_id).toBeTruthy();
  });
});
