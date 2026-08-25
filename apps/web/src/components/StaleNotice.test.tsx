import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StaleNotice, type BehindEntry } from "@/components/StaleNotice";

const behind: BehindEntry[] = [
  { artifact: "advantage.json", recorded_sha: "237c678", commits: 1 },
  { artifact: "warden.json", recorded_sha: "eb040ed", commits: 3 },
];

describe("StaleNotice", () => {
  it("renders nothing when this page's artifacts are current", () => {
    // The assertion that the notice is data-driven. A hardcoded caveat would
    // still be on the page the day someone regenerates, which is exactly when
    // it becomes a false statement rather than a true one.
    const { container } = render(
      <StaleNotice behind={behind} artifacts={["vetting.json", "venue.json"]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when nothing at all is behind", () => {
    const { container } = render(<StaleNotice behind={[]} artifacts={["warden.json"]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names only the artifacts this page draws from", () => {
    render(<StaleNotice behind={behind} artifacts={["advantage.json"]} />);
    expect(screen.getByText(/advantage.json @ 237c678/)).toBeInTheDocument();
    expect(screen.queryByText(/warden.json/)).not.toBeInTheDocument();
  });

  it("reports the largest gap, not the first one it found", () => {
    render(<StaleNotice behind={behind} artifacts={["advantage.json", "warden.json"]} />);
    expect(screen.getByText(/3 commits have landed on the replay engine/)).toBeInTheDocument();
  });

  it("says not-re-derived rather than wrong", () => {
    render(<StaleNotice behind={behind} artifacts={["advantage.json"]} />);
    // The distinction `vetting/badge.py` draws between unknown and failed. An
    // artifact that predates an engine change is not known to be wrong.
    expect(screen.getByText(/Nothing here is known to be wrong/)).toBeInTheDocument();
  });

  it("agrees with itself in number for a single artifact", () => {
    render(
      <StaleNotice
        behind={[{ artifact: "advantage.json", recorded_sha: "237c678", commits: 1 }]}
        artifacts={["advantage.json"]}
      />,
    );
    expect(screen.getByText(/This figure predates/)).toBeInTheDocument();
    // The verb too. The artifact count and the commit count differ, and the
    // first draft agreed one clause with each.
    expect(screen.getByText(/1 commit has landed on the replay engine/)).toBeInTheDocument();
  });
});
