import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readArtifact, serveArtifacts } from "@/test/harness";
import VectorsPage from "./page";

vi.mock("next/navigation", () => ({ usePathname: () => "/vectors" }));

interface Artifact {
  corpus: { cases: number; groups: { group: string; cases: number }[]; pins: unknown[] };
  verification: { replay: Record<string, unknown>; differential: Record<string, unknown> };
  build: unknown;
}

const real = () => readArtifact<Artifact>("vectors.json");

/** The published artifact with one verification block replaced. */
function withReplay(replay: Record<string, unknown>) {
  const d = real();
  return { ...d, verification: { ...d.verification, replay } };
}

beforeEach(() => serveArtifacts());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function loaded() {
  render(<VectorsPage />);
  // Waits for the *loaded* state, not the h1. The heading renders before the
  // fetch resolves — it sits outside the `{d && …}` guard — so awaiting it
  // returns while the page is still a skeleton, and every assertion after it
  // races the artifact. That produced exactly one failure in four full runs,
  // which is the worst possible amount.
  await waitFor(() =>
    expect(document.querySelector("[aria-busy='true']")).not.toBeInTheDocument(),
  );
}

/**
 * One verification card, by its title.
 *
 * Both cards can be in the same state at once — the committed artifact has a
 * recorded replay and no differential — so an unscoped `getByText(/Nothing has
 * been recorded/)` either finds two elements or finds the wrong one. Every
 * assertion about a verification has to name which.
 */
const card = (title: string) =>
  screen.getByRole("heading", { name: title }).closest("section")!;

describe("the corpus is stated as a corpus", () => {
  it("shows every group and its case count from the artifact", async () => {
    await loaded();
    const region = screen.getByRole("region", { name: /Recorded vectors by function/ });

    for (const g of real().corpus.groups) {
      expect(within(region).getByText(g.group)).toBeInTheDocument();
    }
    // Read, never written into the page. `docs/FOR_JUDGES.md` quotes 19,546
    // and the two must not be able to disagree.
    expect(within(region).getAllByText(real().corpus.cases.toLocaleString("en-US")).length)
      .toBeGreaterThan(0);
  });

  it("names the upstream commits it was recorded against", async () => {
    // "Checked against Uniswap" decays quietly: the sentence stays
    // true-sounding while the code it referred to moves on.
    await loaded();
    expect(screen.getByRole("region", { name: /Pinned reference/ })).toBeInTheDocument();
    expect(screen.getByText("v3-core")).toBeInTheDocument();
  });
});

describe("a verification nobody ran", () => {
  it("refuses rather than reporting a pass", async () => {
    serveArtifacts({
      overrides: {
        "vectors.json": withReplay({
          recorded: false,
          reason: "no replay has been recorded — run `make vectors-verify`",
        }),
      },
    });
    await loaded();

    const replay = within(card("Replay"));
    expect(replay.getByText(/Nothing has been recorded for this check/)).toBeInTheDocument();
    expect(replay.getByText(/run `make vectors-verify`/)).toBeInTheDocument();
    // A refusal, not an error: nothing broke and nothing failed. `Refusal` and
    // `ErrorNotice` look different on purpose, and only the latter alerts.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("never shows a case count as though it had been verified", async () => {
    // The failure this whole design exists to prevent: reading the files,
    // counting 19,546, and printing "19,546 comparisons, zero mismatches" —
    // a result nothing observed.
    serveArtifacts({
      overrides: { "vectors.json": withReplay({ recorded: false, reason: "not run" }) },
    });
    await loaded();

    expect(screen.queryByRole("region", { name: /Replay run/ })).not.toBeInTheDocument();
    expect(within(card("Replay")).queryByText("PASS")).not.toBeInTheDocument();
  });

  it("says the differential is unrecorded even though the replay passed", async () => {
    // The two answer different questions and only one has ever been recorded
    // here. `FOR_JUDGES.md` row 1 quotes the differential's headline, so
    // collapsing them is the specific conflation to avoid.
    await loaded();
    expect(screen.getByRole("heading", { name: "Differential" })).toBeInTheDocument();
    expect(screen.getByText(/needs foundry and a local anvil/)).toBeInTheDocument();
  });
});

describe("a recorded run", () => {
  it("reports what pytest said, verbatim", async () => {
    await loaded();
    const replay = real().verification.replay;
    if (!replay.recorded) return; // no receipt committed; the withheld tests cover it

    expect(screen.getByText(String(replay.summary_line))).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /Replay run/ })).toBeInTheDocument();
  });

  it("refuses when the corpus has moved under the receipt", async () => {
    // `make vectors` can regenerate the vectors at any time. A pass recorded
    // before that ran describes files that no longer exist, and it looks
    // exactly like a pass.
    serveArtifacts({
      overrides: {
        "vectors.json": withReplay({
          recorded: true,
          outcome: "PASS",
          summary_line: "10 passed",
          corpus_matches: false,
          corpus_moved: ["constants", "tokens_owed"],
        }),
      },
    });
    await loaded();

    expect(screen.getByText(/recorded run was against a different corpus/)).toBeInTheDocument();
    expect(screen.getByText(/constants, tokens_owed/)).toBeInTheDocument();
    // And it must not also be showing the stale PASS beside the refusal.
    expect(screen.queryByRole("region", { name: /Replay run/ })).not.toBeInTheDocument();
  });

  it("presents a failing replay as a finding, not as a refusal", async () => {
    // A failed replay is the most valuable thing this page can show, and it is
    // not the same as a check that did not happen. Amber is for the second.
    serveArtifacts({
      overrides: {
        "vectors.json": withReplay({
          recorded: true,
          outcome: "FAIL",
          command: "pytest tests/core/test_vectors.py",
          summary_line: "1 failed, 9 passed",
          corpus_matches: true,
          tests_failed: 1,
        }),
      },
    });
    await loaded();

    const replay = within(card("Replay"));
    expect(replay.getByText(/does not reproduce the recorded answers/)).toBeInTheDocument();
    expect(replay.getByText("1 failed, 9 passed")).toBeInTheDocument();
    // Scoped: the differential is genuinely unrecorded in this fixture, so an
    // unscoped query finds its refusal and the assertion means nothing.
    expect(replay.queryByText(/Nothing has been recorded/)).not.toBeInTheDocument();
  });
});
