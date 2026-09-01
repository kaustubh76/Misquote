"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AnsweredBy } from "@/components/AnsweredBy";
import { CoverageStrip, type Run } from "@/components/CoverageStrip";
import { Card, CardHeader } from "@/components/Card";
import { Section } from "@/components/Heading";
import { Pill } from "@/components/Pill";
import { Refusal } from "@/components/Refusal";
import { loadLive, RefusalError, type Source } from "@/lib/api";
import { load } from "@/lib/artifacts";
import { count, hours, shortAddress } from "@/lib/format";

/** One pool as `vetting.json` records it — the half that prerenders. */
export interface VettedPool {
  pool: string;
  label: string;
  badged: boolean;
  safe_to_provide: boolean;
}

export interface BadgeSurvey {
  chain_id: number;
  pools: VettedPool[];
}

/** One pool as `api/tape.py` reports it — the half that needs a running service. */
interface TapePool {
  pool: string;
  summary: {
    swaps?: number;
    mints?: number;
    burns?: number;
    first_ts?: number;
    last_ts?: number;
    first_block?: number;
    last_block?: number;
  };
  cursor_block: number | null;
  coverage: {
    known: boolean;
    runs: Run[];
    longest_contiguous: { from_block: number; to_block: number; blocks: number } | null;
    holes: Array<{ from_block: number; to_block: number }>;
  };
}

interface Tape {
  chain_id: number;
  database: string;
  pools: TapePool[];
}

const SECONDS_PER_HOUR = 3600;

/**
 * The one page on this site that describes a database rather than a run.
 *
 * Every other evidence route renders an artifact: a file an emitter wrote,
 * fixed at the moment it was written. `api/tape.py` exists because there is a
 * question none of them can answer — *what does the index hold right now* —
 * and it had no surface at all. The route was registered, tested, and
 * advertised in `api.json`'s own `routes` map, and nothing in this app had ever
 * called it.
 *
 * ## Why the pool list prerenders and the coverage does not
 *
 * Which pools this repository has verified is a recorded fact, so it comes from
 * `vetting.json` and is in the HTML with JavaScript switched off — the identity
 * of a pool, its badge and whether it is safe to provide into do not depend on
 * a service being up. What the tape *holds* for each is live by definition and
 * cannot be prerendered without becoming the thing this page exists to
 * distinguish itself from.
 *
 * That split is also why the refusal here is a panel per pool rather than a
 * page-level one: with no API configured, the reader still learns which pools
 * are verified. Only the coverage is missing, and only the coverage says so.
 */
