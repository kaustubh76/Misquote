import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentCard } from "./AgentCard";
import type { AgentArtifact, AgentRef } from "@/lib/artifacts";

/**
 * Rendered against the real generated artifact, not a fixture.
 *
 * A fixture proves the component can render *something*. It cannot catch the
 * failure that actually happened here — an artifact field that no view reads —
 * because a fixture is written to match the component rather than the emitter.
 */
const ARTIFACTS = join(process.cwd(), "public", "artifacts");

function artifact(name: string): AgentArtifact {
  return JSON.parse(readFileSync(join(ARTIFACTS, name), "utf8")) as AgentArtifact;
}

const warden = artifact("warden.json");
const ref: AgentRef = { name: "Warden", slug: "warden", category: "Rebalancing", built: true };

describe("the card renders what the emitter actually produced", () => {
  it("shows the honest denominator, not the invented one", () => {
    render(<AgentCard ref_={ref} data={warden} />);

    // 60 = 20 sub-windows x 3 perturbations. The card previously rendered
    // "PASS (100% of 448)" from `result.samples // 100`.
    expect(screen.getByText(/Beats holding: PASS \(100% of 60\)/)).toBeInTheDocument();
    // Anchored on the closing paren: the in-range verdict legitimately reads
    // "FAIL (60% of 44802)", and an unanchored /of 448/ matches inside it.
    expect(screen.queryByText(/of 448\)/)).not.toBeInTheDocument();
  });

  it("draws the P25-P75 band from real percentiles", () => {
    render(<AgentCard ref_={ref} data={warden} />);
    const q = warden.quote_detail!;

    const band = screen.getAllByRole("img")[0]!;
    expect(band).toHaveAccessibleName(new RegExp(`P25 ${q.p25.toFixed(2)}%`));
    expect(band).toHaveAccessibleName(new RegExp(`median ${q.p50.toFixed(2)}%`));
  });

  it("shows the DIY baseline the quote is implicitly claiming to beat", () => {
    render(<AgentCard ref_={ref} data={warden} />);
    expect(screen.getByText(/vs doing it yourself/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(warden.advantage!.verdict))).toBeInTheDocument();
  });

  it("explains the window length instead of contradicting the tape length", () => {
    render(<AgentCard ref_={ref} data={warden} />);
    // Both numbers appear, each labelled, with a route to the arithmetic.
    expect(screen.getByText(/sub-windows of/)).toBeInTheDocument();
    expect(screen.getByText(/Why that differs from the/)).toBeInTheDocument();
  });

  it("carries the counterfactual badge from the artifact, not a literal", () => {
    render(<AgentCard ref_={ref} data={warden} />);
    expect(screen.getByText(warden.badge)).toBeInTheDocument();
  });
});

describe("missing data never renders as a loss", () => {
  it("shows an em dash in neutral colour when net is absent", () => {
    const broken = {
      ...warden,
      replay: { ...warden.replay, net_quote: undefined as unknown as number },
    };
    render(<AgentCard ref_={ref} data={broken} />);

    const table = screen.getByRole("region", { name: /replay metrics/i });
    const netRow = within(table).getByRole("rowheader", { name: "net" }).closest("tr")!;
    const cell = within(netRow).getAllByRole("cell")[0]!;

    expect(cell).toHaveTextContent("—");
    expect(cell.className).not.toContain("text-bad");
  });
});

describe("a withheld quote", () => {
  it("renders the refusal rather than a zeroed band", () => {
    const withheld: AgentArtifact = {
      ...warden,
      quote_sufficient: false,
      quote_detail: {
        ...warden.quote_detail!,
        sufficient: false,
        p25: 0,
        p50: 0,
        p75: 0,
        note: "0 usable replays, assumption A5 requires 20",
      },
    };
    render(<AgentCard ref_={ref} data={withheld} />);

    expect(screen.getByText(/Quote withheld/)).toBeInTheDocument();
    expect(screen.getByText(/assumption A5 requires 20/)).toBeInTheDocument();
  });
});
