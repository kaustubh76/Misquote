"use client";

import { Heading, Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import { useEffect, useState } from "react";
import { Card } from "@/components/Card";
import { ChipGroup, type Chip } from "@/components/ChipGroup";
import { LedgerTable } from "@/components/Ledger";
import { Pill, statusTone } from "@/components/Pill";
import { ErrorNotice } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { load, type IndexArtifact, type Loaded } from "@/lib/artifacts";

interface StatusCheck {
  name: string;
  status: "PASS" | "FAIL" | "UNVERIFIED";
  detail: string;
  remedy: string;
  blocking: boolean;
}

export interface StatusArtifact {
  mainnet: boolean;
  fast: boolean;
  skipped: string[];
  checks: StatusCheck[];
  summary: { pass: number; fail: number; unverified: number; total: number };
  outcome: "GO" | "NO GO" | "NOT YET";
  exit_code: number;
}

/**
 * Verdict order, worst last — the same direction `/vetting`'s rollup uses.
 *
 * Listed rather than derived from the data so the chips do not reorder
 * themselves between runs: a control whose options move when the underlying
 * numbers move is one nobody can build a habit with.
 */
const STATUSES = ["PASS", "UNVERIFIED", "FAIL"] as const;

/** What the filter can be set to: any verdict, or everything. */
type Verdict = (typeof STATUSES)[number];
type Filter = Verdict | "all";

const STATUS_LABEL: Record<Verdict, string> = {
  PASS: "Passing",
  UNVERIFIED: "Unverified",
  FAIL: "Failing",
};

const OUTCOME_STYLE: Record<string, string> = {
  GO: "border-good-line bg-good-bg/50 text-good",
  "NO GO": "border-bad-line bg-bad-bg/50 text-bad",
  "NOT YET": "border-warn-line bg-warn-bg/50 text-warn",
};

export function StatusView({
  initialStatus,
  initialIndex,
}: {
  /** Read from disk at build time by `page.tsx`. See `lib/build-artifact`. */
  initialStatus?: StatusArtifact;
  initialIndex?: IndexArtifact;
}) {
  const [status, setStatus] = useState<Loaded<StatusArtifact> | null>(
    initialStatus ? { ok: true, value: initialStatus } : null,
  );
  const [index, setIndex] = useState<Loaded<IndexArtifact> | null>(
    initialIndex ? { ok: true, value: initialIndex } : null,
  );

  useEffect(() => {
    let live = true;
    Promise.all([load<StatusArtifact>("status.json"), load<IndexArtifact>("index.json")]).then(
      ([s, i]) => {
        if (!live) return;
        setStatus(s);
        setIndex(i);
      },
    );
    return () => {
      live = false;
    };
  }, []);

  const d = status?.ok ? status.value : null;

  /**
   * Which verdict to show. The page's question is "what has nobody checked",
   * and answering it meant reading eleven cards and counting.
   *
   * `"all"` rather than defaulting to the unverified ones: a checklist that
   * opens pre-filtered to its own failures is arguing rather than reporting,
   * and the passing gates are the evidence that the amber ones are not simply
   * everything.
   */
  const [only, setOnly] = useState<Filter>("all");

  const checks = d?.checks ?? [];
  const shown = only === "all" ? checks : checks.filter((c) => c.status === only);

  // Counts off the checks themselves, never off `summary` — the two are the
  // same numbers from different code, and a filter whose label disagrees with
  // the list under it is worse than no filter.
  const chips: Chip<Filter>[] = [
    { value: "all", label: "All", meta: String(checks.length) },
    ...STATUSES.filter((s) => checks.some((c) => c.status === s)).map((s) => ({
      value: s,
      label: STATUS_LABEL[s],
      meta: String(checks.filter((c) => c.status === s).length),
    })),
  ];

  return (
    <Loadable loading={status === null} what="the go/no-go status">
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">Readiness</h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        {/* The opening sentence justified the page rather than describing it. */}
        A checklist that runs. It exits non-zero on a failure, and anything it cannot
        verify is <strong className="text-ink">unverified</strong> — amber, never green.
      </p>

      {status === null && (
        <div className="mt-10">
          <CardSkeleton />
        </div>
      )}

      {status && !status.ok && (
        <div className="mt-10">
          <ErrorNotice
            title="No status has been published"
            detail={status.error.message}
            remedy={
              <>
                Run <code className="font-mono text-xs">make status</code>. It executes
                every gate and writes the result here.
              </>
            }
          />
        </div>
      )}

      {d && (
        <>
          {/* The answer, at the size of an answer.
              This page is a wall of fourteen verdicts and the one line that
              says what they add up to was `text-lg` in a box the same weight as
              the "not run" note beneath it. It is the reason the route exists,
              so it is now the largest thing on it — and it carries the counts
              as a proportional strip, because "11 passed · 0 failed · 3
              unverified" is a shape and reading it as three numbers is work a
              picture does for free. */}
          <div className={`mt-8 rounded-md border p-6 ${OUTCOME_STYLE[d.outcome] ?? ""}`}>
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <p className="m-0 font-mono text-3xl leading-none font-semibold tracking-tight">
                {d.outcome}
              </p>
              <p className="m-0 font-mono text-xs">exit code {d.exit_code}</p>
            </div>

            {/* One `role="img"` over the whole strip with the counts spoken in
                order. Three unlabelled divs would announce as nothing, and the
                sentence below already carries the same figures for anyone who
                is not looking at it — so this is aria-hidden's job, except that
                a bar chart with no name is exactly what a reader using a screen
                reader is entitled to be told the shape of. */}
            <div
              className="mt-4 flex h-2 w-full overflow-hidden rounded-full border border-glass-line"
              role="img"
              aria-label={`${d.summary.pass} of ${d.summary.total} gates passing, ${d.summary.fail} failed, ${d.summary.unverified} unverified.`}
            >
              {(
                [
                  ["bg-good", d.summary.pass],
                  ["bg-bad", d.summary.fail],
                  ["bg-warn", d.summary.unverified],
                ] as const
              ).map(([tone, n]) =>
                n > 0 ? (
                  <div
                    key={tone}
                    className={tone}
                    style={{ width: `${(n / Math.max(1, d.summary.total)) * 100}%` }}
                  />
                ) : null,
              )}
            </div>

            <p className="mt-3 mb-0 text-sm">
              {d.summary.pass} passed · {d.summary.fail} failed · {d.summary.unverified}{" "}
              unverified, of {d.summary.total} gates
              {d.mainnet ? " (mainnet gates included)" : ""}.
            </p>
          </div>

          {d.fast && d.skipped.length > 0 && (
            <div className="surface mt-4 rounded-md border border-glass-line bg-glass p-4">
              <p className="m-0 text-sm text-dim">
                {/* The claim that survives, and appears nowhere else: skipped
                    gates are absent from the counts rather than passing. */}
                <strong className="text-ink">Not run.</strong>{" "}
                <code className="font-mono text-xs">--fast</code> skipped{" "}
                {d.skipped.join(", ")} — absent from the counts above, not passing.
              </p>
            </div>
          )}

          <Section title="Gates">
            <div className="surface mb-5 rounded-lg border border-glass-line bg-glass p-4">
              <ChipGroup
                label="Filter by verdict"
                options={chips}
                value={only}
                onChange={setOnly}
              />
              {/* Announced, not merely rendered — filtering removes cards from
                  below the fold. Named, because `Loadable` already owns an
                  unnamed `role="status"` on this page and two anonymous voices
                  is one too many. */}
              <p role="status" aria-label="Filter result" className="mt-3 mb-0 text-xs text-faint">
                {only === "all"
                  ? `All ${checks.length} gates.`
                  : `${shown.length} of ${checks.length} gates ${STATUS_LABEL[only].toLowerCase()}.`}
              </p>
            </div>

            {shown.length === 0 ? (
              /* In words. A filter that empties the list and says nothing reads
                 as a broken page, and on this page in particular "no gate is
                 failing" is a result worth stating rather than implying with
                 blank space. */
              <p className="m-0 text-sm text-dim">
                No gate is {STATUS_LABEL[only as Verdict].toLowerCase()}.
              </p>
            ) : (
            <div className="grid gap-3">
              {shown.map((check) => (
                <Card key={check.name} className="!p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Heading className="m-0 text-sm font-semibold">{check.name}</Heading>
                      <p className="mt-1 mb-0 font-mono text-xs break-words text-dim">
                        {check.detail}
                      </p>
                      {check.remedy && (
                        <p className="mt-2 mb-0 text-xs text-faint">→ {check.remedy}</p>
                      )}
                    </div>
                    <Pill tone={statusTone(check.status)}>{check.status}</Pill>
                  </div>
                </Card>
              ))}
            </div>
            )}
          </Section>

          {index?.ok && index.value.not_built.length > 0 && (
            <Section title="What is not built" className="mt-12" headingClassName="text-lg font-semibold">
              <p className="mt-2 mb-5 max-w-[68ch] text-sm text-dim">
                {/* Sentence 1 restated the two headings; sentence 3 restated
                    the "Check it" field on every card below. */}
                Capabilities the README advertises and this repository does not contain.
              </p>
              <LedgerTable entries={index.value.not_built} />
            </Section>
          )}
        </>
      )}
    </Loadable>
  );
}
