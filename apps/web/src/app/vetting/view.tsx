"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { ChipGroup, type Chip } from "@/components/ChipGroup";
import { Prose } from "@/components/Blocks";
import { CheckList } from "@/components/CheckList";
import { BadgeLookup } from "@/components/BadgeLookup";
import { SectionRail } from "@/components/SectionRail";
import { Heading, Section } from "@/components/Heading";
import { NotBuiltCard } from "@/components/Ledger";
import { Loadable } from "@/components/LoadingStatus";
import { TallyStrip } from "@/components/TallyStrip";
import { Pill } from "@/components/Pill";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { load, type IndexArtifact, type Loaded } from "@/lib/artifacts";
import { count, shortAddress } from "@/lib/format";

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
  checks?: VettingCheck[];
  summary?: { checked: number; failed: number; unknown: number };
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
  /** Stable key, so a finding is something a proof-of-concept can join to.
   *  Before this a finding was `(pool, name)` — free text, and rewording a
   *  check silently broke every reference to it. */
  id?: string;
  name: string;
  status: "PASS" | "WARN" | "FAIL" | "UNKNOWN";
  detail: string;
  provenance: string;
}

interface BadgeProof {
  ran: boolean;
  reason?: string;
  record?: string;
  coverage: {
    checks: number;
    provable: string[];
    not_provable: Record<string, string>;
    note: string;
  };
  proofs: { check_id: string; held: boolean; detail: string; block: number }[];
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
  proof?: BadgeProof;
}

