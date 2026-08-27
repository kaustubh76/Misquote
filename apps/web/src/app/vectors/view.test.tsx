import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readArtifact, serveArtifacts } from "@/test/harness";
import { VectorsView } from "./view";

vi.mock("next/navigation", () => ({ usePathname: () => "/vectors" }));

interface Artifact {
  corpus: {
    cases: number;
    groups: { group: string; cases: number }[];
    pins: unknown[];
  };
  verification: {
    replay: Record<string, unknown>;
    differential: Record<string, unknown>;
  };
  build: unknown;
}

const real = () => readArtifact<Artifact>("vectors.json");

/** The published artifact with one verification block replaced. */
function withReplay(replay: Record<string, unknown>) {
  const d = real();
  return { ...d, verification: { ...d.verification, replay } };
}

/** The same, for the other run. Both are recorded on the committed artifact
 *  now, so the withheld and failing states need fixtures on either side. */
function withDifferential(differential: Record<string, unknown>) {
  const d = real();
  return { ...d, verification: { ...d.verification, differential } };
}

beforeEach(() => serveArtifacts());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function loaded() {
  // `VectorsView` without `initial`, not `VectorsPage`, and that is the whole
  // fix rather than a stylistic preference.
  //
  // The page prerenders: `page.tsx` passes `readArtifact("vectors.json")` from
  // disk, so `state` is already loaded on first paint and `aria-busy` is false
  // immediately. The wait below then returns **before** the client fetch — the
  // one `serveArtifacts` overrides — has resolved, and every assertion runs
  // against whatever this repository's real artifact happens to say. Where that
  // agrees with the override the test passes by luck; where it does not, it
  // fails. Measured at one failure in five runs of this file.
  //
  // The comment this replaces already recorded the symptom — "exactly one
  // failure in four full runs, which is the worst possible amount" — and fixed
  // the wrong half of it, moving from the h1 to `aria-busy` while the render
  // still supplied the data the wait was meant to be waiting for.
  //
  // With no `initial`, the page starts busy and the wait means what it says. A
  // test wanting the published artifact still gets it: `serveArtifacts()` serves
  // the real files unless something is overridden.
  render(<VectorsView />);
  await waitFor(() =>
    expect(document.querySelector("[aria-busy='true']")).not.toBeInTheDocument()
  );
}

/**
 * One verification card, by its title.
 *
 * Both cards can be in the same state at once — the committed artifact now has
 * a recorded replay *and* a recorded differential, and for a long time it had
 * only the first — so an unscoped `getByText(...)` either finds two elements or
 * finds the wrong one. Every assertion about a verification has to name which.
 */
const card = (title: string) =>
  screen.getByRole("heading", { name: title }).closest("section")!;

