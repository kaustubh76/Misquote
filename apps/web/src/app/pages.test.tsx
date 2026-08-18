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
import VenuePage from "./venue/page";
import VettingPage from "./vetting/page";
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

  it("declares which tape it is, matching the artifact rather than a literal", async () => {
    // This asserted "Synthetic tape" outright and went red the moment the
    // artifacts were regenerated against real chain history — failing for the
    // wrong reason, and pinning the site to one of two states the banner is
    // built to distinguish. What must hold is that the banner agrees with
    // `index.source`, whichever it says.
    const index = readArtifact<IndexArtifact>("index.json");
    render(<OverviewPage />);

    const expected =
      index.source === "chain" ? /Indexed chain history/ : /Synthetic tape — not chain data/;
    const forbidden =
      index.source === "chain" ? /Synthetic tape — not chain data/ : /Indexed chain history/;

    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(screen.queryByText(forbidden)).not.toBeInTheDocument();
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

describe("Overview leads with the comparison", () => {
  it("puts every loaded agent on one scale, above the cards", async () => {
    // The page was a heading, a paragraph, a link and three stacked cards, so
    // "which of these works" took three screens and a memory for numbers.
    const index = readArtifact<IndexArtifact>("index.json");
    render(<OverviewPage />);
    await screen.findByRole("heading", { name: index.agents[0]!.name });

    const caption = screen.getByText(/longest bar is the largest/);
    const panel = caption.closest("div")!;
    for (const agent of index.agents) {
      expect(within(panel).getByRole("link", { name: agent.name })).toHaveAttribute(
        "href",
        `/agent/${agent.slug}`,
      );
    }
  });

  it("scales every agent against the same worst loss, not against itself", async () => {
    // Per-row scaling would draw a $0.68 loss and a $186.74 loss the same
    // length — the mistake `GateHistogram` documents at length.
    const warden = readArtifact<AgentArtifact>("warden.json");
    const grid = readArtifact<AgentArtifact>("grid.json");
    const sentinel = readArtifact<AgentArtifact>("sentinel.json");
    const index = readArtifact<IndexArtifact>("index.json");
    render(<OverviewPage />);
    await screen.findByText(/longest bar is the largest/);

    // Scoped to the comparison panel. An unscoped `li div > div` also matches
    // every CostBars bar inside the three cards below, whose widths differ
    // anyway — so the assertion passed with all three comparison bars pinned to
    // 100%, which a mutation run caught.
    const panel = (await screen.findByText(/longest bar is the largest/)).closest(
      "div",
    )!;
    const bars = [...panel.querySelectorAll<HTMLElement>("li div > div")].map((el) =>
      parseFloat(el.style.width),
    );
    expect(bars).toHaveLength(3);

    // Every bar against the same denominator, checked against every artifact
    // rather than against two of them. Naming Grid as the shortest was an
    // assumption about the committed numbers, not about the component: it held
    // until a regenerated tape made Sentinel the smallest, and then failed for
    // a reason that had nothing to do with scaling.
    // Element-wise, in the order the index lists the agents — so this pins which
    // bar belongs to which agent as well as how long it is. Sorting both sides
    // first would pass on a component that drew the right three lengths against
    // the wrong three names.
    const bySlug: Record<string, AgentArtifact> = { warden, grid, sentinel };
    const nets = index.agents.map((a) => Math.abs(bySlug[a.slug]!.replay.net_quote));
    const worst = Math.max(...nets);

    expect(Math.max(...bars)).toBe(100);

    nets.forEach((net, i) => {
      const share = (net / worst) * 100;
      if (share >= 1) {
        expect(bars[i]!).toBeCloseTo(share, 1);
      } else {
        // A rounding error against the worst still gets a visible mark rather
        // than vanishing: Grid's 0.68 against Warden's 186.74 is 0.36% of the
        // scale, which would read as "lost nothing" at its true width. Floored,
        // and the floor is small enough that it cannot be mistaken for a real
        // comparison — but it is never zero, which would be a different claim.
        expect(bars[i]!).toBeGreaterThan(share);
        expect(bars[i]!).toBeLessThan(1);
      }
    });
  });

  it("calls in-range against the floor the artifact publishes", async () => {
    const warden = readArtifact<AgentArtifact>("warden.json");
    render(<OverviewPage />);
    const caption = await screen.findByText(/longest bar is the largest/);

    // Never typed: the floor is one of the five `/methods` publishes.
    expect(caption.textContent).toContain(`${Math.round(100 * warden.floors.in_range_floor)}%`);
  });

  it("omits an agent whose artifact failed rather than drawing it as zero", async () => {
    // A zero bar reads as an agent that lost nothing.
    serveArtifacts({ missing: ["grid.json"] });
    render(<OverviewPage />);
    const caption = await screen.findByText(/longest bar is the largest/);
    const panel = caption.closest("div")!;

    expect(within(panel).queryByRole("link", { name: "Grid" })).not.toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Warden" })).toBeInTheDocument();
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

    const label = warden.estimators.kappa_label;
    if (warden.estimators.kappa_is_fallback && label) {
      expect(screen.getByText(/κ was not fitted on this run/)).toBeInTheDocument();
      expect(screen.getByText(textFrom(label))).toBeInTheDocument();
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

  it("says what each verdict's n counts, where the artifact proves it", async () => {
    // The two verdicts sit side by side with n = 44,802 and n = 60. They count
    // different populations — decisions against window returns — and with a
    // bare "n =" on each the smaller reads as the weaker evidence, when it is
    // the one built from the quote this page exists to defend.
    const warden = readArtifact<AgentArtifact>("warden.json");
    render(<AgentDetail slug="warden" />);
    await screen.findByRole("heading", { name: "Warden" });

    // Matched on the n-line itself, not on the bare unit: the section intro
    // also names both populations, so `getByText(/window returns/)` finds two
    // elements and a laxer `getAllByText` would pass on the intro alone —
    // green while each card still said only "n = 60".
    if (warden.verdicts.in_range.n === warden.replay.samples) {
      expect(
        screen.getByText(new RegExp(`n = ${warden.replay.samples.toLocaleString("en-US")} replay decisions`)),
      ).toBeInTheDocument();
    }
    if (warden.verdicts.profitable.n === warden.quote_detail?.samples) {
      expect(
        screen.getByText(new RegExp(`n = ${warden.quote_detail.samples} window returns`)),
      ).toBeInTheDocument();
    }
  });

  it("keeps the replay and the journal apart, with a scale on each", async () => {
    // One heading over two cards from two different runs — 44,802 replayed
    // decisions and a live loop's 175 — read as one account, so the gate
    // histogram looked like an explanation of the 44,802.
    const warden = readArtifact<AgentArtifact>("warden.json");
    render(<AgentDetail slug="warden" />);
    await screen.findByRole("heading", { name: "Why it held" });

    expect(
      screen.getByRole("heading", { name: /What it did, and what it would have done/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/of tape/)).toBeInTheDocument();
    expect(screen.getByText(/journalled/)).toBeInTheDocument();

    // The histogram's denominator is the journal's decision count, never the
    // replay's — the two differ by three orders of magnitude.
    const gates = Object.values(warden.activity.held_by_gate);
    if (gates.length > 0 && warden.activity.decisions > 0) {
      expect(
        screen.getAllByText(new RegExp(`of ${warden.activity.decisions}\\b`)).length,
      ).toBeGreaterThan(0);
    }
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
    // The engine's own refusal sentence, verbatim and prominent. The second
    // assertion used to match a phrase in the surrounding prose, which pinned
    // my wording rather than the claim — so shortening the paragraph failed a
    // test about the refusal. What must hold is that a refusal is presented as
    // a result: rendered, and not as an error.
    expect(await screen.findByText(d.overall.label)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
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

  it("does not put a green tick on a task the agent lost", async () => {
    // The tone was `separated ? "pass" : "none"` — green whenever the bands
    // cleared each other, in either direction. So the Protect task rendered
    // "✓ −1.77pp": the glyph said pass and the number said loss.
    //
    // `Pill` carries its verdict as shape, glyph *and* colour precisely so the
    // meaning survives without colour. Both non-colour channels were wrong
    // here, which is worse for a colourblind reader than colour alone.
    const d = readArtifact<AdvantageArtifact>("advantage.json");
    render(<AdvantagePage />);

    for (const task of d.tasks.filter((t) => t.quotable && t.separated)) {
      const heading = await screen.findByRole("heading", { name: task.task });
      const card = heading.closest("article")!;
      // The pill, not the sentence below it — both carry the same number, and
      // `getByText` on the figure alone matches two elements. `inline-flex` is
      // `Pill`'s own class and nothing else in the card uses it.
      const pill = card.querySelector("span.inline-flex")!;

      if (task.delta_pp < 0) {
        expect(pill.textContent).toContain("✕");
        expect(pill.className).toContain("text-bad");
      } else {
        expect(pill.textContent).toContain("✓");
        expect(pill.className).toContain("text-good");
      }
    }
  });

  it("leaves an indistinguishable task neutral rather than calling it", async () => {
    // Overlapping bands mean the sample cannot separate the two. Neither a tick
    // nor a cross is honest there, and the artifact publishes the fact.
    const d = readArtifact<AdvantageArtifact>("advantage.json");
    render(<AdvantagePage />);

    for (const task of d.tasks.filter((t) => t.quotable && !t.separated)) {
      const heading = await screen.findByRole("heading", { name: task.task });
      const card = heading.closest("article")!;
      const pill = card.querySelector("span.inline-flex")!;
      expect(pill.textContent).toContain("—");
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

  it("renders every floor the emitter published, and counts them", async () => {
    // The heading said "The four floors" and so did this test, while `floors`
    // carried five keys — `in_range_floor`, which decides the in-range verdict
    // on every card. Both the page and the assertion hardcoded the same wrong
    // count, on the section whose own argument is that a floor a UI could get
    // wrong is not a floor. Both now count what the artifact contains.
    const warden = readArtifact<AgentArtifact>("warden.json");
    const names = Object.keys(warden.floors);
    render(<MethodsPage />);

    await screen.findByRole("heading", { name: `The ${names.length} floors` });

    // Every floor gets a card carrying its own name and value — so a sixth
    // added to the emitter fails here rather than being silently uncounted.
    for (const name of names) {
      const value = warden.floors[name as keyof typeof warden.floors];
      expect(screen.getByText(`${name} = ${value}`)).toBeInTheDocument();
    }
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

describe("Registry: the escrow claims only what was recorded", () => {
  interface Reg {
    hire_flow: { escrow: { available: boolean; evidence?: string[] } };
    identity: { surveyed: boolean };
  }

  it("shows the recorded findings instead of a verdict nobody computed", async () => {
    // This rendered a green "Verified" pill beside "a chain check confirmed it"
    // while the same artifact says `source: offline` and "no registry read was
    // attempted". `available` is a dict lookup, not a read.
    const reg = readArtifact<Reg>("registry.json");
    render(<RegistryPage />);
    await screen.findByRole("heading", { name: "The escrow contract" });

    expect(screen.queryByText("Verified")).not.toBeInTheDocument();

    // One item per recorded finding. Matched by count plus a tail fragment
    // rather than by whole string: a caveat renders its "NOT VERIFIED" prefix
    // in its own <strong>, so the line is two nodes and a full-text match on it
    // would silently never fire.
    const items = [...document.querySelectorAll("li")].map((li) => li.textContent ?? "");
    for (const finding of reg.hire_flow.escrow.evidence ?? []) {
      const tail = finding.slice(-40);
      expect(items.some((text) => text.includes(tail))).toBe(true);
    }
  });

  it("carries the NOT VERIFIED clause, which is the point of publishing the list", async () => {
    // `JOB_ESCROW_EVIDENCE`'s own comment: the gap between "a live escrow that
    // settles in the token we already use" and "we have exercised ERC-8183's
    // job interface here" is the slippage this project exists to catch. That
    // sentence had no surface at all while the page showed a green tick.
    const reg = readArtifact<Reg>("registry.json");
    const caveats = (reg.hire_flow.escrow.evidence ?? []).filter((e) =>
      /^(NOT VERIFIED|SECURITY|NO TESTNET)\b/.test(e),
    );
    render(<RegistryPage />);
    await screen.findByRole("heading", { name: "The escrow contract" });

    expect(caveats.length).toBeGreaterThan(0);
    for (const caveat of caveats) {
      const label = /^(NOT VERIFIED|SECURITY|NO TESTNET)/.exec(caveat)?.[1] ?? "";
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
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

describe("Vetting: the addresses the signer is pointed at", () => {
  interface Addrs {
    surveyed: boolean;
    verdict?: string;
    checks?: { name: string; status: string }[];
  }

  it("renders every recorded check, through the same renderer as the pools", async () => {
    // Pools and addresses are the same question — named checks, chain
    // readings, a verdict — asked about two subjects. `CheckList` being
    // shareable is the argument that they really are the same shape.
    const a = readArtifact<Addrs>("addresses.json");
    render(<VettingPage />);

    const heading = await screen.findByRole("heading", {
      name: /addresses the signer is pointed at/i,
    });
    const section = heading.closest("[data-heading-scope]") as HTMLElement;

    if (!a.surveyed) {
      expect(within(section).getByText(/were not verified/)).toBeInTheDocument();
      return;
    }
    for (const check of a.checks ?? []) {
      expect(within(section).getByRole("heading", { name: check.name })).toBeInTheDocument();
    }
  });

  it("refuses rather than showing zero when nothing was recorded", async () => {
    // `verify_addresses.py` reaches for public BSC endpoints rather than a
    // configured key, so "no reading was taken" is routine here. An address
    // nobody checked and an address checked clean must not render alike.
    serveArtifacts({
      overrides: {
        "addresses.json": {
          chain_id: 56,
          surveyed: false,
          reason: "no address verification has been recorded",
          checks: [],
        },
      },
    });
    render(<VettingPage />);

    const heading = await screen.findByRole("heading", {
      name: /addresses the signer is pointed at/i,
    });
    const section = heading.closest("[data-heading-scope]") as HTMLElement;

    expect(within(section).getByText(/were not verified/)).toBeInTheDocument();
    expect(within(section).getByText(/no address verification has been recorded/)).toBeInTheDocument();
    // A refusal, not an error. Nothing broke.
    expect(within(section).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("survives vetting.json being unsurveyed, which used to hide it entirely", async () => {
    // The address <Section> was nested inside `{d?.surveyed && (`. With no pool
    // badged — a routine state, `make vet` needs a chain — the second subject
    // disappeared with its own artifact present and clean, and nothing said a
    // second subject existed. The existing "nothing has been badged" test
    // asserted the pool refusal and never looked for it.
    serveArtifacts({
      overrides: {
        "vetting.json": {
          surveyed: false,
          reason: "no badges on disk",
          chain_id: 56,
          badge_dir: "vetting/badges",
          pools: [],
          summary: { pools: 0, badged: 0 },
        },
      },
    });
    render(<VettingPage />);

    const heading = await screen.findByRole("heading", {
      name: /addresses the signer is pointed at/i,
    });
    const section = heading.closest("[data-heading-scope]") as HTMLElement;
    const a = readArtifact<Addrs>("addresses.json");

    if (a.surveyed) {
      for (const check of a.checks ?? []) {
        expect(within(section).getByRole("heading", { name: check.name })).toBeInTheDocument();
      }
    }
  });

  it("counts every subject on the page, not just the pools", async () => {
    // The rollup read `vetting.json` alone — "18 checks" above a page showing
    // 29 — and `worst verdict` never looked at the addresses, so an address
    // FAIL would still have shown PASS at the top.
    const v = readArtifact<{ surveyed: boolean; summary: { checks?: number } }>("vetting.json");
    const a = readArtifact<Addrs & { summary?: { checked: number } }>("addresses.json");
    render(<VettingPage />);
    await screen.findByRole("heading", { name: /addresses the signer is pointed at/i });

    const expected = (v.surveyed ? (v.summary.checks ?? 0) : 0) + (a.surveyed ? (a.summary?.checked ?? 0) : 0);
    expect(screen.getByText(new RegExp(`${expected} checks across`))).toBeInTheDocument();
  });

  it("survives the artifact being absent entirely", async () => {
    serveArtifacts({ missing: ["addresses.json"] });
    render(<VettingPage />);

    const heading = await screen.findByRole("heading", {
      name: /addresses the signer is pointed at/i,
    });
    expect(
      within(heading.closest("[data-heading-scope]") as HTMLElement).getByText(
        /has not been generated/,
      ),
    ).toBeInTheDocument();
  });
});

describe("Vetting", () => {
  it("renders a section per pool with its checks", async () => {
    const d = readArtifact<{ pools: { label: string; checks?: { name: string }[] }[] }>(
      "vetting.json",
    );
    render(<VettingPage />);

    for (const pool of d.pools) {
      expect(await screen.findByRole("heading", { name: pool.label })).toBeInTheDocument();
    }
    // Scoped to one pool: every pool runs the same nine checks, so the names
    // are deliberately not unique across the page.
    const first = screen
      .getByRole("heading", { name: d.pools[0]!.label })
      .closest("[data-heading-scope]") as HTMLElement;
    for (const check of d.pools[0]?.checks ?? []) {
      expect(within(first).getByRole("heading", { name: check.name })).toBeInTheDocument();
    }
  });

  it("treats an unknown check as a refusal, not a failure", async () => {
    // badge.py turns a read it could not make into UNKNOWN rather than a
    // default, and counts it as blocking. So it is the machine declining to
    // say — a Refusal. ErrorNotice sets role="alert"; Refusal does not, and
    // that single difference is the whole claim.
    const d = readArtifact<Record<string, unknown>>("vetting.json");
    const pools = (d.pools as Record<string, unknown>[]).map((p, i) =>
      i === 0
        ? {
            ...p,
            checks: [
              {
                name: "protocol fee read",
                status: "UNKNOWN",
                detail: "the node did not answer",
                provenance: "P-1",
              },
            ],
          }
        : p,
    );
    serveArtifacts({ overrides: { "vetting.json": { ...d, pools } } });
    render(<VettingPage />);

    expect(await screen.findByText("the node did not answer")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says so plainly when nothing has been badged", async () => {
    serveArtifacts({
      overrides: {
        "vetting.json": {
          surveyed: false,
          reason: "no pool has been badged — run `make vet`",
          chain_id: 56,
          badge_dir: "vetting/badges",
          pools: [],
          summary: { pools: 0, badged: 0 },
        },
      },
    });
    render(<VettingPage />);

    expect(await screen.findByText(/No pool has been badged/)).toBeInTheDocument();
    // A refusal, not an error: nothing broke, nothing was read.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("names the artifact when the fetch fails", async () => {
    serveArtifacts({ missing: ["vetting.json"] });
    render(<VettingPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/vetting\.json/);
  });
});

describe("Venue: the divergences, not the pool label", () => {
  interface Venue {
    divergences: { what: string; costs: string; provenance: string }[];
    shared_math: { cases: number; pins: { name: string; commit: string }[] };
    pools: { label: string; fee_protocol: number }[];
    uniswap_only_tier: number;
  }

  it("renders every divergence the artifact carries", async () => {
    // The page exists because these lived only in Python docstrings. If the
    // emitter grows a seventh, the page must show it — a fixed count here
    // would let one go missing silently, which is the failure the artifact
    // contract is built around.
    const venue = readArtifact<Venue>("venue.json");
    render(<VenuePage />);
    await screen.findByRole("heading", { name: "Where it is not" });

    for (const row of venue.divergences) {
      expect(screen.getByText(row.what)).toBeInTheDocument();
    }
  });

  it("states what each one costs, in full", async () => {
    // The amount is the point. A divergence rendered without its cost is a
    // trivia list about a fork.
    const venue = readArtifact<Venue>("venue.json");
    render(<VenuePage />);
    await screen.findByRole("heading", { name: "Where it is not" });

    for (const row of venue.divergences) {
      expect(screen.getByText(row.costs)).toBeInTheDocument();
    }
  });

  it("turns the P- and V- provenance into links to the assumption sheet", async () => {
    // `WithCitations` reads the ids out of the artifact string, so the same
    // text stays byte-identical in the JSON and on the page.
    render(<VenuePage />);
    await screen.findByRole("heading", { name: "Where it is not" });

    const cited = screen.getAllByRole("link", { name: /^P-1$/ });
    expect(cited.length).toBeGreaterThan(0);
    expect(cited[0]).toHaveAttribute("href", "/assumptions#P-1");
  });

  it("leads with the half that is shared, not the half that differs", async () => {
    // Order is the argument: the cores are the same source, which is what makes
    // a differential corpus meaningful rather than circular. Divergences first
    // would read as grievances against a fork.
    render(<VenuePage />);
    // Await a *section* heading, not any heading: the h1 renders before the
    // artifact loads, so `findAllByRole` resolves on it alone and the outline
    // this asserts on does not exist yet.
    await screen.findByRole("heading", { name: "Where it is not" });
    const titles = screen.getAllByRole("heading").map((h) => h.textContent);
    const shared = titles.findIndex((x) => x === "The math is Uniswap's");
    const differs = titles.findIndex((x) => x === "Where it is not");

    expect(shared).toBeGreaterThanOrEqual(0);
    expect(shared).toBeLessThan(differs);
  });

  it("names the missing fee tier as an absence beside the ones that exist", async () => {
    const venue = readArtifact<Venue>("venue.json");
    render(<VenuePage />);
    await screen.findByRole("heading", { name: "The pools we actually read" });

    expect(screen.getByText(`${venue.uniswap_only_tier}\u219260`)).toBeInTheDocument();
  });
});

describe("Overview routes the two integrations", () => {
  interface Status {
    checks: { name: string; status: string; detail: string }[];
  }
  interface Venue {
    venue: { name: string };
    divergences: unknown[];
  }

  it("counts the divergences from the artifact, not from a numeral", async () => {
    const venue = readArtifact<Venue>("venue.json");
    render(<OverviewPage />);
    const card = await screen.findByRole("link", { name: /The venue/ });

    expect(card).toHaveAttribute("href", "/venue");
    expect(card.textContent).toContain(venue.venue.name);
    expect(card.textContent).toContain(`${venue.divergences.length} places`);
  });

  it("shows the deliverable's real verdict rather than advertising it", async () => {
    // The gate is amber and the first screen says so. A track card that only
    // advertised would be the thing this project exists to argue against, and
    // the status string is `status.json`'s own — so this cannot read green
    // while the checklist reads amber.
    const status = readArtifact<Status>("status.json");
    const gate = status.checks.find((c) => c.name === "agent advantage report")!;
    render(<OverviewPage />);
    const card = await screen.findByRole("link", { name: /The track/ });

    expect(card).toHaveAttribute("href", "/registry");
    expect(within(card).getByText(gate.status)).toBeInTheDocument();
    expect(card.textContent).toContain(gate.detail);
  });

  it("finds the gate by name, so inserting a check above it changes nothing", async () => {
    // `go_no_go.py` orders its checks and that order is not a contract. A
    // positional read would start reporting a different gate's verdict the day
    // one is inserted, and it would look right.
    const status = readArtifact<Status>("status.json");
    const gate = status.checks.find((c) => c.name === "agent advantage report")!;
    serveArtifacts({
      overrides: {
        "status.json": {
          ...status,
          checks: [{ name: "a new gate", status: "PASS", detail: "inserted first" }, ...status.checks],
        },
      },
    });
    render(<OverviewPage />);
    const card = await screen.findByRole("link", { name: /The track/ });

    // On `detail`, not on `status`. Several gates read UNVERIFIED, so asserting
    // the status alone passed against a positional read that had shifted onto a
    // different check — the mutation ran green and the weakness was the test's.
    expect(card.textContent).toContain(gate.detail);
    expect(card.textContent).not.toContain("inserted first");
  });

  it("draws no cards at all when neither artifact is there", async () => {
    // Two empty cards would claim two integrations exist and say nothing about
    // either — worse than the silence it replaces.
    serveArtifacts({ missing: ["venue.json", "status.json"] });
    render(<OverviewPage />);
    await screen.findByRole("heading", { name: /Advertised, and not built/ });

    expect(screen.queryByRole("link", { name: /The venue/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /The track/ })).toBeNull();
  });
});

describe("Registry leads with the deliverable, and stops hiding four fields", () => {
  interface Status {
    checks: { name: string; status: string; detail: string }[];
  }
  interface Reg {
    aacp: { available: boolean; chain_id: number; reason?: string };
    hire_flow: { steps: { call: string; contract: string }[] };
    build: { source?: string };
  }

  it("puts the judged deliverable above the hire flow", async () => {
    // A judge arriving here was met with a six-transaction lifecycle and had to
    // infer that the thing they came to assess lived on a different page.
    render(<RegistryPage />);
    await screen.findByRole("heading", { name: "The judged deliverable" });

    const titles = screen.getAllByRole("heading").map((h) => h.textContent);
    expect(titles.indexOf("The judged deliverable")).toBeLessThan(
      titles.indexOf("Hiring an agent, end to end"),
    );
  });

  it("reads the gate's verdict rather than forming its own", async () => {
    const status = readArtifact<Status>("status.json");
    const gate = status.checks.find((c) => c.name === "agent advantage report")!;
    render(<RegistryPage />);
    await screen.findByRole("heading", { name: "The judged deliverable" });

    expect(screen.getByText(gate.status)).toBeInTheDocument();
    expect(screen.getByText(gate.detail)).toBeInTheDocument();
  });

  it("shows what the artifact was built from", async () => {
    // The page removed a green "Verified" pill *citing* `source: offline` and
    // then never showed it, so the reader had to take the removal on trust.
    const reg = readArtifact<Reg>("registry.json");
    render(<RegistryPage />);
    await screen.findByRole("heading", { name: "The judged deliverable" });

    expect(screen.getByText(new RegExp(reg.build.source!))).toBeInTheDocument();
  });

  it("names the chain the TermiX table belongs to", async () => {
    const reg = readArtifact<Reg>("registry.json");
    render(<RegistryPage />);
    const heading = await screen.findByRole("heading", { name: "TermiX AACP" });

    // Scoped to the section. "chain 56" also appears under the escrow, so an
    // unscoped match found two and would have passed on the wrong one.
    const section = heading.closest("section")!;
    expect(
      within(section).getByText(new RegExp(`chain ${reg.aacp.chain_id}`)),
    ).toBeInTheDocument();
  });

  it("says so when no AACP table was read, instead of vanishing", async () => {
    // The section was gated on `available`, so a failed lookup took the
    // recorded reason with it — while the escrow section three above renders
    // its reason as a refusal.
    const reg = readArtifact<Reg>("registry.json");
    serveArtifacts({
      overrides: {
        "registry.json": {
          ...reg,
          aacp: { available: false, reason: "no deployment for chain 97" },
        },
      },
    });
    render(<RegistryPage />);
    await screen.findByRole("heading", { name: "TermiX AACP" });

    expect(screen.getByText(/no deployment for chain 97/)).toBeInTheDocument();
  });

  it("names the contract each call goes to", async () => {
    // `contract` was emitted, declared on the interface, and never read — while
    // a bare "8183" badge marked five rows and left the sixth explaining itself.
    const reg = readArtifact<Reg>("registry.json");
    render(<RegistryPage />);
    await screen.findByRole("heading", { name: "Hiring an agent, end to end" });

    const erc20 = reg.hire_flow.steps.find((s) => s.contract !== "escrow")!;
    expect(screen.getByText(new RegExp(erc20.contract, "i"))).toBeInTheDocument();
  });
});

describe("an artifact missing its estimator block renders rather than throwing", () => {
  it("shows an em dash per parameter, not a blank page", async () => {
    // `tearsheet/generate.py` takes `estimators: dict | None = None` and
    // serialises `dict(estimators or {})`, so an omitted argument writes `{}` —
    // and `tearsheet/__main__.py` already builds without it. Six call sites here
    // read the block straight off the JSON, against a type declaring eleven
    // non-optional fields.
    //
    // There is no boundary deep enough to make that a subtree failure: a throw
    // in render escapes to Next's root handler and replaces the document, nav
    // and all. So the fix is not to catch it, it is not to throw.
    const warden = readArtifact<AgentArtifact>("warden.json");
    serveArtifacts({ overrides: { "warden.json": { ...warden, estimators: {} } } });
    render(<AgentDetail slug="warden" />);

    const heading = await screen.findByRole("heading", {
      name: "The parameters behind the range",
    });
    const section = heading.closest("section")!;

    // Every parameter row present, and every one of them an em dash.
    expect(within(section).getAllByText("—").length).toBeGreaterThanOrEqual(5);
    expect(within(section).getByText(/κ swaps used/)).toBeInTheDocument();
  });
});