export interface VettingArtifact {
  surveyed: boolean;
  reason?: string;
  chain_id: number;
  badge_dir: string;
  pools: VettingPool[];
  /**
   * The emitter's own rollup of `vetting.json`.
   *
   * Only what this page reads. It declared six more — `unbadged`, `cleared`,
   * `blocked`, `checks`, `unknown_checks`, `failed_checks` — and read none of
   * them: the first three never were, and the last three were deliberately
   * abandoned when the rollup started counting off the checks the page
   * actually renders rather than off two files. Leaving them declared
   * advertised six fields the page had decided were the wrong thing to draw,
   * which is the same defect one layer down as publishing a field nothing
   * reads.
   *
   * `verdicts` is the opposite case and is declared now: the emitter publishes
   * a per-verdict tally and the strip above reconstructs it by hand from
   * `everyCheck`. It stays reconstructed — the strip has to agree with the
   * list under it, and only the rendered checks can promise that — but the
   * field being on the wire and off the type is what made it invisible.
   */
  summary: {
    pools: number;
    badged: number;
    worst?: string;
    verdicts?: Record<string, number>;
  };
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

/**
 * Every check inside an address record, including the surveys nested in it.
 *
 * `AddressArtifact` contains other `AddressArtifact`s — `venus`, and one per
 * chain under `erc8183` — and the view renders all of them. Anything that
 * counts checks has to walk the same shape the renderer walks, or it reports a
 * number about a page other than the one on screen.
 */
function checksOf(record: AddressArtifact | undefined): VettingCheck[] {
  if (!record?.surveyed) return [];
  return [
    ...(record.checks ?? []),
    ...checksOf(record.venus),
    ...Object.values(record.erc8183 ?? {}).flatMap((chain) => checksOf(chain)),
  ];
}

/**
 * The rollup verdict's own tone.
 *
 * Not `PASS ? good : bad`. `RANK` distinguishes four verdicts and `badge.py` is
 * explicit that an UNKNOWN blocks without being a failure, so collapsing three
 * of them into red would be the mistake this file argues against for the
 * per-check pills, made one level up at the largest type size on the page.
 */
const VERDICT_STYLE: Record<string, string> = {
  PASS: "border-good-line bg-good-bg/50 text-good",
  FAIL: "border-bad-line bg-bad-bg/50 text-bad",
  WARN: "border-warn-line bg-warn-bg/50 text-warn",
  UNKNOWN: "border-line-strong bg-panel-2/60 text-dim",
};

/** One segment per verdict. UNKNOWN is a texture, not a colour — see the strip. */
const SEGMENT: Record<string, string> = {
  PASS: "bg-good",
  WARN: "bg-warn",
  UNKNOWN: "hatched bg-neutral/40 [--hatch-tone:var(--hatch-none)]",
  FAIL: "bg-bad",
};

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
    initialVetting ? { ok: true, value: initialVetting } : null
  );
  const [index, setIndex] = useState<Loaded<IndexArtifact> | null>(
    initialIndex ? { ok: true, value: initialIndex } : null
  );
  const [addrs, setAddrs] = useState<Loaded<AddressArtifact> | null>(
    initialAddresses ? { ok: true, value: initialAddresses } : null
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

  // Every check this page draws, including the two surveys nested inside the
  // address record.
  //
  // This summed the pools and the address record's own checks and stopped
  // there — 38 — while the page also renders `venus.checks` (18) and both
  // `erc8183` chain records (22) through the same `narrow()` and the same
  // `CheckList`. So the filter chip read "All 38" above 78 rendered checks, the
  // sentence below it said "Every one of the 38 checks below returned PASS"
  // about 78 of them, and narrowing to a verdict would have hidden forty checks
  // the count claimed to be filtering.
  //
  // On a page whose entire subject is counting checks read from chain, on a
  // site whose argument is that every number traces to its source. Recursive
  // now, so a survey nested one level deeper is counted rather than silently
  // dropped the way these two were.
  const everyCheck = [
    ...(state?.ok
      ? (state.value.pools ?? []).flatMap((p) => p.checks ?? [])
      : []),
    ...(addrs?.ok ? checksOf(addrs.value) : []),
  ];

  // The strip's segments, in severity order, off the checks the page renders.
  const tally = RANK.map((verdict) => ({
    verdict,
    n: everyCheck.filter((c) => c.status === verdict).length,
  }));

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
    return verdict === "all"
      ? checks ?? []
      : (checks ?? []).filter((c) => c.status === verdict);
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
  const verdicts = [
    d?.surveyed ? d.summary.worst : null,
    a?.surveyed ? a.verdict : null,
  ].filter((v): v is string => Boolean(v));
  const worstVerdict =
    verdicts.sort((x, y) => RANK.indexOf(y) - RANK.indexOf(x))[0] ?? "UNKNOWN";

  // `pools` is the pool block, or nothing when the run was not surveyed. It
  // used to be six defaulted counts feeding the rollup; the rollup counts the
  // rendered checks now, so the only survivor is the pool total.
  const pools = d?.surveyed ? d.summary : null;
  // Counted off the checks this page renders, not off the `summary` blocks.
  //
  // This was the same undercount `everyCheck` had and it survived the first
  // fix, which is worse than the original bug: the strip's segments came off
  // `everyCheck` (78) while the sentence under them came off these summaries
  // (38), so the picture and its own caption disagreed by forty checks.
  //
  // The summaries are not wrong — they describe `vetting.json` and
  // `addresses.json` as files. They are the wrong thing to describe a page
  // with, because the page also draws the two surveys nested inside the
  // address record. One source for both, and it is the rendered one.
  const totals = {
    subjects:
      (pools?.pools ?? 0) +
      (addrs?.ok && addrs.value.surveyed ? 1 : 0) +
      (addrs?.ok && addrs.value.venus?.surveyed ? 1 : 0) +
      (addrs?.ok
        ? Object.values(addrs.value.erc8183 ?? {}).filter((r) => r.surveyed)
            .length
        : 0),
    checks: everyCheck.length,
    unknown: everyCheck.filter((c) => c.status === "UNKNOWN").length,
    failed: everyCheck.filter((c) => c.status === "FAIL").length,
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
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">
        Due diligence, read from chain
      </h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        Every pool an agent touches and every address the signer is aimed at,
        read from chain. Each check names the defect that paid for it.
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
                Run <code className="font-mono text-xs">make vet</code> to read
                the pools, then{" "}
                <code className="font-mono text-xs">make vetting</code> to
                publish what it found.
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
        <div
          className={`surface mt-8 rounded-md border p-6 ${
            VERDICT_STYLE[worstVerdict] ??
            "border-warn-line bg-warn-bg/50 text-warn"
          }`}
        >
          {/* The answer, at the size of an answer.
              This page is the longest on the site — three near-identical pool
              blocks and two address surveys — and the one line saying what they
              add up to was a `text-xs` badge above them, with two more prose
              count-summaries stacked under it. `/status` and `/advantage` both
              have this exact `{pass}/{fail}/{unknown}` of `{total}` shape and
              both got a mark for it; this was the third and never did. */}
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <p className="m-0 font-mono text-3xl leading-none font-semibold tracking-tight">
              {worstVerdict}
            </p>
            <p className="m-0 font-mono text-xs">
              worst of {count(totals.subjects)} subjects
            </p>
          </div>

          {/* Counted off the checks the page renders, never off `summary` —
              which is what the undercount above this was. A picture that
              disagrees with the list under it is worse than no picture.

              UNKNOWN is hatched rather than tinted. A read that did not happen
              has no finding to colour, and `--hatch-none` is this site's mark
              for "there was never anything here" — the same texture a reader
              has already met on a not-built card. */}
          {/* `everyCheck.length` as the denominator, not the tally's own sum.
              A check whose verdict nobody recognised leaves a gap in the bar
              rather than being redistributed across the verdicts that were
              counted — which is the whole reason `TallyStrip` requires a total
              instead of adding the parts up. */}
          <TallyStrip
            className="mt-4"
            total={everyCheck.length}
            parts={tally.map(({ verdict, n }) => ({
              label: verdict,
              tone: SEGMENT[verdict] ?? "bg-neutral",
              n,
            }))}
            ariaSentence={
              `${worstVerdict} is the worst verdict on this page: ` +
              `${tally.map((t) => `${count(t.n)} ${t.verdict}`).join(", ")}, ` +
              `across ${count(everyCheck.length)} checks read from chain.`
            }
          />

          {/* The same figures in words, and the sentence `pages.test.tsx` looks
              up with a singular `getByText`. It stays exactly one text node. */}
          <p className="mt-3 mb-0 text-sm">
            {count(totals.checks)} checks across {count(totals.subjects)}{" "}
            subjects · {count(totals.unknown)} unknown · {count(totals.failed)}{" "}
            failed
          </p>
        </div>
      )}

      {/* The longest page on the site, and until now the only way down it was
          the scrollbar — three near-identical pool blocks, then two address
          surveys. Every id is gated on the section that owns it actually
          rendering, so a run that badged nothing cannot produce a pill pointing
          at a heading that was never drawn.

          Anchored by address rather than by position: two of the three pool
          labels differ only in their fee tier, and the address is the identity
          `/venue` and `/vetting` already cross-reference each other by. */}
      {d?.surveyed && (
        <SectionRail
          label="On this page"
          items={[
            ...d.pools.map((pool) => ({
              id: pool.pool,
              label: pool.label || shortAddress(pool.pool),
            })),
            ...(addrs?.ok && addrs.value.surveyed
              ? [{ id: "addresses", label: "Addresses" }]
              : []),
            ...(proofs.length > 0
              ? [{ id: "not-proofs", label: "Not proofs" }]
              : []),
          ]}
        />
      )}

      {d?.surveyed && (
        <>
          {/* Three stacked count-summaries became one strip and one line. What
              is left here is the only figure the strip does not carry — how
              many pools came away with a badge — and it sits with the pools it
              counts rather than in a rollup of rollups. */}
          <p className="mt-6 mb-0 font-mono text-xs text-faint">
            {count(d.summary.badged)} of {count(d.summary.pools)} pools badged
          </p>

          {d.pools.map((pool) => (
            <Section
              key={pool.pool}
              id={pool.pool}
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
                    title={
                      pool.safe_to_provide
                        ? "Cleared to provide"
                        : "Not cleared"
                    }
                    aside={
                      <Pill tone={verdictTone(pool.verdict)}>
                        {pool.verdict}
                      </Pill>
                    }
                  />

                  <CheckList checks={narrow(pool.checks)} />

                  {pool.proof && <ProofBlock proof={pool.proof} />}
                </Card>
              )}
            </Section>
          ))}
          {proofs.length > 0 && (
            <Section
              id="not-proofs"
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
          <strong className="text-ink">
            {verdictChips[1]?.value ?? "the same verdict"}
          </strong>
          .
        </p>
      )}

      {everyCheck.length > 0 && verdictChips.length > 2 && (
        <div className="surface mt-8 rounded-lg border border-glass-line bg-glass p-4">
          <ChipGroup
            label="Filter checks by verdict"
            options={verdictChips}
            value={verdict}
            onChange={setVerdict}
          />
          {/* Named, because `Loadable` already owns an unnamed `role="status"`
                on this page. Two anonymous voices is one too many. */}
          <p
            role="status"
            aria-label="Check filter result"
            className="mt-3 mb-0 text-xs text-faint"
          >
            {verdict === "all"
              ? `All ${everyCheck.length} checks, across every subject below.`
              : `${everyCheck.filter((c) => c.status === verdict).length} of ${
                  everyCheck.length
                } checks are ${verdict}.`}
          </p>
        </div>
      )}

      {/* The question this page could not answer: not "which pools have
            badges" but "what about *this* one". `/vetting/{address}` sends two
            different 404s for it — a pool we verified and never vetted, and a
            pool we never verified — and collapsing those is what the route's own
            comment says the surface exists to avoid.

            No `id` and no rail entry: it needs a live service, so an anchor
            would be dead on the static export. */}
      <Section
        title="Ask about an address"
        className="mt-12"
        headingClassName="text-lg font-semibold"
      >
        <p className="mt-2 mb-4 max-w-[62ch] text-sm text-dim">
          Recorded badges only — a badge is a set of chain readings taken at one
          block, and one re-read live under a request timeout would be a weaker
          badge at the same URL with nothing saying so.
        </p>
        <BadgeLookup />
      </Section>

      {/* The addresses the signer is aimed at. Same renderer as the pools
            above, because they are the same question — named checks, chain
            readings, a verdict — asked about a different subject. */}
      <Section
        id="addresses"
        title="The addresses the signer is pointed at"
        className="mt-12"
      >
        {addrs?.ok && addrs.value.surveyed ? (
          <Card>
            <CardHeader
              eyebrow={
                <span className="font-mono">
                  chain {addrs.value.chain_id}
                  {addrs.value.block != null &&
                    ` · block ${addrs.value.block.toLocaleString("en-US")}`}
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
              The strong checks are the mutual ones: the factory naming the pool
              that names itself. Agreeing takes being the deployment.
            </p>
            <CheckList checks={narrow(addrs.value.checks)} />

            {addrs.value.venus?.surveyed && (
              <div className="mt-6 border-t border-line pt-4">
                <Heading className="mt-0 mb-1 text-sm font-semibold">
                  Venus markets — the Yield category&rsquo;s gate
                </Heading>
                <p className="mt-0 mb-3 max-w-[68ch] text-sm text-dim">
                  Router will not quote below two markets that pass all of
                  these. The strong one is the same shape as above: a
                  market&rsquo;s underlying matching a token this repository
                  verified from the PancakeSwap side, months earlier and from
                  the other direction.
                </p>
                <CheckList checks={narrow(addrs.value.venus.checks)} />

                {/* The gate's newest dependant, which this section did not
                      mention.

                      This heading has read "Venus markets — the Yield
                      category's gate" since Router had only lending markets to
                      choose between. Router now allocates to PancakeSwap ranges
                      as venues, and whether it may enter one is decided by the
                      badge above rather than by anything in the policy: one
                      rule, `vetting/badge.py::cleared_to_provide`, shared with
                      the report that decides which pools this site points a
                      reader at.

                      Worth saying on this page in particular. Its whole
                      argument is that due diligence governs what an agent may
                      touch, and the strongest evidence for that is a case where
                      it actually refused something — which it has. */}
                <p className="mt-4 mb-0 max-w-[68ch] text-sm text-dim">
                  The badge is also what lets Router put capital into a{" "}
                  <Link href="/venue">PancakeSwap range</Link> at all. The same
                  rule decides which pools this site points a reader at and
                  which ones the Yield agent may enter as a venue, and an absent
                  badge is a refusal rather than a pass — a pool nobody has
                  checked is one nobody should be steered into, in either
                  direction.
                </p>
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
                      These readings are why the hire flow has an address at
                      all. The registry field in the vendor&rsquo;s table
                      matches the one this repository verified independently, on
                      both chains.
                    </p>
                    <CheckList checks={narrow(record.checks)} />
                  </div>
                ) : null
              )}
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
                ? addrs.value.reason ?? "no reading was recorded"
                : `addresses.json could not be read — ${addrs.error.message}`
            }
            floor="an address nobody checked and an address checked clean look identical once rendered"
          />
        )}
      </Section>
    </Loadable>
  );
}


