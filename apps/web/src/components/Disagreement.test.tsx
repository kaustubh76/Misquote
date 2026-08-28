import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Disagreement } from "@/components/Disagreement";

afterEach(cleanup);

const two = [
  { who: "8004scan", how: "their indexer", n: 285599 },
  { who: "this repository", how: "binary search on ownerOf", n: 280287 },
];

const three = [
  { who: "asked the index", how: "of 285,599", n: 438 },
  { who: "walked every row", how: "of 278,500", n: 510 },
  { who: "counted the table", how: "of 11,719", n: 547 },
];

const ticks = () =>
  [...document.querySelectorAll<HTMLElement>("[role='img'] > div")].filter((d) =>
    d.className.includes("bg-brand")
  );

const draw = (readings: typeof two, sentence = "Two readings. None is chosen.") =>
  render(
    <Disagreement readings={readings} ariaSentence={sentence} spreadNote="5,312 apart" />
  );

describe("readings that will not be reconciled", () => {
  it("draws a tick for every reading, none emphasised over another", () => {
    // "nothing here can say which is right, and picking the larger would be
    // the misquote this project is named after" — so the marks are identical.
    draw(three);
    const marks = ticks();

    expect(marks).toHaveLength(3);
    expect(new Set(marks.map((m) => m.className)).size).toBe(1);
  });

  it("hatches the gap in the neutral tone, not the warm one", () => {
    // `Ledger.tsx`'s rule: warm means evidence exists and fell short, neutral
    // means nothing was ever there. This gap is a region no method speaks for.
    draw(two);
    const gap = document.querySelector("[role='img'] > .hatched");

    expect(gap).toBeTruthy();
    expect(gap?.className).not.toContain("hatch-warn");
  });

  it("labels the ticks when there are two of them", () => {
    draw(two);
    expect(screen.getByText("285,599")).toBeInTheDocument();
    expect(screen.getByText("280,287")).toBeInTheDocument();
  });

  it("drops the tick labels above a pair, because three of them collide", () => {
    // 438, 510 and 547 sit inside a hundred. The alternating right/left
    // placement that works for a pair overlaps into a smear here, so the list
    // below becomes the record and the ticks go `aria-hidden` — the rule
    // `AgentComparison` states for a mark that ranks rather than records.
    draw(three);

    for (const mark of ticks()) {
      expect(mark.getAttribute("aria-hidden")).toBe("true");
      expect(mark.textContent).toBe("");
    }
    // Every figure is still on the page, in the list.
    expect(screen.getByText(/438 · asked the index/)).toBeInTheDocument();
    expect(screen.getByText(/547 · counted the table/)).toBeInTheDocument();
  });

  it("names every method and says none is chosen", () => {
    const sentence =
      "Three ways: 438 asked, 510 walked, 547 counted. None is chosen.";
    draw(three, sentence);

    expect(screen.getByRole("img", { name: sentence })).toBeInTheDocument();
  });

  it("always carries the note that the axis is magnified", () => {
    // "A zoom that is labelled is a reading aid; an unlabelled one is the
    // distortion this page criticises." `spreadNote` is required so a second
    // call site cannot forget it.
    draw(two);
    expect(screen.getByText("5,312 apart")).toBeInTheDocument();
  });

  it("draws nothing for a single reading, which is not a disagreement", () => {
    const { container } = render(
      <Disagreement
        readings={[two[0]!]}
        ariaSentence="One reading."
        spreadNote="nothing to compare"
      />
    );

    expect(container).toBeEmptyDOMElement();
  });
});
