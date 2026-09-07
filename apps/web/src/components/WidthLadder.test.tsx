import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { WidthLadder, type LadderBand } from "./WidthLadder";

/**
 * The flagship's committed ladder, trimmed to four rungs.
 *
 * Real figures from `pools.json`, and the tie sets are the emitter's: ±80
 * overlaps ±40 and ±130 and does *not* overlap ±800, which is the one genuinely
 * separated pair on that pool and therefore the only pair worth testing on.
 */
const band = (
  width: number,
  p25: number,
  p50: number,
  p75: number,
  ties: number[],
): LadderBand => ({
  width_ticks: width,
  p25,
  p50,
  p75,
  observations: 20,
  sufficient: true,
  note: "",
  indistinguishable_from: ties,
});

const flagship: LadderBand[] = [
  band(40, 0.085, 0.155, 0.309, [80, 130, 800]),
  band(80, 0.127, 0.17, 0.282, [40, 130]),
  band(130, 0.101, 0.163, 0.232, [40, 80, 800]),
  band(800, 0.073, 0.107, 0.115, [40, 130]),
];

const draw = (bands = flagship, best: number | null = 80) =>
  render(<WidthLadder bands={bands} bestWidth={best} caption="Fee APR by width" />);

describe("the ladder is rows a reader can still read as numbers", () => {
  it("keeps every rung a labelled table row", () => {
    // The chart is the comparison; the figures are the answer. A `<figure>`
    // would have meant a second copy of all four numbers in a table beside it.
    draw();
    for (const b of flagship) {
      expect(screen.getByRole("rowheader", { name: `±${b.width_ticks} ticks` })).toBeInTheDocument();
    }
  });

  it("says out loud everything the band draws", () => {
    // The band is a picture. A reader who is not looking at it gets the range,
    // the median and the sample size or gets nothing.
    draw();
    const spoken = screen.getByRole("img", { name: /±80 ticks/ });
    expect(spoken).toHaveAccessibleName(/P25 12.7%/);
    expect(spoken).toHaveAccessibleName(/median 17.0%/);
    expect(spoken).toHaveAccessibleName(/P75 28.2%/);
    expect(spoken).toHaveAccessibleName(/20 windows/);
  });

  it("marks the engine's leader without re-deriving one", () => {
    draw();
    expect(screen.getByText(/leads/)).toBeInTheDocument();
  });
});

describe("selecting a width answers the question the table could not", () => {
  it("names what the chosen width is and is not separated from", async () => {
    draw();
    await userEvent.click(screen.getByRole("button", { name: "±80 ticks" }));

    const said = document.body.textContent ?? "";
    expect(said).toContain("±40, ±130");
    expect(said).toContain("±800");
  });

  it("marks the tied rows and the clear ones in text, not only in colour", async () => {
    draw();
    await userEvent.click(screen.getByRole("button", { name: "±80 ticks" }));

    // Scoped to the table: the sentence below it says "not separated" too, and
    // that is the point of the sentence — the row markers and the summary have
    // to agree, not be one element.
    const rows = within(screen.getByRole("table"));
    expect(rows.getAllByText("not separated")).toHaveLength(2);
    expect(rows.getAllByText("separated")).toHaveLength(1);
  });

  it("deselects on a second press, so the verdict can be put down", async () => {
    draw();
    const rung = screen.getByRole("button", { name: "±80 ticks" });
    await userEvent.click(rung);
    expect(rung).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(rung);
    expect(rung).toHaveAttribute("aria-pressed", "false");
    expect(within(screen.getByRole("table")).queryByText("not separated")).not.toBeInTheDocument();
  });

  it("asserts nothing before a width is chosen", () => {
    // With no selection there is no comparison, and a row already coloured
    // "separated" would be a verdict nobody asked for.
    draw();
    expect(screen.queryByText("not separated")).not.toBeInTheDocument();
    expect(screen.queryByText("separated")).not.toBeInTheDocument();
  });
});

describe("an artifact with no ties offers no comparison", () => {
  // `indistinguishable_from` is younger than `pools.json`. A checkout holding
  // the older shape has to draw a ladder, not compute the ties here to cover
  // for their absence — that is the second implementation of the overlap rule
  // this component exists to not be.
  const older = flagship.map(({ indistinguishable_from: _drop, ...rest }) => rest);

  it("draws the rungs and does not make them selectable", () => {
    draw(older);
    expect(screen.getByRole("rowheader", { name: "±80 ticks" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "±80 ticks" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Pick a width/)).not.toBeInTheDocument();
  });
});