/**
 * What a finding's proof did, and what the unproven ones are.
 *
 * `Readme.md` §1 promises findings that ship an executable proof-of-concept.
 * Three of the nine checks have one; the other six are readings, and there is
 * no transaction that demonstrates a reading.
 *
 * **The unproven list is the load-bearing half.** Three green ticks beside nine
 * checks reads as six failures unless the six say why they are absent, so this
 * renders the reasons rather than a count. `vetting/proof.py` has a test
 * asserting every check is either proven or explained.
 */
function ProofBlock({ proof }: { proof: BadgeProof }) {
  const unprovable = Object.entries(proof.coverage.not_provable);
  return (
    <div className="mt-5 border-t border-line pt-4">
      <p className="mt-0 mb-2 text-xs tracking-wide text-faint uppercase">
        They flag, we prove
      </p>

      {proof.ran ? (
        <ul className="m-0 list-none space-y-1.5 p-0 text-sm">
          {proof.proofs.map((entry) => (
            <li key={entry.check_id} className="flex flex-wrap items-baseline gap-2">
              <Pill tone={entry.held ? "pass" : "fail"}>
                {entry.held ? "held" : "did not hold"}
              </Pill>
              <span className="font-mono text-xs text-ink">{entry.check_id}</span>
              <span className="text-dim">{entry.detail}</span>
              <span className="text-xs text-faint">
                on a fork at block {entry.block.toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-0 mb-0 text-sm text-dim">
          <Prose text={proof.reason ?? "No proof has been executed on this badge."} />{" "}
          {proof.coverage.provable.length} of {proof.coverage.checks} checks are
          executable: {proof.coverage.provable.join(", ")}.
        </p>
      )}

      {unprovable.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-faint">
            {unprovable.length} of {proof.coverage.checks} checks have no
            proof-of-concept, and why
          </summary>
          <ul className="mt-2 mb-0 list-none space-y-2 p-0 text-sm">
            {unprovable.map(([id, why]) => (
              <li key={id} className="border-glass-line border-l-2 pl-3">
                <span className="font-mono text-xs text-ink">{id}</span>
                <span className="block text-dim">{why}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 mb-0 text-xs text-faint">{proof.coverage.note}</p>
        </details>
      )}
    </div>
  );
}
