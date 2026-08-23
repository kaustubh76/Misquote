"use client";

import { useEffect, useState } from "react";
import { BuildStamp, type Build } from "@/components/BuildStamp";
import { Badge } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { ChipGroup, type Chip } from "@/components/ChipGroup";
import { CheckList } from "@/components/CheckList";
import { Heading, Section } from "@/components/Heading";
import { NotBuiltCard } from "@/components/Ledger";
import { Loadable } from "@/components/LoadingStatus";
import { Pill } from "@/components/Pill";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { load, type IndexArtifact, type Loaded } from "@/lib/artifacts";
import { count, hours, shortAddress, timestamp } from "@/lib/format";

/**
 * What `make vet-addresses` recorded, or a stated reason it recorded nothing.
 *
 * `surveyed: false` is a routine state, not an exceptional one:
 * `verify_addresses.py` reaches for a list of public BSC endpoints rather than
 * a configured key, and public endpoints are unreliable. Zero checks failing
 * and zero checks run render identically unless the artifact says which.
 */
export interface AddressArtifact {
  chain_id: number;
  surveyed: boolean;
  reason?: string;
  verdict?: string;
  block?: number | null;
  read_at?: string;
  age_hours?: number;
  record?: string;
  checks?: VettingCheck[];
  summary?: { checked: number; failed: number; unknown: number };
  build?: Build;
  /**
   * The other two recorded surveys, published beside the PancakeSwap one.
   *
   * `make venus-verify` gates the whole Yield category and `make erc8183-verify`
   * justifies two mainnet escrow addresses. Both wrote their readings to
   * `vetting/addresses/` and, for a while, `addresses_report.py` republished
   * them into this artifact while nothing on this page read them — evidence a
   * reader cannot see is not evidence, which is the exact sentence that
   * emitter's own docstring uses.
   */
  venus?: AddressArtifact;
  erc8183?: Record<string, AddressArtifact>;
}

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

export interface VettingArtifact {
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


/** Hours between a recorded read and now, or null before the clock is read. */
function ageHours(readAt: string | undefined, now: number | null): number | undefined {
  if (!readAt || now === null) return undefined;
  const then = Date.parse(readAt);
  return Number.isNaN(then) ? undefined : (now - then) / 3_600_000;
}

export function VettingView({
  initialVetting,
  initialIndex,
  initialAddresses,
}: {
  /** Read from disk at build time by `page.tsx`. See `lib/build-artifact`. */
  initialVetting?: VettingArtifact;
  initialIndex?: IndexArtifact;
  initialAddresses?: AddressArtifact;
}) {
  const [state, setState] = useState<Loaded<VettingArtifact> | null>(
    initialVetting ? { ok: true, value: initialVetting } : null,
  );
  const [index, setIndex] = useState<Loaded<IndexArtifact> | null>(
    initialIndex ? { ok: true, value: initialIndex } : null,
  );
  /**
   * When the page is looking, so "N ago" is N ago rather than N at emit time.
   *
   * `age_hours` is computed by the emitter and frozen into the artifact. Both
   * cards rendered it as live freshness: the pool badges read "0.0h ago" for a
   * chain read taken 22 hours earlier, and the addresses card read "13.7h ago"
   * for one taken three days earlier. On the page whose subject is that a stale
   * reading and a fresh one must not look alike.
   *
   * Set in an effect, not at render: these pages are prerendered now, and a
   * clock read during render disagrees between server and client. Before it is
   * set, the absolute timestamp shows on its own — which is the true half.
   */
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => setNow(Date.now()), []);

  const [addrs, setAddrs] = useState<Loaded<AddressArtifact> | null>(
    initialAddresses ? { ok: true, value: initialAddresses } : null,
  );

  useEffect(() => {
    let live = true;
    Promise.all([
      load<VettingArtifact>("vetting.json"),
      load<IndexArtifact>("index.json"),
      load<AddressArtifact>("addresses.json"),
    ]).then(([v, i, a]) => {
      if (!live) return;
      setState(v);
      setIndex(i);
      setAddrs(a);
    });
    return () => {
      live = false;
    };
  }, []);

  const d = state?.ok ? state.value : null;
  const a = addrs?.ok ? addrs.value : null;
  const addressSummary = a?.surveyed ? a.summary : null;

  /**
   * The page's rollup, across every subject on it.
   *
   * `worst` follows `badge.Badge.verdict`: FAIL beats UNKNOWN beats WARN beats
   * PASS. An unknown is deliberately not a pass — a check nobody could make and
   * a check that came back clean must not produce the same headline.
   */
  const RANK = ["PASS", "WARN", "UNKNOWN", "FAIL"];

  /**
   * Which verdict to show, across both subjects at once.
   *
   * Twenty-nine checks render fully expanded — nine per pool, eleven for the
   * addresses — and the page's question is which of them is not a PASS. The
   * rollup at the top already answers it as a number; this makes the number
   * something you can act on.
   *
   * Ordered by `RANK`, the same severity order the rollup is computed with, so
   * the chips read worst-last rather than in whatever order the artifact
   * happened to list them.
   */
  const [verdict, setVerdict] = useState<string>("all");

