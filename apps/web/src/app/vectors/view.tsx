"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BuildStamp, type Build } from "@/components/BuildStamp";
import { Card, CardHeader } from "@/components/Card";
import { DataTable } from "@/components/DataTable";
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
  command?: string;
  outcome?: "PASS" | "FAIL";
  summary_line?: string;
  tests_passed?: number;
  tests_failed?: number;
  cases_covered?: number;
  groups_replayed?: string[];
  generated_at?: string;
  git_sha?: string | null;
  git_dirty?: boolean | null;
  corpus_matches?: boolean;
  corpus_moved?: string[];
  receipt?: string;
}

interface VectorsArtifact {
  corpus: { dir: string; cases: number; groups: Group[]; pins: Pin[] };
  verification: { replay: Verification; differential: Verification };
  build: Build;
}

export function VectorsView() {
  const [state, setState] = useState<Loaded<VectorsArtifact> | null>(null);

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
    <Loadable loading={state === null} what="the vector report">
      <h1 className="text-2xl font-semibold">The tick math, against the real Solidity</h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        Every range this site quotes is priced with tick math — the conversion between a
        tick and a price, the token amounts a position holds, the fees it has accrued. An
        off-by-one there is not a rounding difference; it is a mint that reverts or a
        figure that is quietly wrong everywhere.{" "}
        <strong className="text-ink">
          So the arithmetic is not reviewed, it is compared.
        </strong>
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
                <code className="font-mono text-xs">scripts/gen_vectors.py</code> deploys a
                thin wrapper over upstream v3-core and v3-periphery to a local chain, asks
                it {count(d.corpus.cases)} questions, and writes down what it said. It
                refuses to write anything at all if one answer disagreed with ours — so
                these files existing means a differential run agreed, and nothing more than
                that.
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
                  Seed {d.corpus.groups[0].seed} throughout, so the same run reproduces the
                  same cases. Comparison is exact integer equality — there is no tolerance
                  anywhere in it, which is deliberate: a tolerance is how an off-by-one in
                  tick math survives to production.
                </p>
              )}
            </Card>
          </Section>

          {d.corpus.pins.length > 0 && (
            <Section title="Compared against which code" className="mt-10">
              <Card>
                <p className="mt-0 mb-4 max-w-[68ch] text-sm text-dim">
                  &ldquo;Checked against Uniswap&rdquo; is the kind of claim that decays
                  quietly — the sentence stays true-sounding while the code it referred to
                  moves on. These are the commits, pinned in{" "}
                  <code className="font-mono text-xs">ops/forge_deps.txt</code>, so a
                  reader can go and look at exactly what answered.
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
                v={d.verification.replay}
              />
              <VerificationCard
                title="Differential"
                what="Our math against freshly deployed Solidity. Regenerates the whole comparison rather than reading these files, so it can catch a corpus that was recorded wrong."
                v={d.verification.differential}
              />
            </div>
          </Section>

          <p className="mt-8 max-w-[68ch] text-sm text-dim">
            Every figure the replay defends is used somewhere on this site.{" "}
            <Link href="/methods">How a quote is made →</Link>
          </p>

          <BuildStamp className="mt-10" build={d.build} />
        </>
      )}
    </Loadable>
  );
}

function VerificationCard({
  title,
  what,
  v,
}: {
  title: string;
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
          floor="re-run `make vectors-verify`"
        />
      </Card>
    );
  }

  const failed = v.outcome === "FAIL";
  return (
    <Card className="min-w-0">
      <CardHeader
        title={title}
        aside={<Pill tone={failed ? "fail" : "pass"}>{v.outcome}</Pill>}
      />
      <p className="mt-0 mb-4 max-w-[68ch] text-sm text-dim">{what}</p>

      {failed && (
        <p className="mt-0 mb-4 rounded-md border border-bad-line bg-bad-bg/40 p-3 text-sm text-bad">
          The replay does not reproduce the recorded answers. Every number on this site is
          priced with this arithmetic.
        </p>
      )}

      <DataTable
        caption={`${title} run`}
        rows={[
          { label: "command", value: <span className="font-mono text-xs">{v.command}</span> },
          { label: "pytest said", value: v.summary_line ?? "—" },
          {
            // Never "comparisons made". Nothing watched the assertion loops.
            // What was observed: named tests exited zero, and those tests load
            // these groups, which hold this many cases.
            label: "cases covered",
            value: count(v.cases_covered),
            note: `${(v.groups_replayed ?? []).length} groups`,
          },
          { label: "ran at", value: v.generated_at ?? "—" },
          {
            label: "against commit",
            value: v.git_sha ?? "no commit",
            note: v.git_dirty ? "dirty tree" : "",
          },
        ]}
      />

      {v.receipt && (
        <p className="mt-3 mb-0 font-mono text-xs text-faint">
          recorded in {v.receipt}
        </p>
      )}
    </Card>
  );
}
