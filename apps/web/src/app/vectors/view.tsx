"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { DataTable } from "@/components/DataTable";
import { FloorGauge } from "@/components/FloorGauge";
import { Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import { Pill } from "@/components/Pill";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { load, type Loaded } from "@/lib/artifacts";
import { count } from "@/lib/format";

interface Group {
  group: string;
  cases: number;
  seed: number | null;
  source: string | null;
  recorded_by: string | null;
  path: string;
  sha256: string;
}

interface Pin {
  name: string;
  commit: string;
  pinned: string;
}

/**
 * A recorded run, or a stated reason there is none.
 *
 * `recorded: false` is not an error and not an absence of interest — it is the
 * honest state of a check nobody has run yet. Everything else on this interface
 * only exists once `recorded` is true, which is why they are all optional: a
 * shape that always carries `outcome` invites a view to read it before checking
 * whether anything produced it.
 */
interface Verification {
  recorded: boolean;
  reason?: string;
  outcome?: "PASS" | "FAIL";
  summary_line?: string;
  tests_passed?: number;
  tests_failed?: number;
  cases_covered?: number;
  /**
   * The groups a run touched, under the name that run uses for what it did.
   *
   * Two different words, deliberately. The replay *replays* the committed
   * answers; the differential *fuzzes fresh cases* against redeployed Solidity
   * and never opens those files. Normalising them to one name here would make
   * the weaker claim look like the stronger one in the only place a reader
   * sees either.
   */
  groups_replayed?: string[];
  groups_compared?: string[];
  mismatches?: number;
  seed?: number;
  corpus_matches?: boolean;
  corpus_moved?: string[];
}

export interface VectorsArtifact {
  corpus: { dir: string; cases: number; groups: Group[]; pins: Pin[] };
  verification: { replay: Verification; differential: Verification };
}

export function VectorsView({ initial }: {
  /** Read from disk at build time by `page.tsx`. See `lib/build-artifact`. */
  initial?: VectorsArtifact;
}) {
  const [state, setState] = useState<Loaded<VectorsArtifact> | null>(
    initial ? { ok: true, value: initial } : null,
  );

  useEffect(() => {
    let live = true;
    load<VectorsArtifact>("vectors.json").then((r) => {
      if (live) setState(r);
    });
    return () => {
      live = false;
    };
  }, []);

  const d = state?.ok ? state.value : null;

  return (
    <Loadable loading={state === null} what="the vector report" className="max-w-3xl">
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">The tick math, against the real Solidity</h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        Every range here is priced with tick math, where an off-by-one is a revert or a
        figure quietly wrong everywhere.{" "}
        <strong className="text-ink">So it is not reviewed, it is compared.</strong>
      </p>

      {state === null && (
        <div className="mt-10">
          <CardSkeleton />
        </div>
      )}

      {state && !state.ok && (
        <div className="mt-10">
          <ErrorNotice
            title="The vector report has not been generated"
            detail={state.error.message}
            remedy={
              <>
                Run <code className="font-mono text-xs">make vectors-report</code>. It reads
                the committed vectors and needs no network.
              </>
            }
          />
        </div>
      )}

      {d && (
        <>
          {/* The corpus is stated before either verification, deliberately.
              These files are what Uniswap's libraries returned — recorded
              once, against a deployed contract. Whether this Python still
              reproduces them is a different claim, and putting the counts and
              the verdict in one breath is how "19,546 cases exist" becomes
              "19,546 comparisons passed today". */}
          <Section title="What was recorded" className="mt-10">
            <Card>
              <p className="mt-0 mb-4 max-w-[68ch] text-sm text-dim">
                {/* The refusal is the claim: it is why the files existing is
                    itself the pass, and it appears nowhere else. */}
                <code className="font-mono text-xs">scripts/gen_vectors.py</code> asks
                upstream v3-core and v3-periphery {count(d.corpus.cases)} questions and
                records the answers — writing <strong className="text-ink">nothing</strong>{" "}
                if one disagreed.
              </p>

              <DataTable
                caption="Recorded vectors by function"
                hideCaption={false}
                // The third column is the digest alone. It began as
                // "constants.json · 5646dd13…", which repeated the function
                // name in the first column and pushed the table 50px past the
                // viewport at 390px — caught by `make web-check`, which is the
                // only thing that runs real layout.
                columns={["Function", "Cases", "Digest"]}
                notes="prose"
                rows={[
                  ...d.corpus.groups.map((g) => ({
                    label: <span className="font-mono text-xs">{g.group}</span>,
                    value: count(g.cases),
                    note: <span className="font-mono text-xs break-all text-faint">{g.sha256}</span>,
                  })),
                  {
                    label: <span className="font-semibold">total</span>,
                    value: <span className="font-semibold">{count(d.corpus.cases)}</span>,
                    note: "",
                  },
                ]}
              />

              {d.corpus.groups[0]?.seed != null && (
                <p className="mt-3 mb-0 text-xs text-faint">
                  Seed {d.corpus.groups[0].seed} throughout, so the cases reproduce.
                  Comparison is exact integer equality — no tolerance anywhere, because a
                  tolerance is how an off-by-one survives to production.
                </p>
              )}
            </Card>
          </Section>

          {d.corpus.pins.length > 0 && (
            <Section title="Compared against which code" className="mt-10">
              <Card>
                <p className="mt-0 mb-4 max-w-[68ch] text-sm text-dim">
                  {/* The pin table is the demonstration; the paragraph
                      explaining why pinning matters was rationale. */}
                  The commits that answered, pinned in{" "}
                  <code className="font-mono text-xs">ops/forge_deps.txt</code>.
                </p>
                <DataTable
                  caption="Pinned reference implementations"
                  hideCaption={false}
                  columns={["Library", "Commit", "Pinned"]}
                  notes="prose"
                  rows={d.corpus.pins.map((p) => ({
                    label: <span className="font-mono text-xs">{p.name}</span>,
                    value: (
                      <span className="font-mono text-xs break-all">{p.commit.slice(0, 12)}</span>
                    ),
                    note: <span className="font-mono text-xs text-faint">{p.pinned}</span>,
                  }))}
                />
              </Card>
            </Section>
          )}

          <Section
            title="Whether this Python still reproduces them"
            className="mt-10"
            intro="Two runs can answer that, and they answer different questions. Neither is inferred from the files above."
          >
            <div className="grid gap-4">
              <VerificationCard
                title="Replay"
                what="Our math against the recorded answers. No network, no fork, no foundry — which is what lets it run on every commit."
                said="pytest"
                remedy="make vectors-verify"
                onFailure="The replay does not reproduce the recorded answers."
                v={d.verification.replay}
              />
              <VerificationCard
                title="Differential"
                what="Our math against freshly deployed Solidity. Regenerates the whole comparison rather than reading these files, so it can catch a corpus that was recorded wrong."
                said="the run"
                remedy="make vectors-check"
                onFailure="This Python and Uniswap's own Solidity disagree."
                v={d.verification.differential}
              />
            </div>
          </Section>

          <p className="mt-8 max-w-[68ch] text-sm text-dim">
            Every figure the replay defends is used somewhere on this site.{" "}
            <Link href="/methods">How a quote is made →</Link>
          </p>
        </>
      )}
    </Loadable>
  );
}

/**
 * One recorded run, whichever run it was.
 *
 * This had exactly one caller for as long as the differential could never be
 * recorded, and three of its strings had quietly hardcoded that caller: the
 * table row read "pytest said" for a run that never invokes pytest, the stale
 * branch told a reader to re-run `make vectors-verify` whichever check had gone
 * stale, and the failure banner said "the replay does not reproduce the
 * recorded answers" about a run that does not read them.
 *
 * All three now come from the caller. A shared component whose prose only fits
 * one of its callers is worse than two components.
 */
function VerificationCard({
  title,
  what,
  said,
  remedy,
  onFailure,
  v,
}: {
  title: string;
  /** What the "said" row is quoting — `pytest`, `anvil`, whatever ran. */
  said: string;
  /** The command that would refresh this specific receipt. */
  remedy: string;
  /** What a FAIL means, in this run's terms. */
  onFailure: string;
  what: string;
  v: Verification;
}) {
  // Three withheld states, kept apart. Nothing recorded is not the same as a
  // receipt that has been invalidated, and neither is a run that failed — the
  // last of those is a finding, and the most valuable thing this page can show.
  // `min-w-0` on every branch: these are grid items, and a grid item defaults
  // to `min-width: auto` — it refuses to shrink below its own min-content
  // width. The mono `command` string inside set that floor, so the card
  // measured 420px in a 350px column and the document scrolled sideways at
  // 390px. `make web-check` caught it; nothing else can, because jsdom has no
  // layout and the card looks perfectly fine at 1280.
  if (!v.recorded) {
    return (
      <Card className="min-w-0">
        <CardHeader title={title} aside={<Pill tone="none">Not recorded</Pill>} />
        <p className="mt-0 mb-4 max-w-[68ch] text-sm text-dim">{what}</p>
        <Refusal
          title="Nothing has been recorded for this check"
          reason={v.reason ?? "no run has been recorded"}
          floor="the files above are Solidity's recorded answers; whether this Python still reproduces them is a claim about a run, and no run has been observed"
        />
      </Card>
    );
  }

  if (v.corpus_matches === false) {
    return (
      <Card className="min-w-0">
        <CardHeader title={title} aside={<Pill tone="unverified">Stale</Pill>} />
        <p className="mt-0 mb-4 max-w-[68ch] text-sm text-dim">{what}</p>
        <Refusal
          title="The recorded run was against a different corpus"
          reason={`These vector files have changed since the run was recorded: ${(
            v.corpus_moved ?? []
          ).join(", ")}. A pass against files that no longer exist is not a pass.`}
          floor={`re-run \`${remedy}\``}
        />
      </Card>
    );
  }

  const failed = v.outcome === "FAIL";
  // Which pass figure this run publishes. The differential counts cases and
  // the replay counts tests; neither is renamed to match the other, for the
  // same reason `groups_replayed` and `groups_compared` are two fields.
  const gauge =
    v.mismatches !== undefined && v.cases_covered !== undefined
      ? {
          label: "cases agreeing",
          observed: v.cases_covered - v.mismatches,
          required: v.cases_covered,
        }
      : v.tests_passed !== undefined
        ? {
            label: "tests passing",
            observed: v.tests_passed,
            required: v.tests_passed + (v.tests_failed ?? 0),
          }
        : null;

  return (
    <Card className="min-w-0">
      <CardHeader
        title={title}
        aside={<Pill tone={failed ? "fail" : "pass"}>{v.outcome}</Pill>}
      />
      <p className="mt-0 mb-4 max-w-[68ch] text-sm text-dim">{what}</p>

      {failed && (
        <p className="mt-0 mb-4 rounded-md border border-bad-line bg-bad-bg/40 p-3 text-sm text-bad">
          {onFailure} Every number on this site is priced with this arithmetic.
        </p>
      )}

      {/* The run's own pass bar.
          `mismatches` and `tests_failed` were both declared on this interface
          and drawn nowhere: the differential's zero against 19,546 cases is the
          strongest claim on this page and it reached a reader only inside
          `summary_line`, as prose.

          `FloorGauge` is a genuine fit rather than a stretch. The differential's
          stated rule is exact integer equality with no tolerance anywhere, so
          the floor is not a threshold somebody picked — it is the whole corpus,
          and "every case has to agree" is what that looks like as a picture.
          One mismatch moves the bar by five thousandths of a percent and is
          invisible; what carries it is the texture flipping to a hatch and the
          two figures ceasing to be equal, which is the component's own argument
          that colour is never the only signal. */}
      {gauge && (
        <div className="mb-4">
          <FloorGauge
            label={gauge.label}
            observed={gauge.observed}
            required={gauge.required}
          />
        </div>
      )}

      <DataTable
        caption={`${title} run`}
        rows={[
          // Prose-length, and `whitespace-nowrap` is `DataTable`'s default —
          // correct for a figure, since a wrapped number is unreadable, and
          // wrong for a sentence: the differential's `summary_line` runs about
          // a hundred monospace characters, which forced this table to 866px
          // inside a 718px card and pushed the values of four rows out of sight
          // behind a horizontal scroll. The document never overflowed, so
          // `check-pages.mjs` was right to pass it; the row was simply
          // unreadable.
          {
            label: `${said} said`,
            value: <span className="whitespace-normal">{v.summary_line ?? "—"}</span>,
          },
          {
            // Never "comparisons made". Nothing watched the assertion loops.
            // What was observed: named tests exited zero, and those tests load
            // these groups, which hold this many cases.
            label: "cases covered",
            value: count(v.cases_covered),
            note: `${(v.groups_replayed ?? v.groups_compared ?? []).length} groups`,
          },
          // The complement of the bar above, named rather than implied. Only
          // the differential publishes it; the replay row would be a blank
          // labelled "mismatches", which reads as zero rather than as absent.
          ...(v.mismatches === undefined
            ? []
            : [
                {
                  label: "mismatches",
                  value: count(v.mismatches),
                  tone: v.mismatches > 0 ? "text-bad" : "text-good",
                },
              ]),
        ]}
      />
    </Card>
  );
}
