import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RECORDED_CLIENT, WithWallet, withConnectedWallet } from "@/test/harness";
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
    render(<QuoteView />, { wrapper: WithWallet });

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
    render(<QuoteView />, { wrapper: WithWallet });
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
    render(<QuoteView />, { wrapper: WithWallet });
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
    const { container } = render(<QuoteView stream={STREAM} />, { wrapper: WithWallet });
    await check(user);
    await user.click(await screen.findByRole("button", { name: "Replay this pool" }));

    expect(
      await screen.findByText(/has not said how many replays this is yet/),
    ).toBeInTheDocument();
    // The class, not only the sentence. `.shuttle` is the name the
    // `prefers-reduced-motion` block in globals.css switches off by hand, so a
    // rename that broke the reduced-motion contract would be silent otherwise.
    expect(container.querySelector(".shuttle")).not.toBeNull();

    // No `progressbar` while there is no denominator to report: an
    // indeterminate bar that claimed a value would be claiming the total it
    // was written to avoid claiming.
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();

    status = {
      status: "running",
      progress: { done: 12, total: 60, phase: "replaying" },
      events: 2,
    };
    expect(await screen.findByText("12 of 60 replays")).toBeInTheDocument();
    // Two bars, two claims. Once there is a denominator the indeterminate one
    // must be gone, or the page asserts both at once.
    expect(container.querySelector(".shuttle")).toBeNull();

    // The determinate one is a real progressbar. This is the only genuinely
    // determinate long-running operation on the site, and `aria-valuetext`
    // carries the sentence the page shows rather than a bare percentage.
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "12");
    expect(bar).toHaveAttribute("aria-valuemax", "60");
    expect(bar).toHaveAttribute("aria-valuetext", "12 of 60 replays");
  });

  it("keeps showing progress while the tape loads, which is the longest wait", async () => {
    /**
     * The gap this closes, measured on the deployed instance.
     *
     * A claimed job spends its first minutes in `running` with `total: 0` while
     * the tape loads — nine of them, against a whole job of about seventy-five.
     * The determinate branch needs a denominator it does not have; the
     * indeterminate one was gated on `status === "queued"`. So for the longest
     * single wait in the product, and the one immediately after the only button
     * that commissions work, **neither branch rendered**: a pill reading
     * "running" and blank space under it.
     *
     * The condition is the absence of a denominator, not the name of the state.
     */
    let status: Record<string, unknown> = {
      status: "running",
      progress: { done: 0, total: 0, phase: "loading the tape" },
      events: 1,
    };
    serveApi({
      "/quote/eligibility/": () => json(eligible(holding("0xpoolA", "Pool A"))),
      "/quote/job/": () => json(status),
      "/quote": () => json({ job_id: "job-1", note: "queued" }, 202),
    });
    const user = userEvent.setup();
    const { container } = render(<QuoteView stream={STREAM} />, { wrapper: WithWallet });
    await check(user);
    await user.click(await screen.findByRole("button", { name: "Replay this pool" }));

    // Something is moving, and it names what is being waited for rather than
    // repeating the status word the pill already shows.
    // The bar is the gap. The phase itself was already announced in the status
    // line, which is why this looked like a rendering bug rather than a missing
    // state: the words were there and nothing moved.
    expect(container.querySelector(".shuttle")).not.toBeNull();
    expect(
      await screen.findByText(/the whole tape loads before the first window runs/),
    ).toBeInTheDocument();
    // Still no denominator, so still not a progressbar.
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();

    status = { status: "running", progress: { done: 3, total: 24, phase: "replaying" }, events: 2 };
    expect(await screen.findByText("3 of 24 replays")).toBeInTheDocument();
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
    render(<QuoteView stream={STREAM} />, { wrapper: WithWallet });
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
    render(<QuoteView stream={STREAM} />, { wrapper: WithWallet });
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
    render(<QuoteView stream={STREAM} />, { wrapper: WithWallet });
    await check(user);
    await user.click(await screen.findByRole("button", { name: "Replay this pool" }));
    await waitFor(() => expect(document.documentElement.dataset.tape).toBe("reading"));

    status = { status: "done", progress: { done: 9, total: 9, phase: "" }, events: 2 };
    await waitFor(() => expect(document.documentElement.dataset.tape).toBeUndefined());
  });

  it("releases the tape when the page goes away", async () => {
    twoPools(() => json({}, 500));
    const user = userEvent.setup();
    render(<QuoteView stream={STREAM} />, { wrapper: WithWallet });
    await startFirstPool(user);

    cleanup();
    expect(document.documentElement.dataset.tape).toBeUndefined();
  });
});

