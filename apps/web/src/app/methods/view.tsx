"use client";

import { Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { Cite } from "@/components/Cite";
import { FloorGauge } from "@/components/FloorGauge";
import { DataTable } from "@/components/DataTable";
import { ErrorNotice } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { load, type AgentArtifact, type Loaded } from "@/lib/artifacts";
import { count, EMPTY, fixed, fraction, hours, pct } from "@/lib/format";

/**
 * How a quote is made, and why its window is shorter than the tape.
 *
 * This page exists because the old card contradicted itself in two adjacent
 * lines: the quote read "over 31h" and the metric row directly beneath it read
 * "44,802 over 62.2h". Both were correct — the quote is computed across
 * overlapping sub-windows that are each half the tape — but nothing said so, so
 * the card appeared to disagree with itself about its own history.
 */
export function MethodsView({ initial }: {
  /** Read from disk at build time by `page.tsx`. See `lib/build-artifact`. */
  initial?: AgentArtifact;
}) {
  const [state, setState] = useState<Loaded<AgentArtifact> | null>(
    initial ? { ok: true, value: initial } : null,
  );

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
  // Counted from the artifact. Five cards are written out below because each
  // needs its own sentence; this is what stops the *heading* disagreeing with
  // them, and what would catch a sixth floor being added to the emitter.
  const floorCount = floors ? Object.keys(floors).length : null;

  return (
    <Loadable loading={state === null} what="the method detail" className="max-w-3xl">
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">How a quote is made</h1>
      <p className="mt-3 max-w-[64ch] text-dim">
        {/* Two corrections. "Every figure on this site" was false — /vetting,
            /registry, /vectors and /status are chain reads and test runs, not
            replays, and /advantage is a synthetic tape. And "net of fees" has
            the sign backwards: fees are income. The card's own row says "fees
            earned", and net = fees − adverse selection − costs. */}
        Every <strong className="text-ink">quote</strong> here is a replay over recorded
        pool history, priced net of adverse selection and every cost of being there.
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
      <Section title={<>{/* Two forms. The loaded one names both figures; the unloaded one
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
          )}</>} className="mt-10">
        <Card>
          <p className="mt-0 text-sm text-dim">
            {/* "half the span" is the `× 0.5` row of the table three lines
                below, and the middle sentence explains what the first already
                says. */}
            One replay is <em>one</em> observation, so the tape is cut into{" "}
            <strong className="text-ink">{count(q?.windows)}</strong> overlapping
            sub-windows and the policy is replayed in each.
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
                  // Derived from the two figures either side of it rather than
                  // typed. This label was the string "× 0.5" — the sub-window
                  // fraction, which is in no artifact — on the page whose own
                  // section header argues that "a floor a UI could get wrong is
                  // not a floor". Both operands are published, so the operator
                  // is arithmetic on them and moves when they do.
                  label:
                    q && d && d.replay.hours > 0
                      ? `× ${fixed(q.hours_per_window / d.replay.hours, 2)}`
                      : "×",
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
                  // The magnitude, read. It was typed as "±25%" and was the
                  // only statement of it anywhere on the site; the artifact
                  // carried the count and nothing about how far. A5 is the
                  // assumption it implements, and A5's fraction now travels on
                  // the quote that used it.
                  note:
                    q?.perturbation_fraction === undefined
                      ? "γ and κ, each side of nominal"
                      : `γ and κ at ±${pct(q.perturbation_fraction, 0)}`,
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
              {/* The division was derived; the *conclusion* was typed, and it
                  reversed when the tape grew. At 62h, 20 disjoint windows were
                  ~3.1h each and "far too short for a 24h horizon" was true. At
                  725.7h they are ~36.3h each — comfortably over the floor — and
                  the sentence argued against its own two rendered numbers. So
                  the comparison is now made rather than asserted, and the
                  trade is stated in the terms that hold either way. */}
              {/* The computed comparison is the argument; the closing sermon
                  restated it. */}
              Disjoint, these would be {hours(d.replay.hours / q.windows)} each
              {d.replay.hours / q.windows < floors.min_window_hours ? (
                <> — under the {hours(floors.min_window_hours)} horizon, so each measures nothing</>
              ) : (
                <>
                  {" "}
                  against {hours(q.hours_per_window)} overlapping
                </>
              )}
              . Overlap buys length at the cost of independence. <Cite id="A5" />
            </p>
          )}
        </Card>
      </Section>

      {/* ------------------------------------------------------- the floors -- */}
      {/* Counted, not typed. This said "The four floors" while `floors`
          carried five keys — `in_range_floor` decides `verdicts.in_range` and
          renders as "threshold 70%" on every card, so it is a floor by every
          definition this page uses. A hardcoded count of the floors, on the
          section arguing that a floor a UI could get wrong is not a floor. */}
      <Section title={<>The {count(floorCount)} floors</>}>
        <p className="mb-5 max-w-[64ch] text-sm text-dim">
          {/* The changelog — "hardcoded until a test served a different
              artifact" — moved to a comment. The demonstration is that every
              number in these titles is visibly interpolated. */}
          Each can stop this product printing a number, at the value the code enforces.
          A floor a UI could get wrong is not a floor.
        </p>

        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader
              title={<>{count(floors?.min_windows)} usable sub-windows</>}
              eyebrow={`min_windows = ${floors?.min_windows ?? EMPTY}`}
            />
            <p className="m-0 text-sm text-dim">
              Below this the quote is withheld entirely rather than estimated from a
              handful. <Cite id="A5" />
            </p>
            {q && d && floors && (
              <div className="mt-4">
                <FloorGauge
                  label="Windows in this run"
                  observed={q.windows}
                  required={floors.min_windows}
                />
              </div>
            )}
          </Card>

          <Card>
            <CardHeader
              title={<>{hours(floors?.min_window_hours, 0)} per window</>}
              eyebrow={`min_window_hours = ${floors?.min_window_hours ?? EMPTY}`}
            />
            <p className="m-0 text-sm text-dim">
              {/* "Twenty of them are still twenty measurements of nothing" —
                  the exact restatement this section says it eliminated, one
                  card below the sentence saying so. `pages.test.tsx` serves
                  `min_windows: 999`; the title followed and this did not. */}
              A window shorter than the policy horizon measures nothing, however many
              of them there are.
            </p>
            {q && d && floors && (
              <div className="mt-4">
                <FloorGauge
                  label="Hours per window"
                  observed={q.hours_per_window}
                  required={floors.min_window_hours}
                  unit="h"
                />
              </div>
            )}
          </Card>

          <Card>
            <CardHeader
              title={<>{hours(floors?.min_hours_to_annualise, 0)} before annualising</>}
              eyebrow={`min_hours_to_annualise = ${floors?.min_hours_to_annualise ?? EMPTY}`}
            />
            <p className="m-0 text-sm text-dim">
              {/* This offered `q.basis` as an example of the *not*-annualised
                  path while the artifact reports `annualised`, so the card
                  illustrated its rule with a case that breaks it. Which side
                  of the floor this run falls on is knowable, so it is said. */}
              {/* The generic half went; the run-specific half is the whole
                  value of the card, and it is the only explanation on the site
                  for the magnitude on every quote. */}
              {q && d && floors ? (
                <>
                  This run is{" "}
                  <strong className="text-ink">
                    {d.replay.hours >= floors.min_hours_to_annualise ? "over" : "under"}
                  </strong>{" "}
                  it at {hours(d.replay.hours)}, so the quote reads{" "}
                  <code className="font-mono text-xs">{q.basis}</code>
                  {q.annualised && (
                    <> — a {hours(d.replay.hours)} result multiplied up to a year</>
                  )}
                  .
                </>
              ) : (
                <>Below it, the figure is reported as-is with its span attached.</>
              )}
            </p>
            {q && d && floors && (
              <div className="mt-4">
                <FloorGauge
                  label="Hours of tape"
                  observed={d.replay.hours}
                  required={floors.min_hours_to_annualise}
                  unit="h"
                />
              </div>
            )}
          </Card>

          <Card>
            <CardHeader
              title={<>{count(floors?.min_observations)} observations before a verdict</>}
              eyebrow={`min_observations = ${floors?.min_observations ?? EMPTY}`}
            />
            <p className="m-0 text-sm text-dim">
              Below it the tearsheet prints &ldquo;no verdict&rdquo; and the count that
              was missing. A confident number on a tiny sample is worth less than a
              refusal.
            </p>
            {q && d && floors && (
              <div className="mt-4">
                <FloorGauge
                  label="Observations in this run"
                  observed={q.samples}
                  required={floors.min_observations}
                />
              </div>
            )}
          </Card>

          {/* The fifth. It was missing while the heading said four — and it is
              the only one of the five that decides a *verdict* rather than
              whether a number prints at all, which is presumably how it came to
              be left out of a section about withholding. */}
          <Card>
            <CardHeader
              title={<>{fraction(floors?.in_range_floor)} of the time in range</>}
              eyebrow={`in_range_floor = ${floors?.in_range_floor ?? EMPTY}`}
            />
            <p className="m-0 text-sm text-dim">
              The one floor that calls a verdict rather than withholding a number: below
              it, in-range fails on every card.
            </p>
            {/* The only floor on this page the current run fails, and it was
                the only one of the five without a picture. A page arguing that
                floors stop numbers printing should show one stopping one. */}
            {q && d && floors && (
              <div className="mt-4">
                <FloorGauge
                  label="In range, this run"
                  observed={q.in_range_p50}
                  required={floors.in_range_floor}
                  format={fraction}
                />
              </div>
            )}
          </Card>
        </div>
      </Section>

      {/* ------------------------------------------------ no look-ahead --- */}
      <Section title="Why the replay cannot cheat">
        <Card>
          <p className="mt-0 text-sm text-dim">
            Look-ahead is prevented structurally rather than by review.
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
      </Section>

      <p className="mt-10 text-sm">
        <Link href="/assumptions">Every assumption these methods rest on →</Link>
      </p>
    </Loadable>
  );
}
