import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentCard } from "./AgentCard";
import { textFrom } from "@/test/harness";
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
    // Read from the artifact, not hardcoded. An earlier version asserted
    // "PASS (100% of 60)" — the count from one particular tape — so shortening
    // the demo tape failed the test for the wrong reason. What must hold is
    // that the card says exactly what the emitter computed.
    expect(
      screen.getByText(`Beats holding: ${warden.verdicts.profitable.label}`),
    ).toBeInTheDocument();
    // The denominator is never the invented one: 44,802 decisions // 100.
    expect(screen.queryByText(/of 448\)/)).not.toBeInTheDocument();
  });

  it("draws the P25-P75 band from real percentiles, or withholds it", () => {
    render(<AgentCard ref_={ref} data={warden} />);
    const q = warden.quote_detail!;
    const band = screen.getAllByRole("img")[0]!;

    if (q.sufficient) {
      expect(band).toHaveAccessibleName(new RegExp(`P25 ${q.p25.toFixed(2)}%`));
      expect(band).toHaveAccessibleName(new RegExp(`median ${q.p50.toFixed(2)}%`));
    } else {
      // A tape below the 24h window floor withholds, and the card must show
      // the refusal rather than a band drawn at zero.
      expect(band).toHaveAccessibleName(/withheld/i);
      // The engine's note appears twice on a withheld card — once in the
      // band and once in the advantage verdict — which is consistent, not
      // duplicated: both are quoting the same refusal.
      expect(screen.getAllByText(textFrom(q.note.slice(0, 40))).length).toBeGreaterThan(0);
    }
  });

  it("shows the DIY baseline the quote is implicitly claiming to beat", () => {
    render(<AgentCard ref_={ref} data={warden} />);
    expect(screen.getByText(/vs doing it yourself/)).toBeInTheDocument();
    expect(screen.getByText(textFrom(warden.advantage!.verdict))).toBeInTheDocument();
  });

  it("explains the window length instead of contradicting the tape length", () => {
    render(<AgentCard ref_={ref} data={warden} />);
    // Only meaningful when there is a quote; a withheld card has no window
    // length to reconcile against the tape.
    const q = warden.quote_detail;
    if (q?.sufficient) {
      // The count beside "sub-windows" must be `windows`, never `samples`.
      // It was `samples` (60), which claimed 60 windows of ~362.9h each — 21,771
      // hours drawn from a 725.7h tape, impossible on its face — and
      // contradicted /methods, which this card links to on the next line and
      // which separates the two in a table.
      expect(
        screen.getByText(new RegExp(`${q.windows} sub-windows of`)),
      ).toBeInTheDocument();
      expect(screen.queryByText(new RegExp(`${q.samples} sub-windows`))).not.toBeInTheDocument();
      expect(q.samples).toBe(q.windows * q.perturbations);

      // And how many of them finished in profit, beside the range rather than a
      // page away. On the current tape the median is annualised and deeply
      // negative; "0 of 60" is the fact that tells a reader it is a result and
      // not a unit error.
      expect(
        screen.getByText(
          new RegExp(`${q.net_positive} of ${q.samples} observations finished in profit`),
        ),
      ).toBeInTheDocument();
      expect(screen.getByText(/Why that differs from the/)).toBeInTheDocument();
    } else {
      expect(screen.getByText(/Quote withheld/)).toBeInTheDocument();
    }
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
    // Twice on a withheld card: the band and the advantage verdict both quote
    // the same refusal, which is agreement rather than duplication.
    expect(screen.getAllByText(/assumption A5 requires 20/).length).toBeGreaterThan(0);
  });
});
