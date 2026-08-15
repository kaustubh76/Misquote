import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readArtifact, serveArtifacts, textFrom } from "@/test/harness";
import type { AdvantageArtifact, AgentArtifact, IndexArtifact } from "@/lib/artifacts";

import AdvantagePage from "./advantage/page";
import AssumptionsPage from "./assumptions/page";
import MethodsPage from "./methods/page";
import OverviewPage from "./page";
import RegistryPage from "./registry/page";
import StatusPage from "./status/page";
import { AgentDetail } from "@/components/AgentDetail";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

beforeEach(() => serveArtifacts());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/**
 * Every view, rendered end to end against the artifacts on disk.
 *
 * These pages fetch after mount, so nothing above this line proves they ever
 * paint: a typecheck passes on a component that throws on its first render, and
 * a static export returns 200 for a page whose body is a skeleton forever.
 */
describe("Overview", () => {
  it("renders a card per agent, from the index", async () => {
    const index = readArtifact<IndexArtifact>("index.json");
    render(<OverviewPage />);

    for (const agent of index.agents) {
      expect(await screen.findByRole("heading", { name: agent.name })).toBeInTheDocument();
    }
  });

  it("declares the tape as synthetic rather than burying it", async () => {
    render(<OverviewPage />);
    expect(await screen.findByText(/Synthetic tape — not chain data/)).toBeInTheDocument();
  });

  it("shows the fourth category as not built instead of omitting it", async () => {
    render(<OverviewPage />);
    expect(await screen.findByRole("heading", { name: "Router" })).toBeInTheDocument();
    expect(screen.getAllByText("Not built").length).toBeGreaterThan(0);
  });

  it("stops loading — the skeleton is not the final state", async () => {
    const { container } = render(<OverviewPage />);
    await waitFor(() =>
      expect(container.querySelector("[aria-busy='true']")).not.toBeInTheDocument(),
    );
  });
});

