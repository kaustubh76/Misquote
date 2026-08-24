"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/Button";
import { Card, CardHeader } from "@/components/Card";
import { Heading, Section } from "@/components/Heading";
import { Pill } from "@/components/Pill";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { apiBase, loadLive, RefusalError } from "@/lib/api";
import { type JobEvent, subscribe, isFinished } from "@/lib/stream";

/** One pool the wallet holds a position in, as `/quote/eligibility` reports it. */
interface Holding {
  pool: string;
  label: string;
  positions: number;
  open_positions: number;
  quotable: boolean;
  why_not: string[];
}

/** A job as `/quote/job/{id}` reports it. */
interface JobView {
  jobId: string;
  status: string;
  done: number;
  total: number;
  phase: string;
  note: string;
  refusal?: { note?: string; remedy?: string };
  result?: { p25: number; p50: number; p75: number; samples: number; interactive_budget: boolean };
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
  | { phase: "done"; value: Eligibility }
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
export function QuoteView() {
  const [address, setAddress] = useState("");
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

    if (got.ok) return setState({ phase: "done", value: got.value });
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

        {state.phase === "done" && <Result value={state.value} />}
      </div>
    </>
  );
}

function Result({ value }: { value: Eligibility }) {
  return (
    <Section title="What this wallet holds" headingClassName="text-lg font-semibold">
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

      <Heading className="mt-8 mb-2 text-md font-semibold">Run one</Heading>
      <p className="m-0 mb-4 max-w-[62ch] text-sm text-dim">
        A replay is minutes of arithmetic, not milliseconds, and it needs a worker
        draining the queue (<code className="font-mono text-xs">make api-worker</code>).
        Progress below is the job&rsquo;s own event log, so closing this page does
        not lose it — reopening replays from where it got to.
      </p>
      {value.holdings
        .filter((h) => h.quotable)
        .map((h) => (
          <QuoteRun key={h.pool} pool={h.pool} label={h.label} />
        ))}
    </Section>
  );
}


type RunState =
  | { phase: "idle" }
  | { phase: "queueing" }
  | { phase: "watching"; job: JobView }
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

function QuoteRun({ pool, label }: { pool: string; label: string }) {
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

    const stop = subscribe(state.job.jobId, {
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
        const base = await apiBase();
        if (!base) return;
        const res = await fetch(`${base}/quote/job/${state.job.jobId}`, { cache: "no-store" });
        const body = (await res.json()) as JobView & { job_id: string };
        setState({
          phase: "watching",
          job: { ...body, jobId: state.job.jobId, done: 0, total: 0, phase: "" },
        });
      },
      onError: (message) => setState({ phase: "failed", message }),
    });

    return stop;
    // Keyed on the job id: re-subscribing on every progress tick would open a
    // stream per event, which on a job with sixty of them is sixty streams.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.phase === "watching" ? state.job.jobId : null]);

  async function enqueue() {
    setState({ phase: "queueing" });
    const base = await apiBase();
    if (!base) {
      return setState({
        phase: "failed",
        message: "No live API is configured. Start one with `make api` and `make api-config`.",
      });
    }

    const res = await fetch(`${base}/quote`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ pool }),
    });
    const body = await res.json().catch(() => null);

    if (res.status === 202 && body?.job_id) {
      return setState({
        phase: "watching",
        job: { jobId: body.job_id, status: "queued", done: 0, total: 0, phase: "", note: body.note },
      });
    }

    const detail = body?.detail;
    if (detail?.error) {
      return setState({
        phase: "refused",
        reason: [detail.error, detail.note].filter(Boolean).join(" — "),
        remedy: detail.remedy ?? "",
      });
    }
    setState({ phase: "failed", message: `The API returned ${res.status}.` });
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
  const pct = job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;

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
          <div className="hatched mt-3 h-1.5 w-full overflow-hidden rounded-full border border-glass-line">
            <div
              className="h-full rounded-full bg-brand transition-[width] duration-[var(--dur-3)] ease-band"
              style={{ width: `${pct}%` }}
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

      {job.refusal && (
        <div className="mt-4">
          {/* The engine's own sentence, not a rewording of it. */}
          <Refusal
            title="The evidence could not support a quote"
            reason={job.refusal.note ?? ""}
            floor={job.refusal.remedy}
          />
        </div>
      )}

      {job.result && (
        <div className="surface mt-4 rounded-md border border-glass-line bg-glass p-4">
          <p className="tabular m-0 text-lg font-semibold text-ink">
            {job.result.p25.toFixed(2)}% – {job.result.p75.toFixed(2)}%
          </p>
          <p className="m-0 text-sm text-dim">
            median {job.result.p50.toFixed(2)}% over {job.result.samples} observations
          </p>
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