export function TapeView({ vetted }: { vetted?: BadgeSurvey }) {
  const [badges, setBadges] = useState<BadgeSurvey | undefined>(vetted);
  const [tape, setTape] = useState<Tape | null>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [refusal, setRefusal] = useState<RefusalError | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let live = true;
    (async () => {
      // No fallback, and there could not be one. A snapshot of what a database
      // held yesterday, rendered where a reader asked what it holds now, is the
      // substitution this whole page argues against.
      const got = await loadLive<Tape>("/tape");
      if (!live) return;
      if (got.ok) {
        setTape(got.value);
        setSource(got.source);
      } else if (got.error instanceof RefusalError) {
        setRefusal(got.error);
      }
      setChecked(true);
    })();

    // The recorded half, refetched on the same terms every other view uses:
    // `readArtifact` supplies a first paint, and this overwrites it, so editing
    // the JSON and reloading still works. Only a successful read replaces it —
    // a missing `vetting.json` means nothing has been badged, and the honest
    // surface for that is the empty state below rather than a blank list.
    load<BadgeSurvey>("vetting.json").then((r) => {
      if (live && r.ok) setBadges(r.value);
    });

    return () => {
      live = false;
    };
  }, []);

  const byPool = new Map((tape?.pools ?? []).map((p) => [p.pool.toLowerCase(), p]));

  return (
    <>
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">
        What the index actually holds.
      </h1>
      <p className="mt-4 max-w-[62ch] text-md text-dim">
        Every other page reads a file written when some run finished. Only this
        one asks the database, live, what it actually holds.
      </p>

      <Section
        title="Why a span is not a coverage"
        className="mt-8"
        headingClassName="text-lg font-semibold"
      >
        <p className="mt-2 max-w-[62ch] text-dim">
          The obvious measure of how much history a tape holds is the distance
          between its first event and its last. It is the wrong one, and the way it
          is wrong is silent.
        </p>
        <p className="mt-3 max-w-[62ch] text-dim">
          A quiet range and a range nobody fetched both hold zero swaps, so a tape
          with a month-long gap reports a month and holds two days.
        </p>
        <p className="mt-3 max-w-[62ch] text-dim">
          So the indexer records what it <em>read</em>, not just what produced
          events. Hatching below is a range nobody fetched — absence, not a fault.
        </p>
        <p className="mt-3 mb-0 max-w-[62ch] text-dim">
          A database written before that table existed reports{" "}
          <strong className="text-ink">no</strong> coverage rather than full
          coverage. Unknown does not become pass — the same rule the{" "}
          <Link href="/vetting">badges</Link> follow.
        </p>
      </Section>

      <Section
        title="Every verified pool"
        className="mt-10"
        headingClassName="text-lg font-semibold"
      >
        <div className="mt-2 mb-5 flex flex-wrap items-baseline gap-x-4 gap-y-2">
          <p className="m-0 max-w-[62ch] text-sm text-dim">
            Which pools are verified is recorded. What the tape holds for each is
            read live, and cannot be anything else.
          </p>
          {checked && source && <AnsweredBy source={source} />}
        </div>

        {badges && badges.pools.length === 0 && (
          <Refusal
            title="No pool has been badged"
            reason="Nothing has read a pool from chain, so there is no verified pool to report a tape for."
            floor="Badge them with `make vet`, then index one with `make indexer POOL=0x…`."
          />
        )}

        <div className="grid gap-4">
          {(badges?.pools ?? []).map((pool) => {
            const live = byPool.get(pool.pool.toLowerCase());
            const summary = live?.summary;
            const span =
              summary?.first_ts && summary?.last_ts
                ? (summary.last_ts - summary.first_ts) / SECONDS_PER_HOUR
                : null;

            return (
              <Card key={pool.pool} as="article">
                <CardHeader
                  title={pool.label}
                  // `CardHeader`'s eyebrow is `uppercase`, which is right for
                  // the words it usually carries and wrong for a hex address:
                  // `shortAddress` returns `0x3669…2050` and it rendered as
                  // `0X3669…2050`, a prefix that does not exist.
                  eyebrow={<span className="normal-case">{shortAddress(pool.pool)}</span>}
                  aside={
                    pool.badged ? (
                      <Pill tone={pool.safe_to_provide ? "pass" : "unverified"}>
                        {pool.safe_to_provide ? "Verified" : "Badged, not cleared"}
                      </Pill>
                    ) : (
                      <Pill tone="none">Unbadged</Pill>
                    )
                  }
                />

                {live ? (
                  <>
                    <dl className="m-0 mb-4 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
                      <Figure label="swaps" value={count(summary?.swaps)} />
                      <Figure label="mints" value={count(summary?.mints)} />
                      <Figure label="burns" value={count(summary?.burns)} />
                      <Figure label="span" value={hours(span)} />
                    </dl>
                    <CoverageStrip
                      runs={live.coverage.runs}
                      known={live.coverage.known}
                      caption={`Blocks read for ${pool.label}`}
                    />
                    {live.cursor_block !== null && (
                      <p className="mt-3 mb-0 text-xs text-faint">
                        Reading stopped at block{" "}
                        <span className="tabular font-mono">{count(live.cursor_block)}</span>.
                        That is a resume point, not a claim of completeness — it is a
                        single high-water mark, so it cannot describe a tape with a
                        hole in it.
                      </p>
                    )}
                  </>
                ) : checked ? (
                  <Refusal
                    title="No live answer for this pool"
                    reason={
                      refusal?.message ??
                      "No running service answered, so what the index holds right now is unknown."
                    }
                    floor={
                      refusal?.remedy ||
                      "Start one with `make api` and publish its address with `make api-config`."
                    }
                  />
                ) : (
                  <p className="m-0 text-sm text-dim" role="status">
                    Reading the index…
                  </p>
                )}
              </Card>
            );
          })}
        </div>
      </Section>
    </>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-mono text-[11px] tracking-wide text-faint uppercase">{label}</dt>
      <dd className="tabular m-0 text-sm text-ink">{value}</dd>
    </div>
  );
}
