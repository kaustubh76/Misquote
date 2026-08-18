import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BuildStamp } from "./BuildStamp";

const clean = {
  command: "python scripts/vetting_report.py --chain 56",
  generated_at: "2026-08-16T08:48:55+00:00",
  git_sha: "344fda7",
  git_dirty: false,
};

describe("a dirty tree is stated, because it makes the sha unusable", () => {
  it("says so in words when the tree had uncommitted changes", () => {
    render(<BuildStamp build={{ ...clean, git_dirty: true }} />);
    expect(screen.getByText(/dirty tree/)).toBeInTheDocument();
    expect(screen.getByText(/uncommitted changes/)).toBeInTheDocument();
  });

  it("says nothing when the tree was clean", () => {
    render(<BuildStamp build={clean} />);
    expect(screen.queryByText(/dirty/)).not.toBeInTheDocument();
    expect(screen.getByText(/344fda7/)).toBeInTheDocument();
  });

  it("treats an absent flag as unknown, not as clean", () => {
    // `git_dirty` is optional on `Build` because an older artifact may not
    // carry it. Rendering nothing is right — but it must not be reachable by
    // *dropping* a flag the artifact does have, which is what the local type in
    // `/vetting` did. That direction is held by the type, not by this test:
    // `Build` is imported rather than restated at all three call sites.
    render(<BuildStamp build={{ ...clean, git_dirty: undefined }} />);
    expect(screen.queryByText(/dirty/)).not.toBeInTheDocument();
  });
});

describe("the stamp names the command that produced the numbers", () => {
  it("prints the command, the time and the commit together", () => {
    const { container } = render(<BuildStamp build={clean} />);
    const text = container.textContent ?? "";

    // One line carrying all three. Splitting them across the page is how a
    // reader ends up attributing a figure to the wrong run.
    expect(text).toContain("vetting_report.py");
    expect(text).toContain("344fda7");
    expect(text).toMatch(/2026/);
  });

  it("says 'no commit' rather than leaving a gap when there is no sha", () => {
    // `git_sha` is null when the emitter ran outside a git checkout. An empty
    // space where a commit should be reads as a rendering bug; the words read
    // as the fact they are.
    render(<BuildStamp build={{ ...clean, git_sha: null }} />);
    expect(screen.getByText(/no commit/)).toBeInTheDocument();
  });

  it("appends whatever the artifact adds without swallowing the rest", () => {
    render(<BuildStamp build={clean} extra="9,000 events over 62.22h" />);
    const text = screen.getByText(/9,000 events/).textContent ?? "";
    expect(text).toContain("344fda7");
  });
});

describe("the source it was built from", () => {
  it("renders it, and first", () => {
    // Declared on the interface since the component existed and dropped by the
    // JSX. `/registry` removed a green "Verified" pill *citing* this field —
    // `"source": "offline"` — and never showed it, so the page's most careful
    // decision rested on a fact the reader had to take on trust.
    render(
      <BuildStamp
        build={{
          command: "python scripts/registry_report.py",
          generated_at: "2026-08-17T16:50:50+00:00",
          git_sha: "92038cf",
          source: "offline",
        }}
      />,
    );

    const line = screen.getByText(/offline/).textContent ?? "";
    expect(line.indexOf("offline")).toBeLessThan(line.indexOf("scripts/registry_report.py"));
  });

  it("says nothing when the artifact does not carry one", () => {
    render(
      <BuildStamp
        build={{
          command: "python scripts/showcase.py",
          generated_at: "2026-08-17T16:50:50+00:00",
          git_sha: "92038cf",
        }}
      />,
    );

    expect(screen.getByText(/scripts\/showcase\.py/).textContent).not.toContain("undefined");
  });
});
