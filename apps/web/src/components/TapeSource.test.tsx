import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { TapeSource } from "@/components/TapeSource";

afterEach(cleanup);

/**
 * `provenance.build_stamp` states the requirement this component exists for:
 * "chain" and "synthetic" are two different claims, "and the UI is required to
 * say which one it is showing". The UI stopped saying when `SourceBanner` was
 * deleted, and nothing failed — `test_source_disclosure.py` had been narrowed
 * to guard the artifact, which was never the half that broke.
 */
describe("which tape a number came from", () => {
  it("says chain when it is chain, rather than staying quiet on the ordinary case", () => {
    // The tempting shortcut is to render only the alarming value. Then a
    // reader learns nothing from its absence, and the day a card goes
    // synthetic the change is a mark appearing rather than a mark changing.
    render(<TapeSource source="chain" />);
    expect(screen.getByText("chain tape")).toBeInTheDocument();
  });

  it("marks a synthetic tape with texture as well as the word", () => {
    render(<TapeSource source="synthetic" />);
    const mark = screen.getByText("synthetic tape");

    expect(mark.className).toContain("hatched");
    expect(mark.className).toContain("hatch-warn");
  });

  it("prints a value it does not recognise instead of guessing one", () => {
    // A source nobody anticipated is exactly the case where a default is
    // worst: `advantage.py` emits "mixed" when its tasks disagree, and a
    // future emitter may add another.
    render(<TapeSource source="fork" />);
    expect(screen.getByText("fork tape")).toBeInTheDocument();
  });

  it("renders nothing when no tape was recorded, which is not the same as chain", () => {
    const { container } = render(<TapeSource source={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
