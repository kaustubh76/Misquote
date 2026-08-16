import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GateHistogram } from "./GateHistogram";

/** The bar is the inner div; its width is the whole claim. */
function barWidths(container: HTMLElement): string[] {
  return [...container.querySelectorAll<HTMLElement>("li div > div")].map(
    (bar) => bar.style.width,
  );
}

describe("a bar means a share of decisions, not a share of the tallest bar", () => {
  it("does not draw tied gates as full when most decisions were not held", () => {
    // The committed artifact, exactly: three gates holding on the same 115 of
    // 175 journalled decisions. Scaled to `max`, all three rendered 100% —
    // three full-width bars saying "every gate blocked every decision", when
    // two decisions in three is the truth.
    const { container } = render(
      <GateHistogram blocks={{ R1: 115, R2: 115, R3: 115 }} total={175} />,
    );

    expect(barWidths(container)).toEqual([
      "65.71428571428571%",
      "65.71428571428571%",
      "65.71428571428571%",
    ]);
  });

  it("writes the denominator next to the count", () => {
    render(<GateHistogram blocks={{ R1: 115 }} total={175} />);
    // "115" alone invites the reader to supply a denominator, and the nearest
    // number on the page is the replay's 44,802 — a different run entirely.
    expect(screen.getByText("115 of 175")).toBeInTheDocument();
    expect(screen.getByText(/66% of decisions/)).toBeInTheDocument();
  });

  it("keeps the gates separate rather than presenting them as parts of a whole", () => {
    // R1+R2+R3 = 345 against 175 decisions. Gates are not exclusive: one
    // decision can trip several. Nothing may render a total or a stacked bar.
    const { container } = render(
      <GateHistogram blocks={{ R1: 115, R2: 115, R3: 115 }} total={175} />,
    );
    expect(container.textContent).not.toContain("345");
    expect(container.textContent).not.toMatch(/100%/);
  });
});

describe("when there is no denominator", () => {
  it("falls back to relative scaling and says that it has", () => {
    const { container } = render(<GateHistogram blocks={{ R1: 115, R2: 40 }} />);

    expect(barWidths(container)).toEqual(["100%", "34.78260869565217%"]);
    // A relative chart and an absolute one are pixel-identical. The difference
    // has to be in words or it is not communicated at all.
    expect(screen.getByText(/scaled to the largest gate/)).toBeInTheDocument();
    expect(screen.queryByText(/of decisions/)).not.toBeInTheDocument();
  });

  it("treats a zero total as unknown rather than dividing by it", () => {
    const { container } = render(<GateHistogram blocks={{ R1: 5 }} total={0} />);
    expect(barWidths(container)).toEqual(["100%"]);
    expect(screen.getByText(/scaled to the largest gate/)).toBeInTheDocument();
  });
});

describe("no journal at all", () => {
  it("says there is nothing to attribute, rather than drawing an empty chart", () => {
    render(<GateHistogram blocks={{}} total={0} />);
    expect(screen.getByText(/wrote no decision journal/)).toBeInTheDocument();
  });
});
