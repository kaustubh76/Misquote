"use client";

import { useEffect, useState } from "react";
import { AnsweredBy } from "@/components/AnsweredBy";
import { Section } from "@/components/Heading";
import { Pill } from "@/components/Pill";
import { Refusal } from "@/components/Refusal";
import { loadLive, RefusalError, type Source } from "@/lib/api";
import { count, EMPTY, hours, pct, timestamp } from "@/lib/format";

/**
 * One line of the journal — and not every line is a decision.
 *
 * The warden writes lifecycle rows too: four of its 181 are
 * `{event: "run_start", chain_id, head_block, poll_seconds, …}` with no `ts`
 * and no `action` at all. `read_journal` already knows this, which is why its
 * summary reports `rows` and `decisions` as separate numbers.
 *
 * Both fields are therefore optional here. Typing `ts: number` did not make it
 * one: `new Date(undefined * 1000).toISOString()` throws `RangeError: Invalid
 * time value`, and because this renders inside the page rather than beside it,
 * that took the whole of `/agent/warden` down — a blank route, in all three
 * viewports, from a component that renders nothing at all when the API is
 * absent.
 */
interface Row {
  ts?: number;
  action?: string;
  reasons?: Record<string, number>;
}

interface Summary {
  rows: number;
  decisions: number;
  holds: number;
  mints: number;
  rebalances: number;
  pulls: number;
  errors: number;
  executed: number;
  first_ts?: number | null;
  last_ts?: number | null;
}

interface Journal {
  agent: string;
  total_rows: number;
  unparsed_rows: number;
  returned: number;
  summary: Summary;
  /**
   * Present when a live service answered, absent from the recorded fallback.
   *
   * `journal.json` carries the summary and not the rows: 344 decisions across
   * two agents was a 340KB artifact, and it made every tick index and float in
   * the file a literal no component may write — `-1` among them. The list below
   * is the part that needs the rows; the figures above it do not.
   */
  rows?: Row[];
}

const SECONDS_PER_HOUR = 3600;

/** How many of the newest decisions to render. The route's own tail is larger. */
const SHOWN = 8;

/**
 * What the live agent actually did, as distinct from what the replay found.
 *
 * Every figure on an agent's tearsheet comes from replaying its policy over
 * recorded history. None of it is a record of the agent *running* — and one
 * does exist: `data/journal/<agent>.jsonl` is append-only, is the tearsheet's
 * only input, and is served row by row at `/journal/{agent}` by a module whose
 * docstring explains that it deliberately does not summarise, because a summary
 * here would be a second implementation of `read_journal` and the two would
 * disagree. Nothing had ever fetched it.
 *
 * It is also the evidence behind a gate that is currently red. `/status`
 * reports the 24-hour testnet burn-in as UNVERIFIED with the detail "journal
 * covers 0.2h across 181 rows" — a blocking gate whose subject had no surface
 * anywhere on the site. On `/agent/warden` this section now shows that same
 * 0.2h across those same 181 rows, because it reads the same file.
 *
 * ## The gate looks at one agent
 *
 * `go_no_go.py` opens `journal/warden.jsonl` by name and nothing else. Router
 * has been writing too — 169 decisions across 168 hours on the tree this was
 * written against, unattended, which is seven times the gate's own 24-hour
 * threshold — and no gate counts it, because no gate looks. That is not an
 * argument for widening the gate here: burn-in means the *signing* agent ran
 * unattended, and Router records rather than signs. It is an argument for the
 * journal being visible per agent, which is what this is.
 *
 * An earlier version of this comment claimed the gate and the file disagreed by
 * three orders of magnitude. They do not. That was Router's 168h read against
 * Warden's 0.2h gate — two different agents, two different files, compared as
 * though they were one.
 *
 * ## No anchor, and therefore no rail entry
 *
 * The section renders only when a live service answers, so a rail pill pointing
 * at it would be dead on the static export — which `check-pages.mjs` sweeps for
 * and which `RouterDetail` has already been fixed for once. It has no `id` for
 * that reason, and the absence is the guard.
 *
 * ## Absent, not empty
 *
 * An agent that has never run has no journal, and `agent_names()` reads the
 * directory rather than the four agents we ship "because reporting it as
 * available would be advertising an empty file as a record". A 404 here is that
 * case, so it renders as nothing at all rather than as a section reading zero.
 */
