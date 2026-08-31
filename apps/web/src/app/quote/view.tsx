"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "wagmi";
import { Band } from "@/components/Band";
import { ObservationGrid } from "@/components/ObservationGrid";
import { Button } from "@/components/Button";
import { Card, CardHeader } from "@/components/Card";
import { Section } from "@/components/Heading";
import { Pill } from "@/components/Pill";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { AnsweredBy } from "@/components/AnsweredBy";
import { loadLive, postLive, RefusalError, type Source } from "@/lib/api";
import { count, hours, isNum, pct } from "@/lib/format";
import {
  isFinished,
  type JobEvent,
  type StreamOptions,
  subscribe,
} from "@/lib/stream";

/** One pool the wallet holds a position in, as `/quote/eligibility` reports it. */
interface Holding {
  pool: string;
  label: string;
  positions: number;
  open_positions: number;
  quotable: boolean;
  why_not: string[];
}

/**
 * A run this marketplace already published for the pool being hired.
 *
 * Not a cache of the job just queued, and deliberately not rendered as one.
 * The job replays the engine's *default* policy on the reduced interactive
 * budget; these are named agents at the count each card publishes, already
 * replayed over the tape and stamped with the commit that produced them. So
 * they answer a different question — what has this marketplace got on this
 * pool — and the answer arrives in the time an HTTP request takes.
 *
 * `quote` is a sentence rather than an object because `api/quote.py` skips any
 * card without a `quote_detail`: Router's record is allocation-shaped and its
 * quote is an object, and letting it through here would put one where a string
 * is typed.
 */
interface PublishedRun {
  agent: string;
  quote: string;
  windows?: number;
  perturbations?: number;
  observations?: number;
  net_positive?: number;
}

/**
 * The 202 from `POST /quote`.
 *
 * Typed because it stopped being an untyped `await res.json()` off a raw fetch:
 * `published` was on the wire and dropped at this boundary once already, which
 * made a marketplace with agents on this pool look like one with none.
 */
interface QuoteSubmission {
  job_id?: string;
  note?: string;
  published?: unknown;
}

/** A job as `/quote/job/{id}` reports it. */
interface JobView {
  jobId: string;
  status: string;
  done: number;
  total: number;
  phase: string;
  note: string;
  /**
   * Why the engine declined, with the two figures behind it.
   *
   * `windows` and `samples` were on the wire and not on this type
   * (`ops/quote_job.py` writes both into the refusal), so the withheld branch
   * could print the sentence and not the shortfall — on the one page where a
   * reader has just asked for the number and is being told no.
   */
  refusal?: { note?: string; remedy?: string; windows?: number; samples?: number };
  /**
   * What the marketplace already has on this pool, from the 202.
   *
   * It was on the wire and dropped at this boundary, so a hire showed a
   * progress bar and nothing else — which made a marketplace with agents on
   * this pool look like one with none, on the screen where somebody has just
   * asked it for a number.
   */
  published?: PublishedRun[];
  /**
   * The quote, as the worker publishes it.
   *
   * This declared five fields of thirteen. The worker writes `windows`,
   * `perturbations`, `hours_per_window`, `net_positive`, `annualised`, `basis`
   * and `note` onto the same object, and `AgentCard` prints four of them
   * directly under its own band — so every other quote on this site says how
   * many windows it came from and how many finished in profit, and the live one
   * said neither. Not scope creep: it is what lets this page make the same
   * claim in the same words.
   *
   * `distinct_returns` is a count, not an array. There is no `returns[]` for a
   * job, which is why the band below draws no rug.
   */
  result?: {
    p25: number;
    p50: number;
    p75: number;
    samples: number;
    interactive_budget: boolean;
    windows?: number;
    perturbations?: number;
    hours_per_window?: number;
    net_positive?: number;
    distinct_returns?: number;
    annualised?: boolean;
    basis?: string;
    note?: string;
  };
}

