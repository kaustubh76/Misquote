"use client";

import { Heading, Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import { useEffect, useState } from "react";
import { Card } from "@/components/Card";
import { LedgerTable } from "@/components/Ledger";
import { Pill, statusTone } from "@/components/Pill";
import { ErrorNotice } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { load, type IndexArtifact, type Loaded } from "@/lib/artifacts";
import { BuildStamp, type Build } from "@/components/BuildStamp";
import { timestamp } from "@/lib/format";

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

  return (
    <Loadable loading={status === null} what="the go/no-go status">
      <h1 className="text-2xl font-semibold">Readiness</h1>
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

          <Section title="Gates">
            <div className="grid gap-3">
              {d.checks.map((check) => (
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
