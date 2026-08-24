import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QuoteView } from "./view";

/**
 * `/quote`'s first behavioural coverage.
 *
 * `scripts/check-pages.mjs` has always held this route to a 1,200-character
 * no-JS floor and the needle "not a button that returns a number", so its
 * *prerender* was guarded. Nothing watched what it does after that — and it is
 * the only route on the site with a form, an async state machine, an SSE
 * subscription, refusal handling and a live side effect on `documentElement`.
 * Everything that can go wrong here was unwatched, and something had: with more
 * than one quotable pool the tape stopped reporting the running job, silently.
 *
 * ## Why the fetch is stubbed here rather than through `serveArtifacts`
 *
 * The harness serves `/artifacts/*` and **throws** on anything else, which is
 * every request this page makes. `/quote` reads a live API, not an artifact.
 * `apiBase()` checks `window.__MISQUOTE_API__` *before* its module-scope memo,
 * which is the seam a demo uses to repoint a built export — so this file drives
 * the page the way a deployment does rather than around it. Overriding
 * `api.json` instead would not work: the memo is per module registry, so the
 * first test in the file would decide the base for every test after it.
 *
 * ## Why `eventSource: null` is passed explicitly
 *
 * `lib/stream.ts` resolves its transport from `typeof EventSource` when it is
 * not told. jsdom has none, so the polling branch would be taken by accident —
 * and the day jsdom ships one, these tests would start exercising a path they
 * have no fixture for and hang until the timeout instead of failing. Naming the
 * branch keeps it named. `pollMs` comes with it: the production default is two
 * seconds, and a suite that waits two of those per progress event is the flake
 * class `vitest.config.ts` is written around.
 */
const BASE = "https://api.example.test";

beforeEach(() => vi.stubGlobal("__MISQUOTE_API__", BASE));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  // `documentElement` is shared by every test in this worker, and this page
  // writes to it. Not clearing it would let one test's tape decide the next
  // one's assertion.
  delete document.documentElement.dataset.tape;
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

/**
 * The live API as a table of path prefixes, matched longest-first.
 *
 * Longest-first rather than in declaration order, because `/quote` is a prefix
 * of `/quote/job/` and `/quote/eligibility/`: an insertion-ordered match would
 * route a job poll to the enqueue handler and the failure would look like a
 * state-machine bug. Anything unrouted throws by name, loudly, rather than
 * resolving to undefined three awaits later.
 */
function serveApi(routes: Record<string, () => Response>) {
  const byLength = Object.entries(routes).sort((a, b) => b[0].length - a[0].length);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      for (const [suffix, reply] of byLength) {
        if (url.startsWith(`${BASE}${suffix}`)) return reply();
      }
      throw new Error(`unstubbed fetch: ${url}`);
    }),
  );
}

const holding = (pool: string, label: string) => ({
  pool,
  label,
  positions: 2,
  open_positions: 1,
  quotable: true,
  why_not: [],
});

const eligible = (...holdings: ReturnType<typeof holding>[]) => ({
  owner: "0xabc",
  read_at_block: 45_000_000,
  held: holdings.length,
  in_unverified_pools: 0,
  holdings,
});

/** Type an address and submit. The only way into every other state. */
async function check(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Wallet address"), "0xabc");
  await user.click(screen.getByRole("button", { name: "Check my positions" }));
}

const STREAM = { eventSource: null, pollMs: 20 } as const;

