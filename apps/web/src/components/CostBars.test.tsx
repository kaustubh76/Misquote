import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CostBars } from "./CostBars";

// The committed Warden shape: costs 8,960× fees.
const warden = [
  { label: "fees earned", value: 0.0208, direction: "earned" as const },
  { label: "adverse selection (upper bound)", value: 0.0054, direction: "spent" as const },
  { label: "costs", value: 186.757, direction: "spent" as const },
];

const chart = () => screen.getByRole("group", { name: /where the money went/i });

const widths = (container: HTMLElement) =>
  [...container.querySelectorAll<HTMLElement>("li div > div")].map((el) =>
    parseFloat(el.style.width),
  );

describe("bars are absolute against a stated denominator", () => {
  it("scales every component against the largest, not against itself", () => {
    // `GateHistogram` learned this the hard way: scaled to their own maximum,
    // three gates blocking 115 of 175 each drew three full-width bars. The same
    // mistake here would draw fees and costs the same length and destroy the
    // only thing worth seeing.
    const { container } = render(
      <CostBars rows={warden} net={-186.74} caption="Warden: where the money went" />,
    );
    const [fees, lvr, costs] = widths(container);

    expect(costs).toBe(100);
    expect(fees).toBeLessThan(1);
    expect(lvr).toBeLessThan(1);
  });

  it("names the denominator rather than leaving it to be inferred", () => {
    render(<CostBars rows={warden} net={-186.74} caption="Warden: where the money went" />);
    expect(within(chart()).getByText(/largest component/)).toBeInTheDocument();
  });

  it("keeps a rounding-error component visible", () => {
    // 0.02 against 186.76 is 0.011% — it would vanish, and an invisible bar
    // reads as "no fees at all" rather than "almost none".
    const { container } = render(
      <CostBars rows={warden} net={-186.74} caption="Warden: where the money went" />,
    );
    expect(widths(container)[0]).toBeGreaterThan(0);
  });

  it("draws nothing for a component that is genuinely zero", () => {
    const { container } = render(
      <CostBars
        rows={[{ label: "fees earned", value: 0, direction: "earned" }, ...warden.slice(1)]}
        net={-186.76}
        caption="Warden: where the money went"
      />,
    );
    expect(widths(container)[0]).toBe(0);
  });
});

describe("every figure survives without the bars", () => {
  it("writes each value beside its bar, signed by direction", () => {
    render(<CostBars rows={warden} net={-186.74} caption="Warden: where the money went" />);
    const region = within(chart());

    // Colour is never the only signal: earned and spent differ by sign and by
    // label as well as by tone.
    expect(region.getByText("+0.02")).toBeInTheDocument();
    expect(region.getByText("−186.76")).toBeInTheDocument();
  });
});

describe("a net nobody measured", () => {
  it("renders as neither a profit nor a loss", () => {
    // `net < 0` compares false for `undefined`, which rendered an absent net
    // green — a missing measurement shown as a profit.
    render(
      <CostBars rows={warden} net={undefined} caption="Warden: where the money went" />,
    );
    const net = within(chart()).getByText("—");

    expect(net.className).not.toContain("text-good");
    expect(net.className).not.toContain("text-bad");
  });
});
