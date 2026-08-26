import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readArtifact, serveArtifacts, textFrom } from "@/test/harness";
import type { AdvantageArtifact, AgentArtifact, IndexArtifact } from "@/lib/artifacts";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { money, signed } from "@/lib/format";

import AdvantagePage from "./advantage/page";
import AssumptionsPage from "./assumptions/page";
import MethodsPage from "./methods/page";
import OverviewPage from "./page";
import RegistryPage from "./registry/page";
import StatusPage from "./status/page";
import VenuePage from "./venue/page";
import { VenueView, type VenueArtifact } from "./venue/view";
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
    // Every agent whose return is *comparable*. Allocation agents supply to a
    // lending market and have neither an in-range fraction nor an LVR, so they
    // are excluded — and the page says which and why rather than leaving a
    // reader to notice four cards above three rows.
    const comparable = index.agents.filter((a) => a.slug !== "router");
    for (const agent of comparable) {
      expect(within(panel).getByRole("link", { name: agent.name })).toHaveAttribute(
        "href",
        `/agent/${agent.slug}`,
      );
    }
    const excluded = index.agents.filter((a) => a.slug === "router");
    for (const agent of excluded) {
      expect(within(panel).queryByRole("link", { name: agent.name })).toBeNull();
      expect(screen.getByText(new RegExp(`${agent.name}.*not on this table`, "s"))).toBeTruthy();
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
    // Allocation agents are not on this table and have no `replay.net_quote` to
    // scale — see the comparability note the page renders beneath it.
    const bySlug: Record<string, AgentArtifact> = { warden, grid, sentinel };
    const nets = index.agents
      .filter((a) => bySlug[a.slug])
      .map((a) => Math.abs(bySlug[a.slug]!.replay.net_quote));
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
    //
    // Filtered on the emitter's own verdict, not on `delta_pp < 0`. The sign of
    // the float is not the rule: `Comparison.verdict_line` says "loses to DIY"
    // only above `MATERIAL_PP`, and below it says "indistinguishable" instead.
    // The Route task lands at -0.01pp — negative, immaterial, and correctly
    // never described as a loss — so the arithmetic filter had this test
    // demanding a sentence the emitter is right not to write. Re-deriving the
    // materiality rule here would be a second implementation of it one
    // screen-inch from the one Python wrote, which is the thing this codebase
    // refuses to do in `Band.tsx`.
    const d = readArtifact<AdvantageArtifact>("advantage.json");
    const losing = d.tasks.filter((t) => t.quotable && t.verdict.includes("loses to"));
    expect(losing.length).toBeGreaterThan(0);
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
    hire_flow: {
      escrow: { available: boolean; address?: string; reason?: string; evidence?: string[] };
    };
    identity: { surveyed: boolean; agents?: { agent_id: number }[] };
  }

  const CAVEAT = /^(NOT VERIFIED|SECURITY|NO TESTNET)\b/;

  /**
   * Which branch runs is the artifact's decision, not this file's.
   *
   * Both of these tests asserted the shape of the *available* branch
   * unconditionally, and `0bac20b` removed the one escrow we had — its deployed
   * bytecode implements none of createJob/setProvider/setBudget/fund/submit/
   * complete/reject across 5,894 candidate signatures, so it is a real escrow
   * that is not this standard. The view took its refusal branch, correctly, and
   * the suite went red at a page that was doing exactly the right thing.
   *
   * A test that fails when its subject correctly changes state is testing the
   * run rather than the behaviour. The escrow has now been through both states
   * once, so both are asserted, and the artifact picks.
   */
  const escrow = readArtifact<Reg>("registry.json").hire_flow.escrow;

  it("shows the recorded findings instead of a verdict nobody computed", async () => {
    // This rendered a green "Verified" pill beside "a chain check confirmed it"
    // while the same artifact says `source: offline` and "no registry read was
    // attempted". `available` is a dict lookup, not a read.
    render(<RegistryPage />);
    await screen.findByRole("heading", { name: "The escrow contract" });

    // Neither branch, ever. The pill was removed for a stated reason and the
    // refusal branch must not be the door it comes back through.
    expect(screen.queryByText("Verified")).not.toBeInTheDocument();

    if (!escrow.available) {
      // Nothing was recorded, so nothing is counted. A "0 recorded findings"
      // line here would be the opposite claim to the one the artifact makes:
      // an absence of evidence, rendered as evidence of an absence.
      expect(screen.queryByText(/recorded findings/)).not.toBeInTheDocument();
      return;
    }

    // One item per recorded finding. Matched by count plus a tail fragment
    // rather than by whole string: a caveat renders its "NOT VERIFIED" prefix
    // in its own <strong>, so the line is two nodes and a full-text match on it
    // would silently never fire.
    const items = [...document.querySelectorAll("li")].map((li) => li.textContent ?? "");
    for (const finding of escrow.evidence ?? []) {
      const tail = finding.slice(-40);
      expect(items.some((text) => text.includes(tail))).toBe(true);
    }
  });

  it("carries the NOT VERIFIED clause, or the reason there is nothing to caveat", async () => {
    render(<RegistryPage />);
    await screen.findByRole("heading", { name: "The escrow contract" });

    if (!escrow.available) {
      // The refusal is the product working, and what makes it work is that the
      // emitter's own sentence reaches the reader instead of a house phrase.
      // `registry/erc8183.py::escrow_address` raises rather than returning a
      // plausible address — why it raises is the finding, and it names the
      // contract that was carried here and removed.
      expect(escrow.reason, "an unavailable escrow with no reason is a silent absence").toBeTruthy();
      expect(screen.getByText(escrow.reason as string)).toBeInTheDocument();
      expect(screen.getByText(/erc8183\.py/)).toBeInTheDocument();
      return;
    }

    // `JOB_ESCROW_EVIDENCE`'s own comment: the gap between "a live escrow that
    // settles in the token we already use" and "we have exercised ERC-8183's
    // job interface here" is the slippage this project exists to catch. That
    // sentence had no surface at all while the page showed a green tick.
    const caveats = (escrow.evidence ?? []).filter((e) => CAVEAT.test(e));

    expect(
      caveats.length,
      "an address published with no caveat against it is the green tick again",
    ).toBeGreaterThan(0);

    for (const caveat of caveats) {
      const label = CAVEAT.exec(caveat)?.[1] ?? "";
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });
});

