import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { EngineStamp } from "@/components/EngineStamp";

afterEach(cleanup);

/**
 * The mark that would have made an eighty-one point contradiction visible.
 *
 * `/advantage` and `/agent/warden` publish the same comparison from artifacts
 * written by different make targets. Run one without the other and they are
 * nine engine commits apart; both pages rendered a number and neither rendered
 * the commit behind it.
 */
describe("which engine produced a number", () => {
  it("names the commit and when it ran", () => {
    render(<EngineStamp sha="04a388b" generatedAt="2026-08-28T23:14:41+00:00" />);

    expect(screen.getByText(/04a388b/)).toBeInTheDocument();
  });

  it("says a tree was dirty, because that makes the commit a lie", () => {
    // The removed `BuildStamp` made this argument and it was right: the sha is
    // a real commit and the code that produced the number is not in it. It is
    // true on every artifact this repository currently publishes.
    render(<EngineStamp sha="04a388b" generatedAt="2026-08-28T23:14:41+00:00" dirty />);

    expect(screen.getByText(/uncommitted changes/)).toBeInTheDocument();
  });

  it("does not claim a clean tree by staying silent about a dirty one", () => {
    render(<EngineStamp sha="04a388b" generatedAt="2026-08-28T23:14:41+00:00" dirty={false} />);

    expect(screen.queryByText(/uncommitted changes/)).not.toBeInTheDocument();
    expect(screen.getByText(/04a388b/)).toBeInTheDocument();
  });

  it("renders nothing at all when the artifact recorded no stamp", () => {
    // Not a dash and not "unknown". An artifact with no stamp cannot be placed
    // against this history, which is the case `check_artifact_freshness`
    // already answers UNVERIFIED for — a mark here would put something on the
    // page for a fact nobody has.
    const { container } = render(<EngineStamp sha={null} generatedAt={null} />);

    expect(container).toBeEmptyDOMElement();
  });
});
