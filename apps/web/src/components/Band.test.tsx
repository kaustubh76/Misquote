import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Band, cluster, overlaps, type BandSeries } from "./Band";
import { textFrom } from "@/test/harness";

const agent: BandSeries = { label: "Warden", p25: 36.88, p50: 37.74, p75: 38.72, tone: "agent" };
const diy: BandSeries = { label: "DIY", p25: 5.63, p50: 9.99, p75: 26.05, tone: "baseline" };

describe("a withheld quote is a result, not an empty chart", () => {
  it("renders the engine's own note verbatim rather than a zero-width bar", () => {
    const note = "0 usable replays, assumption A5 requires 20";
    render(<Band series={[]} sufficient={false} note={note} />);

    expect(screen.getByText(/Quote withheld/)).toBeInTheDocument();
    expect(screen.getByText(textFrom(note))).toBeInTheDocument();
    // A withheld quote must not be drawn as a band at 0-0-0, which would read
    // as "we measured zero" rather than "we declined to say".
    expect(screen.getByRole("img")).toHaveAccessibleName(/withheld/i);
  });

  it("still says something when the engine gave no note", () => {
    render(<Band series={[]} sufficient={false} />);
    expect(screen.getByText(/Not enough history/)).toBeInTheDocument();
  });
});

describe("the range is available without looking at it", () => {
  it("exposes every percentile in the accessible name", () => {
    render(<Band series={[agent]} sufficient caption="Warden net return" />);
    const figure = screen.getByRole("img");
    expect(figure).toHaveAccessibleName(/P25 36\.88%/);
    expect(figure).toHaveAccessibleName(/median 37\.74%/);
    expect(figure).toHaveAccessibleName(/P75 38\.72%/);
  });
});

describe("overlap is stated, not left to the eye", () => {
  it("calls out separated bands", () => {
    render(<Band series={[agent, diy]} sufficient />);
    expect(screen.getByText(/separated/)).toBeInTheDocument();
  });

  it("calls out overlapping bands as indistinguishable", () => {
    const close: BandSeries = { ...diy, p25: 30, p50: 37, p75: 45 };
    render(<Band series={[agent, close]} sufficient />);
    expect(screen.getByText(/overlap/)).toBeInTheDocument();
    expect(screen.getByText(/not distinguishable/)).toBeInTheDocument();
  });
});

describe("overlaps()", () => {
  it("matches Comparison.ranges_overlap in the Python", () => {
    // agent.p25 <= baseline.p75 && baseline.p25 <= agent.p75
    expect(overlaps(agent, diy)).toBe(false);
    expect(overlaps(agent, { ...diy, p75: 37 })).toBe(true);
    // Touching at a single point counts as overlapping, as it does in Python.
    expect(overlaps(agent, { ...diy, p25: 38.72, p75: 50 })).toBe(true);
  });
});

describe("the engine is the authority on overlap", () => {
  // The caption sits one screen-inch from a verdict sentence Python wrote. If
  // the component decides "separated" from its own arithmetic while the
  // artifact says "overlap", the card contradicts itself — which is the exact
  // failure this product is named after.
  // The caption is assembled from several elements, so it is read off the
  // <figcaption> as a whole. Matching a substring that happens to straddle two
  // of those elements silently never matches, which makes a negative assertion
  // pass whatever the component renders.
  const caption = (container: HTMLElement) =>
    container.querySelector("figcaption")?.textContent ?? "";

  it("obeys the passed verdict over its own geometry", () => {
    // Geometrically separated, but told they overlap.
    const { container } = render(
      <Band series={[agent, diy]} sufficient overlap deltaPp={27.75} />,
    );
    expect(caption(container)).toMatch(/bands overlap/);
    expect(caption(container)).not.toMatch(/separated/);
  });

  it("prints the engine's delta, not a recomputed one", () => {
    const { container } = render(
      <Band series={[agent, diy]} sufficient overlap={false} deltaPp={-1.77} />,
    );
    // 37.74 − 9.99 would be +27.75; the artifact's figure must win.
    expect(caption(container)).toMatch(/−1\.77pp at the median/);
    expect(caption(container)).not.toMatch(/27\.75/);
  });

  it("falls back to geometry only when the engine said nothing", () => {
    const { container } = render(<Band series={[agent, diy]} sufficient />);
    expect(caption(container)).toMatch(/bands are separated/);
  });
});