describe("the corpus is stated as a corpus", () => {
  it("shows every group and its case count from the artifact", async () => {
    await loaded();
    const region = screen.getByRole("region", {
      name: /Recorded vectors by function/,
    });

    for (const g of real().corpus.groups) {
      expect(within(region).getByText(g.group)).toBeInTheDocument();
    }
    // Read, never written into the page. `docs/FOR_JUDGES.md` quotes 19,546
    // and the two must not be able to disagree.
    expect(
      within(region).getAllByText(real().corpus.cases.toLocaleString("en-US"))
        .length
    ).toBeGreaterThan(0);
  });

  it("names the upstream commits it was recorded against", async () => {
    // "Checked against Uniswap" decays quietly: the sentence stays
    // true-sounding while the code it referred to moves on.
    await loaded();
    expect(
      screen.getByRole("region", { name: /Pinned reference/ })
    ).toBeInTheDocument();
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
    expect(
      replay.getByText(/Nothing has been recorded for this check/)
    ).toBeInTheDocument();
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
      overrides: {
        "vectors.json": withReplay({ recorded: false, reason: "not run" }),
      },
    });
    await loaded();

    expect(
      screen.queryByRole("region", { name: /Replay run/ })
    ).not.toBeInTheDocument();
    expect(within(card("Replay")).queryByText("PASS")).not.toBeInTheDocument();
  });

  it("refuses the differential on its own terms, not the replay's", async () => {
    // This asserted against the committed artifact that the differential had
    // never been run — true for as long as nothing could write its receipt, and
    // false the moment one did. The durable claim is the one it was reaching
    // for: the two answer different questions, and a page that has recorded one
    // must still refuse the other rather than let a passing replay stand in.
    //
    // `FOR_JUDGES.md` row 1 quotes the differential's headline, so that
    // substitution is the specific one to prevent.
    serveArtifacts({
      overrides: {
        "vectors.json": withDifferential({
          recorded: false,
          reason:
            "no differential run has been recorded — `make vectors-check` needs foundry",
        }),
      },
    });
    await loaded();

    const differential = within(card("Differential"));
    expect(
      differential.getByText(/Nothing has been recorded for this check/)
    ).toBeInTheDocument();
    expect(differential.getByText(/make vectors-check/)).toBeInTheDocument();
    // The replay is recorded in this fixture and must not lend its pass across.
    expect(differential.queryByText("PASS")).not.toBeInTheDocument();
  });

  it("gives each run its own remedy, and never the other one's", async () => {
    // `VerificationCard` had one caller for as long as the differential could
    // not be recorded, and had hardcoded that caller in three places: the table
    // row read "pytest said" for a run that never invokes pytest, the stale
    // branch told a reader to re-run `make vectors-verify` whichever check had
    // gone stale, and the failure banner described the replay.
    //
    // Both stale, both scoped, so neither can be satisfied by the other card.
    serveArtifacts({
      overrides: {
        "vectors.json": {
          ...real(),
          verification: {
            replay: {
              recorded: true,
              corpus_matches: false,
              corpus_moved: ["constants"],
            },
            differential: {
              recorded: true,
              corpus_matches: false,
              corpus_moved: ["constants"],
            },
          },
        },
      },
    });
    await loaded();

    expect(
      within(card("Replay")).getByText(/make vectors-verify/)
    ).toBeInTheDocument();
    expect(
      within(card("Replay")).queryByText(/make vectors-check/)
    ).not.toBeInTheDocument();
    expect(
      within(card("Differential")).getByText(/make vectors-check/)
    ).toBeInTheDocument();
    expect(
      within(card("Differential")).queryByText(/make vectors-verify/)
    ).not.toBeInTheDocument();
  });

  it("does not attribute the differential's summary to pytest", async () => {
    // The third hardcoded string, and the one a mutation run walked straight
    // through: the table row said "pytest said" on both cards, for a run that
    // spawns anvil and forge and never invokes pytest. Asserted against the
    // committed artifact, which now records both.
    const both = real().verification;
    if (!both.replay.recorded || !both.differential.recorded) return;

    await loaded();
    expect(within(card("Replay")).getByText("pytest said")).toBeInTheDocument();
    expect(
      within(card("Differential")).queryByText("pytest said")
    ).not.toBeInTheDocument();
  });
});

describe("a recorded run", () => {
  it("reports what pytest said, verbatim", async () => {
    await loaded();
    const replay = real().verification.replay;
    if (!replay.recorded) return; // no receipt committed; the withheld tests cover it

    expect(screen.getByText(String(replay.summary_line))).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /Replay run/ })
    ).toBeInTheDocument();
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

    expect(
      screen.getByText(/recorded run was against a different corpus/)
    ).toBeInTheDocument();
    expect(screen.getByText(/constants, tokens_owed/)).toBeInTheDocument();
    // And it must not also be showing the stale PASS beside the refusal.
    expect(
      screen.queryByRole("region", { name: /Replay run/ })
    ).not.toBeInTheDocument();
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
    expect(
      replay.getByText(/does not reproduce the recorded answers/)
    ).toBeInTheDocument();
    expect(replay.getByText("1 failed, 9 passed")).toBeInTheDocument();
    // Scoped, because both cards render through one component and an unscoped
    // query cannot say which one it found.
    expect(
      replay.queryByText(/Nothing has been recorded/)
    ).not.toBeInTheDocument();
  });
});