  const everyCheck = [
    ...(state?.ok ? (state.value.pools ?? []).flatMap((p) => p.checks ?? []) : []),
    ...(addrs?.ok ? (addrs.value.checks ?? []) : []),
  ];

  const verdictChips: Chip<string>[] = [
    { value: "all", label: "All", meta: String(everyCheck.length) },
    ...RANK.filter((r) => everyCheck.some((c) => c.status === r)).map((r) => ({
      value: r,
      label: r.charAt(0) + r.slice(1).toLowerCase(),
      meta: String(everyCheck.filter((c) => c.status === r).length),
    })),
  ];

  /** A subject's checks, narrowed. Kept here so both subjects narrow alike. */
  function narrow<T extends { status: string }>(checks: T[] | undefined): T[] {
    return verdict === "all" ? (checks ?? []) : (checks ?? []).filter((c) => c.status === verdict);
  }

  /**
   * A subject-level verdict's tone.
   *
   * Both rollup pills were `verdict === "PASS" ? "pass" : "fail"`, so a WARN or
   * an UNKNOWN rendered in the failure colour with its own word beside it —
   * the exact collapse this file argues against at length for the per-check
   * pills, made two levels up. `CheckList` gets it right; the pills above it
   * did not.
   */
  const verdictTone = (v?: string) =>
    v === "PASS" ? "pass" : v === "FAIL" ? "fail" : ("unverified" as const);
  const verdicts = [d?.surveyed ? d.summary.worst : null, a?.surveyed ? a.verdict : null]
    .filter((v): v is string => Boolean(v));
  const worstVerdict =
    verdicts.sort((x, y) => RANK.indexOf(y) - RANK.indexOf(x))[0] ?? "UNKNOWN";

  // The pool counts are optional on the artifact, so each is defaulted rather
  // than asserted — an emitter that stops publishing one should subtract from
  // the rollup, not blank the page.
  const pools = d?.surveyed ? d.summary : null;
  const totals = {
    subjects: (pools?.pools ?? 0) + (addressSummary ? 1 : 0),
    checks: (pools?.checks ?? 0) + (addressSummary?.checked ?? 0),
    unknown: (pools?.unknown_checks ?? 0) + (addressSummary?.unknown ?? 0),
    failed: (pools?.failed_checks ?? 0) + (addressSummary?.failed ?? 0),
  };

  const proofs = index?.ok
    ? index.value.not_built.filter((e) => e.category === "Due diligence")
    : [];