describe("Registry", () => {
  interface Reg {
    identity: { surveyed: boolean; agents?: { agent_id: number }[] };
  }

  it("leads with the number of transactions the client signs", async () => {
    render(<RegistryPage />);
    expect(await screen.findByText("Signed by the client")).toBeInTheDocument();
    expect(screen.getByText("Transactions end to end")).toBeInTheDocument();
  });

  it("reports the registry survey as the artifact actually found it", async () => {
    // This asserted the refusal unconditionally — "the registry was not
    // surveyed" — which was true for as long as the survey was gated on a
    // `BSC_RPC_URL` it did not need. The reads are `eth_call`, every free
    // endpoint serves them, and the survey runs now. A test that pins a
    // limitation passes until the limitation is fixed and then fails for the
    // best possible reason, so it tracks the artifact instead.
    const reg = readArtifact<Reg>("registry.json");
    render(<RegistryPage />);
    await screen.findByRole("heading", { name: "ERC-8004 identity registry" });

    if (reg.identity.surveyed) {
      expect(await screen.findByText(/substantive agent cards/i)).toBeInTheDocument();
    } else {
      expect(await screen.findByText(/registry was not surveyed/i)).toBeInTheDocument();
    }
  });

  it("never quotes a third-party agent", async () => {
    // The one thing this surface may not do. Our agents are quoted because
    // their policies replay on real history; a registry listing cannot be, so
    // the card says so rather than borrowing a rating from somewhere.
    const reg = readArtifact<Reg>("registry.json");
    if (!reg.identity.surveyed || !(reg.identity.agents ?? []).length) return;

    render(<RegistryPage />);
    const notes = await screen.findAllByText(/cannot replay a policy we do not have/i);
    expect(notes.length).toBe((reg.identity.agents ?? []).length);
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

/**
 * Every check `/vetting` renders, counted the way the view counts them.
 *
 * These two tests built the total from `vetting.pools` plus `addresses.checks`
 * and stopped there, which is exactly the undercount the view had: the address
 * record nests a `venus` survey and one `erc8183` record per chain, and the
 * page draws all of them. The tests agreed with the bug because they
 * reimplemented it. Counting recursively is what makes them able to disagree.
 */
function renderedChecks(record: {
  surveyed?: boolean;
  checks?: { status: string }[];
  venus?: unknown;
  erc8183?: Record<string, unknown>;
}): { status: string }[] {
  if (!record?.surveyed) return [];
  const nested = record.venus as Parameters<typeof renderedChecks>[0] | undefined;
  return [
    ...(record.checks ?? []),
    ...(nested ? renderedChecks(nested) : []),
    ...Object.values(record.erc8183 ?? {}).flatMap((chain) =>
      renderedChecks(chain as Parameters<typeof renderedChecks>[0]),
    ),
  ];
}

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

    // Awaited, not asserted synchronously. The heading belongs to `vetting.json`
    // and the refusal to `addresses.json`, which are two fetches — so finding
    // the heading says nothing about whether the second has resolved, and the
    // skeleton is what renders until it does. This passed only because the
    // second fetch happened to win, and stopped when `vetting.json` grew from
    // two badged pools to three.
    expect(await within(section).findByText(/were not verified/)).toBeInTheDocument();
    expect(
      within(section).getByText(/no address verification has been recorded/),
    ).toBeInTheDocument();
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
    //
    // It then understated by the same mechanism one level deeper, and this test
    // agreed with it because it summed the same two `summary` blocks the view
    // did. The address record nests a `venus` survey and one `erc8183` record
    // per chain, all rendered — so the page said 38 above 78. Counted the way
    // the view counts now, which is what lets the two disagree.
    const v = readArtifact<{ surveyed: boolean; pools: { checks: { status: string }[] }[] }>(
      "vetting.json",
    );
    const a = readArtifact<Addrs>("addresses.json");
    render(<VettingPage />);
    await screen.findByRole("heading", { name: /addresses the signer is pointed at/i });

    const expected =
      (v.surveyed ? v.pools.flatMap((p) => p.checks).length : 0) + renderedChecks(a).length;
    expect(screen.getByText(new RegExp(`${expected} checks across`))).toBeInTheDocument();
  });

  it("survives the artifact being absent entirely", async () => {
    serveArtifacts({ missing: ["addresses.json"] });
    render(<VettingPage />);

    const heading = await screen.findByRole("heading", {
      name: /addresses the signer is pointed at/i,
    });
    // Awaited, like its sibling above and for the same reason: the heading
    // belongs to `vetting.json` and this refusal to `addresses.json`, so
    // finding the heading says nothing about whether the second fetch has
    // resolved. It passed only while that fetch happened to win the race.
    expect(
      await within(heading.closest("[data-heading-scope]") as HTMLElement).findByText(
        // Was `/has not been generated/`, which the page said about a file it
        // had merely not fetched yet. It now reports what it knows: the read
        // failed, and why.
        /could not be read/,
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

/**
 * The pool table and the badge run, which disagreed.
 *
 * `/venue` lists every pool this repository has verified — four of them, one on
 * chain 97 — under a link that read **"The nine checks each of them passed"**.
 * `/vetting` runs against one chain, so the chapel mirror has never been through
 * a single check, and the sentence overstated a quarter of its own table on the
 * page whose entire argument is that these details were read rather than
 * assumed.
 *
 * Both halves are asserted from the artifacts, so this holds whichever pools
 * exist and whichever have been badged.
 */
describe("Venue: what has been checked, and what has not", () => {
  interface Pools {
    pools: { label: string; address: string; chain_id: number }[];
  }
  interface Badges {
    chain_id: number;
    pools: { pool?: string; badged?: boolean }[];
  }

  const pools = readArtifact<Pools>("venue.json").pools;
  const badged = new Set(
    readArtifact<Badges>("vetting.json")
      .pools.filter((p) => p.badged && p.pool)
      .map((p) => (p.pool as string).toLowerCase()),
  );
  const covered = pools.filter((p) => badged.has(p.address.toLowerCase()));

  it("counts the checked pools rather than claiming all of them", async () => {
    // Both bounds. Zero would mean the join is broken and every row reads "not
    // checked"; all of them would mean the artifacts no longer disagree and
    // this test has stopped covering the case it was written for.
    expect(covered.length).toBeGreaterThan(0);
    expect(
      covered.length,
      "every listed pool is badged now — the overstatement is unreachable, retarget this",
    ).toBeLessThan(pools.length);

    render(<VenuePage />);
    await screen.findByRole("heading", { name: "The pools we actually read" });

    const link = screen.getByRole("link", { name: /through the nine checks/ });
    expect(link.textContent).toContain(`${covered.length} of ${pools.length}`);
    expect(link).toHaveAttribute("href", "/vetting");
  });

  it("marks the unchecked pool as unchecked, beside its constants", async () => {
    const unchecked = pools.filter((p) => !badged.has(p.address.toLowerCase()));
    render(<VenuePage />);
    await screen.findByRole("heading", { name: "The pools we actually read" });

    const rows = [...document.querySelectorAll("tr")].map((r) => r.textContent ?? "");
    for (const pool of unchecked) {
      const row = rows.find((t) => t.includes(pool.label));
      expect(row, `${pool.label} is not in the table at all`).toBeTruthy();
      expect(row).toContain("not checked");
    }
    for (const pool of covered) {
      expect(rows.find((t) => t.includes(pool.label))).toContain("nine checks passed");
    }
  });
});

/**
 * The width ladder, which existed for a while and reached no page.
 *
 * `pools.json` was emitted by `make pools`, covered by tests and served by
 * `GET /pools`, and nothing rendered it. That is the one failure mode this
 * repository is least entitled to: a measurement nobody can see is not a
 * benefit delivered, it is a benefit claimed.
 *
 * Everything here is asserted from the artifact, so it holds whichever pools
 * were measured and whichever widths cleared the floor.
 */
describe("Venue: which pool, and how wide", () => {
  interface Ladder {
    pools: {
      label: string;
      address: string;
      verdict: string;
      best_width_ticks: number | null;
      ladder: { width_ticks: number; sufficient: boolean; observations: number }[];
      demand: { swaps: number; fee_per_unit_liquidity: number; volume_quote: number };
    }[];
  }

  it("renders the engine's verdict verbatim, overlap clause and all", async () => {
    // Verbatim is the whole point. The load-bearing half of the sentence is the
    // clause saying the lead is *not separated at this sample size*, and a page
    // that recomputed a winner from the medians would drop exactly that and
    // publish the leaderboard this project is named against.
    const measured = readArtifact<Ladder>("pools.json");
    render(<VenuePage />);
    await screen.findByRole("heading", { name: "Which pool, and how wide" });

    for (const pool of measured.pools) {
      expect(screen.getByText(pool.verdict)).toBeInTheDocument();
    }
  });

  it("shows a row per width that cleared the floor, and none that did not", async () => {
    const measured = readArtifact<Ladder>("pools.json");
    render(<VenuePage />);
    await screen.findByRole("heading", { name: "Which pool, and how wide" });

    const rows = [...document.querySelectorAll("tr")].map((r) => r.textContent ?? "");
    for (const pool of measured.pools) {
      for (const band of pool.ladder) {
        const present = rows.some((t) => t.includes(`\u00b1${band.width_ticks} ticks`));
        if (band.sufficient) {
          expect(present, `+/-${band.width_ticks} cleared the floor and is not rendered`).toBe(
            true,
          );
        }
      }
    }
  });

  it("says a pool has no verdict rather than drawing it as a blank", async () => {
    // A pool below the evidence floor is the case that most needs saying out
    // loud: "we have no idea" and "it pays nothing" must not render the same,
    // and the second is what an empty row means to a reader.
    const measured = readArtifact<Ladder>("pools.json");
    const silent = measured.pools.filter((p) => !p.ladder.some((b) => b.sufficient));
    if (silent.length === 0) return;

    render(<VenuePage />);
    await screen.findByRole("heading", { name: "Which pool, and how wide" });

    const text = document.body.textContent ?? "";
    for (const pool of silent) {
      // `getAllByText`, not `getByText`: the pool table further up this page
      // lists the same label, and a singular query would fail on the ambiguity
      // rather than on the thing under test.
      expect(screen.getAllByText(pool.label).length).toBeGreaterThan(0);
    }
    expect(text).toContain("No width on the ladder cleared");
  });

  it("stays a complete page when the ladder was never measured", async () => {
    // `make artifacts` does not build `pools`, so a clean checkout has no
    // ladder at all. The section has to degrade into the command that would
    // produce it rather than vanishing or throwing.
    //
    // `VenueView` directly rather than `VenuePage`, and the difference is the
    // point: the page reads the artifact off disk at build time, so a fetch
    // stubbed as missing would still be handed the file this repository
    // happens to have. Only the view can be asked what it does without one.
    serveArtifacts({ missing: ["pools.json"] });
    render(<VenueView initial={readArtifact<VenueArtifact>("venue.json")} />);
    await screen.findByRole("heading", { name: "Which pool, and how wide" });

    expect(document.body.textContent ?? "").toContain("No width ladder has been measured");
    // The rest of the page is unaffected — this section is additive.
    expect(
      screen.getByRole("heading", { name: "The pools we actually read" }),
    ).toBeInTheDocument();
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
    build: { source?: string; git_sha?: string };
    identity: { surveyed: boolean; agents?: { agent_id: number }[] };
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
    // Scoped to the section, for the reason the TermiX test below gives. A bare
    // `getByText("PASS")` was unique only while the deliverable held the page's
    // only verdict pill; the section listing our own ERC-8004 registrations
    // carries one too, and an unscoped match then finds two and throws. Scoping
    // is also the stronger assertion — it says *this* gate reads PASS rather
    // than "the word PASS appears somewhere on the page".
    const status = readArtifact<Status>("status.json");
    const gate = status.checks.find((c) => c.name === "agent advantage report")!;
    render(<RegistryPage />);
    const heading = await screen.findByRole("heading", { name: "The judged deliverable" });
    const section = heading.closest("section")!;

    expect(within(section).getByText(gate.status)).toBeInTheDocument();
    expect(within(section).getByText(gate.detail)).toBeInTheDocument();
  });

  it("shows what the artifact was built from", async () => {
    // The page removed a green "Verified" pill *citing* `source: offline` and
    // then never showed it, so the reader had to take the removal on trust.
    //
    // Scoped to the build stamp, for the reason the TermiX test below gives.
    // `source` was "offline" when this was written and is "chain" now that the
    // registry is surveyed, and "chain" also appears in the third-party
    // listings ("card is on chain") — so the unscoped match found several and
    // would have passed on whichever came first.
    const reg = readArtifact<Reg>("registry.json");
    render(<RegistryPage />);
    await screen.findByRole("heading", { name: "The judged deliverable" });

    const stamp = screen
      .getByText(new RegExp(reg.build.git_sha!))
      .closest("p, div") as HTMLElement;
    expect(within(stamp).getByText(new RegExp(reg.build.source!))).toBeInTheDocument();
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

    // Awaited: the heading and the refusal come from the same fetch but not the
    // same paint, and this page grew a list of third-party agent cards between
    // them. A synchronous assertion here was passing on render timing.
    expect(await screen.findByText(/no deployment for chain 97/)).toBeInTheDocument();
  });

  it("refuses rather than showing an empty table when we have registered nothing", async () => {
    // The distinction /vetting's two 404s exist to preserve, applied here: a
    // checkout that never ran `make identity-register` and a run that found
    // nothing must not render alike. An empty grid would read as "we looked and
    // there are none", which is the opposite of what the artifact says.
    const reg = readArtifact<Reg>("registry.json");
    serveArtifacts({
      overrides: {
        "registry.json": {
          ...reg,
          ours: { surveyed: false, reason: "nobody has looked", chain_id: 97, agents: [], checks: [] },
        },
      },
    });
    render(<RegistryPage />);
    await screen.findByRole("heading", { name: /Our own agents/ });
    expect(await screen.findByText(/nobody has looked/)).toBeInTheDocument();
  });

  it("links both transactions for every agent of ours, not just the outcome", async () => {
    // The mint and the handover are separately checkable, and that is the whole
    // reason the two-transaction shape was chosen over putting the operator's
    // key on this machine. Rendering only the result would throw away the half
    // that lets a reader verify ownership without trusting this page.
    const reg = readArtifact<Reg>("registry.json");
    const agent = {
      agent: "warden",
      name: "Warden",
      agent_id: 1913,
      token_uri_bytes: 721,
      gas_used: 700000,
      register_tx: "0xaaaa000000000000000000000000000000000000000000000000000000000001",
      transfer_tx: "0xbbbb000000000000000000000000000000000000000000000000000000000002",
      register_url: "https://testnet.bscscan.com/tx/0xaaaa",
      transfer_url: "https://testnet.bscscan.com/tx/0xbbbb",
      agent_url: "https://testnet.bscscan.com/token/0xreg?a=1913",
    };
    serveArtifacts({
      overrides: {
        "registry.json": {
          ...reg,
          ours: {
            surveyed: true,
            chain_id: 97,
            verdict: "PASS",
            owner: "0x0c501EE1924bfb91a028DB4BcD68f4861B0Ff6eE",
            signer: "0xbF4ef75a443E00415Ee2E368caC089e0834930E6",
            explorer: "https://testnet.bscscan.com",
            agents: [agent],
            checks: [],
          },
        },
      },
    });
    render(<RegistryPage />);
    const heading = await screen.findByRole("heading", { name: /Our own agents/ });
    const section = heading.closest("section")!;

    expect(within(section).getByRole("link", { name: /register/ })).toHaveAttribute(
      "href",
      agent.register_url,
    );
    expect(within(section).getByRole("link", { name: /transfer/ })).toHaveAttribute(
      "href",
      agent.transfer_url,
    );
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

describe("Vetting distinguishes not-yet-read from not-generated", () => {
  it("does not claim a file is missing while it is still being fetched", async () => {
    // `addrs` is null until the fetch resolves, and null fell into the same
    // branch as a failed read — so the page asserted "addresses.json has not
    // been generated" about a file sitting beside it. That is the claim this
    // page exists to make impossible about an address, made about itself.
    render(<VettingPage />);

    expect(screen.queryByText(/has not been generated/)).toBeNull();

    await screen.findByRole("heading", { name: /The addresses the signer is pointed at/ });
    expect(screen.queryByText(/has not been generated/)).toBeNull();
  });

  it("still says so when the file genuinely cannot be read", async () => {
    // The refusal has to survive the fix, or this trades a false negative for
    // silence — which on this page is the worse of the two.
    serveArtifacts({ missing: ["addresses.json"] });
    render(<VettingPage />);

    expect(await screen.findByText(/addresses\.json could not be read/)).toBeInTheDocument();
    expect(
      screen.getByText(/an address nobody checked and an address checked clean/),
    ).toBeInTheDocument();
  });
});

describe("the agent page is rendered before JavaScript runs", () => {
  it("paints from the build-time artifact with no fetch resolved", () => {
    // `output: "export"` is justified by the site rendering with no process
    // alive. The exported HTML for this route was the nav and the word
    // "warden" — 397 characters, no figures — because every view fetches after
    // mount. The route already read this directory at build time for the slug
    // list and the tab title, and threw the contents away.
    const warden = readArtifact<AgentArtifact>("warden.json");
    // No `serveArtifacts()`: nothing may resolve, and the figures must be there
    // anyway. That is the whole claim.
    render(<AgentDetail slug="warden" initial={warden} />);

    expect(screen.getByRole("heading", { name: warden.agent })).toBeInTheDocument();
    expect(screen.queryByText(/Loading/)).toBeNull();
  });

  it("lets the client fetch win, so editing a JSON and reloading still works", async () => {
    // The route's own promise, written in `agent/[slug]/page.tsx`. A baked-in
    // value goes stale at the next edit, so the effect still runs and overwrites
    // it — the build is the first paint, the fetch is the truth.
    const warden = readArtifact<AgentArtifact>("warden.json");
    serveArtifacts({
      overrides: { "warden.json": { ...warden, agent: "Warden (from the fetch)" } },
    });
    render(<AgentDetail slug="warden" initial={warden} />);

    expect(screen.getByRole("heading", { name: warden.agent })).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Warden (from the fetch)" }),
    ).toBeInTheDocument();
  });

  it("still reaches the client error path when the build read found nothing", async () => {
    // A missing artifact must stay a page that says which command to run, not a
    // build that fails with a stack trace — so the server read returns undefined
    // and the client owns the failure, which is where the remedy text lives.
    serveArtifacts({ missing: ["warden.json"] });
    render(<AgentDetail slug="warden" initial={undefined} />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/make showcase-demo/)).toBeInTheDocument();
  });
});

describe("Status can be narrowed to what nobody checked", () => {
  interface Status {
    checks: { name: string; status: string }[];
  }

  it("counts each verdict from the checks, not from the summary block", async () => {
    // Two sets of the same numbers exist in the artifact — `summary` and the
    // checks themselves — and a filter whose label disagrees with the list
    // under it is worse than no filter.
    const status = readArtifact<Status>("status.json");
    const unverified = status.checks.filter((c) => c.status === "UNVERIFIED").length;
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Gates" });

    expect(screen.getByRole("radio", { name: `All ${status.checks.length}` })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: `Unverified ${unverified}` })).toBeInTheDocument();
  });

  it("narrows the list and says by how much", async () => {
    const user = userEvent.setup();
    const status = readArtifact<Status>("status.json");
    const unverified = status.checks.filter((c) => c.status === "UNVERIFIED");
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Gates" });

    await user.click(screen.getByRole("radio", { name: /^Unverified/ }));

    // The gates that remain are exactly the unverified ones.
    for (const check of unverified) {
      expect(screen.getByRole("heading", { name: check.name })).toBeInTheDocument();
    }
    for (const check of status.checks.filter((c) => c.status === "PASS")) {
      expect(screen.queryByRole("heading", { name: check.name })).toBeNull();
    }

    // Announced, because the cards it removed are below the fold.
    expect(screen.getByLabelText("Filter result")).toHaveTextContent(
      `${unverified.length} of ${status.checks.length} gates unverified.`,
    );
  });

  it("says so in words when a verdict has no gates", async () => {
    // A filter that empties the list and renders blank space reads as a broken
    // page — and on this page "no gate is failing" is a result worth stating.
    const user = userEvent.setup();
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Gates" });

    const failing = screen.queryByRole("radio", { name: /^Failing/ });
    if (failing) {
      await user.click(failing);
      expect(screen.getByText(/No gate is failing/)).toBeInTheDocument();
    } else {
      // No FAIL chip is offered when nothing failed — which is itself the
      // answer, and is why the chips are built from the checks present.
      expect(screen.getByRole("radio", { name: /^All/ })).toBeInTheDocument();
    }
  });
});

describe("Vetting offers a verdict filter only when there is a choice", () => {
  interface Vetting {
    pools: { checks: { name: string; status: string }[] }[];
  }
  interface Addrs {
    checks: { name: string; status: string }[];
  }

  it("states the result in a sentence when every check agrees", async () => {
    // On a clean run every check is a PASS, and a chip row reading
    // "All 29 · Pass 29" offers one button that does nothing. The count is the
    // useful part; the control is not.
    const vetting = readArtifact<Vetting>("vetting.json");
    const addrs = readArtifact<Addrs>("addresses.json");
    const all = [...vetting.pools.flatMap((p) => p.checks), ...renderedChecks(addrs)];
    const verdicts = new Set(all.map((c) => c.status));
    render(<VettingPage />);
    await screen.findByRole("heading", { name: /Due diligence/ });

    if (verdicts.size === 1) {
      expect(
        await screen.findByText(new RegExp(`Every one of the ${all.length} checks`)),
      ).toBeInTheDocument();
      expect(screen.queryByRole("radio", { name: /^All/ })).toBeNull();
    }
  });

  it("filters both subjects at once when verdicts differ", async () => {
    // Pools and addresses are the same question asked of two subjects, so one
    // control narrows both — a filter that silently applied to half the page
    // would be worse than none.
    const vetting = readArtifact<Vetting>("vetting.json");
    const addrs = readArtifact<Addrs>("addresses.json");
    const doctored = {
      ...vetting,
      pools: vetting.pools.map((p, i) =>
        i === 0 ? { ...p, checks: p.checks.map((c, j) => (j === 0 ? { ...c, status: "FAIL" } : c)) } : p,
      ),
    };
    serveArtifacts({ overrides: { "vetting.json": doctored } });
    const user = userEvent.setup();
    render(<VettingPage />);
    await screen.findByRole("heading", { name: /Due diligence/ });

    const total =
      doctored.pools.flatMap((p) => p.checks).length + renderedChecks(addrs).length;
    expect(await screen.findByRole("radio", { name: `All ${total}` })).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /^Fail/ }));
    expect(screen.getByLabelText("Check filter result")).toHaveTextContent(
      `1 of ${total} checks are FAIL.`,
    );
  });
});

/**
 * Two artifacts, one question, and whether a reader can tell they disagree.
 *
 * `advantage.json` and the agent cards both answer "did the agent beat doing it
 * yourself", from different runs. On the tree these tests were written against
 * the report is `source: "chain"` and the cards are `source: "synthetic"`, and
 * they disagree by as much as a sign — Sentinel loses by 38.17pp on one page and
 * wins by 0.72pp on the other, one click apart.
 *
 * Nothing here asserts which is right, and nothing asserts they agree: two runs
 * over different tape are *supposed* to be able to differ. What is asserted is
 * that neither page can state its answer without saying which tape it read and
 * what the other one said.
 */
describe("Two runs, one question", () => {
  const report = readArtifact<AdvantageArtifact>("advantage.json");
  const index = readArtifact<IndexArtifact>("index.json");

  /** The report's row for an agent, by the same rule `lib/counterpart` uses. */
  const taskFor = (name: string) =>
    report.tasks.find((t) => t.with_agent.toLowerCase().startsWith(name.toLowerCase()));

  const sourceLabel = (source: string) =>
    source === "chain" ? /Indexed chain history/ : /Synthetic tape — not chain data/;

  it("says which tape it read before it says what the tape showed", async () => {
    // The defect was position, not absence. `source` was on this page the whole
    // time — as a row in a provenance table 330 lines below the headline — so
    // an assertion that the word is *present* passes on the broken page and
    // proves nothing. Document order is the claim.
    const card = readArtifact<AgentArtifact>("sentinel.json");
    render(<AgentDetail slug="sentinel" />);

    const banner = await screen.findByText(sourceLabel(card.source));

    // Before *every* claim, not merely before the delta. Written the narrow way
    // first, and a mutation run walked straight through it: moving the banner
    // down past the quote section still left it above the advantage figure, so
    // the test went green on a page where the source had been pushed halfway
    // down again. The first heading is where the claims start.
    const headings = screen.getAllByRole("heading");
    expect(headings.length, "the card renders no headings — retarget this").toBeGreaterThan(1);
    expect(card.advantage, "sentinel.json publishes no advantage — retarget this").toBeTruthy();

    for (const claim of [
      headings[1]!,
      screen.getAllByText(signed(card.advantage!.delta_pp, 2, "pp"))[0]!,
    ]) {
      expect(
        banner.compareDocumentPosition(claim) & Node.DOCUMENT_POSITION_FOLLOWING,
        `"${claim.textContent}" is stated before the page says which tape it read`,
      ).toBeTruthy();
    }
  });

  it("carries the other run's answer, its figure, and a way to reach it", async () => {
    const task = taskFor("Sentinel");
    expect(task, "the report has no Sentinel task — retarget this test").toBeTruthy();

    render(<AgentDetail slug="sentinel" />);
    await screen.findByRole("heading", { name: "Sentinel" });

    // The figure is read from the report, not restated: change `advantage.json`
    // and this must change with it.
    expect(screen.getByText(signed(task!.delta_pp, 2, "pp"))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: `${task!.task} →` })).toHaveAttribute(
      "href",
      "/advantage",
    );
  });

  it("renders no cross-reference for an agent the report does not judge", async () => {
    // Grid appears in none of the report's rows, and the third row hires nobody
    // at all — its agent column is a paragraph about which pool to provide to.
    // So two of the six pairings resolve to nothing, and nothing must render as
    // nothing rather than as an empty box or a link to a page that would answer
    // a different question.
    expect(taskFor("Grid"), "the report now judges Grid — retarget this test").toBeUndefined();

    const card = readArtifact<AgentArtifact>("grid.json");
    render(<AgentDetail slug="grid" />);
    await screen.findByRole("heading", { name: "Grid" });

    expect(screen.getByText(sourceLabel(card.source))).toBeInTheDocument();
    expect(
      screen.queryAllByText((_, el) =>
        (el?.textContent ?? "").includes("The same task, replayed over"),
      ),
    ).toEqual([]);
    expect(document.querySelectorAll('a[href="/advantage"]')).toHaveLength(0);
  });

  it("links each task to the agent card that answers it, and only those", async () => {
    render(<AdvantagePage />);
    await screen.findByRole("heading", { name: /^The \d+ tasks$/ });

    for (const task of report.tasks) {
      const agent = index.agents.find((a) =>
        task.with_agent.toLowerCase().startsWith(a.name.toLowerCase()),
      );

      if (agent) {
        expect(screen.getByRole("link", { name: task.with_agent })).toHaveAttribute(
          "href",
          `/agent/${agent.slug}`,
        );
      } else {
        // Still named, just not linked. A slug guessed from the name would
        // resolve in dev and 404 on the static export, where only the slugs
        // `index.json` lists are built.
        expect(screen.queryByRole("link", { name: task.with_agent })).not.toBeInTheDocument();
        expect(screen.getAllByText(task.with_agent).length).toBeGreaterThan(0);
      }
    }
  });

  it("quotes each task on its own capital basis rather than a dash", async () => {
    // `capital_quote` at the report level stopped being a number when the tasks
    // stopped sharing a basis: the emitter writes the literal string "per task
    // — see tasks[].capital_quote" when they differ, and `money()` returns a
    // dash for anything that is not a number. All three cards on the page this
    // project is judged by read "on — of capital", while every figure they
    // needed was one level down in the same file.
    render(<AdvantagePage />);
    await screen.findByRole("heading", { name: /^The \d+ tasks$/ });

    const lines = [...document.querySelectorAll("p")].map((p) => p.textContent ?? "");
    expect(lines.some((t) => t.includes("of capital"))).toBe(true);
    expect(lines.filter((t) => t.includes("on — of capital"))).toEqual([]);

    for (const task of report.tasks) {
      if (!task.quotable) continue;
      const basis = task.capital_quote ?? report.capital_quote;
      expect(
        lines.some((t) => t.includes(`on ${money(basis, report.quote_symbol)} of capital`)),
        `${task.task} is not quoted on its own capital`,
      ).toBe(true);
    }
  });
});

/**
 * How current the readiness gates are, counted rather than asserted.
 *
 * `/status` is a recording of one run, and it rendered as a wall of verdicts
 * with nothing saying how old the recording was. On the tree this was written
 * against its gate read "agent advantage report: 0/3 tasks on chain data" —
 * recorded at `fa185b4` on 18 Aug, false since the chain run landed, sitting
 * under a heading whose entire subject is what has and has not been checked.
 *
 * The census is recomputed here from the directory rather than read back from
 * the component, so this fails if `censusArtifacts` starts looking in the wrong
 * place for a commit — which is the part with a real decision in it, since
 * `build.json` records its sha at the top level and everything else records it
 * under `build`.
 */
describe("Status says how current its gates are", () => {
  const dir = join(process.cwd(), "public", "artifacts");
  const files = readdirSync(dir).filter((n) => n.endsWith(".json")).sort();
  const EXEMPT = ["assumptions.json"];

  const shaOf = (name: string) => {
    const blob = JSON.parse(readFileSync(join(dir, name), "utf8"));
    const sha = blob?.build?.git_sha ?? blob?.git_sha;
    return typeof sha === "string" && sha.length > 0 ? sha : undefined;
  };

  const counted = files.filter((n) => !EXEMPT.includes(n));
  const unstamped = counted.filter((n) => !shaOf(n));

  it("counts the artifacts that record no commit, and names them", async () => {
    // Both halves. A census reporting zero unstamped artifacts would be the
    // more comfortable page and, on this tree, a false one — every file behind
    // `/`, `/advantage` and the three agent cards records nothing.
    expect(unstamped.length, "every artifact is stamped — this notice is now moot").toBeGreaterThan(
      0,
    );

    render(<StatusPage />);
    const notice = await screen.findByText(/How current this is/);
    // The whole notice, not the sentence. `parentElement` is the <p> the
    // heading sits in, and the list of unnamed artifacts is its sibling — so
    // scoping there asserted the counts against a string that could never have
    // contained the names.
    const text = notice.closest("div")?.textContent ?? "";

    expect(text).toContain(`${files.length} artifacts`);
    expect(text).toContain(`${unstamped.length} record no commit`);

    // Scoped to the notice. Unscoped, several of these filenames also appear in
    // the gate details below — "build.json is 2 engine commit(s) behind" — and
    // the assertion passed on a notice that listed nothing at all.
    for (const name of unstamped) {
      expect(text, `${name} is counted but not named`).toContain(name);
    }
  });

  it("names what it excluded and why, rather than quietly not counting it", async () => {
    render(<StatusPage />);
    await screen.findByText(/How current this is/);

    for (const name of EXEMPT.filter((n) => files.includes(n))) {
      const line = screen.getByText(/is not counted against that/);
      expect(line.textContent).toContain(name);
      expect(line.textContent).toMatch(/projection of docs/);
    }
  });

  it("reports the run's own commit, from the artifact", async () => {
    const status = readArtifact<{ build?: { git_sha?: string } }>("status.json");
    expect(status.build?.git_sha, "status.json records no commit — retarget this").toBeTruthy();

    render(<StatusPage />);
    const notice = await screen.findByText(/How current this is/);
    expect(notice.closest("div")?.textContent).toContain(status.build!.git_sha!);
  });
});