interface Eligibility {
  owner: string;
  read_at_block: number;
  held: number;
  in_unverified_pools: number;
  holdings: Holding[];
}

type State =
  | { phase: "idle" }
  | { phase: "reading" }
  | { phase: "done"; value: Eligibility; source: Source }
  | { phase: "refused"; error: RefusalError }
  | { phase: "failed"; message: string };

/**
 * The pre-flight, not the quote.
 *
 * `replay/ranges.py::quote()` documents its own cost — 4.6 hours for four
 * agents on the 30-day tape — and is process-global non-reentrant, so a quote
 * is a job and not a request. This page is deliberately the half that can
 * answer immediately: which of your positions sit in pools we have verified,
 * and whether each pool's tape could support a replay at all.
 *
 * That ordering is the point rather than a limitation. A refusal that arrives
 * in a hundred milliseconds and names the missing tape is worth more than a
 * spinner that resolves into the same refusal twenty minutes later.
 */
/**
 * How a job is watched. Injected, and only ever by a test.
 *
 * `lib/stream.ts` has carried an `eventSource` option since it was written —
 * "**EventSource does not exist in jsdom**, and cannot be stubbed by the fetch
 * mock", "Injected in tests" — and the seam stopped one component short of its
 * only call site, so nothing could reach it and the module's docstring
 * described a suite that did not exist. Three props, no logic.
 *
 * Passing `{ eventSource: null }` is not the same as letting jsdom's missing
 * global decide. The default resolves the branch from `typeof EventSource`, so
 * the day jsdom ships one, a suite written against the polling path would
 * silently start exercising a path it has no fixture for and hang until the
 * timeout instead of failing. A test that names its branch keeps naming it.
 */
export function QuoteView({ stream }: { stream?: StreamOptions } = {}) {
  const [address, setAddress] = useState("");

  // Offered, never filled in. This form's own promise is that it asks for
  // nothing, and silently populating it with an address the page learned from
  // a wallet connection would be the page taking something rather than being
  // given it. One click is the whole difference and it is the honest one.
  const { address: connected } = useAccount();
  const [state, setState] = useState<State>({ phase: "idle" });

  async function check(event: React.FormEvent) {
    event.preventDefault();
    const wanted = address.trim();
    if (!wanted) return;

    setState({ phase: "reading" });
    // No fallback artifact, deliberately. There is no precomputed answer for a
    // stranger's wallet, and `loadLive` returning a snapshot here would be
    // answering a question nobody asked about an address nobody indexed.
    const got = await loadLive<Eligibility>(`/quote/eligibility/${wanted}`);

    if (got.ok) return setState({ phase: "done", value: got.value, source: got.source });
    if (got.error instanceof RefusalError) {
      return setState({ phase: "refused", error: got.error });
    }
    setState({ phase: "failed", message: got.error.message });
  }

  return (
    <>
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">
        What would these agents have done with your positions?
      </h1>
      <p className="mt-4 max-w-[62ch] text-md text-dim">
        Paste an address. This reads the positions it actually holds on chain, and
        checks each against the indexed tape — so a quote that could not be
        supported is refused <strong className="text-ink">before</strong> it is
        queued rather than after.
      </p>

      <Section
        title="Why this is not a button that returns a number"
        className="mt-8"
        headingClassName="text-lg font-semibold"
      >
        <p className="mt-2 mb-0 max-w-[62ch] text-dim">
          A quote is a replay of each agent&rsquo;s policy across overlapping
          sub-windows of real history, at several parameter settings. Over a
          month of tape that is hours of arithmetic, not milliseconds, and the
          engine refuses to run two at once in the same process. So the honest
          shape is a pre-flight now and a job afterwards —{" "}
          <Link href="/methods">how a quote is made</Link> sets out the windows
          and the floors it has to clear.
        </p>
      </Section>

      <form onSubmit={check} className="mt-8 max-w-xl">
        <label htmlFor="wallet" className="block text-sm font-medium text-ink">
          Wallet address
        </label>
        <div className="mt-2 flex flex-wrap gap-2">
          <input
            id="wallet"
            name="wallet"
            type="text"
            inputMode="text"
            autoComplete="off"
            spellCheck={false}
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="0x…"
            className="min-w-0 flex-1 rounded-md border border-glass-line bg-glass px-3 py-2.5 font-mono text-sm text-ink transition-colors placeholder:text-faint focus:border-brand focus:shadow-[inset_3px_0_0_0_var(--brand)]"
          />
          <Button
            type="submit"
            disabled={state.phase === "reading" || !address.trim()}
          >
            {state.phase === "reading" ? "Reading chain…" : "Check my positions"}
          </Button>
        </div>
        <p className="mt-2 mb-0 text-xs text-faint">
          Read-only. This never asks for a key, a signature, or an approval.
          {connected && !address && (
            <>
              {" "}
              <button
                type="button"
                onClick={() => setAddress(connected)}
                className="underline underline-offset-2"
              >
                Use my connected wallet
              </button>
            </>
          )}
        </p>
      </form>

      <div className="mt-8" aria-busy={state.phase === "reading"}>
        {state.phase === "reading" && (
          <p role="status" className="text-sm text-dim">
            Reading positions from chain…
          </p>
        )}

        {state.phase === "refused" && (
          <Refusal
            title="No quote for this address"
            reason={state.error.message}
            floor={state.error.remedy || undefined}
          />
        )}

        {state.phase === "failed" && (
          <ErrorNotice
            title="Could not read this wallet"
            detail={state.message}
            remedy={
              <>
                This page needs the live API. Start it with{" "}
                <code className="font-mono text-xs">make api</code> and publish its
                address with <code className="font-mono text-xs">make api-config</code>.
              </>
            }
          />
        )}

        {state.phase === "done" && (
          <Result value={state.value} source={state.source} stream={stream} />
        )}
      </div>
    </>
  );
}