  return (
    <Loadable loading={state === null} what="the due-diligence reads">
      {/* Two subjects, so the title cannot be "Pool due diligence" any more.
          Pools are what an agent provides liquidity to; the addresses below are
          the contracts a signer is aimed at, and a pool can pass every check
          here while the factory constant used to find it points elsewhere. */}
      <h1 className="text-2xl font-semibold">Due diligence, read from chain</h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        Every pool an agent touches and every address the signer is aimed at, read from
        chain. Each check names the defect that paid for it.
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

      {/* The rollup counts every subject on the page.
          It read `vetting.json` alone — "18 checks" above a page showing 29 —
          and `worst verdict` never looked at the addresses at all, so an
          address FAIL would still have shown PASS at the top. Both artifacts
          publish the counts; neither was read. `worst` takes the more severe of
          the two by the same ordering `badge.py` uses: FAIL beats UNKNOWN beats
          WARN beats PASS. */}
      {(d?.surveyed || addressSummary) && (
        <div className="mt-8 flex flex-wrap items-center gap-2">
          <Badge tone={worstVerdict === "PASS" ? "neutral" : "warn"}>
            worst verdict: {worstVerdict}
          </Badge>
          <span className="font-mono text-xs text-faint">
            {count(totals.checks)} checks across {count(totals.subjects)} subjects ·{" "}
            {count(totals.unknown)} unknown · {count(totals.failed)} failed
          </span>
        </div>
      )}

      {d?.surveyed && (
        <>
          <div className="mt-6 font-mono text-xs text-faint">
            pools: {count(d.summary.badged)} of {count(d.summary.pools)} badged ·{" "}
            {count(d.summary.checks)} checks · {count(d.summary.unknown_checks)} unknown ·{" "}
            {count(d.summary.failed_checks)} failed
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
                      <Pill tone={verdictTone(pool.verdict)}>{pool.verdict}</Pill>
                    }
                  />

                  <CheckList checks={narrow(pool.checks)} />

                  <p className="mt-5 mb-0 border-t border-line pt-3 font-mono text-xs break-all text-faint">
                    read {timestamp(pool.read_at)}
                    {now !== null && <> · {hours(ageHours(pool.read_at, now))} ago</>} ·{" "}
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


        {/* Only when there is something to choose between.
            Every check on a clean run carries the same verdict, and a chip row
            reading "All 29 · Pass 29" offers one button that does nothing —
            which is the kind of control this pass exists to remove, not add.
            The count is the useful part, so it is stated in a sentence instead
            and the group appears the moment a second verdict does. */}
        {everyCheck.length > 0 && verdictChips.length <= 2 && (
          <p className="mt-8 mb-0 text-sm text-dim">
            Every one of the {everyCheck.length} checks below returned{" "}
            <strong className="text-ink">{verdictChips[1]?.value ?? "the same verdict"}</strong>.
          </p>
        )}

        {everyCheck.length > 0 && verdictChips.length > 2 && (
          <div className="mt-8 rounded-lg border border-line bg-panel-2 p-4">
            <ChipGroup
              label="Filter checks by verdict"
              options={verdictChips}
              value={verdict}
              onChange={setVerdict}
            />
            {/* Named, because `Loadable` already owns an unnamed `role="status"`
                on this page. Two anonymous voices is one too many. */}
            <p role="status" aria-label="Check filter result" className="mt-3 mb-0 text-xs text-faint">
              {verdict === "all"
                ? `All ${everyCheck.length} checks, across every subject below.`
                : `${everyCheck.filter((c) => c.status === verdict).length} of ${everyCheck.length} checks are ${verdict}.`}
            </p>
          </div>
        )}

        {/* The addresses the signer is aimed at. Same renderer as the pools
            above, because they are the same question — named checks, chain
            readings, a verdict — asked about a different subject. */}
        <Section title="The addresses the signer is pointed at" className="mt-12">
          {addrs?.ok && addrs.value.surveyed ? (
            <Card>
              <CardHeader
                eyebrow={
                  <span className="font-mono">
                    chain {addrs.value.chain_id}
                    {addrs.value.block != null && ` · block ${addrs.value.block.toLocaleString("en-US")}`}
                  </span>
                }
                title="Read, and cross-checked against each other"
                aside={
                  <Pill tone={verdictTone(addrs.value.verdict)}>
                    {addrs.value.verdict}
                  </Pill>
                }
              />
              <p className="mt-0 mb-4 max-w-[68ch] text-sm text-dim">
                {/* The claim is that mutual agreement is the strong check —
                    the rest was the reasoning behind it. */}
                The strong checks are the mutual ones: the factory naming the pool that
                names itself. Agreeing takes being the deployment.
              </p>
              <CheckList checks={narrow(addrs.value.checks)} />

              {addrs.value.venus?.surveyed && (
                <div className="mt-6 border-t border-line pt-4">
                  <Heading className="mt-0 mb-1 text-sm font-semibold">
                    Venus markets — the Yield category&rsquo;s gate
                  </Heading>
                  <p className="mt-0 mb-3 max-w-[68ch] text-sm text-dim">
                    Router will not quote below two markets that pass all of these. The
                    strong one is the same shape as above: a market&rsquo;s underlying
                    matching a token this repository verified from the PancakeSwap side,
                    months earlier and from the other direction.
                  </p>
                  <CheckList checks={narrow(addrs.value.venus.checks)} />
                </div>
              )}

              {addrs.value.erc8183 &&
                Object.entries(addrs.value.erc8183).map(([chain, record]) =>
                  record?.surveyed ? (
                    <div key={chain} className="mt-6 border-t border-line pt-4">
                      <Heading className="mt-0 mb-1 text-sm font-semibold">
                        ERC-8183 deployment, chain {chain}
                      </Heading>
                      <p className="mt-0 mb-3 max-w-[68ch] text-sm text-dim">
                        These readings are why the hire flow has an address at all. The
                        registry field in the vendor&rsquo;s table matches the one this
                        repository verified independently, on both chains.
                      </p>
                      <CheckList checks={narrow(record.checks)} />
                    </div>
                  ) : null,
                )}

              <p className="mt-5 mb-0 border-t border-line pt-3 font-mono text-xs break-all text-faint">
                read {timestamp(addrs.value.read_at)}
                {now !== null && <> · {hours(ageHours(addrs.value.read_at, now))} ago</>}
                {addrs.value.record && ` · ${addrs.value.record}`}
              </p>
            </Card>
          ) : addrs === null ? (
            /* Still loading, which is a third state and was being reported as
               the second.
               `addrs` is `null` until the fetch resolves, and `null` fell into
               the branch below — so the shipped static HTML told every reader
               without JavaScript that `addresses.json` "has not been generated",
               while the file sat beside it in the same directory, 2,472 bytes,
               copied into the export by the same build.
               On this page. Under a `floor` line reading "an address nobody
               checked and an address checked clean look identical once
               rendered". The page did the thing it exists to warn about, to the
               one reader who could not see it corrected a moment later. */
            <CardSkeleton />
          ) : (
            <Refusal
              title="The addresses were not verified"
              reason={
                addrs.ok
                  ? (addrs.value.reason ?? "no reading was recorded")
                  : `addresses.json could not be read — ${addrs.error.message}`
              }
              floor="an address nobody checked and an address checked clean look identical once rendered"
            />
          )}
        </Section>

    </Loadable>
  );
}
