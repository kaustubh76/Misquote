import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ObservationGrid } from "@/components/ObservationGrid";

afterEach(cleanup);

const cells = () =>
  document.querySelectorAll("[role='img'] > span").length;

describe("the observations a quote rests on", () => {
  it("draws one cell per observation the engine counted", () => {
    // Not `windows × perturbations`: a window shorter than the policy horizon
    // is dropped, so the product and the count can differ and the count is the
    // denominator every verdict divides by.
    render(
      <ObservationGrid windows={20} perturbations={3} samples={57} floor={30} caption="" />
    );

    expect(cells()).toBe(57);
  });

  it("hatches every cell when the count is short of the floor", () => {
    // Texture carries the verdict, not colour — `FloorGauge`'s rule, and
    // `Pill`'s: colour is never the only signal.
    render(
      <ObservationGrid windows={6} perturbations={3} samples={18} floor={30} caption="" />
    );

    const first = document.querySelector("[role='img'] > span");
    expect(first?.className).toContain("hatched");
    expect(screen.getByText(/floor 30 — short/)).toBeInTheDocument();
  });

  it("says it is clear when it is, rather than saying nothing", () => {
    render(
      <ObservationGrid windows={20} perturbations={3} samples={60} floor={30} caption="" />
    );

    const first = document.querySelector("[role='img'] > span");
    expect(first?.className).not.toContain("hatched");
    expect(screen.getByText(/floor 30 — clear/)).toBeInTheDocument();
  });

  it("names every figure in the spoken description, including the floor", () => {
    // Never a bare `role="img"`: "a screen reader that got 'image, bar' would
    // have been told there was a figure and not what it said."
    render(
      <ObservationGrid windows={6} perturbations={3} samples={18} floor={30} caption="" />
    );

    const label = screen.getByRole("img").getAttribute("aria-label") ?? "";
    expect(label).toContain("18 observations");
    expect(label).toContain("6 windows");
    expect(label).toContain("3 perturbations");
    expect(label).toContain("short of the floor of 30");
  });

  it("says nothing about a floor nobody passed", () => {
    // `/quote`'s refusal does not read the floors artifact, and a threshold
    // invented here would be a fabricated number under a refusal — the
    // objection `Band`'s withheld branch already makes about guessing one.
    render(<ObservationGrid windows={6} perturbations={3} samples={18} caption="" />);

    const label = screen.getByRole("img").getAttribute("aria-label") ?? "";
    expect(label).not.toContain("floor");
    expect(screen.queryByText(/floor/)).not.toBeInTheDocument();
  });

  it("refuses to draw a grid nobody could count", () => {
    // A grid of thousands of cells is a texture, not a count. `FloorGauge` is
    // already the component for one quantity against a threshold.
    render(
      <ObservationGrid windows={500} perturbations={3} samples={1500} floor={30} caption="" />
    );

    expect(cells()).toBe(0);
    expect(screen.getByText(/too many to draw one by one/)).toBeInTheDocument();
  });

  it("draws nothing at all rather than an empty grid", () => {
    const { container } = render(
      <ObservationGrid windows={0} perturbations={0} samples={0} caption="" />
    );

    expect(container).toBeEmptyDOMElement();
  });
});
