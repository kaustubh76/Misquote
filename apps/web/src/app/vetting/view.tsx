"use client";

import { useEffect, useState } from "react";
import { BuildStamp, type Build } from "@/components/BuildStamp";
import { Badge } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { WithCitations } from "@/components/Cite";
import { Heading, Section } from "@/components/Heading";
import { NotBuiltCard } from "@/components/Ledger";
import { Loadable } from "@/components/LoadingStatus";
import { Pill, type PillTone } from "@/components/Pill";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { load, type IndexArtifact, type Loaded } from "@/lib/artifacts";
import { count, hours, shortAddress, timestamp } from "@/lib/format";

interface VettingCheck {
  name: string;
  status: "PASS" | "WARN" | "FAIL" | "UNKNOWN";
  detail: string;
  provenance: string;
}

interface VettingPool {
  pool: string;
  label: string;
  badged: boolean;
  listed?: boolean;
  reason?: string;
  verdict?: string;
  safe_to_provide?: boolean;
  checks?: VettingCheck[];
  path?: string;
  read_at?: string;
  age_hours?: number;
}

interface VettingArtifact {
  surveyed: boolean;
  reason?: string;
  chain_id: number;
  badge_dir: string;
  pools: VettingPool[];
  summary: {
    pools: number;
    badged: number;
    unbadged?: number;
    cleared?: number;
    blocked?: number;
    checks?: number;
    unknown_checks?: number;
    failed_checks?: number;
    worst?: string;
  };
  // `Build`, not a local restatement of it. The hand-written version here
  // declared no `git_dirty`, so the field was dropped at the type boundary and
  // the page rendered a bare sha for a run made against a dirty tree.
  build?: Build;
}

/**
 * `PASS`/`WARN`/`FAIL` are verdicts. `UNKNOWN` is not.
 *
 * `vetting/badge.py` is explicit that a read it could not make becomes UNKNOWN
 * rather than defaulting to a pass, and it counts UNKNOWN as blocking. So an
 * unknown check is the machine declining to say — which is a `Refusal` here,
 * not a `Pill` and certainly not an `ErrorNotice`. Amber is never green, and it
 * is not red either.
 */
const CHECK_TONE: Record<string, PillTone> = {
  PASS: "pass",
  WARN: "unverified",
  FAIL: "fail",
};

