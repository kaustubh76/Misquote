import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ShareIntervals, type ShareInterval } from "./ShareIntervals";

// The committed registry survey: six shares over one sample of 400 cards.
const SAMPLED = 400;
const rows: ShareInterval[] = [
  { key: "resolvable", label: "card resolves", n: 369, low: 0.8920944082797374, high: 0.9448674104135325 },
  { key: "on_chain_cards", label: "card held on chain", n: 222, low: 0.5060035322825036, high: 0.6029500772515317 },
  { key: "substantive", label: "substantive", n: 139, low: 0.30248524680204364, high: 0.3954161085808589 },
  { key: "placeholders", label: "placeholder text", n: 0, low: 0, high: 0.009512640599680667 },
];

const draw = (over: Partial<Parameters<typeof ShareIntervals>[0]> = {}) =>
  render(<ShareIntervals rows={rows} sampled={SAMPLED} caption="Registry survey" {...over} />);

const bar = (name: RegExp) => screen.getByRole("img", { name });

describe("a share is drawn with the interval it is worth", () => {
  it("draws every published share, not only the one the page used to print", () => {
    draw();
    for (const row of rows) {
      expect(screen.getByRole("img", { name: new RegExp(`^${row.label}:`) })).toBeInTheDocument();
    }
  });

  it("names the count, the denominator and both bounds in one sentence", () => {
    // The bar is the only thing a sighted reader gets; this is the whole of
    // what anyone else gets, so it has to carry all four figures rather than
    // announcing "image".
    draw();
    const label = bar(/^card resolves:/).getAttribute("aria-label") ?? "";
    expect(label).toContain("369 of 400 sampled");
    expect(label).toContain("92.3%");
    expect(label).toContain("89.2%");
    expect(label).toContain("94.5%");
    expect(label).toContain("95% confidence interval");
  });

  it("puts every bar on the same axis rather than scaling each to itself", () => {
    // The failure this rules out is `GateHistogram`'s: three rows scaled to
    // their own maximum drew "every gate blocked every decision". Here it
    // would draw the 0-of-400 row the same width as the 369-of-400 row.
    draw();
    const width = (name: RegExp) =>
      parseFloat((bar(name).querySelector<HTMLElement>("div")!).style.width);
    expect(width(/^card resolves:/)).toBeCloseTo(5.28, 1);
    expect(width(/^placeholder text:/)).toBeCloseTo(0.95, 1);
  });

  it("still draws a bar for a share nothing was observed at", () => {
    // 0 of 400 is not 0% of the registry, and the interval is what says so.
    // A row that collapsed to nothing would be the stronger claim.
    draw();
    const el = bar(/^placeholder text:/).querySelector<HTMLElement>("div")!;
    expect(parseFloat(el.style.width)).toBeGreaterThan(0);
    expect(screen.getByText(/none of the 400 was one/i)).toBeInTheDocument();
  });

  it("keeps a second decimal on a bound below one percent, and only there", () => {
    // At one decimal the placeholder bound reads "1.0%", rounding *up* past
    // the round number it sits below — on the one row whose point is that
    // none observed is not none existing.
    draw();
    const label = bar(/^placeholder text:/).getAttribute("aria-label") ?? "";
    expect(label).toContain("0.95%");
    expect(label).not.toContain("1.0%");
    expect(bar(/^substantive:/).getAttribute("aria-label")).toContain("34.8%");
  });

  it("renders nothing rather than dividing by a denominator it was not given", () => {
    const { container } = draw({ sampled: 0 });
    expect(container).toBeEmptyDOMElement();
  });
});
