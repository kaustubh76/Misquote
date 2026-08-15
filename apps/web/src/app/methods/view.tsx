"use client";

import { Loadable } from "@/components/LoadingStatus";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { Cite } from "@/components/Cite";
import { DataTable } from "@/components/DataTable";
import { ErrorNotice } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { load, type AgentArtifact, type Loaded } from "@/lib/artifacts";
import { count, EMPTY, hours } from "@/lib/format";

/**
 * How a quote is made, and why its window is shorter than the tape.
 *
 * This page exists because the old card contradicted itself in two adjacent
 * lines: the quote read "over 31h" and the metric row directly beneath it read
 * "44,802 over 62.2h". Both were correct — the quote is computed across
 * overlapping sub-windows that are each half the tape — but nothing said so, so
 * the card appeared to disagree with itself about its own history.
 */
export function MethodsView() {
  const [state, setState] = useState<Loaded<AgentArtifact> | null>(null);

  useEffect(() => {
    let live = true;
    load<AgentArtifact>("warden.json").then((r) => {
      if (live) setState(r);
    });
    return () => {
      live = false;
    };
  }, []);

  const d = state?.ok ? state.value : null;
  const q = d?.quote_detail ?? null;
  const floors = d?.floors ?? null;

  return (
    <Loadable loading={state === null} what="the method detail">
      <h1 className="text-2xl font-semibold">How a quote is made</h1>
      <p className="mt-3 max-w-[64ch] text-dim">
        Every figure on this site is a replay: the policy is run over recorded pool
        history, priced net of fees, adverse selection and every cost of having been
        there. What follows is the arithmetic between that replay and the range on the
        card.
      </p>

      {state && !state.ok && (
        <div className="mt-8">
          <ErrorNotice
            title="Cannot show the live numbers"
            detail={state.error.message}
            remedy={
              <>
                The method below does not change, but the figures illustrating it come
                from a generated artifact. Run{" "}
                <code className="font-mono text-xs">make showcase-demo</code>.
              </>
            }
          />
        </div>
      )}

      {state === null && (
        <div className="mt-8">
          <CardSkeleton />
        </div>
      )}

      {/* ------------------------------------------- the window arithmetic -- */}
      <section className="mt-10">
        <h2 className="mb-4 text-lg font-semibold">
          {/* Two forms. The loaded one names both figures; the unloaded one
              states the relationship and no magnitude, because "~31h" and
              "62.2h" were literals standing in for numbers nobody had fetched —
              on the page that argues a floor a UI could get wrong is not a
              floor. They also went stale silently: they are Warden's, on one
              tape, and survived every regeneration. */}
          {q && d ? (
            <>
              Why the quote says {hours(q.hours_per_window)} and the tape says{" "}
              {hours(d.replay.hours)}
            </>
          ) : (
            <>Why the quote window is shorter than the tape</>
          )}
        </h2>
        <Card>
          <p className="mt-0 text-sm text-dim">
            A single replay over the whole tape is <em>one</em> observation. One number
            from one run tells you what happened, not what the strategy does — so the
            history is cut into <strong className="text-ink">{count(q?.windows)}</strong>{" "}
            overlapping sub-windows, each covering{" "}
            <strong className="text-ink">half the span</strong>, and the policy is replayed
            in each.
          </p>

          <div className="my-5">
            <DataTable
              caption="From tape to quote"
              hideCaption={false}
              rows={[
                {
                  label: "tape span",
                  value: d ? hours(d.replay.hours) : "—",
                  note: "everything the replay saw",
                },
                {
                  label: "× 0.5",
                  value: q ? hours(q.hours_per_window) : "—",
                  note: "one sub-window",
                },
                {
                  label: "windows",
                  value: count(q?.windows),
                  note: "overlapping, not disjoint",
                },
                {
                  label: "× perturbations",
                  value: count(q?.perturbations),
                  note: "γ and κ at ±25%",
                },
                {
                  label: "= observations",
                  value: count(q?.samples),
                  note: "the denominator on every verdict",
                },
              ]}
            />
          </div>

          {q && d && floors && (
            <p className="mb-0 text-sm text-dim">
              Overlapping rather than disjoint is a deliberate trade.{" "}
              {count(q.windows)} disjoint windows over this tape would be about{" "}
              {/* Divided by the window count the artifact reports, not by a
                  literal 20 — the two agree today and would part company the
                  moment the emitter changed, silently and in prose. */}
              {hours(d.replay.hours / q.windows)} each — far too short for a{" "}
              {floors.min_window_hours}h policy horizon to mean anything. Overlap costs
              independence and buys length, and length is what the horizon needs.{" "}
              <Cite id="A5" />
            </p>
          )}
        </Card>
      </section>

      {/* ------------------------------------------------------- the floors -- */}
      <section className="mt-8">
        <h2 className="mb-4 text-lg font-semibold">The four floors</h2>
        <p className="mb-5 max-w-[64ch] text-sm text-dim">
          Each of these can stop this product from printing a number. They are published
          here with the values the code enforces — including the numbers in these four
          titles, which were hardcoded until a test served a different artifact and
          they failed to follow it. A floor a UI could get wrong is not a floor.
        </p>

        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader
              title={<>{count(floors?.min_windows)} usable sub-windows</>}
              eyebrow={`min_windows = ${floors?.min_windows ?? EMPTY}`}
            />
            <p className="m-0 text-sm text-dim">
              Below this the quote is withheld entirely rather than estimated from four
              windows. <Cite id="A5" />
            </p>
          </Card>

          <Card>
            <CardHeader
              title={<>{hours(floors?.min_window_hours, 0)} per window</>}
              eyebrow={`min_window_hours = ${floors?.min_window_hours ?? EMPTY}`}
            />
            <p className="m-0 text-sm text-dim">
              A window shorter than the policy horizon is a measurement of nothing.
              Twenty of them are still twenty measurements of nothing.
            </p>
          </Card>

          <Card>
            <CardHeader
              title={<>{hours(floors?.min_hours_to_annualise, 0)} before annualising</>}
              eyebrow={`min_hours_to_annualise = ${floors?.min_hours_to_annualise ?? EMPTY}`}
            />
            <p className="m-0 text-sm text-dim">
              Under a week of history, the figure is reported as-is with the span
              attached — {q ? <code className="font-mono text-xs">{q.basis}</code> : null}{" "}
              — rather than multiplied up into an annual rate nobody can support.
            </p>
          </Card>

          <Card>
            <CardHeader
              title={<>{count(floors?.min_observations)} observations before a verdict</>}
              eyebrow={`min_observations = ${floors?.min_observations ?? EMPTY}`}
            />
            <p className="m-0 text-sm text-dim">
              Below the floor the tearsheet prints &ldquo;no verdict&rdquo; and the count
              that was missing. A card saying &ldquo;83% win rate&rdquo; on twelve
              observations is worth less than one that refuses.
            </p>
          </Card>
        </div>
      </section>

      {/* ------------------------------------------------ no look-ahead --- */}
      <section className="mt-8">
        <h2 className="mb-4 text-lg font-semibold">Why the replay cannot cheat</h2>
        <Card>
          <p className="mt-0 text-sm text-dim">
            A backtest that can see the future is the easiest way to produce an impressive
            number, so this one is prevented structurally rather than by review.
          </p>
          <ul className="mt-4 mb-0 list-none space-y-3 p-0 text-sm text-dim">
            <li className="border-l-2 border-line pl-4">
              <strong className="text-ink">The estimators cannot read a clock.</strong> The
              pure layer — policy, estimators, LVR, replay — is forbidden from importing
              web3, sqlite3, asyncio or the wall clock, and a test walks the imports to
              enforce it. Time arrives as an argument.
            </li>
            <li className="border-l-2 border-line pl-4">
              <strong className="text-ink">Ingest asserts on future events.</strong> Any
              event newer than the decision time raises, unconditionally, in both the live
              and the replay driver. There is no flag to disable it. <Cite id="A3" />
            </li>
            <li className="border-l-2 border-line pl-4">
              <strong className="text-ink">The tape bounds itself in SQL.</strong> The
              frontier is a bind parameter on the query, not an <code>if</code> in Python,
              so there is no in-memory future available to leak.
            </li>
          </ul>
          <p className="mt-4 mb-0 text-sm text-faint">
            Verified by tests T1–T4 and L1 — <code className="font-mono text-xs">make replay-tests</code>.
          </p>
        </Card>
      </section>

      <p className="mt-10 text-sm">
        <Link href="/assumptions">Every assumption these methods rest on →</Link>
      </p>
    </Loadable>
  );
}