describe("Overview, when one agent artifact is missing", () => {
  it("loses one card, not all of them", async () => {
    // The old page used Promise.all, so a single 404 erased every card and
    // reported it as "no artifacts yet — run make showcase".
    serveArtifacts({ missing: ["grid.json"] });
    render(<OverviewPage />);

    expect(await screen.findByRole("heading", { name: "Warden" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sentinel" })).toBeInTheDocument();

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/Grid card could not be loaded/);
    // And it names the real cause rather than a parse error or a wrong remedy.
    expect(alert).toHaveTextContent(/404/);
  });
});

describe("Agent detail", () => {
  it("renders the blocks the card page dropped", async () => {
    render(<AgentDetail slug="warden" />);

    expect(await screen.findByRole("heading", { name: "Warden" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Why it held" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Provenance" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "The parameters behind the range" }),
    ).toBeInTheDocument();
  });

  it("discloses that kappa was not fitted, when it was not", async () => {
    const warden = readArtifact<AgentArtifact>("warden.json");
    render(<AgentDetail slug="warden" />);
    await screen.findByRole("heading", { name: "Warden" });

    if (warden.estimators.kappa_is_fallback) {
      expect(screen.getByText(/κ was not fitted on this run/)).toBeInTheDocument();
      expect(screen.getByText(textFrom(warden.estimators.kappa_label))).toBeInTheDocument();
    }
  });

  it("says so when the provenance journal is empty", async () => {
    const warden = readArtifact<AgentArtifact>("warden.json");
    render(<AgentDetail slug="warden" />);
    await screen.findByRole("heading", { name: "Provenance" });

    if (warden.provenance.journal_rows === 0) {
      expect(screen.getByText(/journal .* has zero rows/i)).toBeInTheDocument();
    }
  });

  it("names the file when the artifact is absent", async () => {
    serveArtifacts({ missing: ["warden.json"] });
    render(<AgentDetail slug="warden" />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/warden\.json/);
  });
});

describe("Advantage", () => {
  it("renders every task with its verdict", async () => {
    const d = readArtifact<AdvantageArtifact>("advantage.json");
    render(<AdvantagePage />);

    for (const task of d.tasks) {
      expect(await screen.findByRole("heading", { name: task.task })).toBeInTheDocument();
    }
  });

  it("presents the overall refusal as the headline, not an error", async () => {
    const d = readArtifact<AdvantageArtifact>("advantage.json");
    render(<AdvantagePage />);
    expect(await screen.findByText(d.overall.label)).toBeInTheDocument();
    expect(screen.getByText(/refuses to call it/)).toBeInTheDocument();
  });

  it("shows the short-tape panel withholding every task", async () => {
    const short = readArtifact<AdvantageArtifact>("advantage_short.json");
    render(<AdvantagePage />);

    await screen.findByRole("heading", { name: /same report, on too little history/i });
    expect(short.summary.withheld).toBe(short.summary.tasks);
    expect(
      await screen.findByText(`${short.summary.withheld} of ${short.summary.tasks} withheld`),
    ).toBeInTheDocument();
  });

  it("publishes a task where the agent lost", async () => {
    // Sentinel loses to DIY on the Protect task. Nothing may reorder or hide it.
    const d = readArtifact<AdvantageArtifact>("advantage.json");
    const losing = d.tasks.filter((t) => t.quotable && t.delta_pp < 0);
    render(<AdvantagePage />);

    for (const task of losing) {
      const heading = await screen.findByRole("heading", { name: task.task });
      const card = heading.closest("article")!;
      expect(within(card).getByText(/loses to DIY/)).toBeInTheDocument();
    }
  });
});

describe("Methods", () => {
  it("reconciles the window length against the tape length", async () => {
    const warden = readArtifact<AgentArtifact>("warden.json");
    render(<MethodsPage />);

    const heading = await screen.findByRole("heading", { name: /Why the quote says/ });
    // Both numbers, in one sentence, so the card can stop appearing to
    // contradict itself.
    expect(heading).toHaveTextContent(warden.quote_detail!.hours_per_window.toFixed(1));
    expect(heading).toHaveTextContent(warden.replay.hours.toFixed(1));
  });

  it("renders the four floors from the emitted values", async () => {
    const warden = readArtifact<AgentArtifact>("warden.json");
    render(<MethodsPage />);

    await screen.findByRole("heading", { name: "The four floors" });
    expect(
      screen.getByText(`min_windows = ${warden.floors.min_windows}`),
    ).toBeInTheDocument();
    expect(
      screen.getByText(`min_observations = ${warden.floors.min_observations}`),
    ).toBeInTheDocument();
  });
});

describe("Assumptions", () => {
  it("renders every entry, addressable by its id", async () => {
    render(<AssumptionsPage />);
    await screen.findByRole("heading", { name: /^Assumptions \(/ });

    for (const id of ["A5", "A6", "A8", "A10", "P-1", "G-4"]) {
      expect(document.getElementById(id), `${id} has no anchor`).toBeTruthy();
    }
  });

  it("reports no dead citations", async () => {
    render(<AssumptionsPage />);
    await screen.findByRole("heading", { name: /^Assumptions \(/ });
    expect(screen.queryByText(/Dead citations/)).not.toBeInTheDocument();
  });
});

describe("Registry", () => {
  it("leads with the number of transactions the client signs", async () => {
    render(<RegistryPage />);
    expect(await screen.findByText("Signed by the client")).toBeInTheDocument();
    expect(screen.getByText("Transactions end to end")).toBeInTheDocument();
  });

  it("states plainly that the registry was not surveyed without an RPC", async () => {
    render(<RegistryPage />);
    expect(await screen.findByText(/registry was not surveyed/i)).toBeInTheDocument();
  });
});

describe("Status", () => {
  it("renders the verdict, the exit code and every gate", async () => {
    const status = readArtifact<{
      outcome: string;
      exit_code: number;
      checks: { name: string }[];
      skipped: string[];
    }>("status.json");

    render(<StatusPage />);
    expect(await screen.findByText(status.outcome)).toBeInTheDocument();
    expect(screen.getByText(`exit code ${status.exit_code}`)).toBeInTheDocument();

    for (const check of status.checks) {
      expect(screen.getByRole("heading", { name: check.name })).toBeInTheDocument();
    }
  });

  it("names the gates --fast skipped rather than omitting them", async () => {
    const status = readArtifact<{ fast: boolean; skipped: string[] }>("status.json");
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Gates" });

    if (status.fast) {
      expect(screen.getByText(/Not run\./)).toBeInTheDocument();
      for (const gate of status.skipped) {
        expect(screen.getByText(textFrom(gate))).toBeInTheDocument();
      }
    }
  });
});

describe("Methods states no figure it has not loaded", () => {
  // The page argued "a floor a UI could get wrong is not a floor" while
  // restating all four floors as literals directly beneath that sentence, and
  // fell back to "~31h" / "62.2h" / 20 / 3 / 60 / 24 whenever warden.json was
  // absent — which, since the error notice did not suppress the sections below
  // it, was permanently.
  it("invents nothing when the artifact is missing", async () => {
    serveArtifacts({ missing: ["warden.json"] });
    render(<MethodsPage />);

    await screen.findByRole("alert");

    for (const literal of [/~?31h/, /62\.2h/, /\b20 usable/, /\b24h per window/,
                           /\b168h before/, /\b30 observations/]) {
      expect(screen.queryByText(literal)).not.toBeInTheDocument();
    }
    expect(
      screen.getByRole("heading", { name: /quote window is shorter than the tape/ }),
    ).toBeInTheDocument();
  });

  it("reads the floors rather than restating them", async () => {
    const warden = readArtifact<AgentArtifact>("warden.json");
    serveArtifacts({
      overrides: {
        "warden.json": {
          ...warden,
          floors: { ...warden.floors, min_windows: 999, min_observations: 777 },
        },
      },
    });
    render(<MethodsPage />);

    // If these were literals the page would still read "20" and "30".
    expect(await screen.findByText(/999 usable sub-windows/)).toBeInTheDocument();
    expect(screen.getByText(/777 observations before a verdict/)).toBeInTheDocument();
    expect(screen.queryByText(/20 usable sub-windows/)).not.toBeInTheDocument();
  });
});

describe("Overview never shows a bare region", () => {
  it("keeps the skeletons up until the cards are ready to replace them", async () => {
    const { container } = render(<OverviewPage />);

    // The invariant: at no observed moment is the page done loading while
    // having nothing to show. Gating on index alone broke exactly this.
    await waitFor(() =>
      expect(container.querySelector("[aria-busy='true']")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("heading", { name: "Warden" })).toBeInTheDocument();
  });
});
