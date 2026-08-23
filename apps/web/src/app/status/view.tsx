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
import { load, type ArtifactCensus, type IndexArtifact, type Loaded } from "@/lib/artifacts";
import { BuildStamp, type Build } from "@/components/BuildStamp";
import { count, timestamp } from "@/lib/format";

interface StatusCheck {
  name: string;
  status: "PASS" | "FAIL" | "UNVERIFIED";
  detail: string;
  remedy: string;
  blocking: boolean;
}

export interface StatusArtifact {
  generated_at: string;
  mainnet: boolean;
  fast: boolean;
  skipped: string[];
  checks: StatusCheck[];
  summary: { pass: number; fail: number; unverified: number; total: number };
  outcome: "GO" | "NO GO" | "NOT YET";
  exit_code: number;
  /**
   * Which tree the verdict was a verdict about.
   *
   * Optional because a `status.json` written before the emitter carried one is
   * still readable — and an absent stamp is itself the reading: this file could
   * not say what it checked. See `go_no_go.to_payload`.
   */
  build?: Build;
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
  census,
}: {
  /** Read from disk at build time by `page.tsx`. See `lib/build-artifact`. */
  initialStatus?: StatusArtifact;
  initialIndex?: IndexArtifact;
  /**
   * What every artifact on this site records about the tree that made it.
   *
   * Build-time only, and deliberately not refreshed the way the artifacts
   * themselves are: it is a fact about the directory the site was exported
   * from, and there is no fetch that could re-derive it in a browser.
   */
  census?: ArtifactCensus;
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
  // Artifacts recording a commit other than the one these gates were run
  // against. Not "stale" — an artifact can legitimately predate a run that did
  // not touch it — but it is the difference a reader needs to weigh a verdict.
  const elsewhere = census
    ? census.stamped.filter((a) => a.sha !== d?.build?.git_sha).length
    : 0;
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
          <div className={`mt-8 rounded-md border p-5 ${OUTCOME_STYLE[d.outcome] ?? ""}`}>
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <p className="m-0 font-mono text-lg font-semibold">{d.outcome}</p>
              <p className="m-0 font-mono text-xs">exit code {d.exit_code}</p>
            </div>
            <p className="mt-2 mb-0 text-sm">
              {d.summary.pass} passed · {d.summary.fail} failed · {d.summary.unverified}{" "}
              unverified, of {d.summary.total} gates
              {d.mainnet ? " (mainnet gates included)" : ""}.
            </p>
          </div>

          {d.fast && d.skipped.length > 0 && (
            <div className="mt-4 rounded-md border border-line bg-panel-2 p-4">
              <p className="m-0 text-sm text-dim">
                {/* The claim that survives, and appears nowhere else: skipped
                    gates are absent from the counts rather than passing. */}
                <strong className="text-ink">Not run.</strong>{" "}
                <code className="font-mono text-xs">--fast</code> skipped{" "}
                {d.skipped.join(", ")} — absent from the counts above, not passing.
              </p>
            </div>
          )}

          {/* How current these gates are, which the page had no way to say.
              `status.json` was recorded at `fa185b4` on 18 Aug and its gate
              still read "agent advantage report: 0/3 tasks on chain data" —
              false since the chain run landed, under a heading whose whole
              subject is what has and has not been checked.

              Re-running would fix that run and not the problem: the next
              emitter to run would stale it again and nothing would say so. So
              the page states what is on disk beside it instead, counted rather
              than typed. */}
          {census && d.build?.git_sha && (
            <div className="mt-4 rounded-md border border-warn-line bg-warn-bg/40 p-4">
              <p className="m-0 max-w-[72ch] text-sm text-dim">
                <strong className="text-ink">How current this is.</strong> A recording
                of one run against{" "}
                <code className="font-mono text-xs">{d.build.git_sha}</code>, not a live
                reading. Of the {count(census.total)} artifacts on this site,{" "}
                {count(census.unstamped.length)} record no commit at all
                {elsewhere > 0 && <> and {count(elsewhere)} record a different one</>} — so
                a gate below can be describing a number that has been regenerated since.
              </p>
              {census.unstamped.length > 0 && (
                <p className="mt-2 mb-0 font-mono text-xs break-words text-faint">
                  {census.unstamped.join(" · ")}
                </p>
              )}
              {census.exempt.map((file) => (
                <p key={file.name} className="mt-2 mb-0 text-xs text-faint">
                  <span className="font-mono">{file.name}</span> is not counted against
                  that: {file.why}.
                </p>
              ))}
            </div>
          )}

          <Section title="Gates">
            <div className="mb-5 rounded-lg border border-line bg-panel-2 p-4">
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

          {/* `BuildStamp`, not a hand-written line. This footer showed a
              timestamp and the command and nothing else, so a two-day-old NOT
              YET was indistinguishable from a fresh one — on the page whose
              whole job is to say what has been verified. The shared component
              carries the sha and the dirty-tree sentence with it. */}
          {d.build ? (
            <BuildStamp className="mt-10" build={d.build} />
          ) : (
            <p className="mt-10 font-mono text-xs text-faint">
              Generated {timestamp(d.generated_at)} · <code>make status</code> · this run
              recorded no commit, so what it checked cannot be established
            </p>
          )}
        </>
      )}
    </Loadable>
  );
}