describe("the axis stays legible when zero crowds an endpoint", () => {
  const axis = (container: HTMLElement) =>
    container.querySelector<HTMLElement>("[aria-hidden='true'].relative.mb-2");

  it("drops the zero label when it would print on top of the minimum", () => {
    // The committed Warden domain: [-3.6%, 48%] puts zero at 7% of the axis.
    // At 390px that is 23px in, while "−3.6%" set at 10px runs to about 28px,
    // so the two labels printed over each other and neither could be read.
    const low: BandSeries = { label: "Warden", p25: -3.3, p50: 20, p75: 44, tone: "agent" };
    const { container } = render(<Band series={[low]} sufficient />);

    const text = axis(container)?.textContent ?? "";
    expect(text).not.toContain("0");
    // The endpoints still label the scale, and the zero *line* is drawn
    // separately — the meaning is not lost with the label.
    expect(text).toMatch(/-\d+\.\d%/);
  });

  it("keeps the zero label when there is room for it", () => {
    const straddling: BandSeries = { label: "Warden", p25: -30, p50: 5, p75: 40, tone: "agent" };
    const { container } = render(<Band series={[straddling]} sufficient />);

    const zero = [...(axis(container)?.querySelectorAll("span") ?? [])].find(
      (s) => s.textContent === "0",
    );
    expect(zero).toBeDefined();
  });
});

describe("a degenerate range is drawn as the line it is", () => {
  // The committed Warden shape: 20 windows × 3 identical perturbations, an
  // interquartile range of 0.0062pp inside an observed span of 7.25.
  const wardenish = {
    p25: -233.5647,
    p50: -233.5625,
    p75: -233.5585,
    label: "Warden",
    tone: "agent" as const,
  };
  const wardenReturns = [
    ...Array<number>(51).fill(-233.5625),
    ...Array<number>(3).fill(-229.9438),
    ...Array<number>(3).fill(-229.9451),
    ...Array<number>(3).fill(-237.1934),
  ];

  const bandWidth = (container: HTMLElement) => {
    const box = container.querySelector<HTMLElement>("[class*='rounded-sm'][class*='border']");
    return parseFloat(box?.style.width ?? "0");
  };

  it("does not clamp a sub-pixel band to a visible width", () => {
    // `Math.max(right - left, 0.4)` rendered 0.0023% as 0.4% — about 1.3px on a
    // 330px axis. A range where the data has none is the one thing this
    // component must never draw.
    const { container } = render(
      <Band series={[wardenish]} returns={wardenReturns} sufficient />,
    );
    expect(bandWidth(container)).toBeLessThan(0.4);
  });

  it("states the concentration the box cannot show", () => {
    render(<Band series={[wardenish]} returns={wardenReturns} sufficient />);
    // 51 of 60 sit within a hundredth of the observed span of the median.
    expect(screen.getByText(/51 of 60 observations fall within/)).toBeInTheDocument();
  });

  it("says so when every observation is identical", () => {
    const flat = Array<number>(60).fill(-1.7083);
    render(
      <Band
        series={[{ ...wardenish, p25: -1.7083, p50: -1.7083, p75: -1.7083 }]}
        returns={flat}
        sufficient
      />,
    );
    expect(screen.getByText(/All 60 observations fall within/)).toBeInTheDocument();
    expect(screen.getByText(/no spread to draw/)).toBeInTheDocument();
  });
});

describe("the axis fits the data rather than zero", () => {
  const far = { label: "Warden", p25: -237, p50: -233, p75: -229, tone: "agent" as const };

  it("does not anchor to zero when no observation is near it", () => {
    // Anchoring made the domain 275pp wide to hold data spanning 7, and every
    // band collapsed. The axis end labels are the observable proof.
    const { container } = render(<Band series={[far]} returns={[-237, -229]} sufficient />);
    const axis = container.querySelector("[aria-hidden='true'].relative.mb-2");
    expect(axis?.textContent).not.toContain("0.0%");
    expect(axis?.textContent).toMatch(/-2\d\d/);
  });

  it("says which side of zero everything falls, since zero is off the axis", () => {
    render(<Band series={[far]} returns={[-237, -229]} sufficient />);
    expect(screen.getByText(/below zero, which is off this axis/)).toBeInTheDocument();
  });

  it("still draws zero when the data straddles it", () => {
    const straddling = { label: "A", p25: -10, p50: 2, p75: 14, tone: "agent" as const };
    const { container } = render(
      <Band series={[straddling]} returns={[-10, 14]} sufficient />,
    );
    const axis = container.querySelector("[aria-hidden='true'].relative.mb-2");
    expect([...(axis?.querySelectorAll("span") ?? [])].some((s) => s.textContent === "0")).toBe(
      true,
    );
    expect(screen.queryByText(/off this axis/)).not.toBeInTheDocument();
  });
});

describe("cluster()", () => {
  it("collapses the identical perturbations into one stack", () => {
    // 20 windows × 3 perturbations, all three identical — which is 0 of 60
    // differing on grid and sentinel, and 3 of 60 on warden.
    const triples = [1.5, 1.5, 1.5, 2.5, 2.5, 2.5];
    expect(cluster(triples)).toEqual([
      { value: 1.5, count: 3 },
      { value: 2.5, count: 3 },
    ]);
  });

  it("keeps windows that differ in the fourth decimal apart", () => {
    // At 2dp warden's 20 windows collapse to 5 values, which would hide real
    // structure; 4dp is what separates a window from float noise.
    expect(cluster([-233.5625, -233.5647])).toHaveLength(2);
  });
});
