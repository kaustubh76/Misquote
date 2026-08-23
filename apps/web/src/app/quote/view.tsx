"use client";

import Link from "next/link";
import { useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { Heading, Section } from "@/components/Heading";
import { Pill } from "@/components/Pill";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { loadLive, RefusalError } from "@/lib/api";

/** One pool the wallet holds a position in, as `/quote/eligibility` reports it. */
interface Holding {
  pool: string;
  label: string;
  positions: number;
  open_positions: number;
  quotable: boolean;
  why_not: string[];
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
            className="min-w-0 flex-1 rounded-md border border-line bg-panel px-3 py-2.5 font-mono text-sm text-ink placeholder:text-faint"
          />
          <button
            type="submit"
            disabled={state.phase === "reading" || !address.trim()}
            className="rounded-md border border-transparent bg-brand px-4 py-2.5 text-sm font-medium text-brand-ink shadow-elev-brand transition-opacity hover:opacity-90 disabled:opacity-45"
          >
            {state.phase === "reading" ? "Reading chain…" : "Check my positions"}
          </button>
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

      <Heading className="mt-8 mb-2 text-md font-semibold">What happens next</Heading>
      <p className="m-0 max-w-[62ch] text-sm text-dim">
        Queuing the replay itself is not built. The pre-flight above is what
        decides whether it would be worth queuing, and it is the part that can
        answer honestly today — see <Link href="/status">readiness</Link> for what
        else is and is not built.
      </p>
    </Section>
  );
}