export function VettingView() {
  const [state, setState] = useState<Loaded<VettingArtifact> | null>(null);
  const [index, setIndex] = useState<Loaded<IndexArtifact> | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([load<VettingArtifact>("vetting.json"), load<IndexArtifact>("index.json")]).then(
      ([v, i]) => {
        if (!live) return;
        setState(v);
        setIndex(i);
      },
    );
    return () => {
      live = false;
    };
  }, []);

  const d = state?.ok ? state.value : null;
  const proofs = index?.ok
    ? index.value.not_built.filter((e) => e.category === "Due diligence")
    : [];

  return (
    <Loadable loading={state === null} what="the pool badges">
      <h1 className="text-2xl font-semibold">Pool due diligence</h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        Every pool a listed agent touches, read from chain and checked against the defects
        this project actually hit. Each check names the matrix item that paid for it, so a
        reader can go and see the arithmetic rather than take the badge&rsquo;s word.
      </p>

      {state === null && (
        <div className="mt-10">
          <CardSkeleton />
        </div>
      )}

      {state && !state.ok && (
        <div className="mt-10">
          <ErrorNotice
            title="The badges have not been published"
            detail={state.error.message}
            remedy={
              <>
                Run <code className="font-mono text-xs">make vet</code> to read the pools,
                then <code className="font-mono text-xs">make vetting</code> to publish what
                it found.
              </>
            }
          />
        </div>
      )}

      {d && !d.surveyed && (
        <div className="mt-10">
          <Refusal
            title="No pool has been badged"
            reason={d.reason ?? "Nothing has been read yet."}
            floor={`${d.badge_dir} is empty — vetting/read.py turns a read it could not make into UNKNOWN rather than a default`}
          />
        </div>
      )}

      {d?.surveyed && (
        <>
          <div className="mt-8 flex flex-wrap items-center gap-2">
            <Badge tone={d.summary.worst === "PASS" ? "neutral" : "warn"}>
              worst verdict: {d.summary.worst}
            </Badge>
            <span className="font-mono text-xs text-faint">
              {count(d.summary.badged)} of {count(d.summary.pools)} pools badged ·{" "}
              {count(d.summary.checks)} checks · {count(d.summary.unknown_checks)} unknown ·{" "}
              {count(d.summary.failed_checks)} failed
            </span>
          </div>

          {d.pools.map((pool) => (
            <Section
              key={pool.pool}
              title={pool.label || shortAddress(pool.pool)}
              className="mt-10"
            >
              {!pool.badged ? (
                <Refusal
                  title="Not badged"
                  reason={pool.reason ?? "No badge exists for this pool."}
                  floor="listed in chain/addresses.py — run `make vet`"
                />
              ) : (
                <Card>
                  <CardHeader
                    eyebrow={
                      <span className="font-mono">
                        {shortAddress(pool.pool)} · chain {d.chain_id}
                      </span>
                    }
                    title={pool.safe_to_provide ? "Cleared to provide" : "Not cleared"}
                    aside={
                      <Pill tone={pool.safe_to_provide ? "pass" : "fail"}>
                        {pool.verdict}
                      </Pill>
                    }
                  />

                  <ul className="m-0 list-none space-y-4 p-0">
                    {(pool.checks ?? []).map((check) =>
                      check.status === "UNKNOWN" ? (
                        // Not a pill. The read did not happen, so there is no
                        // finding to colour — only a refusal to claim one.
                        <li key={check.name}>
                          <Refusal
                            title={check.name}
                            reason={check.detail}
                            floor={check.provenance}
                          />
                        </li>
                      ) : (
                        <li
                          key={check.name}
                          className="border-l-2 border-line pl-4 first:border-l-2"
                        >
                          <div className="flex flex-wrap items-baseline justify-between gap-2">
                            {/* Explicitly h4. `Card` cannot provide a level —
                                `CardHeader` arrives as a child, so the card
                                never knows whether it has a title. Without
                                this, each check is a sibling of the verdict it
                                is the evidence for. The escape hatch exists for
                                exactly this, and using it is visible in a diff. */}
                            <Heading level={4} className="m-0 text-sm font-semibold">
                              {check.name}
                            </Heading>
                            <Pill tone={CHECK_TONE[check.status] ?? "info"}>
                              {check.status}
                            </Pill>
                          </div>
                          <p className="mt-1 mb-0 font-mono text-xs break-words text-dim">
                            {check.detail}
                          </p>
                          <p className="mt-1 mb-0 text-xs text-faint">
                            {/* The provenance strings cite matrix items, so P-6
                                and V-10 become links into /assumptions. */}
                            <WithCitations text={check.provenance} />
                          </p>
                        </li>
                      ),
                    )}
                  </ul>

                  <p className="mt-5 mb-0 border-t border-line pt-3 font-mono text-xs break-all text-faint">
                    read {timestamp(pool.read_at)} · {hours(pool.age_hours)} ago ·{" "}
                    {pool.path}
                  </p>
                </Card>
              )}
            </Section>
          ))}

          {proofs.length > 0 && (
            <Section
              title="What a badge still cannot do"
              className="mt-12"
              intro="The checks above are reads. They are not proofs, and the difference is the whole of the remaining work."
            >
              <div className="grid gap-4 sm:grid-cols-2">
                {proofs.map((entry) => (
                  <NotBuiltCard key={entry.name} entry={entry} />
                ))}
              </div>
            </Section>
          )}

          {d.build && <BuildStamp className="mt-10" build={d.build} />}
        </>
      )}
    </Loadable>
  );
}
