"use client";

import { useState } from "react";
import { AnsweredBy } from "@/components/AnsweredBy";
import { Button } from "@/components/Button";
import { DataTable } from "@/components/DataTable";
import { Refusal } from "@/components/Refusal";
import { loadLive, RefusalError, type Source } from "@/lib/api";
import { count, fraction } from "@/lib/format";

/** One pool's ladder, as `/pools/{address}` returns it. */
interface PoolReport {
  address: string;
  label: string;
  quote_symbol: string;
  best_width_ticks: number | null;
  verdict: string;
  ladder: {
    width_ticks: number;
    p25: number;
    p50: number;
    p75: number;
    observations: number;
    sufficient: boolean;
  }[];
  demand: { swaps: number };
}

/**
 * Asking about one pool, and getting an answer shaped like the question.
 *
 * `/venue` renders every pool `make pools` measured. What that cannot do is
 * answer the question a reader actually arrives with — *what about the pool I
 * already hold a position in* — and `/pools/{address}` was built to. It says so
 * itself: *"`pools.json` is a list, and the question a reader actually arrives
 * with is about one pool."*
 *
 * **Nothing had ever called it.** The route was registered, unit-tested, served,
 * and until recently named in neither of the service's two descriptions of
 * itself. `api/tape.py` exists because of the milder version of the same thing,
 * and its docstring is the sentence this component is written against.
 *
 * A sibling of `BadgeLookup` rather than a generalisation of it: that asks about
 * due diligence and renders a checklist, this asks about earnings and renders a
 * band ladder, and the two refusals differ. Their shared parts —`loadLive`,
 * `RefusalError`, `AnsweredBy`, `Refusal` — are already shared.
 *
 * ## Why there is no fallback to the artifact
 *
 * The published report answers a different question — which pools were measured
 * — and returning it for "what about 0xabc" would be a stale yes in place of a
 * considered no. The route sends two different refusals and the distinction is
 * the product: a pool this deployment never verified is not the same as a pool
 * it verified and could not rank, and the second is the one that says the gap is
 * ours. Both arrive here in the service's own words.
 */
export function PoolLookup() {
  const [address, setAddress] = useState("");
  const [state, setState] = useState<
    | { phase: "idle" }
    | { phase: "reading" }
    | { phase: "found"; report: PoolReport; source: Source }
    | { phase: "refused"; error: RefusalError }
    | { phase: "unavailable" }
  >({ phase: "idle" });

  async function look(event: React.FormEvent) {
    event.preventDefault();
    const wanted = address.trim();
    if (!wanted) return;

    setState({ phase: "reading" });
    const got = await loadLive<PoolReport>(`/pools/${wanted}`);
    if (got.ok)
      return setState({
        phase: "found",
        report: got.value,
        source: got.source,
      });
    if (got.error instanceof RefusalError)
      return setState({ phase: "refused", error: got.error });
    setState({ phase: "unavailable" });
  }

  const usable =
    state.phase === "found"
      ? state.report.ladder.filter((b) => b.sufficient)
      : [];

  return (
    <div>
      <form onSubmit={look} className="flex flex-wrap items-end gap-2">
        <label className="min-w-0 flex-1 text-sm">
          <span className="text-dim">Look up one pool</span>
          <input
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            placeholder="0x…"
            className="mt-1 w-full rounded-sm border border-glass-line bg-glass px-2.5 py-1.5 font-mono text-sm text-ink transition-colors placeholder:text-faint focus:border-brand focus:shadow-[inset_3px_0_0_0_var(--brand)]"
          />
        </label>
        <Button
          type="submit"
          disabled={state.phase === "reading" || !address.trim()}
        >
          {state.phase === "reading" ? "Reading…" : "Check"}
        </Button>
      </form>

      <div className="mt-4" aria-busy={state.phase === "reading"}>
        {state.phase === "refused" && (
          <Refusal
            title="No ladder for that address"
            reason={state.error.message}
            floor={state.error.remedy || undefined}
          >
            {state.error.note && (
              <p className="mt-2 mb-0 text-sm">{state.error.note}</p>
            )}
          </Refusal>
        )}

        {state.phase === "unavailable" && (
          <Refusal
            title="No live service answered"
            reason="Asking about a single pool needs a running API. The ladders below are what this export carries."
            floor="Start one with `make api` and publish its address with `make api-config`."
          />
        )}

        {state.phase === "found" && (
          <div className="surface rounded-md border border-glass-line bg-glass p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <span className="min-w-0 text-sm font-semibold text-ink">
                {state.report.label}
              </span>
              <AnsweredBy source={state.source} />
            </div>
            {/* The engine's sentence, verbatim. Its load-bearing half is the
                clause about the lead not being separated, and re-deriving a
                winner here would drop exactly that. */}
            <p className="mt-2 mb-0 max-w-[68ch] text-sm text-dim">
              {state.report.verdict}
            </p>

            {usable.length > 0 ? (
              <div className="mt-3">
                <DataTable
                  caption={`Fee APR by width, net of the convexity cost, in ${state.report.quote_symbol}`}
                  rows={usable.map((band) => ({
                    label: `±${count(band.width_ticks)} ticks`,
                    value: `${fraction(band.p25)} – ${fraction(band.p75)}`,
                    note: `${fraction(band.p50)} · ${count(
                      band.observations
                    )} windows${
                      band.width_ticks === state.report.best_width_ticks
                        ? " · leads"
                        : ""
                    }`,
                  }))}
                  notes="prose"
                />
              </div>
            ) : (
              <p className="mt-3 mb-0 max-w-[68ch] text-sm text-dim">
                No width cleared the evidence floor on this pool, so there is no
                answer here rather than a small number. It saw{" "}
                <span className="tabular text-ink">
                  {count(state.report.demand.swaps)}
                </span>{" "}
                swaps across the tape.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