function Result({
  value,
  source,
  stream,
}: {
  value: Eligibility;
  source: Source;
  stream?: StreamOptions;
}) {
  return (
    <Section title="What this wallet holds" headingClassName="text-lg font-semibold">
      {/* `loadLive` is called here with no fallback, deliberately — there is no
          precomputed answer for a stranger's wallet — so this reads "answered
          live" every time it renders at all. That is not a reason to omit it:
          the claim a reader needs is that a service read their positions from
          chain just now, and the alternative to seeing it is assuming it. */}
      <AnsweredBy source={source} className="mt-2" />
      <p className="mt-2 mb-5 max-w-[62ch] text-sm text-dim">
        {value.held} position{value.held === 1 ? "" : "s"} at block{" "}
        <span className="tabular">{value.read_at_block.toLocaleString("en-US")}</span>.{" "}
        {value.in_unverified_pools > 0 && (
          <>
            {value.in_unverified_pools} of them sit in pools this repository has not
            verified and cannot replay — a pool&rsquo;s fee tier and protocol cut
            decide what its swaps mean, so an unchecked one produces a complete,
            plausible, wrongly-denominated answer.
          </>
        )}
      </p>

      {value.holdings.length === 0 ? (
        <Refusal
          title="Nothing here can be quoted"
          reason="This wallet holds no position in a pool this repository has verified and indexed."
          floor="The pools that would work are listed on /vetting."
        />
      ) : (
        <div className="grid gap-4">
          {value.holdings.map((h) => (
            <Card key={h.pool} as="article">
              <CardHeader
                title={h.label || h.pool}
                // `normal-case`: the eyebrow is uppercased by default, which is
                // right for a category and wrong for a hex address — it rendered
                // "0X36696169…", and a checksummed address is not case-noise,
                // it is the address.
                eyebrow={<span className="normal-case">{h.pool}</span>}
                aside={
                  <Pill tone={h.quotable ? "pass" : "none"}>
                    {h.quotable ? "Tape supports a quote" : "Not quotable yet"}
                  </Pill>
                }
              />
              <p className="m-0 text-sm text-dim">
                {h.positions} position{h.positions === 1 ? "" : "s"}, {h.open_positions}{" "}
                still open.
              </p>
              {h.why_not.length > 0 && (
                <ul className="mt-3 mb-0 list-none space-y-1 p-0 text-sm text-warn">
                  {h.why_not.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              )}
            </Card>
          ))}
        </div>
      )}

      {/* A `Section`, like the other two on this page. It was a bare `Heading`
          followed by an intro paragraph followed by a list of cards, which is
          the shape `Section` exists for — so it carried no `TickRule`, and its
          heading level came from context rather than from a section that would
          deepen it, leaving "Run one" at the same depth as the pool cards
          underneath it. */}
      <Section
        title="Run one"
        className="mt-8"
        headingClassName="mb-2 text-md font-semibold"
        intro={
          <>
            A replay is minutes of arithmetic, not milliseconds, and it needs a worker
            draining the queue (<code className="font-mono text-xs">make api-worker</code>).
            Progress below is the job&rsquo;s own event log, so closing this page does
            not lose it — reopening replays from where it got to.
          </>
        }
      >
        {value.holdings
          .filter((h) => h.quotable)
          .map((h) => (
            <QuoteRun key={h.pool} pool={h.pool} label={h.label} stream={stream} />
          ))}
      </Section>
    </Section>
  );
}


type RunState =
  | { phase: "idle" }
  | { phase: "queueing" }
  | {
      phase: "watching";
      job: JobView;
      /**
       * The 202 came from a scenario, so there is no stream behind it.
       *
       * Carried on the state rather than re-derived, because the thing that
       * knows is the answer `postLive` already returned, and asking the URL
       * again would be a second source of truth for one fact.
       */
      simulated?: boolean;
    }
  | { phase: "refused"; reason: string; remedy: string }
  | { phase: "failed"; message: string };

/**
 * Enqueue one pool's replay and watch it.
 *
 * The 409 path is the one worth reading closely. `POST /quote` runs the
 * engine's own sufficiency check before minting a job id, so a tape that cannot
 * support a quote comes back as a refusal in a hundred milliseconds rather than
 * as a job that resolves into one twenty minutes later. That refusal renders as
 * a `Refusal`, not an `ErrorNotice` — nothing broke.
 */
/**
 * What each replay card is currently claiming about the tape, keyed by pool.
 *
 * Module-level rather than React state on purpose: the thing being coordinated
 * is a single attribute on `document.documentElement`, which is outside every
 * component's tree and shared by every route. Lifting it into a context would
 * put a provider on the layout for one attribute that only `/quote` writes.
 */
type TapeClaim = "reading" | "refused";
const TAPE_CLAIMS = new Map<string, TapeClaim>();

/**
 * The root attribute, recomputed from every claim rather than assigned by one.
 *
 * A running job outranks a refused one: if any pool is still being replayed the
 * head is reading, whatever a finished sibling concluded. The amber only shows
 * once nothing is running and something was refused — which is when it is the
 * page's actual state rather than one card's.
 */
function applyTape(): void {
  const claims = [...TAPE_CLAIMS.values()];
  const next = claims.includes("reading")
    ? "reading"
    : claims.includes("refused")
      ? "refused"
      : null;

  const root = document.documentElement;
  if (next) root.dataset.tape = next;
  else delete root.dataset.tape;
}

function QuoteRun({
  pool,
  label,
  stream,
}: {
  pool: string;
  label: string;
  stream?: StreamOptions;
}) {
  const [state, setState] = useState<RunState>({ phase: "idle" });

  /*
   * The tape is the status indicator, and one card may not speak for the page.
   *
   * `.tape` in globals.css draws the event tape this product replays, drifting
   * at `--tape-rate`. While a replay job is running the read head is reading,
   * and the backdrop is the one surface that can say so without another widget
   * competing with the progress bar. A refusal stops the tape and turns the
   * head amber. The attribute is all this writes: the rates and the amber live
   * in globals.css under `:root[data-tape=…]`, so a colour keeps one home.
   *
   * The first version of this assigned `root.dataset.tape` directly from one
   * card's phase and deleted it on cleanup, which was wrong the moment a wallet
   * held two pools. `/quote` renders one `QuoteRun` per quotable holding, they
   * all address the same root element, and the write was last-one-wins: an idle
   * sibling deleted the attribute a running sibling had just set, and any
   * unmount cleared it while another job was still going. The feature worked
   * only for wallets with exactly one quotable pool, and failed silently for
   * every other wallet — no error, just a backdrop that stopped reporting.
   *
   * So the attribute is *derived* rather than assigned. Each card publishes its
   * own state into a module-level registry keyed by pool, and the root gets
   * whatever the whole registry adds up to.
   */
  // Read from the *job*, not from the phase, and this is the second half of the
  // bug above. `onFinished` calls `setState({ phase: "watching", … })` — the
  // same string it was already on — so an effect with `[state.phase]` in its
  // dependency list never re-ran when a job ended. The tape kept reading at
  // 26s indefinitely, for the whole site, with nothing behind it. The phase
  // says what the card is doing; only `job.status` says whether the work is
  // over, and `isFinished` is now the one place that knows which states those
  // are.
  const status = state.phase === "watching" ? state.job.status : null;
  const claim: TapeClaim | null =
    state.phase === "refused" || status === "refused"
      ? "refused"
      : state.phase === "queueing" || (status !== null && !isFinished(status))
        ? "reading"
        : null;

  useEffect(() => {
    if (claim) TAPE_CLAIMS.set(pool, claim);
    else TAPE_CLAIMS.delete(pool);
    applyTape();

    return () => {
      TAPE_CLAIMS.delete(pool);
      applyTape();
    };
  }, [claim, pool]);

  useEffect(() => {
    if (state.phase !== "watching") return;

    // A scenario has no stream behind it, and must not mime one.
    //
    // `scenario.matches()` deliberately refuses to let `/quote/job/{id}` answer
    // for `/quote/job/{id}/stream` — the segment counts differ — so there is no
    // recorded SSE and there should not be. A progress bar counting to a number
    // nobody computed is the kind of thing this site exists to argue against, so
    // the recorded terminal job is read once and shown as what it is.
    if (state.simulated) {
      let live = true;
      const jobId = state.job.jobId;
      void (async () => {
        const got = await loadLive<JobView & { job_id?: string }>(`/quote/job/${jobId}`);
        if (!live) return;
        if (!got.ok) {
          return setState({ phase: "failed", message: got.error.message });
        }
        setState((prev) =>
          prev.phase === "watching"
            ? {
                ...prev,
                job: { ...prev.job, ...got.value, jobId, published: prev.job.published },
              }
            : prev,
        );
      })();
      return () => {
        live = false;
      };
    }

    const stop = subscribe(
      state.job.jobId,
      {
      onEvent: (event: JobEvent) =>
        setState((prev) =>
          prev.phase === "watching"
            ? {
                phase: "watching",
                job: {
                  ...prev.job,
                  status: event.kind,
                  done: Number(event.payload.done ?? prev.job.done),
                  total: Number(event.payload.total ?? prev.job.total),
                  phase: String(event.payload.phase ?? prev.job.phase),
                },
              }
            : prev,
        ),
      onFinished: async () => {
        // `loadLive`, so no path on this page reaches the network below the
        // scenario short-circuit. This branch is live-only today — a simulated
        // run never subscribes — but "unreachable under a scenario" is a
        // property of the caller, and the last raw `fetch` here is how the
        // previous one came to be missed.
        const got = await loadLive<JobView & { job_id: string }>(
          `/quote/job/${state.job.jobId}`,
        );
        if (!got.ok) return;
        const body = got.value;
        setState({
          phase: "watching",
          job: {
            ...body,
            jobId: state.job.jobId,
            done: 0,
            total: 0,
            phase: "",
            // `/quote/job/{id}` reports the job and knows nothing about the
            // pool's published runs — those came with the 202. Spreading the
            // body over the state would drop them at the moment the fresh
            // number lands, which is exactly when there is something to
            // compare it against.
            published: state.job.published,
          },
        });
      },
        onError: (message) => setState({ phase: "failed", message }),
      },
      stream,
    );

    return stop;
    // Keyed on the job id: re-subscribing on every progress tick would open a
    // stream per event, which on a job with sixty of them is sixty streams.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.phase === "watching" ? state.job.jobId : null]);

  async function enqueue() {
    setState({ phase: "queueing" });

    // `postLive`, not a raw `fetch`, and that is the whole of a defect rather
    // than a refactor. This called `apiBase()` and then `fetch` directly, which
    // sits **below** the scenario short-circuit in `lib/api.ts` — so
    // `scenarios/quote-thin-tape.json`, whose only key is `"POST /quote"`, could
    // never match anything. A page under `?scenario=quote-thin-tape` showed the
    // simulation banner and then talked to the live API.
    //
    // The path is spelled `"POST /quote"` because that is the fixture's key and
    // what `matches()` compares against; `postLive` strips the verb before
    // building the URL.
    const got = await postLive<QuoteSubmission>("POST /quote", { pool });

    if (!got.ok) {
      if (got.error instanceof RefusalError) {
        return setState({
          phase: "refused",
          reason: [got.error.message, got.error.note].filter(Boolean).join(" — "),
          remedy: got.error.remedy ?? "",
        });
      }
      return setState({ phase: "failed", message: got.error.message });
    }

    const body = got.value;
    if (!body?.job_id) {
      return setState({ phase: "failed", message: "The API queued nothing." });
    }

    setState({
      phase: "watching",
      simulated: got.source === "simulated",
      job: {
        jobId: body.job_id,
        status: "queued",
        done: 0,
        total: 0,
        phase: "",
        note: body.note ?? "",
        // Kept across the whole watch, not only the queued frame: the
        // published runs are what the fresh one has to be read against, and
        // they stay true after it finishes.
        published: Array.isArray(body.published) ? body.published : undefined,
      },
    });
  }

  const running = state.phase === "queueing" || state.phase === "watching";

  return (
    <Card as="article" className="mb-4">
      <CardHeader
        title={label || pool}
        eyebrow={<span className="normal-case">{pool}</span>}
        aside={
          <Button size="sm" onClick={enqueue} disabled={running}>
            {running ? "Running…" : "Replay this pool"}
          </Button>
        }
      />

      {state.phase === "refused" && (
        <Refusal title="No quote for this pool" reason={state.reason} floor={state.remedy} />
      )}

      {state.phase === "failed" && (
        <ErrorNotice title="The run could not be started" detail={state.message} />
      )}

      {state.phase === "watching" && <RunProgress job={state.job} />}
    </Card>
  );
}

function RunProgress({ job }: { job: JobView }) {
  // `donePct`, not `pct`. `lib/format` exports a `pct` that formats an
  // already-percentage value, and a local of the same name shadowed it — the
  // collision `RouterDetail.tsx` renamed its own local to `rate` to avoid.
  const donePct = job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;

  return (
    <div aria-busy={!isFinished(job.status)}>
      <p className="m-0 text-sm text-dim">
        <span className="font-mono text-xs text-faint">{job.jobId.slice(0, 8)}</span>{" "}
        <Pill tone={job.status === "done" ? "pass" : job.status === "failed" ? "fail" : "none"}>
          {job.status}
        </Pill>{" "}
        {job.phase}
      </p>

      {/* Two bars, because there are two states and they are not the same
          claim. Once the worker has announced a total, the bar is a fraction of
          it and `transition: width` interpolates between the discrete SSE
          events so a jump from 12/60 to 13/60 reads as motion rather than as a
          twitch. Before that announcement there is no denominator, and a
          full-width bar at 0% would be asserting a total the server has not
          sent — so the queued state gets a sliver that shuttles and measures
          nothing, which is what "queued" means. */}
      {job.total > 0 ? (
        <>
          {/* A real `progressbar`, which this is the only genuinely determinate
              long-running operation on the site to deserve. It had `aria-busy`
              on the wrapper and a `role="status"` line above it, so a reader
              was told something was happening and never how far along — while
              `donePct` was already computed and spent only on a CSS width.

              `aria-valuetext` as well as `aria-valuenow`, because "12 of 60
              replays" is what the page says in words and a bare "20" is not.
              The indeterminate branch below is deliberately not a progressbar:
              it has no denominator to report. */}
          <div
            className="hatched mt-3 h-1.5 w-full overflow-hidden rounded-full border border-glass-line"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={job.total}
            aria-valuenow={job.done}
            aria-valuetext={`${count(job.done)} of ${count(job.total)} replays`}
          >
            <div
              className="h-full rounded-full bg-brand transition-[width] duration-[var(--dur-3)] ease-band"
              style={{ width: `${donePct}%` }}
            />
          </div>
          <p className="tabular mt-1 mb-0 text-xs text-faint">
            {job.done} of {job.total} replays
          </p>
        </>
      ) : (
        job.status === "queued" && (
          <>
            <div className="hatched mt-3 h-1.5 w-full overflow-hidden rounded-full border border-glass-line">
              <div className="shuttle h-full w-[28%] rounded-full bg-brand" />
            </div>
            <p className="mt-1 mb-0 text-xs text-faint">
              Queued. The worker has not said how many replays this is yet.
            </p>
          </>
        )
      )}

      {/* What the marketplace already has, while the fresh run is still
          queued. This is the answer that arrives immediately, and without it a
          hire on a pool three agents have replayed showed a progress bar and
          nothing else.

          Kept visually quieter than the live result below and labelled with
          its own window count, because the two are not comparable: these are
          full-budget published runs and the job is the reduced interactive one
          A15 describes. Saying which is which is the whole reason the count
          rides on each row rather than being stated once in prose. */}
      {job.published && job.published.length > 0 && (
        <div className="mt-4 min-w-0 rounded-sm border border-glass-line bg-panel-2/50 p-3">
          <p className="m-0 text-xs text-faint">
            Already published for this pool — full-budget runs of named agents, not this
            job.
          </p>
          <ul className="mt-2 mb-0 list-none space-y-2 p-0">
            {job.published.map((run) => (
              <li key={run.agent} className="min-w-0 text-sm">
                <span className="text-ink">{run.agent}</span>{" "}
                <span className="tabular text-dim [overflow-wrap:anywhere]">{run.quote}</span>
                {(isNum(run.observations) || isNum(run.windows)) && (
                  <span className="block text-xs text-faint">
                    {isNum(run.net_positive) && isNum(run.observations) && (
                      <>
                        {count(run.net_positive)} of {count(run.observations)} observations
                        finished in profit
                      </>
                    )}
                    {isNum(run.net_positive) && isNum(run.observations) && isNum(run.windows) && (
                      <> · </>
                    )}
                    {isNum(run.windows) && (
                      <>
                        {count(run.windows)} windows
                        {isNum(run.perturbations) && <> × {count(run.perturbations)}</>}
                      </>
                    )}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {job.refusal && (
        <div className="mt-4">
          {/* The engine's own sentence, not a rewording of it. */}
          <Refusal
            title="The evidence could not support a quote"
            reason={job.refusal.note ?? ""}
            floor={job.refusal.remedy}
          >
            {/* The shortfall, not only the sentence about it. `windows` and
                `samples` ride on the refusal and were dropped at the type
                boundary, so this page could say no and not say by how much —
                on the one screen where somebody has just asked for the number.
                Drawn only when both are known; a gauge against a floor this
                file invented would be a fabricated number under a refusal. */}
            {isNum(job.refusal.windows) && isNum(job.refusal.samples) && (
              <div className="mt-3">
                {/* The shortfall drawn, not only counted. A grid that visibly
                    does not fill is the refusal — on the one screen where
                    somebody has just asked for a number and is being told no.
                    Same component draws the quote that succeeded below, so the
                    two are one picture with a different amount filled in.

                    No `floor` is passed: this page does not read the floors
                    artifact, and a threshold invented here would be a
                    fabricated number under a refusal — the objection `Band`'s
                    withheld branch already makes about guessing one. The
                    engine's own sentence above says what the floor was. */}
                <ObservationGrid
                  windows={job.refusal.windows}
                  perturbations={
                    job.refusal.samples > 0 && job.refusal.windows > 0
                      ? Math.max(1, Math.round(job.refusal.samples / job.refusal.windows))
                      : 1
                  }
                  samples={job.refusal.samples}
                  caption="what the tape could support"
                />
              </div>
            )}
          </Refusal>
        </div>
      )}

      {job.result && (
        <div className="surface mt-4 rounded-md border border-glass-line bg-glass p-4">
          {/* The range, drawn.
              This printed `1.89% – 1.93%` over `median 1.91%` — a sentence, on
              the one page in this product where a reader watches a range being
              computed and then receives it. Every other quote on the site is a
              band; the live one, the one somebody asked for, was the exception.
              `RouterDetail` was fixed for exactly this two commits ago and the
              surface pass walked past this.

              One series and no rug, and both are the data rather than a
              simplification: a job has no baseline to compare against, and
              `ops/quote_job.py` publishes `distinct_returns` as a count rather
              than the array `Band` would draw a rug from. */}
          <Band
            sufficient
            caption="This wallet's replay, on the pool above"
            series={[
              {
                label: "This replay",
                p25: job.result.p25,
                p50: job.result.p50,
                p75: job.result.p75,
                tone: "agent",
              },
            ]}
          />

          {/* The median and the sample shape, in text, and not redundancy:
              `Band` writes P25–P75 in its label row and puts the median only in
              an `aria-label`, which contributes no `innerText` — and this
              route has a 1,200-character no-JS floor in check-pages.mjs.
              Drawing the range must not cost the page the number.

              The three fields beside it were on the wire and off the type until
              this commit, which is why the live quote said less about itself
              than every card on `/` does. */}
          <p className="mt-4 mb-0 text-sm text-dim">
            <span className="tabular text-ink">median {pct(job.result.p50)}</span> over{" "}
            <span className="tabular">{count(job.result.samples)}</span> observations
            {isNum(job.result.windows) && (
              <>
                {" "}
                — {count(job.result.windows)} windows
                {isNum(job.result.perturbations) && (
                  <> × {count(job.result.perturbations)} perturbations</>
                )}
                {isNum(job.result.hours_per_window) && (
                  <> of ~{hours(job.result.hours_per_window)} each</>
                )}
              </>
            )}
            .
          </p>
          {isNum(job.result.net_positive) && (
            <p className="mt-1 mb-0 text-sm">
              <span
                className={job.result.net_positive === 0 ? "text-warn" : "text-dim"}
              >
                {count(job.result.net_positive)} of {count(job.result.samples)} observations
                finished in profit.
              </span>
            </p>
          )}
          {job.result.interactive_budget && (
            <p className="mt-2 mb-0 text-xs text-warn">
              Run on the reduced interactive budget, so this range is wider than a
              published card&rsquo;s and is not comparable with one.{" "}
              <Link href="/assumptions#A15">A15</Link> says what was traded away.
            </p>
          )}
        </div>
      )}

      {job.note && <p className="mt-3 mb-0 text-xs text-faint">{job.note}</p>}
    </div>
  );
}