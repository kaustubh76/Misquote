import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CoverageStrip } from "@/components/CoverageStrip";

/**
 * The committed tape has one unbroken run per pool, so the live page never
 * draws a hole. That is the case worth testing: a figure whose only job is to
 * make an interrupted backfill visible, verified against data that has never
 * been interrupted, is verified against nothing.
 */
describe("CoverageStrip", () => {
  it("counts the gaps between runs, not the runs", () => {
    render(
      <CoverageStrip
        known
        runs={[
          { from_block: 100, to_block: 199 },
          { from_block: 300, to_block: 399 },
          { from_block: 500, to_block: 599 },
        ]}
        caption="Blocks read"
      />,
    );
    // Two holes: 200-299 and 400-499, 200 blocks between three runs.
    expect(screen.getByText(/2 unread gaps totalling 200 blocks/)).toBeInTheDocument();
  });

  it("says so plainly when there is nothing between the runs", () => {
    render(<CoverageStrip known runs={[{ from_block: 1, to_block: 900 }]} caption="Blocks read" />);
    expect(screen.getByText(/one unbroken run/)).toBeInTheDocument();
  });

  it("gives a hole too small to see a floor, and does not give one to a run", () => {
    const { container } = render(
      <CoverageStrip
        known
        runs={[
          { from_block: 1, to_block: 1_000_000 },
          // One block missing out of a two-million-block claim: 0.00005%, which
          // rounds to an invisible sliver. That is precisely the interruption
          // the `covered` table exists to surface, so it gets a minimum width.
          { from_block: 1_000_002, to_block: 2_000_000 },
        ]}
        caption="Blocks read"
      />,
    );
    const widths = [...container.querySelectorAll<HTMLElement>("figure > div > div")].map(
      (el) => Number.parseFloat(el.style.width),
    );
    expect(widths).toHaveLength(3);
    expect(widths[1]).toBeGreaterThan(0.3); // the hole, floored
    // The runs keep their true share — inflating one would overstate what was
    // read, which is the opposite of this component's purpose.
    expect(widths[0]).toBeCloseTo(50, 0);
    expect(widths[2]).toBeCloseTo(50, 0);
  });

  it("refuses to draw anything when coverage was never recorded", () => {
    render(<CoverageStrip known={false} runs={[]} caption="Blocks read" />);
    expect(screen.getByText(/before coverage was recorded/)).toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });

  it("distinguishes an unrecorded database from one with no range read", () => {
    render(<CoverageStrip known runs={[]} caption="Blocks read" />);
    expect(screen.getByText(/No range is recorded as read/)).toBeInTheDocument();
  });
});
