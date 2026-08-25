"use client";

import { useState } from "react";
import { AnsweredBy } from "@/components/AnsweredBy";
import { Button } from "@/components/Button";
import { CheckList } from "@/components/CheckList";
import { Pill, verdictTone } from "@/components/Pill";
import { Refusal } from "@/components/Refusal";
import { loadLive, RefusalError, type Source } from "@/lib/api";

/**
 * A badge check as the wire carries it.
 *
 * `provenance` is optional here and required on `CheckList`'s own `CheckRow`,
 * and the difference is deliberate. All 27 checks in `vetting/badges/*.json`
 * carry one, so typing it required would be true of today's files — but this
 * arrives over HTTP from a service that may be a different version of the
 * repository, and a type assertion is not a runtime check. It is defaulted
 * where it crosses into the renderer instead.
 */
interface Check {
  name: string;
  status: string;
  detail: string;
  provenance?: string;
}

interface Badge {
  pool: string;
  label?: string;
  chain_id: number;
  verdict: { called: boolean; label: string };
  safe_to_provide?: boolean;
  read_at?: number;
  checks: Check[];
}

/**
 * Asking about one address, and getting the right kind of no.
 *
 * `/vetting` renders every badge `make vet` wrote. What that cannot do is
 * answer the question a reader actually arrives with — *what about this
 * address* — and `/vetting/{address}` was built to, with the distinction that
 * makes it worth having: a pool we verified and never vetted is a gap in our
 * own work, and a pool we never verified is a refusal to index it at all.
 * Collapsing those into one "not found" is what the route's own comment says
 * this surface exists to avoid. Nothing had ever called it.
 *
 * ## Why there is no refresh
 *
 * `api/vetting.py` had a `?refresh=1` in an earlier draft and removed it, and
 * the reasoning is worth not undoing from this side: a badge is nine chain
 * readings taken at one block, and `read_pool` degrades field by field when an
 * endpoint refuses. Served from a handler with a short RPC timeout on a free
 * tier, that produces a *different, weaker* badge than `make vet` produced, at
 * the same URL, with nothing saying which one you got. So this reads recorded
 * badges and nothing else.
 */
export function BadgeLookup() {
  const [address, setAddress] = useState("");
  const [state, setState] = useState<
    | { phase: "idle" }
    | { phase: "reading" }
    | { phase: "found"; badge: Badge; source: Source }
    | { phase: "refused"; error: RefusalError }
    | { phase: "unavailable" }
  >({ phase: "idle" });

  async function look(event: React.FormEvent) {
    event.preventDefault();
    const wanted = address.trim();
    if (!wanted) return;

    setState({ phase: "reading" });
    // No fallback. The published aggregate answers a different question — which
    // pools have badges — and returning it for "what about 0xabc" would be a
    // stale yes in place of one of the two considered nos.
    const got = await loadLive<Badge>(`/vetting/${wanted}`);
    if (got.ok) return setState({ phase: "found", badge: got.value, source: got.source });
    if (got.error instanceof RefusalError) return setState({ phase: "refused", error: got.error });
    setState({ phase: "unavailable" });
  }

  return (
    <div>
      <form onSubmit={look} className="flex flex-wrap items-end gap-2">
        <label className="min-w-0 flex-1 text-sm">
          <span className="text-dim">Look up one address</span>
          <input
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            placeholder="0x…"
            className="mt-1 w-full rounded-sm border border-glass-line bg-glass px-2.5 py-1.5 font-mono text-sm text-ink transition-colors placeholder:text-faint focus:border-brand focus:shadow-[inset_3px_0_0_0_var(--brand)]"
          />
        </label>
        <Button type="submit" disabled={state.phase === "reading" || !address.trim()}>
          {state.phase === "reading" ? "Reading…" : "Check"}
        </Button>
      </form>

      <div className="mt-4" aria-busy={state.phase === "reading"}>
        {state.phase === "refused" && (
          // The route sends two different 404s and the difference is the point:
          // "no badge recorded" means we verified this pool and did not vet it,
          // and its note says the absence is ours. "No verified pool" means
          // nothing has ever looked at it. Both arrive here as the service's own
          // words rather than as a rewrite of them.
          <Refusal
            title="No badge for that address"
            reason={state.error.message}
            floor={state.error.remedy || undefined}
          >
            {state.error.note && <p className="mt-2 mb-0 text-sm">{state.error.note}</p>}
          </Refusal>
        )}

        {state.phase === "unavailable" && (
          <Refusal
            title="No live service answered"
            reason="Looking up a single address needs a running API. The badges below are what this export carries."
            floor="Start one with `make api` and publish its address with `make api-config`."
          />
        )}

        {state.phase === "found" && (
          <div className="surface rounded-md border border-glass-line bg-glass p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <span className="min-w-0 font-mono text-xs break-all text-dim">
                {state.badge.pool}
              </span>
              <div className="flex items-center gap-3">
                <AnsweredBy source={state.source} />
                <Pill tone={verdictTone(state.badge.verdict)}>{state.badge.verdict.label}</Pill>
              </div>
            </div>
            <div className="mt-3">
              <CheckList
                checks={state.badge.checks.map((check) => ({
                  ...check,
                  provenance: check.provenance ?? "",
                }))}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