describe("a hire shows what the marketplace already has on the pool", () => {
  /**
   * The defect: `POST /quote` returns the pool's completed runs alongside the
   * job id, and this view read `job_id` and `note` and dropped the rest. So a
   * hire on the one pool three agents have replayed showed a progress bar and
   * nothing else — a marketplace with a track record looking like one with
   * none, on the screen where somebody has just asked it for a number.
   */
  // Named, not indexed. `published[0].quote` is `possibly undefined` under
  // `noUncheckedIndexedAccess`, and `tsc` did not say so for as long as this
  // line has existed: `incremental: true` reruns only changed files and their
  // dependents, so a green typecheck was not a checked file. It surfaced the
  // moment an unrelated edit to `test/harness.tsx` — which every test imports
  // — invalidated the cache. Removing the index is the fix; a `!` would have
  // asserted past a warning that was correct.
  const publishedRun = {
    agent: "Grid",
    quote: "21.91% to 31.06% (median 26.40%, annualised)",
    windows: 20,
    perturbations: 3,
    observations: 60,
    net_positive: 60,
  };
  const published = [publishedRun];

  it("prints the published runs while the fresh one is still queued", async () => {
    serveApi({
      "/quote/eligibility/": () => json(eligible(holding("0xpoolA", "Pool A"))),
      "/quote/job/": () => json({ status: "queued", progress: {}, events: 1 }),
      "/quote": () => json({ job_id: "job-1", note: "queued", published }, 202),
    });
    const user = userEvent.setup();
    render(<QuoteView stream={STREAM} />, { wrapper: WithWallet });
    await check(user);
    await user.click(await screen.findByRole("button", { name: "Replay this pool" }));

    expect(await screen.findByText("Grid")).toBeInTheDocument();
    expect(screen.getByText(publishedRun.quote)).toBeInTheDocument();
    // The track record, with its denominator travelling beside it.
    expect(screen.getByText(/60 of 60 observations finished in profit/)).toBeInTheDocument();
    // And the window count on the row, which is what tells a reader this is a
    // full-budget published run rather than the reduced interactive one.
    expect(screen.getByText(/20 windows/)).toBeInTheDocument();
  });

  it("keeps them after the job finishes, which is when they are worth reading", async () => {
    let status: Record<string, unknown> = { status: "queued", progress: {}, events: 1 };
    serveApi({
      "/quote/eligibility/": () => json(eligible(holding("0xpoolA", "Pool A"))),
      "/quote/job/": () => json(status),
      "/quote": () => json({ job_id: "job-1", note: "queued", published }, 202),
    });
    const user = userEvent.setup();
    render(<QuoteView stream={STREAM} />, { wrapper: WithWallet });
    await check(user);
    await user.click(await screen.findByRole("button", { name: "Replay this pool" }));
    expect(await screen.findByText("Grid")).toBeInTheDocument();

    // `/quote/job/{id}` reports the job and knows nothing about the pool's
    // published runs. Spreading its body over the state dropped them at the
    // exact moment there was a fresh number to read them against.
    status = {
      status: "done",
      progress: { done: 8, total: 8, phase: "" },
      events: 2,
      result: { p25: 1, p50: 2, p75: 3, samples: 24, interactive_budget: true },
    };
    expect(await screen.findByText(/Run on the reduced interactive budget/)).toBeInTheDocument();
    expect(screen.getByText("Grid")).toBeInTheDocument();
  });

  it("draws nothing at all when the pool has no published run", async () => {
    serveApi({
      "/quote/eligibility/": () => json(eligible(holding("0xpoolA", "Pool A"))),
      "/quote/job/": () => json({ status: "queued", progress: {}, events: 1 }),
      "/quote": () => json({ job_id: "job-1", note: "queued", published: [] }, 202),
    });
    const user = userEvent.setup();
    render(<QuoteView stream={STREAM} />, { wrapper: WithWallet });
    await check(user);
    await user.click(await screen.findByRole("button", { name: "Replay this pool" }));

    expect(await screen.findByText(/has not said how many replays this is yet/)).toBeInTheDocument();
    // An empty heading over an empty list would read as "we have nothing and
    // want you to notice"; the ordinary case is that most pools have no run.
    expect(screen.queryByText(/Already published for this pool/)).not.toBeInTheDocument();
  });
});