describe("the form asks for an address and promises nothing else", () => {
  it("will not submit an empty address, and says it needs no key", () => {
    serveApi({});
    render(<QuoteView />);

    expect(screen.getByLabelText("Wallet address")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Check my positions" })).toBeDisabled();
    // The one sentence on this page that is a promise rather than a
    // description. A form that asked for an address and lost this line would
    // look identical to one about to ask for a signature.
    expect(
      screen.getByText(/never asks for a key, a signature, or an approval/),
    ).toBeInTheDocument();
  });
});

describe("a refusal for a wallet is an answer, not a fault", () => {
  it("renders the engine's sentence and its remedy, and raises no alert", async () => {
    serveApi({
      "/quote/eligibility/": () =>
        json(
          {
            detail: {
              error: "no indexed pool holds a position for this address",
              remedy: "the pools that would work are listed on /vetting",
            },
          },
          409,
        ),
    });
    const user = userEvent.setup();
    render(<QuoteView />);
    await check(user);

    expect(
      await screen.findByText(/no indexed pool holds a position/),
    ).toBeInTheDocument();
    expect(screen.getByText(/listed on \/vetting/)).toBeInTheDocument();
    // The whole claim in one line. `ErrorNotice` sets `role="alert"` and
    // `Refusal` does not, and that single difference is what separates "we
    // considered this and declined" from "something broke".
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does raise an alert when nothing answered at all", async () => {
    // Asserted alongside the refusal above, because the refusal test proves
    // nothing on its own if every state on this page is quiet.
    serveApi({ "/quote/eligibility/": () => json({ detail: { error: "boom" } }, 503) });
    const user = userEvent.setup();
    render(<QuoteView />);
    await check(user);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});

describe("a queued job draws no denominator it has not been given", () => {
  it("shuttles while queued, and measures once a total arrives", async () => {
    // `progress` and `events`, because that is what the polling fallback reads:
    // it lifts `body.progress` into the event payload and emits only when
    // `body.events` changes. A fixture with top-level `done`/`total` and no
    // sequence number produces no events at all, which looks like a broken
    // state machine and is a broken fixture.
    let status: Record<string, unknown> = { status: "queued", progress: {}, events: 1 };
    serveApi({
      "/quote/eligibility/": () => json(eligible(holding("0xpoolA", "Pool A"))),
      "/quote/job/": () => json(status),
      "/quote": () => json({ job_id: "job-1", note: "queued behind 0" }, 202),
    });
    const user = userEvent.setup();
    const { container } = render(<QuoteView stream={STREAM} />);
    await check(user);
    await user.click(await screen.findByRole("button", { name: "Replay this pool" }));

    expect(
      await screen.findByText(/has not said how many replays this is yet/),
    ).toBeInTheDocument();
    // The class, not only the sentence. `.shuttle` is the name the
    // `prefers-reduced-motion` block in globals.css switches off by hand, so a
    // rename that broke the reduced-motion contract would be silent otherwise.
    expect(container.querySelector(".shuttle")).not.toBeNull();

    status = {
      status: "running",
      progress: { done: 12, total: 60, phase: "replaying" },
      events: 2,
    };
    expect(await screen.findByText("12 of 60 replays")).toBeInTheDocument();
    // Two bars, two claims. Once there is a denominator the indeterminate one
    // must be gone, or the page asserts both at once.
    expect(container.querySelector(".shuttle")).toBeNull();
  });
});

describe("the tape belongs to whichever pool is still running", () => {
  /**
   * The defect this was written against: one effect per card, writing one
   * attribute on `document.documentElement`, keyed on that card's own phase.
   * With one pool it is correct. With two it is last-writer-wins, and the loser
   * is always the card doing work.
   *
   * `QuoteView` is rendered rather than `QuoteRun`, deliberately. The bug lives
   * in the composition — siblings under one `Result` — so a test that mounted
   * `QuoteRun` twice by hand would be testing an arrangement the app never
   * makes.
   */
  function twoPools(second: () => Response) {
    let posts = 0;
    serveApi({
      "/quote/eligibility/": () =>
        json(eligible(holding("0xpoolA", "Pool A"), holding("0xpoolB", "Pool B"))),
      "/quote/job/": () =>
        json({ status: "running", progress: { done: 1, total: 9, phase: "replaying" }, events: 1 }),
      "/quote": () => (posts++ === 0 ? json({ job_id: "job-1" }, 202) : second()),
    });
  }

  async function startFirstPool(user: ReturnType<typeof userEvent.setup>) {
    await check(user);
    const buttons = await screen.findAllByRole("button", { name: "Replay this pool" });
    await user.click(buttons[0]!);
    await waitFor(() => expect(document.documentElement.dataset.tape).toBe("reading"));
    return buttons;
  }

  it("keeps reading when a second pool is refused", async () => {
    twoPools(() =>
      json(
        { detail: { error: "the tape cannot support a quote here", remedy: "index it first" } },
        409,
      ),
    );
    const user = userEvent.setup();
    render(<QuoteView stream={STREAM} />);
    const buttons = await startFirstPool(user);

    await user.click(buttons[1]!);
    expect(await screen.findByText(/the tape cannot support a quote here/)).toBeInTheDocument();

    // `refused` sets `--tape-rate: 0s`, which stops the tape. Pool A is still
    // replaying, so a stopped tape is a false picture drawn by the one surface
    // whose whole job is to say what is happening.
    expect(document.documentElement.dataset.tape).toBe("reading");
  });

  it("keeps reading when a second pool fails to start", async () => {
    twoPools(() => json({}, 500));
    const user = userEvent.setup();
    render(<QuoteView stream={STREAM} />);
    const buttons = await startFirstPool(user);

    await user.click(buttons[1]!);
    // The failing card's cleanup used to delete the attribute outright.
    // Any alert will do: the assertion under test is the tape, and scoping to
    // pool B's card would key on a heading its label also produces in the
    // holdings list above.
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(document.documentElement.dataset.tape).toBe("reading");
  });

  it("stops when the job stops, not at the next phase change", async () => {
    // `onFinished` calls `setState({ phase: "watching", … })` — the same string
    // it was already on — so an effect keyed on the phase never re-ran when a
    // job ended and the whole site kept running at replay speed with nothing
    // behind it. The claim comes off `job.status` now.
    let status: Record<string, unknown> = {
      status: "running",
      progress: { done: 1, total: 9, phase: "replaying" },
      events: 1,
    };
    serveApi({
      "/quote/eligibility/": () => json(eligible(holding("0xpoolA", "Pool A"))),
      "/quote/job/": () => json(status),
      "/quote": () => json({ job_id: "job-1" }, 202),
    });
    const user = userEvent.setup();
    render(<QuoteView stream={STREAM} />);
    await check(user);
    await user.click(await screen.findByRole("button", { name: "Replay this pool" }));
    await waitFor(() => expect(document.documentElement.dataset.tape).toBe("reading"));

    status = { status: "done", progress: { done: 9, total: 9, phase: "" }, events: 2 };
    await waitFor(() => expect(document.documentElement.dataset.tape).toBeUndefined());
  });

  it("releases the tape when the page goes away", async () => {
    twoPools(() => json({}, 500));
    const user = userEvent.setup();
    render(<QuoteView stream={STREAM} />);
    await startFirstPool(user);

    cleanup();
    expect(document.documentElement.dataset.tape).toBeUndefined();
  });
});
