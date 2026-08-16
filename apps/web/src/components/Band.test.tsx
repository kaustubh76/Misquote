import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Band, overlaps, type BandSeries } from "./Band";
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