describe("under a scenario, the page reaches nothing", () => {
  /**
   * The end-to-end version of the defect.
   *
   * `lib/api.test.ts` proves `postLive` short-circuits. This proves the *page*
   * uses it — which is the half that was wrong: `enqueue` called `apiBase()` and
   * a raw `fetch` below the scenario layer, so `scenarios/quote-thin-tape.json`
   * could never match and a page displaying the simulation banner talked to
   * production.
   *
   * The assertion that matters is the negative one, and it is only worth
   * anything because the click happens first. The browser gate asserted "zero
   * API requests" on this route for weeks while nothing was ever submitted.
   */
  const fixture = {
    name: "thin",
    label: "A quote the tape cannot support",
    why: "The engine refuses before it starts.",
    responses: {
      // `eligible()`, so the fixture cannot drift from the shape the page
      // reads — `read_at_block` is rendered with `toLocaleString` and a body
      // without it takes the component down rather than failing an assertion.
      "/quote/eligibility/{address}": {
        status: 200,
        body: eligible(holding("0xpool", "WBNB/USDT 0.05%")),
      },
      // `api/quote.py`'s own words, verbatim. The earlier body here was
      // invented prose — "the tape supports 6 windows and 18 observations" —
      // and no code path emits it; `preflight.assess` reports the widest
      // sub-window against the 24h floor. A test that asserts a refusal the
      // service does not word will pass forever and prove nothing about it.
      //
      // The *combination* is constructed on purpose: eligibility and the
      // submit both call `assess`, so a pre-flight that says quotable is
      // followed by a submit that agrees, and this pair cannot arise in
      // production. It is pinned apart here because the POST path is what
      // needs driving, and a holding has to be quotable to draw the button
      // that drives it.
      "POST /quote": {
        status: 409,
        body: {
          detail: {
            error: "the tape cannot support a quote for this pool",
            remedy: "make indexer POOL=0xpool",
            note:
              "the widest sub-window is 4.6h and the engine's floor is 24h — " +
              "shorter than the policy's own horizon, so a replay would measure " +
              "startup rather than strategy",
          },
        },
      },
    },
  };

  it("submits, refuses, and never touches the API", async () => {
    window.history.replaceState({}, "", "/quote?scenario=thin");
    const reached: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/scenarios/")) return json(fixture);
        reached.push(url);
        throw new Error(`a scenario must not reach ${url}`);
      }),
    );

    const user = userEvent.setup();
    render(<QuoteView />, { wrapper: WithWallet });
    await check(user);

    const run = await screen.findByRole("button", { name: /Replay this pool/ }, { timeout: 5000 });
    await user.click(run);

    // The engine's own sentence, rendered — not a generic failure.
    await waitFor(() =>
      expect(
        screen.getByText(/the tape cannot support a quote for this pool/),
      ).toBeInTheDocument(),
    );
    // And the load-bearing half, which now means something because a POST was
    // actually attempted above.
    expect(reached).toHaveLength(0);

    window.history.replaceState({}, "", "/quote");
  });
});

describe("the connected-wallet offer", () => {
  it("offers to fill the address in, once the page has mounted", async () => {
    // This route was the last place in the app rendering wagmi account state
    // during render. The server emits that paragraph as one text node, so a
    // wallet present on the first client render turns it into a three-child
    // array and React error #418 — which `ConnectButton`'s docstring exists to
    // forbid. The fix is a `mounted` gate, and the way a `mounted` gate goes
    // wrong is by never opening, so the offer is asserted to still arrive.
    serveApi({});
    render(<QuoteView />, { wrapper: withConnectedWallet() });

    const offer = await screen.findByRole("button", { name: "Use my connected wallet" });
    await userEvent.click(offer);
    expect(screen.getByLabelText("Wallet address")).toHaveValue(RECORDED_CLIENT);
  });

  it("makes no offer when no wallet is connected", async () => {
    serveApi({});
    render(<QuoteView />, { wrapper: WithWallet });

    expect(await screen.findByLabelText("Wallet address")).toHaveValue("");
    expect(
      screen.queryByRole("button", { name: "Use my connected wallet" }),
    ).not.toBeInTheDocument();
  });
});

describe("arriving from the guided run", () => {
  /**
   * `/demo` used to send a judge to an empty form and tell them to press a
   * button that is not rendered until an address has been submitted. The
   * fixture answers for any address, so the link carries one now and the page
   * runs it on arrival — under a scenario, which issues no request at all.
   */
  const ADDRESS = "0x000000000000000000000000000000000000dEaD";

  const fixture = {
    name: "guided",
    label: "A quote the tape can support",
    // `activeScenario` requires both `label` and `why` to be strings and
    // silently resolves to null without them — which sends the read to the real
    // API base instead of the fixture. A scenario that does not describe itself
    // is not a scenario.
    why: "The recorded answer, so the guided run lands on one.",
    responses: {
      "/quote/eligibility/{address}": {
        status: 200,
        body: eligible(holding("0xabc", "USDT/USDC 0.01%")),
      },
    },
  };

  afterEach(() => window.history.replaceState({}, "", "/quote"));

  it("fills the address in and shows the answer without a submit", async () => {
    window.history.replaceState(
      {},
      "",
      `/quote?scenario=guided&address=${ADDRESS}`,
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/scenarios/")) return json(fixture);
        throw new Error(`a scenario must not reach ${url}`);
      }),
    );

    render(<QuoteView />, { wrapper: WithWallet });

    expect(await screen.findByDisplayValue(ADDRESS)).toBeInTheDocument();
    // The point of the change: a rendered answer, with nothing pressed.
    expect(
      await screen.findByRole("button", { name: /Replay this pool/ }, { timeout: 5000 }),
    ).toBeInTheDocument();
  });

  it("fills the address in but does not read it when there is no scenario", async () => {
    // Without a fixture this would be a live call to a stranger's wallet, made
    // because a link said so. The page's promise is that it asks for nothing it
    // was not given.
    window.history.replaceState(
      {},
      "",
      `/quote?address=${ADDRESS}`,
    );
    const reached: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        reached.push(String(input));
        throw new Error("no read should happen");
      }),
    );

    render(<QuoteView />, { wrapper: WithWallet });

    expect(await screen.findByDisplayValue(ADDRESS)).toBeInTheDocument();
    expect(reached.filter((u) => u.includes("/quote/eligibility/"))).toEqual([]);
  });
});