export function AgentJournal({ agent }: { agent: string }) {
  const [journal, setJournal] = useState<Journal | null>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [refused, setRefused] = useState<RefusalError | null>(null);

  useEffect(() => {
    let live = true;
    (async () => {
      // The recorded summary as the fallback, so this section survives the API
      // being asleep. `journal.json` is keyed by agent and this call is about
      // one, hence `select`.
      const got = await loadLive<Journal>(`/journal/${agent}`, {
        fallback: "journal.json",
        select: (artifact) =>
          (artifact as { agents?: Record<string, unknown> })?.agents?.[agent],
      });
      if (!live) return;
      if (got.ok) {
        setJournal(got.value);
        setSource(got.source);
        return;
      }
      // A refusal is the service answering, and this used to throw it away.
      setRefused(got.error instanceof RefusalError ? got.error : null);
    })();
    return () => {
      live = false;
    };
  }, [agent]);

  // A refusal is rendered; an absence is not.
  //
  // These were one branch, and collapsing them cost the page a finding. The
  // API does not 404 blankly here — it answers `{error: "no journal for
  // 'grid'", remedy: "make warden ENV=testnet, or make router", available:
  // ["router", "warden"], note: "Either this agent has never run, or the name
  // is not one of ours. Both are absences and neither is an empty journal."}`
  // — and `return null` discarded all of it, on grid and sentinel every time
  // and on all four agents whenever nothing answered at all.
  //
  // The original reasoning still holds for the second case and is kept: an
  // agent with no journal, on a page full of replay results, should not report
  // an absence the reader did not ask about. But that argument is about
  // silence where there is nothing to say, and a service that took the trouble
  // to say why is not that.
  if (refused) {
    return (
      <Section
        title="What it did when it ran"
        className="mt-10"
        headingClassName="text-lg font-semibold"
      >
        <Refusal
          title="This agent has written no journal"
          reason={refused.message}
          floor={refused.remedy}
        />
      </Section>
    );
  }

  if (!journal || journal.total_rows === 0) return null;

  const { summary } = journal;
  const covered =
    summary.first_ts && summary.last_ts
      ? (summary.last_ts - summary.first_ts) / SECONDS_PER_HOUR
      : null;
  const acted = summary.mints + summary.rebalances + summary.pulls;
  // Decisions only. A `run_start` row has no action and is not something the
  // agent decided; listing it among the decisions would inflate the one number
  // on this page that is about the policy.
  const decisions = (journal.rows ?? []).filter((row) => typeof row.action === "string");

  return (
    <Section
      title="What it did when it ran"
      className="mt-10"
      headingClassName="text-lg font-semibold"
    >
      <div className="mt-2 mb-4 flex flex-wrap items-baseline justify-between gap-3">
        <p className="m-0 max-w-[62ch] text-sm text-dim">
          Everything above is this policy replayed over recorded history. This is the
          decision journal the live agent appended — the same file the readiness gate
          measures, served as rows rather than as a summary.
        </p>
        {source && <AnsweredBy source={source} />}
      </div>

      <dl className="m-0 mb-4 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        <Figure label="decisions" value={count(summary.decisions)} />
        <Figure
          label="held"
          // The share, because "168 holds" and "168 of 169 decisions were holds"
          // are different claims and only the second one is about the policy.
          value={
            summary.decisions > 0
              ? `${count(summary.holds)} · ${pct((summary.holds / summary.decisions) * 100, 0)}`
              : count(summary.holds)
          }
        />
        <Figure label="acted" value={count(acted)} />
        <Figure label="covers" value={covered === null ? "—" : hours(covered)} />
      </dl>

      {journal.unparsed_rows > 0 && (
        // Counted rather than swallowed by the route, so it is reported rather
        // than swallowed here: a journal with unreadable lines is a journal
        // whose totals are short by an unknown amount.
        <p className="mt-0 mb-4 text-xs text-warn">
          {count(journal.unparsed_rows)} line(s) in this journal could not be parsed and
          are not counted above.
        </p>
      )}

      <ol className="m-0 list-none space-y-1.5 p-0">
        {decisions.slice(-SHOWN).reverse().map((row, index) => (
          <li
            key={`${row.ts ?? "no-ts"}-${row.action}-${index}`}
            className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-line pb-1.5 text-xs last:border-0"
          >
            <span className="tabular shrink-0 font-mono text-faint">{when(row.ts)}</span>
            <Pill tone={row.action === "hold" ? "info" : "pass"}>{row.action}</Pill>
            {/* The reason keys the writer set to 1, which is how the agents
                record which branch they took. Rendered as the names rather than
                as the numbers: `reason_no_quotable_venue: 1.0` is a flag, and
                printing the 1.0 beside it would suggest a magnitude. */}
            <span className="min-w-0 font-mono break-words text-faint">
              {Object.entries(row.reasons ?? {})
                .filter(([key, value]) => key.startsWith("reason_") && value === 1)
                .map(([key]) => key.replace(/^reason_/, ""))
                // A `reason_hold` beside a "hold" pill is the same word twice.
                // The agents set a reason key named after the branch as well as
                // ones naming why it was taken, and only the second kind adds
                // anything next to the action.
                .filter((reason) => reason !== row.action)
                .join(" · ") || "—"}
            </span>
          </li>
        ))}
      </ol>

      <p className="mt-3 mb-0 text-xs text-faint">
        Newest first here; the file is append-only and newest last. Showing{" "}
        {count(Math.min(SHOWN, decisions.length))} of {count(summary.decisions)} recorded
        decisions
        {journal.total_rows > summary.decisions && (
          <> — the file also holds {count(journal.total_rows - summary.decisions)} lifecycle
          row(s), which are not decisions</>
        )}
        .
      </p>
    </Section>
  );
}

/** A journal timestamp, or a dash. Seconds since the epoch, and sometimes absent. */
function when(ts: number | undefined): string {
  if (typeof ts !== "number" || !Number.isFinite(ts)) return EMPTY;
  return timestamp(new Date(ts * 1000).toISOString());
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-mono text-[11px] tracking-wide text-faint uppercase">{label}</dt>
      <dd className="tabular m-0 text-sm text-ink">{value}</dd>
    </div>
  );
}
