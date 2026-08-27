import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TallyStrip } from "@/components/TallyStrip";

/**
 * The three rules the extraction had to preserve, each of which one of the
 * originals depended on.
 */
const widths = () =>
  [...document.querySelectorAll<HTMLElement>("[role='img'] > div")].map(
    (d) => d.style.width
  );

describe("a tally of counts that add to a whole", () => {
  it("scales every part against the total it was given, not against their sum", () => {
    // The rule `/vetting` needs. Its verdict tally is scaled against every
    // check read from chain, so a check whose verdict nobody recognised leaves
    // a gap rather than being redistributed across the verdicts that were
    // counted. Summing the parts here would silently fill that gap in.
    render(
      <TallyStrip
        total={10}
        parts={[
          { label: "pass", tone: "bg-good", n: 3 },
          { label: "fail", tone: "bg-bad", n: 2 },
        ]}
        ariaSentence="3 passed and 2 failed, of 10 checks."
      />
    );

    expect(widths()).toEqual(["30%", "20%"]);
  });

  it("renders nothing for a part that is zero", () => {
    // Not a zero-width div: in a flex row that still occupies its border, and a
    // hairline where a count is zero reads as a count that is small. All three
    // originals guarded on `n > 0`.
    render(
      <TallyStrip
        total={4}
        parts={[
          { label: "ahead", tone: "bg-good", n: 0 },
          { label: "behind", tone: "bg-bad", n: 4 },
        ]}
        ariaSentence="None ahead, 4 behind, of 4 tasks."
      />
    );

    expect(widths()).toEqual(["100%"]);
  });

  it("speaks the caller's sentence rather than one assembled from the labels", () => {
    // `/status` names its exit-code verdict and `/vetting` names the worst
    // verdict *and* that its counts come off the rendered checks rather than
    // off `summary`. A sentence built from labels would flatten both into
    // "3 pass, 0 fail", which is what the mark already shows.
    const sentence =
      "PASS is the worst verdict on this page: 27 PASS, across 27 checks read from chain.";
    render(
      <TallyStrip
        total={27}
        parts={[{ label: "PASS", tone: "bg-good", n: 27 }]}
        ariaSentence={sentence}
      />
    );

    expect(screen.getByRole("img", { name: sentence })).toBeInTheDocument();
  });

  it("lets a part carry a texture, so an absence is not a colour", () => {
    // `/vetting`'s UNKNOWN is `--hatch-none` behind a neutral tint: a reading
    // that did not happen has no finding to colour. The component takes the
    // class rather than knowing what any verdict means.
    render(
      <TallyStrip
        total={2}
        parts={[
          { label: "UNKNOWN", tone: "hatched bg-neutral/40 [--hatch-tone:var(--hatch-none)]", n: 1 },
          { label: "PASS", tone: "bg-good", n: 1 },
        ]}
        ariaSentence="1 unknown and 1 pass, of 2 checks."
      />
    );

    const [unknown] = [...document.querySelectorAll<HTMLElement>("[role='img'] > div")];
    expect(unknown?.className).toContain("hatched");
  });

  it("does not divide by zero when nothing was counted", () => {
    render(
      <TallyStrip
        total={0}
        parts={[{ label: "pass", tone: "bg-good", n: 0 }]}
        ariaSentence="No checks were read."
      />
    );

    expect(widths()).toEqual([]);
  });
});
