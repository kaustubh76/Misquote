"use client";

import { Heading, Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import { useEffect, useState } from "react";
import { Badge } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { Prose } from "@/components/Blocks";
import { DataTable } from "@/components/DataTable";
import { Disagreement } from "@/components/Disagreement";
import { SectionRail } from "@/components/SectionRail";
import { IndexedAgreement } from "@/components/IndexedAgreement";
import type { OursAsIndexed, OursCrossCheck, TestnetCounts } from "@/components/IndexedAgreement";
import { NameCollisionsCard, ScanLeaderboardCard } from "@/components/ScanAgents";
import type { NameCollisions, ScanLeaderboard } from "@/components/ScanAgents";
import { ShareIntervals, type ShareInterval } from "@/components/ShareIntervals";
import { TallyStrip } from "@/components/TallyStrip";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { EscrowConsole } from "@/components/EscrowConsole";
import { CheckList, type CheckRow } from "@/components/CheckList";
import { CardSkeleton } from "@/components/Skeleton";
import Link from "next/link";
import { Pill, statusTone } from "@/components/Pill";
import { RegistrySearch } from "@/components/RegistrySearch";
import { load, type Loaded } from "@/lib/artifacts";
import { count, fixed, hours, isNum, pct, shortAddress } from "@/lib/format";

interface Step {
  call: string;
  sender: string;
  contract: string;
  why: string;
  is_erc8183: boolean;
}

/**
 * One third-party agent from the ERC-8004 registry.
 *
 * Deliberately shaped unlike our own agent cards, which carry a P25-P75 range
 * replayed from thirty days of real history. We do not have a third party's
 * policy, so there is nothing to replay and there is no number to show. Every
 * other marketplace fills that gap with stars or install counts; filling it
 * here would be the misquote this project is named after, on our own page.
 *
 * `tests/web/test_third_party_listings.py` asserts against the artifact that no
 * field on this type is performance-shaped, so the absence cannot be undone by
 * an edit to this file alone.
 */
export interface ThirdPartyListing {
  agent_id: number;
  name: string;
  description: string;
  endpoints: string[];
  declares_active: boolean;
  declares_schema: boolean;
  resolvable: boolean;
  describes_a_service: boolean;
  looks_like_a_placeholder: boolean;
  substantive: boolean;
  on_chain: boolean;
  notes: string[];
}

function ListingCard({ agent }: { agent: ThirdPartyListing }) {
  const name = agent.name.trim() || `Agent #${agent.agent_id}`;
  return (
    <Card as="article" className="flex min-w-0 flex-col gap-2">
      <CardHeader
        title={name}
        eyebrow={`ERC-8004 #${agent.agent_id}`}
        aside={
          <Pill tone={agent.substantive ? "pass" : "unverified"}>
            {agent.substantive ? "describes a service" : "registration only"}
          </Pill>
        }
      />
      {/* `break-words`, and it is not decorative. These descriptions are written
          by strangers: one agent in the first real survey describes itself as
          "5301971776071525618169367322226036917262739277182945465082…", sixty
          digits with no space in them. Rendered without this it set the card's
          min-content width to 599px and pushed /registry **234px** past a 390px
          viewport — the same failure `Refusal` documents for its floor line and
          `vectors/view.tsx` for its command string.

          `min-w-0` on the card and its grid item for the other half of it: a
          grid item defaults to `min-width: auto` and refuses to shrink below
          its own min-content, so wrapping the text is not enough on its own. */}
      {agent.description.trim() && (
        <p className="text-sm break-words text-dim line-clamp-3">{agent.description}</p>
      )}
      <ul className="flex flex-wrap gap-1.5">
        <Pill tone={agent.resolvable ? "pass" : "fail"}>
          {agent.resolvable ? "card resolves" : "card does not resolve"}
        </Pill>
        <Pill tone={agent.declares_active ? "pass" : "none"}>
          {agent.declares_active ? "declares active" : "not active"}
        </Pill>
        {agent.on_chain && <Pill tone="info">card is on chain</Pill>}
        {agent.looks_like_a_placeholder && <Pill tone="fail">placeholder</Pill>}
      </ul>
      {agent.endpoints.length > 0 && (
        <p className="font-mono text-xs break-all text-dim">{agent.endpoints[0]}</p>
      )}
      {/* The sentence that makes this page honest. It is on every card, not in
          a footnote, because the absence of a number is the claim. */}
      <p className="text-xs text-dim">
        No quote — we cannot replay a policy we do not have.
      </p>
    </Card>
  );
}

function ThirdPartyListings({
  agents,
  population,
}: {
  agents: ThirdPartyListing[];
  population?: number;
}) {
  const substantive = agents.filter((a) => a.substantive).length;
  return (
    <Card className="mt-4">
      <CardHeader
        title="Third-party agents, as the registry describes them"
        aside={
          <Pill tone="info">
            {substantive} of {agents.length} sampled
          </Pill>
        }
      />
      <p className="mt-2 text-sm text-dim">
        Sampled across{" "}
        {population ? population.toLocaleString() : "the"} registered agents. Listings, not
        tearsheets: each repeats what its registration claims and carries{" "}
        <strong>no performance figure</strong>. Only a policy we hold can be replayed.
      </p>
      <ul className="mt-4 grid gap-3 sm:grid-cols-2">
        {agents.map((agent) => (
          <li key={agent.agent_id} className="min-w-0">
            <ListingCard agent={agent} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** One agent of ours, as `scripts/register_identity.py` recorded it. */
export interface OwnIdentity {
  agent: string;
  name: string;
  agent_id: number;
  token_uri_bytes: number;
  register_tx: string;
  transfer_tx: string;
  register_url: string;
  transfer_url: string;
  agent_url: string;
  gas_used: number;
}

/**
 * The registrations this project made in the registry it surveys.
 *
 * `surveyed: false` is the ordinary state of a checkout that has not run
 * `make identity-register`, and it renders as the service's own refusal rather
 * than as an empty table — the distinction `/vetting` draws between a subject
 * nobody checked and a subject that came back clean.
 *
 * `checks` is the same `{name, status, detail, provenance}` shape every other
 * chain reading on this site publishes, so `CheckList` renders it unchanged.
 */
export interface OwnIdentities {
  surveyed: boolean;
  /**
   * How long ago the record was read, in hours.
   *
   * Computed by the emitter on every build from the file's mtime and drawn
   * nowhere, so the page presented a reading of unknown age as current.
   */
  age_hours?: number;
  /**
   * The check tally. All four, including the two that are zero — see the note
   * at the render site for why the failing halves are not optional.
   */
  summary?: {
    checked?: number;
    registered?: number;
    failed?: number;
    unknown?: number;
  };
  reason?: string;
  chain_id: number;
  verdict?: string;
  owner?: string;
  signer?: string;
  registry?: string;
  block?: number | null;
  explorer?: string;
  agents: OwnIdentity[];
  checks: CheckRow[];
}

export interface RegistryArtifact {
  ours?: OwnIdentities;
  hire_flow: {
    steps: Step[];
    transaction_count: number;
    client_transaction_count: number;
    states: string[];
    terminal_states: string[];
    escrow: { available: boolean; address?: string; reason?: string; evidence?: string[] };
    recourse?: Step[];
    /** Selector -> what it means. None of these is in any ABI: `createJob`
     *  reverts with bare four-byte selectors and no reason string, so each was
     *  isolated by varying one argument at a time. Three were then matched to a
     *  name; the rest say "unresolved" rather than guessing one. */
    errors?: Record<string, string>;
    /** What happened when the flow was actually sent, as opposed to priced. */
    proof?: {
      ran: boolean;
      reason?: string;
      job_id?: number;
      escrowed?: boolean;
      mined?: string[];
      reverted?: string[];
      not_escrowed_because?: string;
      transactions?: { call: string; tx_hash?: string; explorer?: string; reverted?: string; meaning?: string }[];
    };
    /**
     * The same flow on a fork, which is a different claim and never merged.
     *
     * `proof` is chapel, mined, and stops at `fund`. This one runs to
     * settlement against the mainnet deployment's own bytecode at a forked
     * block, because a fork can impersonate the payment token's owner and a
     * live wallet has to buy from PancakeSwap first. `network` is rendered
     * beside `escrowed` for that reason: the two records disagree, and the only
     * thing that makes the disagreement legible is saying which is which.
     */
    fork_proof?: {
      ran: boolean;
      reason?: string;
      network?: string;
      job_id?: number;
      escrowed?: boolean;
      settled?: boolean;
      escrowed_on_mainnet?: boolean;
      why_not_on_mainnet?: string;
      transactions?: { call: string; ok?: boolean }[];
    };
    /**
     * The run that cost money, and the one that did not finish.
     *
     * `fund` moved 0.1 of the payment token into a real job on BSC mainnet.
     * `submit` and `settle` then refused, and the fork above only got past that
     * by moving the clock seven days — which is the whole reason these are
     * three records and not one averaged claim.
     */
    mainnet_proof?: {
      ran: boolean;
      reason?: string;
      network?: string;
      job_id?: number;
      escrowed?: boolean;
      settled?: boolean;
      budget?: number;
      transactions?: { call: string; ok?: boolean; reverted?: string; explorer?: string }[];
    };
    /**
     * Getting it back, which is a different claim from escrowing it.
     *
     * `mainnet_proof` ends with the money in the kernel and both release calls
     * refusing. `claimRefund` is the way out, and it opens at `expiredAt` — a
     * `block.timestamp` comparison, so on mainnet it cannot be hurried and on a
     * fork it is the one thing that can. This record says which of the two it
     * was, and a fork hash is deliberately not a link: it was never on a chain
     * anyone can look it up on.
     */
    submit_proof?: {
      ran: boolean;
      reason?: string;
      network?: string;
      job_id?: number;
      submitted?: boolean;
      settled?: boolean;
      escrowed?: boolean;
      expires_at_utc?: string;
      settle_earliest_utc?: string;
      why_settle_reverted?: string;
      what_this_run_changes?: string;
      transactions?: {
        actor?: string;
        call: string;
        ok?: boolean;
        tx_hash?: string;
        explorer?: string;
        reverted?: string;
      }[];
    };
    refund_proof?: {
      ran: boolean;
      reason?: string;
      network?: string;
      job_id?: number;
      refunded?: boolean;
      recovered?: number;
      expires_at_utc?: string;
      status_before?: number;
      status_after?: number;
      transactions?: { call: string; ok?: boolean; when?: string; tx?: string }[];
    };
    /** Every address a browser needs to send this itself, by chain id. */
    deployments?: Record<
      string,
      {
        chain_id: number;
        name: string;
        explorer: string;
        kernel: string;
        router: string;
        policy: string;
        erc20: string;
      }
    >;
  };
  identity: {
    surveyed: boolean;
    reason?: string;
    population?: number;
    agents?: ThirdPartyListing[];
    identity_registry: Record<string, string>;
    reputation_registry: Record<string, string>;
    reputation_note: string;
    substantive_share?: number;
    /** Numerator and denominator of `substantive_share`, so the page need not
     *  reconstruct either from a percentage it was handed. */
    substantive?: number;
    sampled?: number;
    sampled_at_block?: number;
    sampled_ids?: number[];
    /** How many of the sampled agents are published as cards. The shares are
     *  computed from the whole sample; this bounds only what renders, and both
     *  numbers are carried so the card count cannot be read as the sample size. */
    listings_shown?: number;
    /** The level those bounds are at, as a fraction — 0.95 for a 95% interval.
     *
     *  Optional because a survey recorded before the emitter published it has
     *  the bounds and not the level, and the label says "CI" without a number
     *  rather than asserting one. It was typed as "95%" beside intervals the
     *  emitter computes, which made the one figure that gives a pair of bounds
     *  a meaning the one figure not read from anything. */
    confidence_level?: number;
    /** A Wilson interval per share. A share from a few hundred of ~280,000
     *  agents is not a point, and printing it as one is the false precision
     *  this page exists to criticise. */
    intervals?: Record<string, { low: number; high: number }>;
    /**
     * The numerators for the other five shares in `intervals`, all out of
     * `sampled`.
     *
     * `substantive` was declared from the start and these were not, so the page
     * could draw one interval and had no honest way to draw the rest — a bar
     * needs the count the survey made, and multiplying a published percentage
     * back out to get one is precisely the false precision the comment above
     * objects to. So five intervals went unrendered next to a note explaining
     * why rendering them as points would be wrong.
     *
     * Optional for the same reason `substantive` and `sampled` are: an offline
     * run writes `{ surveyed: false }` and none of them.
     */
    resolvable?: number;
    declared_active?: number;
    on_chain_cards?: number;
    with_endpoint?: number;
    placeholders?: number;
    /** The sampler's seed, recorded so the survey is reproducible. */
    seed?: number;
  };
  aacp: {
    available: boolean;
    chain_id?: number;
    shares_our_identity_registry?: boolean;
    contracts?: Record<string, string>;
    note?: string;
    reason?: string;
    /**
     * How much of the deployed escrow's interface was recovered.
     *
     * `resolved` of `total` selectors matched to a signature. Deliberately not
     * rendered as a `FloorGauge`: nobody required 65, so "short of the floor"
     * would draw a counted unknown as a failure. `note` says what the rest are
     * — counted, not guessed — and renders verbatim.
     */
    escrow_selectors?: { resolved: number; total: number; note: string };
    /**
     * The two findings this block exists to report, and the interface behind them.
     *
     * Not in this type until now, which is why they were unrendered: the
     * emitter has carried them since it was written, `Readme.md` §8 leans on
     * both, and the page could not read what it had not declared.
     */
    not_erc8183?: string;
    order_decode?: string;
  };
  /**
   * What a third-party index says about the same registry.
   *
   * Declared partially, on purpose. `registry.json`'s `third_party` block also
   * carries a `stats` and a `sample` section that nothing draws, and typing
   * those would be the "declared and never read" defect
   * `tests/web/test_no_dead_exports.py` exists for, one layer down. Only what
   * is rendered is declared.
   */
  third_party?: {
    source?: string;
    tier?: string;
    /** Our own four, read back from an index we do not run. */
    ours_as_indexed?: OursAsIndexed;
    ours_cross_check?: OursCrossCheck;
    counts_testnet?: TestnetCounts;
    name_collisions?: NameCollisions;
    leaderboard?: ScanLeaderboard;
    /**
     * Shares 8004scan reported, each with the proof that its filter applied.
     *
     * `applied` is a different word from `available` and the distinction is the
     * whole mechanism: `available: false` means the API did not answer,
     * `applied: false` means it answered and did not listen. This API accepts
     * filters it does not implement and returns the entire population under
     * the label you asked for, so a share with no proof beside it is a
     * population wearing a name.
     */
    counts?: {
      available: boolean;
      baseline?: number;
      requests?: number;
      refused?: string[];
      note?: string;
      filters?: Record<
        string,
        {
          applied: boolean;
          reason: string | null;
          baseline: number;
          rows_checked: number;
          rows_satisfying: number;
          differs_from_baseline?: boolean;
          total?: number;
          share?: number;
          complement_total?: number;
          sum_vs_baseline?: number;
          within_tolerance?: boolean;
          growth_tolerance?: number;
        }
      >;
    };
    /** The same quantity walked and asked, with both denominators. */
    counts_cross_check?: {
      available: boolean;
      hours_apart: number | null;
      note: string;
      rows: {
        quantity: string;
        compared: boolean;
        reason?: string;
        walked?: number;
        walked_of?: number;
        walked_share?: number | null;
        asked?: number;
        asked_of?: number;
        asked_share?: number | null;
        difference?: number;
        share_difference_pp?: number | null;
        agree?: boolean;
      }[];
    };
    /**
     * Who does the rating.
     *
     * The shares here carry no confidence interval, and that is the opposite of
     * the `ShareIntervals` block above: those describe a sample of 400 and are
     * ranges because they must be. These describe a table that was walked in
     * full, so `rows` is the denominator and nothing was inferred.
     */
    feedback_graph?: {
      available: boolean;
      reason?: string;
      rows: number;
      total_reported: number;
      complete: boolean;
      distinct_raters: number;
      distinct_rated_agents: number;
      top_rater_share: number | null;
      top_five_rater_share: number | null;
      anchored: number;
      with_comment: number;
      uris_decoded: number;
      declaring_a_method: number;
      declaring_known_defects: number;
      revoked: number;
      note: string;
    };
    /** One quantity, three routes, published as a spread. */
    agents_with_feedback_three_ways?: {
      available: boolean;
      readings: {
        route: string;
        agents: number;
        of: number | null;
        read_at: string | null;
        carried_forward?: boolean;
      }[];
      low: number;
      high: number;
      spread: number;
      agree: boolean;
      note: string;
    };
    /** The walk. Kept for the six shares no filter answers, and stamped. */
    census?: {
      available: boolean;
      reason: string | null;
      carried_forward: boolean;
      read_at: string | null;
      counted: number | null;
      complete: boolean | null;
      distinct_owners: number | null;
      distinct_descriptions: number | null;
    };
    /**
     * The feedback table's own total, counted from the other end.
     *
     * `feedbacks` reaches the page through `feedback_cross_check`, which
     * compares it against the sum over agent rows. What was unrendered until
     * now is the half that makes the count checkable: `anchored`, and an
     * example row naming the transaction and block that wrote it.
     */
    feedback_reach?: {
      available: boolean;
      anchored?: boolean;
      example_transaction_hash?: string;
      example_block_number?: number;
    };
    feedback_cross_check?: {
      available: boolean;
      summed_over_agents?: number;
      counted_in_feedback_table?: number;
      difference?: number;
      agree?: boolean;
      note: string;
    };
    reconciliation?: {
      ours: number;
      ours_method: string;
      theirs: number;
      theirs_method: string;
      difference: number;
      /**
       * The gap as a share **of the larger** count, in percentage points and
       * always positive: `1.86` means 1.86%.
       *
       * It used to be a share of *ours*, signed. Both went wrong the day
       * 8004scan's count overtook ours: the page rendered a negative distance,
       * and the denominator became the smaller count while the caption went on
       * calling it the larger. `difference` beside it stays signed, because
       * which one leads is a fact worth keeping.
       */
      difference_pct: number;
      /** Whether both methods are counting the same contract at all. */
      same_contract: boolean;
      /** The emitter's own sentence on why the gap is not resolved. Verbatim. */
      note: string;
    };
  };
  // `registry.json` has carried this since the emitter was written, and this
  // page showed none of it — every address on it read as a standing fact rather
  // than as something a named command read at a named time.
}

/** Only what the deliverable's gate needs. `/status` owns the rest of the shape. */
export interface StatusSummary {
  checks: { name: string; status: string; detail: string; remedy?: string }[];
}

/** The gate the track turns on, by the name `scripts/go_no_go.py` gives it. */
const DELIVERABLE_GATE = "agent advantage report";

/**
 * The six shares, under the names the emitter's own report gives them.
 *
 * Verbatim from `RegistrySurvey.render()` in
 * `packages/misquote/registry/erc8004.py`, which already prints "card
 * resolves", "declares an endpoint", "placeholder text", "declares itself
 * live" and "card held on chain" — so the page does not invent a second
 * vocabulary for categories that have one.
 *
 * `substantive` is the exception and is deliberately just the word: the survey
 * table below has a row labelled "substantive agent cards", and
 * `src/app/pages.test.tsx` looks that string up with a singular `findByText`
 * that throws on two matches. Same claim, two scales, one of them named once.
 */
const SHARE_LABEL: Record<string, string> = {
  resolvable: "card resolves",
  declared_active: "declares itself live",
  on_chain_cards: "card held on chain",
  with_endpoint: "declares an endpoint",
  substantive: "substantive",
  placeholders: "placeholder text",
};

/**
 * Each published interval joined to the numerator that produced it.
 *
 * Driven off `intervals` rather than off the counts, so a share the emitter
 * stops publishing an interval for disappears rather than quietly reverting to
 * a point estimate.
 *
 * A key with no numerator on this interface is **dropped, never reconstructed**
 * from `substantive_share` or from a bound. Turning a published percentage back
 * into a count is exactly the false precision the interface comment above
 * objects to, and doing it to fill a bar would be that mistake inside the fix
 * for it.
 *
 * Sorted by count, which is presentation and not a claim: it puts the survey's
 * shape on the page without asserting the rows are a funnel, which they are not
 * — `placeholders` runs the other way.
 */
function shareRows(identity: RegistryArtifact["identity"]): ShareInterval[] {
  const counts: Record<string, number | undefined> = {
    resolvable: identity.resolvable,
    declared_active: identity.declared_active,
    on_chain_cards: identity.on_chain_cards,
    with_endpoint: identity.with_endpoint,
    substantive: identity.substantive,
    placeholders: identity.placeholders,
  };

  return Object.entries(identity.intervals ?? {})
    .map(([key, ci]) => ({
      key,
      label: SHARE_LABEL[key] ?? key,
      n: counts[key],
      low: ci.low,
      high: ci.high,
    }))
    .filter((row): row is ShareInterval => isNum(row.n))
    .sort((a, b) => b.n - a.n);
}

export function RegistryView({
  initialRegistry,
  initialStatus,
}: {
  /** Read from disk at build time by `page.tsx`. See `lib/build-artifact`. */
  initialRegistry?: RegistryArtifact;
  initialStatus?: StatusSummary;
}) {
  const [state, setState] = useState<Loaded<RegistryArtifact> | null>(
    initialRegistry ? { ok: true, value: initialRegistry } : null,
  );
  const [status, setStatus] = useState<Loaded<StatusSummary> | null>(
    initialStatus ? { ok: true, value: initialStatus } : null,
  );

  useEffect(() => {
    let live = true;
    // The gate lives in `status.json`, not here — the deliverable is judged by
    // the readiness checklist, and this page reads that verdict rather than
    // forming its own.
    Promise.all([
      load<RegistryArtifact>("registry.json"),
      load<StatusSummary>("status.json"),
    ]).then(([r, s]) => {
      if (!live) return;
      setState(r);
      setStatus(s);
    });
    return () => {
      live = false;
    };
  }, []);

  const d = state?.ok ? state.value : null;

  // Found by name. `go_no_go.py` orders its checks and that order is not a
  // contract, so a positional read would quietly start reporting a different
  // gate the day one is inserted above it.
  const gate = status?.ok
    ? status.value.checks.find((c) => c.name === DELIVERABLE_GATE)
    : undefined;

  return (
    <Loadable loading={state === null} what="the registry sample">
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">TermiX, and what its standards cost</h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        {/* The track asks for one thing and this page is organised around it.
            Reordered from "standards, generally" because a judge arriving here
            was met with a six-transaction hire flow and had to infer that the
            deliverable they came to assess was on a different page. */}
        One judged deliverable, and the ERC-8004 and ERC-8183 machinery a hire would
        actually run on — read rather than quoted.
      </p>
      {/* The second half of that sentence promises a survey that this run may
          not have made — `identity.surveyed` is false without an RPC, and the
          section below then renders a refusal directly under a claim to have
          read it. Said here rather than left to be discovered two sections
          down. */}
      {d && !d.identity.surveyed && (
        <p className="mt-2 max-w-[68ch] text-sm text-warn">
          This run read no registry. The ERC-8183 half below needs no network; the
          ERC-8004 half says why it is missing.
        </p>
      )}

      {state === null && (
        <div className="mt-10">
          <CardSkeleton />
        </div>
      )}

      {state && !state.ok && (
        <div className="mt-10">
          <ErrorNotice
            title="The registry report has not been generated"
            detail={state.error.message}
            remedy={
              <>
                Run <code className="font-mono text-xs">make registry</code>. The ERC-8183
                half needs no network.
              </>
            }
          />
        </div>
      )}

      {d && (
        <>
          {/* Five sections and the second-longest route on the site by body
              text, and it had no way through it.

              Not added to `/advantage` or `/status` in the same pass: two
              sections each, both reachable in a screen or two, and a two-pill
              rail is chrome rather than navigation. The threshold is whether a
              reader can lose a section, not whether the component exists.

              `deliverable` is gated on `gate`, so it is listed only when the
              section it points at renders — the dead-anchor shape found in
              `AgentDetail` this same pass. */}
          <SectionRail
            label="On this page"
            items={[
              ...(gate ? [{ id: "deliverable", label: "Deliverable" }] : []),
              { id: "ours", label: "Our agents" },
              { id: "hiring", label: "Hiring" },
              { id: "escrow", label: "Escrow" },
              { id: "identity", label: "Identity" },
              { id: "third-party", label: "Third-party index" },
              { id: "aacp", label: "AACP" },
            ]}
          />

          {/* --------------------------------------------- the deliverable -- */}
          {gate && (
            <Section
              id="deliverable"
              title="The judged deliverable"
              className="mt-10"
              headingClassName="mb-2 text-lg font-semibold"
            >
              <Card>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="m-0 text-sm text-ink">
                      Real tasks, run both ways — with an agent and without one.
                    </p>
                    {/* Verbatim from the gate. The track's criterion is encoded
                        in `go_no_go.py` as a check that executes — distinct
                        baselines, and amber until the tape is chain-sourced —
                        so this reads that verdict instead of restating the
                        criterion beside it.

                        The sentence above carries no count, and that is the
                        correction. It said "Three real tasks" directly above a
                        gate detail reading "4 tasks on a chain tape" — the
                        artifact says `summary.tasks: 4`, and this comment said
                        "three" as well, so the prose, the comment and the data
                        disagreed three ways on one card, one line apart.

                        `advantage.json` is not loaded on this page, so there is
                        no local number to read. Rather than fetch an artifact to
                        restate a figure the next line already carries, the
                        sentence now says what the deliverable *is* and lets the
                        gate say how much of it there is. A count stated twice is
                        a count that can disagree with itself, which is what
                        happened. */}
                    <p className="mt-2 mb-0 font-mono text-xs text-dim">{gate.detail}</p>
                    {gate.remedy && (
                      <p className="mt-2 mb-0 text-xs text-faint">→ {gate.remedy}</p>
                    )}
                  </div>
                  <Pill tone={statusTone(gate.status)}>{gate.status}</Pill>
                </div>

                <p className="mt-4 mb-0 border-t border-line pt-3 text-xs text-faint">
                  <Link href="/advantage">The report itself, task by task →</Link>
                </p>
              </Card>
            </Section>
          )}

          {/* ------------------------------------------------- the hire flow -- */}
          {/* ------------------------------------------------ our own row -- */}
          {/* Above the survey of everybody else's agents, deliberately. This
              page's argument is that a registry row proves nothing and a
              resolvable card proves a little — an argument made entirely about
              strangers until this section existed. Putting our own four first
              means the reader meets the standard being applied before they meet
              the four hundred it was applied to. */}
          <Section
            id="ours"
            title="Our own agents, in the registry we survey"
            className="mt-10"
            headingClassName="mb-2 text-lg font-semibold"
            intro={
              <>
                Every other number on this page is about somebody else&rsquo;s agent.
                These are ours, registered on BSC testnet and transferred to
                the address this project publishes as its own &mdash; and held to{" "}
                <em>the same</em> <code className="font-mono text-xs">assess()</code>{" "}
                that decides whether a stranger&rsquo;s listing counts as substantive.
              </>
            }
          >
            <OurAgents ours={d.ours} />

            {/* Self-report, then corroboration, in that order and adjacent.
                `OurAgents` above renders `vetting/identity/97.json` — a file we
                wrote about registrations we made. It is the only block on this
                page that nothing could contradict, which is a strange property
                for the page that measures everybody else. This reads the same
                four back out of an index we do not run.

                The collisions sit directly under it because they undercut its
                own `name` column: two other agents on BSC mainnet are called
                Warden and three are called Sentinel, and none of them is ours. */}
            <IndexedAgreement
              indexed={d.third_party?.ours_as_indexed}
              cross={d.third_party?.ours_cross_check}
              testnet={d.third_party?.counts_testnet}
            />
            <NameCollisionsCard collisions={d.third_party?.name_collisions} />
          </Section>

          <Section id="hiring" title="Hiring an agent, end to end" className="mt-10" headingClassName="mb-2 text-lg font-semibold">
            <p className="mb-5 max-w-[68ch] text-sm text-dim">
              The number that matters is the second one.
            </p>

            <div className="mb-5 grid gap-4 sm:grid-cols-2">
              <Card className="!p-4">
                <p className="m-0 text-xs tracking-wide text-faint uppercase">
                  Transactions end to end
                </p>
                <p className="tabular mt-1 mb-0 text-2xl font-semibold">
                  {count(d.hire_flow.transaction_count)}
                </p>
              </Card>
              <Card className="!p-4">
                <p className="m-0 text-xs tracking-wide text-faint uppercase">
                  Signed by the client
                </p>
                <p className="tabular mt-1 mb-0 text-2xl font-semibold text-warn">
                  {count(d.hire_flow.client_transaction_count)}
                </p>
              </Card>
            </div>

            <Card>
              <DataTable
                caption="The ERC-8183 job lifecycle"
                hideCaption={false}
                columns={["Call", "Signed by", "Why"]}
                // "Why" is a sentence, not a figure. Left as the default, the
                // nowrap that keeps `ComparisonTable`'s numbers aligned cut
                // every row here mid-clause — the first one losing "reverts",
                // which is the whole reason the row is on the page.
                notes="prose"
                rows={d.hire_flow.steps.map((step) => ({
                  label: (
                    <span className="font-mono">
                      {step.call}
                      {/* Which contract, and whether it is the standard's.
                          `contract` was emitted and declared and never read,
                          while a bare "8183" badge marked five rows and left
                          the sixth explaining itself — it is an ERC-20
                          `approve`, which is exactly what `contract` says and
                          the badge could only imply by its absence. */}
                      <span className="ml-2 text-[10px] tracking-wide text-faint uppercase">
                        {step.contract}
                        {step.is_erc8183 && " · 8183"}
                      </span>
                    </span>
                  ),
                  value: step.sender,
                  note: step.why,
                  tone: step.sender === "client" ? "text-warn" : "text-dim",
                }))}
              />

              <div className="mt-5 border-t border-line pt-4">
                <p className="mt-0 mb-2 text-xs tracking-wide text-faint uppercase">
                  Job states
                </p>
                {/* The legend used to read "Shaded states are terminal", and
                    the shade was --line against --line-strong: about 1.1:1,
                    and identical in greyscale or print. A legend nobody can
                    read is not a legend, so terminal states now carry a glyph
                    and a word as well. */}
                <div className="flex flex-wrap gap-1.5">
                  {d.hire_flow.states.map((s) => {
                    const terminal = d.hire_flow.terminal_states.includes(s);
                    return (
                      <span
                        key={s}
                        className={`rounded-sm border px-2 py-0.5 font-mono text-xs ${
                          terminal
                            ? "border-line-strong bg-panel-2 text-dim"
                            : "border-line text-faint"
                        }`}
                      >
                        {terminal && <span aria-hidden="true">■ </span>}
                        {s}
                        {terminal && <span className="visually-hidden"> (terminal state)</span>}
                      </span>
                    );
                  })}
                </div>
                <p className="mt-2 mb-0 text-xs text-faint">
                  States marked ■ are terminal.
                </p>
              </div>
            </Card>
          </Section>

          {/* ------------------------------------------------- what happened -- */}
          {/* The section above prices a sequence. This is what the chain did
              when it was sent, and the two are deliberately not merged: one is
              a claim about a standard, the other is a claim about transaction
              hashes, and a reader should be able to tell which they are looking
              at. */}
          {d.hire_flow.proof?.ran ? (
            <Section
              id="hired"
              title="And what happened when we sent it"
              className="mt-10"
              headingClassName="mb-2 text-lg font-semibold"
              intro={
                <>
                  The missing piece was an <strong>ABI</strong>, recovered from the
                  deployed kernel&rsquo;s bytecode rather than copied. Job{" "}
                  <span className="font-mono">{d.hire_flow.proof.job_id}</span> on
                  chapel is the result.
                </>
              }
            >
              <Card>
                <ol className="m-0 list-none space-y-3 p-0">
                  {(d.hire_flow.proof.transactions ?? []).map((sent, index) => (
                    <li key={`${sent.call}-${index}`} className="flex gap-3">
                      <span
                        className={`tabular mt-0.5 shrink-0 rounded-full px-2 py-0.5 font-mono text-xs ${
                          sent.tx_hash ? "bg-brand-bg text-brand" : "bg-panel-2 text-fail"
                        }`}
                      >
                        {index + 1}
                      </span>
                      <span className="min-w-0">
                        <span className="font-mono text-sm text-ink">{sent.call}</span>
                        {sent.tx_hash && sent.explorer ? (
                          <a
                            className="block truncate font-mono text-xs text-dim underline"
                            href={sent.explorer}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {sent.tx_hash}
                          </a>
                        ) : (
                          <>
                            <span className="block font-mono text-xs text-fail">
                              reverted {sent.reverted}
                            </span>
                            {sent.meaning && (
                              <span className="block text-xs text-dim">{sent.meaning}</span>
                            )}
                          </>
                        )}
                      </span>
                    </li>
                  ))}
                </ol>

                <div className="mt-5 flex flex-wrap gap-3 text-sm">
                  <Pill tone="pass">
                    mined: {(d.hire_flow.proof.mined ?? []).join(", ") || "nothing"}
                  </Pill>
                  <Pill tone="fail">
                    reverted: {(d.hire_flow.proof.reverted ?? []).join(", ") || "nothing"}
                  </Pill>
                  <Pill tone={d.hire_flow.proof.escrowed ? "pass" : "fail"}>
                    escrowed: {String(d.hire_flow.proof.escrowed ?? false)}
                  </Pill>
                </div>

                {d.hire_flow.proof.not_escrowed_because && (
                  <p className="mt-4 mb-0 max-w-[70ch] text-sm text-dim">
                    <strong className="text-ink">Why no escrow.</strong>{" "}
                    <Prose text={d.hire_flow.proof.not_escrowed_because} />
                  </p>
                )}

                {/* The half the chapel run cannot reach, and the label that
                    keeps it from being read as the chapel run. A fork is not a
                    chain, and a page that let `escrowed: true` sit next to
                    `escrowed: false` without saying which network each is would
                    be the misquote this site is named after. */}
                {/* The mainnet run, above the fork one: it is the stronger
                    claim and the weaker outcome, and a reader who stops after
                    the first block should have read the one that cost money. */}
                {!d.hire_flow.mainnet_proof?.ran && d.hire_flow.mainnet_proof?.reason && (
                  <p className="mt-4 mb-0 border-t border-line pt-4 text-xs text-faint">
                    No mainnet run: {d.hire_flow.mainnet_proof.reason}
                  </p>
                )}

                {d.hire_flow.mainnet_proof?.ran && (
                  <div className="mt-5 border-t border-line pt-4">
                    <div className="flex flex-wrap items-center gap-3 text-sm">
                      <Badge tone="neutral">
                        {d.hire_flow.mainnet_proof.network ?? "BSC mainnet"}
                      </Badge>
                      <Pill tone={d.hire_flow.mainnet_proof.escrowed ? "pass" : "fail"}>
                        escrowed: {String(d.hire_flow.mainnet_proof.escrowed ?? false)}
                      </Pill>
                      <Pill tone={d.hire_flow.mainnet_proof.settled ? "pass" : "fail"}>
                        settled: {String(d.hire_flow.mainnet_proof.settled ?? false)}
                      </Pill>
                      <span className="font-mono text-xs text-faint">
                        job {d.hire_flow.mainnet_proof.job_id} ·{" "}
                        {(d.hire_flow.mainnet_proof.transactions ?? []).filter((t) => t.ok).length} of{" "}
                        {(d.hire_flow.mainnet_proof.transactions ?? []).length} steps
                      </span>
                    </div>
                    <p className="mt-3 max-w-[70ch] text-sm text-dim">
                      Real money, escrowed. Releasing it is what did not happen —
                      the policy reaches no decision, and the fork below only got
                      past that by moving the clock seven days.
                    </p>
                    {/* These hashes were in the artifact from the first mainnet
                        run and rendered as a count. A count is a claim about
                        transactions; a link is the transaction. */}
                    <ul className="mt-3 mb-0 grid list-none gap-1 p-0">
                      {(d.hire_flow.mainnet_proof.transactions ?? []).map((sent, index) => (
                        <li key={`${sent.call}-${index}`} className="flex flex-wrap items-baseline gap-2 text-xs">
                          <span className="font-mono text-ink">{sent.call}</span>
                          {sent.explorer ? (
                            <a
                              // `truncate` cannot shrink a 64-character hash:
                              // it has no break opportunity, so its min-content
                              // width is the whole string and the row was 462px
                              // wide inside a 390px viewport. Wrapping is what
                              // every other hash on this page does.
                              className="min-w-0 font-mono break-all text-dim underline"
                              href={sent.explorer}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {sent.explorer.split("/tx/")[1]}
                            </a>
                          ) : (
                            <span className="font-mono text-fail">
                              reverted {sent.reverted}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {!d.hire_flow.fork_proof?.ran && d.hire_flow.fork_proof?.reason && (
                  <p className="mt-4 mb-0 border-t border-line pt-4 text-xs text-faint">
                    No fork proof: {d.hire_flow.fork_proof.reason}
                  </p>
                )}

                {d.hire_flow.fork_proof?.ran && (
                  <div className="mt-5 border-t border-line pt-4">
                    <div className="flex flex-wrap items-center gap-3 text-sm">
                      <Badge tone="warn">
                        on a {d.hire_flow.fork_proof.network ?? "fork"}, not a chain
                      </Badge>
                      <Pill tone={d.hire_flow.fork_proof.escrowed ? "pass" : "fail"}>
                        escrowed: {String(d.hire_flow.fork_proof.escrowed ?? false)}
                      </Pill>
                      <Pill tone={d.hire_flow.fork_proof.settled ? "pass" : "fail"}>
                        settled: {String(d.hire_flow.fork_proof.settled ?? false)}
                      </Pill>
                      <span className="font-mono text-xs text-faint">
                        job {d.hire_flow.fork_proof.job_id} ·{" "}
                        {(d.hire_flow.fork_proof.transactions ?? []).filter((t) => t.ok).length} of{" "}
                        {(d.hire_flow.fork_proof.transactions ?? []).length} steps
                      </span>
                    </div>
                    <p className="mt-3 mb-0 max-w-[70ch] text-sm text-dim">
                      The same seven calls, run to settlement against the mainnet
                      kernel&rsquo;s own bytecode.{" "}
                      {d.hire_flow.fork_proof.escrowed_on_mainnet === false &&
                        d.hire_flow.fork_proof.why_not_on_mainnet}
                    </p>
                  </div>
                )}

                {/* The run where submit mined. Placed before the refund
                    because it is the later claim and the stronger one: 56681
                    funded and reclaimed, 56718 funded and *delivered into*.
                    The only difference between them is an argument. */}
                {d.hire_flow.submit_proof?.ran && (
                  <div className="mt-5 border-t border-line pt-4">
                    <div className="flex flex-wrap items-center gap-3 text-sm">
                      <Badge tone="neutral">
                        {d.hire_flow.submit_proof.network ?? "BSC mainnet"}
                      </Badge>
                      <Pill tone={d.hire_flow.submit_proof.submitted ? "pass" : "fail"}>
                        submitted: {String(d.hire_flow.submit_proof.submitted ?? false)}
                      </Pill>
                      <Pill tone={d.hire_flow.submit_proof.settled ? "pass" : "none"}>
                        settled: {String(d.hire_flow.submit_proof.settled ?? false)}
                      </Pill>
                      <span className="font-mono text-xs text-faint">
                        job {d.hire_flow.submit_proof.job_id} &middot; expires{" "}
                        {d.hire_flow.submit_proof.expires_at_utc}
                      </span>
                    </div>
                    {/* `tx_hash` and the record's own `explorer`, the way the
                        chapel block above does it. This read `sent.tx` against a
                        URL built here from `bscscan.com` — a field the record
                        does not have, so the filter dropped all seven rows and
                        the block rendered its prose with no hash under it. The
                        record carries the explorer link; building one here would
                        also mean this block deciding which network it is on. */}
                    {(d.hire_flow.submit_proof.transactions ?? [])
                      .filter((sent) => sent.tx_hash && sent.explorer)
                      .map((sent) => (
                        <p key={sent.tx_hash} className="mt-2 mb-0 text-xs">
                          <span className="font-mono text-faint">{sent.call}</span>{" "}
                          <a
                            className="font-mono break-all text-dim underline"
                            href={sent.explorer}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {sent.tx_hash}
                          </a>
                        </p>
                      ))}
                    {/* Both through `Prose`: these are emitter prose with
                        backticks around the selector names, and printing the
                        characters is the failure `test_prose_is_rendered`
                        exists for. */}
                    <p className="mt-3 mb-0 max-w-[70ch] text-sm text-dim">
                      <Prose text={d.hire_flow.submit_proof.what_this_run_changes ?? ""} />
                    </p>
                    <p className="mt-2 mb-0 max-w-[70ch] text-sm text-dim">
                      <Prose text={d.hire_flow.submit_proof.why_settle_reverted ?? ""} /> Settle is
                      due{" "}
                      <strong className="text-ink">
                        {d.hire_flow.submit_proof.settle_earliest_utc}
                      </strong>
                      .
                    </p>
                  </div>
                )}

                {/* The fourth record, and the only one about money coming
                    back. It reads under the fork block because it is
                    one until the mainnet clock passes `expiredAt` — a
                    `block.timestamp` comparison, so the clock is the one thing
                    a fork can move and a chain cannot. It is a sibling of that
                    block and not a child of it: a refund that happened does not
                    stop being true because no fork proof was run. No hash here is a link — it was never mined
                    anywhere a reader could check it. */}
                {!d.hire_flow.refund_proof?.ran && d.hire_flow.refund_proof?.reason && (
                  <p className="mt-4 mb-0 border-t border-line pt-4 text-xs text-faint">
                    No refund: {d.hire_flow.refund_proof.reason}
                  </p>
                )}

                {d.hire_flow.refund_proof?.ran && (
                  <div className="mt-4 border-t border-line pt-4">
                    <div className="flex flex-wrap items-center gap-3 text-sm">
                      <Badge
                        tone={
                          d.hire_flow.refund_proof.network === "fork" ? "warn" : "neutral"
                        }
                      >
                        {d.hire_flow.refund_proof.network === "fork"
                          ? "refund, rehearsed on a fork"
                          : "refund, on BSC mainnet"}
                      </Badge>
                      <Pill tone={d.hire_flow.refund_proof.refunded ? "pass" : "fail"}>
                        refunded: {String(d.hire_flow.refund_proof.refunded ?? false)}
                      </Pill>
                      <span className="font-mono text-xs text-faint">
                        job {d.hire_flow.refund_proof.job_id} · status{" "}
                        {d.hire_flow.refund_proof.status_before} &rarr;{" "}
                        {d.hire_flow.refund_proof.status_after} · opens{" "}
                        {d.hire_flow.refund_proof.expires_at_utc}
                      </span>
                    </div>
                    {d.hire_flow.refund_proof.network !== "fork" &&
                      (d.hire_flow.refund_proof.transactions ?? [])
                        .filter((sent) => sent.ok && sent.tx)
                        .map((sent) => (
                          <p key={sent.tx} className="mt-3 mb-0 text-xs">
                            <a
                              className="font-mono break-all text-dim underline"
                              href={`https://bscscan.com/tx/${sent.tx}`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {sent.tx}
                            </a>
                          </p>
                        ))}
                    <p className="mt-3 mb-0 max-w-[70ch] text-sm text-dim">
                      {/* Read off the record rather than asserted. The
                          rehearsal attempts the claim before the expiry as well
                          as after it; the mainnet run only ever makes the one
                          call, because the early one would burn real gas to be
                          told something a fork already established. Saying
                          "attempted before the expiry" over a record with a
                          single transaction in it is the misquote in
                          miniature. */}
                      {(d.hire_flow.refund_proof.transactions ?? []).some(
                        (t) => t.when === "before expiry" && !t.ok,
                      )
                        ? "The claim was attempted before the expiry as well as after it, and refused — a recovery path only ever watched succeeding has not been told apart from a contract that would pay out at any time."
                        : "The claim was made once the expiry had passed. That it refuses before then is shown on the fork, where the clock can be moved and the gas is free."}{" "}
                      {typeof d.hire_flow.refund_proof.recovered === "number" &&
                        `${d.hire_flow.refund_proof.recovered / 1e18} of the payment token came back.`}
                    </p>
                  </div>
                )}
              </Card>

              {d.hire_flow.errors && (
                <Card className="mt-4">
                  <p className="mt-0 mb-3 text-xs tracking-wide text-faint uppercase">
                    What reverts, and what it means
                  </p>
                  <p className="mt-0 mb-4 max-w-[70ch] text-sm text-dim">
                    None of these is in any ABI &mdash; the kernel reverts with a
                    bare selector and no reason. The unnamed ones are counted, not
                    guessed.
                  </p>
                  <ul className="m-0 list-none space-y-2 p-0 text-sm">
                    {Object.entries(d.hire_flow.errors).map(([selector, meaning]) => (
                      <li key={selector} className="border-glass-line border-l-2 pl-3">
                        <span className="font-mono text-xs text-ink">{selector}</span>
                        <span className="block text-dim">{meaning}</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}

              {d.hire_flow.recourse?.length ? (
                <Card className="mt-4">
                  <p className="mt-0 mb-3 text-xs tracking-wide text-faint uppercase">
                    If nobody settles
                  </p>
                  <ul className="m-0 list-none space-y-2 p-0 text-sm">
                    {d.hire_flow.recourse.map((step) => (
                      <li key={step.call}>
                        <span className="font-mono text-xs text-ink">{step.call}</span>{" "}
                        <span className="text-faint">· {step.sender}</span>
                        <span className="block text-dim">{step.why}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-3 mb-0 max-w-[70ch] text-xs text-faint">
                    Deliberately not counted among the seven. It is an alternative
                    ending, not an eighth transaction &mdash; nobody sends both this
                    and <span className="font-mono">settle</span>, so folding it in
                    would make the published count describe a hire nobody performs.
                  </p>
                </Card>
              ) : null}
            </Section>
          ) : (
            /* An absent record used to remove the section, which is the one
               outcome a page about honest reporting must not have: a reader
               cannot tell "not run" from "never existed". The emitter carries
               `reason` for exactly this. */
            <Section
              id="hired"
              title="And what happened when we sent it"
              className="mt-10"
              headingClassName="mb-2 text-lg font-semibold"
            >
              <Refusal
                title="No hire has been sent from here"
                reason={d.hire_flow.proof?.reason ?? "No run has been recorded."}
                floor="The sequence above is priced either way; only the transaction hashes are missing."
              />
            </Section>
          )}

          {/* ----------------------------------------------------- the escrow -- */}
          <Section id="escrow" title="The escrow contract">
            {d.hire_flow.escrow.available ? (
              <Card>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="m-0 font-mono text-sm break-all">
                    {d.hire_flow.escrow.address}
                  </p>
                  {/* No verdict pill. This said `<Pill tone="pass">Verified</Pill>`
                      beside the sentence "carried only because a chain check
                      confirmed it" — while this same artifact says
                      `"source": "offline"` and "no registry read was attempted".
                      `available` is a dict lookup, not a read, so the pill was a
                      verdict typed into the view.

                      The findings a real check recorded are published now, and
                      they are what goes here: seven of them, two of which are a
                      NOT VERIFIED clause and a SECURITY note. A reader can weigh
                      those. A green tick asks them not to. */}
                  <span className="font-mono text-xs text-faint">
                    {count(d.hire_flow.escrow.evidence?.length)} recorded findings
                  </span>
                </div>
                <p className="mt-3 mb-0 text-sm text-dim">
                  Read from chain and written down — including the parts still
                  unverified.
                </p>
                {d.hire_flow.escrow.evidence?.length ? (
                  <ul className="mt-4 mb-0 list-none space-y-3 p-0">
                    {d.hire_flow.escrow.evidence.map((finding) => {
                      // The emitter's own prefixes decide the tone. "NOT
                      // VERIFIED" and "SECURITY" are the two most important
                      // lines in the list and would otherwise read as four more
                      // reassurances in a row of reassurances.
                      const caveat = /^(NOT VERIFIED|SECURITY|NO TESTNET)\b/.exec(finding);
                      return (
                        <li
                          key={finding}
                          className={`border-l-2 pl-4 text-sm ${
                            caveat ? "border-warn-line text-warn" : "border-line text-dim"
                          }`}
                        >
                          {caveat && (
                            <strong className="mr-1 font-mono text-xs">{caveat[1]}</strong>
                          )}
                          {/* Only the remainder. The prefix above is sliced off and
                              drives the tone, and it must stay a plain string for the
                              regex that found it. */}
                          <Prose
                            text={
                              caveat
                                ? finding.slice(caveat[0].length).replace(/^:\s*/, "")
                                : finding
                            }
                          />
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <Refusal
                    title="No findings were published for this address"
                    reason="The artifact carries the address but not the evidence behind it."
                    floor="run `make registry`"
                  />
                )}
              </Card>
            ) : (
              <Refusal
                title="No verified deployment"
                reason={d.hire_flow.escrow.reason ?? "The address has not been verified."}
                floor="The lookup refuses rather than returning a plausible address."
              />
            )}

            {/* Everything above this line is a recording. This is the same
                calls with nothing recorded — the reader's wallet signs and the
                chain answers, including when the answer is a revert. */}
            <EscrowConsole
              deployments={d.hire_flow.deployments}
              defaultJob={d.hire_flow.mainnet_proof?.job_id}
              defaultBudget={d.hire_flow.mainnet_proof?.budget}
              errors={d.hire_flow.errors}
            />
          </Section>

          {/* --------------------------------------------------- the registry -- */}
          <Section id="identity" title="ERC-8004 identity registry">
            {d.identity.surveyed ? (
              <Card>
                {/* Six intervals, where the page used to print one point.

                    The artifact has published all six since the survey was
                    written, and the interface note beside `intervals` says a
                    share of a few hundred out of ~280,000 "is not a point, and
                    printing it as one is the false precision this page exists
                    to criticise". The page then printed exactly that: one
                    share, as "34.8%", with the other five dropped. The table
                    below is unchanged and still carries the substantive row in
                    words; this is the same survey with the arithmetic drawn. */}
                {(() => {
                  const rows = shareRows(d.identity);
                  const sampled = d.identity.sampled;
                  return rows.length > 0 && sampled !== undefined ? (
                    <div className="mb-6">
                      <p className="mt-0 mb-4 max-w-[68ch] text-sm text-dim">
                        {/* `rows.length`, not the word. It read "six ways"
                            two lines below the array whose length that is —
                            the same array the intervals underneath are built
                            from — so adding a seventh share would have left
                            the sentence introducing them saying six. */}
                        Every card in one sample of {count(sampled)}, checked {rows.length}{" "}
                        {rows.length === 1 ? "way" : "ways"}.
                        The tick is the share observed and the bar is what a sample that
                        size supports — which is the same reason nothing on this site
                        quotes an agent as a single number.
                      </p>
                      <ShareIntervals
                        rows={rows}
                        sampled={sampled}
                        caption="What the sample supports, per check"
                        confidenceLevel={d.identity.confidence_level}
                      />
                    </div>
                  ) : null;
                })()}

                {/* The share carries its own denominator, and the registry
                    carries its own size.

                    This read "substantive agent cards — 30.0%" with the sample
                    size two rows below it and the population only in a prose
                    sentence one card further down. 30% of forty agents drawn
                    from two hundred and seventy-two thousand is a different
                    claim from 30% of the registry, and the table was letting a
                    reader pick either. Both numbers are in the artifact; the
                    emitter measures the population rather than assuming it,
                    precisely so a share here can say what it is a share of. */}
                <DataTable
                  caption="Registry survey"
                  rows={[
                    {
                      label: "substantive agent cards",
                      value:
                        d.identity.substantive_share !== undefined
                          ? `${(100 * d.identity.substantive_share).toFixed(1)}%`
                          : "—",
                      note: (() => {
                        const { substantive, sampled, intervals } = d.identity;
                        if (substantive === undefined || sampled === undefined) return "";
                        const of = `${count(substantive)} of ${count(sampled)} sampled`;
                        // Empty when the survey did not record its level, so
                        // the label reads "CI 30-40%" rather than asserting a
                        // level nobody published. It said "95%" as a literal.
                        const levelLabel =
                          d.identity.confidence_level === undefined
                            ? ""
                            : `${(100 * d.identity.confidence_level).toFixed(0)}% `;
                        const ci = intervals?.substantive;
                        // The interval, never omitted when we have it: a share
                        // this size is a range, and the range is the honest half.
                        return ci
                          ? `${of} · ${levelLabel}CI ${(100 * ci.low).toFixed(0)}–${(100 * ci.high).toFixed(0)}%`
                          : of;
                      })(),
                    },
                    {
                      label: "registered agents",
                      value: count(d.identity.population),
                      note: "measured at the block below, not carried from a doc",
                    },
                    { label: "sampled at block", value: count(d.identity.sampled_at_block) },
                    { label: "ids sampled", value: count(d.identity.sampled_ids?.length) },
                  ]}
                />
              </Card>
            ) : (
              <Refusal
                title="The registry was not surveyed"
                reason={d.identity.reason ?? "No survey was attempted."}
                floor="A count carried over from a previous run would be indistinguishable from a fresh one."
              />
            )}

            {d.identity.surveyed && (d.identity.agents?.length ?? 0) > 0 && (
              <>
                <ThirdPartyListings
                  agents={d.identity.agents ?? []}
                  population={d.identity.population}
                />
                {/* The cards above are `identity.listings_shown` of
                    `identity.sampled` — twenty-four of four hundred on the
                    artifact this was written against. The rest were read and
                    scored and were reachable only through `/registry/agents`,
                    which nothing had ever called. */}
                <Card className="mt-4">
                  <CardHeader
                    title="The rest of the survey"
                    eyebrow="live"
                    aside={
                      <Pill tone="info">
                        {count(d.identity.listings_shown)} of {count(d.identity.sampled)}{" "}
                        published
                      </Pill>
                    }
                  />
                  <RegistrySearch published={d.identity.listings_shown ?? 0} />
                </Card>
              </>
            )}

            {/* Two counts of the same registry, and the gap between them is
                the answer.

                The mark is `Disagreement`, and every argument for its shape
                moved into that file with it — why an interval rather than two
                bars, why the axis is magnified and must say so, why the gap is
                hatched neutral rather than warm. What stays here is the one
                sentence this block is for.

                `third_party.reconciliation` has been in the artifact since the
                survey learned to cross-check itself and no page read it —
                including its note, which is the only sentence in this
                repository that says out loud where the project's name comes
                from. It renders verbatim, because a paraphrase of a refusal is
                how it becomes an apology.

                Drawn as an interval rather than as two bars, and that was a
                correction. Two bars from a shared zero are the honest picture
                of a disagreement this size and they are also two identical bars —
                the block carried its whole finding in the numbers and nothing
                in the mark. But two methods that will not be reconciled *are* a
                range, which is the one figure this entire site is built to
                draw: the registry holds somewhere between these two counts, and
                naming a single number would be the misquote.

                The axis is magnified — it spans the two counts with padding,
                not zero to the larger — and that is stated rather than hidden.
                A zoom that is labelled is a reading aid; an unlabelled one is
                the distortion this page criticises. The caption carries the
                width as a share of the count so the magnification cannot
                mislead. */}
            {(() => {
              const rec = d.third_party?.reconciliation;
              if (!rec) return null;

              return (
                <Card className="mt-4">
                  <CardHeader
                    title="Two counts of the same registry"
                    eyebrow="Not reconciled"
                    aside={
                      <Badge tone={rec.same_contract ? "neutral" : "warn"}>
                        {rec.same_contract ? "Same contract" : "Different contracts"}
                      </Badge>
                    }
                  />

                  <Disagreement
                    readings={[
                      { who: "8004scan", how: rec.theirs_method, n: rec.theirs },
                      { who: "this repository", how: rec.ours_method, n: rec.ours },
                    ]}
                    ariaSentence={
                      `Two counts of the same registry: ${count(rec.theirs)} by ` +
                      `${rec.theirs_method}, and ${count(rec.ours)} by ${rec.ours_method}. ` +
                      `${count(Math.abs(rec.difference))} apart, ` +
                      `${fixed(rec.difference_pct, 2)}% of the larger. Neither is chosen.`
                    }
                    spreadNote={
                      <>
                        {/* The magnitude. `difference` is signed on purpose — it
                            says which of the two counts is larger, and that has
                            changed — but the word beside it is "apart", and a
                            distance has no sign. This rendered "-5,312 apart"
                            for as long as 8004scan's count led ours, here and in
                            the spoken description. */}
                        <span className="tabular font-semibold text-warn">
                          {count(Math.abs(rec.difference))}
                        </span>{" "}
                        apart — {fixed(rec.difference_pct, 2)}% of the larger, which is why
                        the axis above is drawn across the counts rather than from zero. At
                        true scale the marks would sit on top of each other.
                      </>
                    }
                  />

                  {/* The emitter's own words. This is the sentence. */}
                  <p className="mt-2 mb-0 max-w-[72ch] text-sm text-dim">{rec.note}</p>
                </Card>
              );
            })()}

            <Card className="mt-4">
              <CardHeader
                title="Reputation is deliberately not displayed"
                aside={<Badge tone="neutral">By design</Badge>}
              />
              <p className="m-0 text-sm text-dim">{d.identity.reputation_note}</p>
            </Card>

            <Card className="mt-4">
              <CardHeader title="Deployments" />
              <DataTable
                caption="Registry addresses by chain"
                rows={[
                  ...Object.entries(d.identity.identity_registry).map(([chain, addr]) => ({
                    label: `identity · chain ${chain}`,
                    value: <span className="font-mono">{shortAddress(addr)}</span>,
                  })),
                  ...Object.entries(d.identity.reputation_registry).map(([chain, addr]) => ({
                    label: `reputation · chain ${chain}`,
                    value: <span className="font-mono">{shortAddress(addr)}</span>,
                  })),
                ]}
              />
            </Card>
          </Section>

          {/* ------------------------------------------------------- the AACP -- */}
          {/* Ungated. The whole section used to be conditional on
              `aacp.available`, so a failed lookup made it vanish and dropped
              the recorded `reason` with it — while the escrow section three
              above renders its reason as a refusal. Same grammar for both. */}
          {/* ------------------------------------------ the third-party index -- */}
          <Section
            id="third-party"
            title="What a second index says about the same registry"
            className="mt-10"
            headingClassName="mb-2 text-lg font-semibold"
            intro={
              <>
                Every count above was taken on chain by this repository; these come
                from <code className="font-mono text-xs">8004scan.io</code>. Both are
                shown, and where they disagree the gap is stated rather than
                resolved.
              </>
            }
          >
            <CountsProof counts={d.third_party?.counts} cross={d.third_party?.counts_cross_check} />
            <FeedbackReach
              three={d.third_party?.agents_with_feedback_three_ways}
              graph={d.third_party?.feedback_graph}
              cross={d.third_party?.feedback_cross_check}
              reach={d.third_party?.feedback_reach}
            />
            <ScanLeaderboardCard leaderboard={d.third_party?.leaderboard} />
            <Census census={d.third_party?.census} />
          </Section>

          <Section id="aacp" title="TermiX AACP">
            {!d.aacp.available ? (
              <Refusal
                title="No AACP contract table was read"
                reason={d.aacp.reason ?? "the report recorded no reason"}
                floor="The lookup refuses rather than defaulting — TermiX documents chains 56 and 8453 only."
              />
            ) : (
              <Card>
                {d.aacp.shares_our_identity_registry && (
                  <div className="mb-4 rounded-md border border-good-line bg-good-bg/40 p-4">
                    <p className="m-0 text-sm text-good">
                      <strong>The same contract, byte for byte.</strong> Both sides
                      followed ERC-8004 to the same address, independently.
                    </p>
                  </div>
                )}
                {d.aacp.contracts && (
                  <DataTable
                    caption="TermiX published contract table"
                    rows={Object.entries(d.aacp.contracts).map(([name, addr]) => ({
                      label: name,
                      value: <span className="font-mono">{shortAddress(addr)}</span>,
                    }))}
                  />
                )}
                {/* How much of the deployed interface was actually recovered.

                    Deliberately not a `FloorGauge`: nobody required 65, so
                    "short of the floor" would draw a counted unknown as a
                    failure. What the bar says is coverage — the resolved part
                    is solid and the rest is hatched, because the hatch means
                    "there is deliberately nothing here" and an unresolved
                    selector is precisely that. The emitter's note says why, and
                    it is the argument: they are counted, not guessed. */}
                {/* The negative findings, verbatim.
                    These are the strongest claims in this artifact — that
                    TermixEscrow implements *none* of ERC-8183's seven calls
                    across 5,894 candidate signatures, and that
                    `orders(bytes32)` returns thirteen words of which exactly
                    one is decoded — and neither reached a page. The block above
                    renders how many selectors were named; these say what the
                    contract turned out not to be.

                    Verbatim rather than paraphrased, the rule this file already
                    follows for `rec.note`: a paraphrase of a refusal is how it
                    becomes an apology. */}
                {(d.aacp.not_erc8183 || d.aacp.order_decode) && (
                  <div className="mt-5 space-y-3 border-t border-line pt-4">
                    {d.aacp.not_erc8183 && (
                      <p className="m-0 max-w-[72ch] text-sm text-dim">{d.aacp.not_erc8183}</p>
                    )}
                    {d.aacp.order_decode && (
                      <p className="m-0 max-w-[72ch] text-sm text-dim">{d.aacp.order_decode}</p>
                    )}
                  </div>
                )}
                {d.aacp.escrow_selectors && (
                  <div className="mt-5 border-t border-line pt-4">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
                      <span className="text-dim">escrow selectors named</span>
                      <span className="tabular text-ink">
                        {count(d.aacp.escrow_selectors.resolved)} of{" "}
                        {count(d.aacp.escrow_selectors.total)}
                      </span>
                    </div>
                    <div
                      className="hatched relative mt-1.5 h-3 overflow-hidden rounded-full border border-glass-line"
                      role="img"
                      aria-label={`${count(d.aacp.escrow_selectors.resolved)} of ${count(
                        d.aacp.escrow_selectors.total,
                      )} escrow selectors were matched to a signature.`}
                    >
                      <div
                        className="absolute inset-y-0 left-0 rounded-full bg-brand/40"
                        style={{
                          width: `${
                            (d.aacp.escrow_selectors.resolved /
                              Math.max(1, d.aacp.escrow_selectors.total)) *
                            100
                          }%`,
                        }}
                      />
                    </div>
                    <p className="mt-2 mb-0 max-w-[72ch] text-xs text-faint">
                      {d.aacp.escrow_selectors.note}
                    </p>
                  </div>
                )}              </Card>
            )}
          </Section>
        </>
      )}
    </Loadable>
  );
}

/**
 * The four registrations, their transactions, and what a re-read found.
 *
 * The transaction links are the first on this site. Everything published here
 * until now was a *reading* of chain state — a pool's fee tier, an escrow's
 * bytecode — and a reading is a claim about the present that has to be trusted
 * to have been taken honestly. A transaction hash is different: it is a
 * permanent, third-party-hosted record of an action, and the reader checks it
 * without this page's cooperation. That is why both hashes are shown rather
 * than only the outcome. The mint and the handover are separately visible, so
 * "this address owns these agents" needs nothing from us.
 */

/**
 * A share the index reported, and the three checks that let it be printed.
 *
 * The proof is rendered, not just its verdict. 8004scan accepts filters it does
 * not implement — `is_verified`, `has_feedback`, `protocol` — and answers each
 * with the entire population under the label you asked for, at HTTP 200, with
 * twenty-five rows that look correct because any twenty-five rows look correct.
 * A share printed without showing what was checked is exactly the assertion
 * this mechanism replaced, so the checks travel with the number.
 */
function CountsProof({
  counts,
  cross,
}: {
  counts?: RegistryArtifact["third_party"] extends infer T
    ? T extends { counts?: infer C }
      ? C
      : never
    : never;
  cross?: RegistryArtifact["third_party"] extends infer T
    ? T extends { counts_cross_check?: infer C }
      ? C
      : never
    : never;
}) {
  if (!counts?.available) {
    return (
      <Refusal
        title="No filtered count was taken"
        reason={"the keyed tier answers these; without it nothing here is published"}
      />
    );
  }

  const filters = Object.entries(counts.filters ?? {});
  return (
    <Card>
      <CardHeader
        title="Counted by walking, asked of the index"
        eyebrow={`${counts.requests ?? 0} requests`}
        aside={
          (counts.refused ?? []).length > 0 ? (
            <Badge tone="warn">{count((counts.refused ?? []).length)} refused</Badge>
          ) : (
            <Badge tone="neutral">All proven</Badge>
          )
        }
      />
      <p className="text-sm text-muted">{counts.note}</p>

      <ul className="mt-4 list-none p-0">
        {filters.map(([name, f]) => (
          <li key={name} className="border-t border-line py-3 first:border-t-0">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-semibold text-ink">{name.replace(/_/g, " ")}</span>
              {f.applied ? (
                <span className="font-mono text-sm text-ink">
                  {count(f.total)} of {count(f.baseline)} &middot; {pct(f.share, 2)}
                </span>
              ) : (
                <Badge tone="warn">not published</Badge>
              )}
            </div>
            {f.applied ? (
              <p className="mt-1 font-mono text-xs text-faint">
                {count(f.rows_satisfying)} of {count(f.rows_checked)} sampled rows satisfy it
                {f.differs_from_baseline && " · the total is not the population"}
                {f.complement_total !== undefined &&
                  ` · with its complement it reaches the population, ${count(f.sum_vs_baseline)} out against ${count(f.growth_tolerance)} allowed for growth`}
              </p>
            ) : (
              <p className="mt-1 text-sm text-muted">{f.reason}</p>
            )}
          </li>
        ))}
      </ul>

      {cross?.available && (
        <div className="mt-5">
          <Heading className="m-0 font-mono text-xs tracking-wide text-faint uppercase">
            The same two shares, both ways
          </Heading>
          {/* A table rather than the interval mark the reconciliation block
              above uses. That mark draws two counts of *one* quantity as a
              span, which is right there and wrong here: these are two
              quantities with two denominators each, and three unrelated spans
              side by side would invite a comparison across them. */}
          <DataTable
            caption="One index, asked twice"
            columns={["Quantity", "Walked", "Asked"]}
            notes="figures"
            rows={cross.rows.map((r) => ({
              label: r.quantity.replace(/_/g, " "),
              value: r.compared ? `${count(r.walked)} of ${count(r.walked_of)}` : "—",
              note: r.compared ? `${count(r.asked)} of ${count(r.asked_of)}` : (r.reason ?? ""),
            }))}
          />
          <p className="mt-2 text-sm text-muted">
            {cross.note}
            {cross.hours_apart !== null && ` The two readings are ${fixed(cross.hours_apart, 1)} hours apart.`}
          </p>
        </div>
      )}
    </Card>
  );
}

/**
 * How many agents anyone has ever rated, and who did the rating.
 *
 * The spread is the finding. One index holds three different answers to one
 * question — the walk counted agent rows with a feedback, the filter was asked
 * directly, and the feedback table was counted from the other end — and they
 * disagree. Rendered as a range because a single number here would be a choice
 * nobody can defend.
 *
 * Beneath it, the concentration: a registry of 285,000 agents whose entire
 * reputation layer was written by a number of addresses small enough to print.
 * That is the argument this whole site makes, arriving from somebody else's
 * data rather than from ours.
 */
function FeedbackReach({
  three,
  graph,
  cross,
  reach,
}: {
  three?: NonNullable<RegistryArtifact["third_party"]>["agents_with_feedback_three_ways"];
  graph?: NonNullable<RegistryArtifact["third_party"]>["feedback_graph"];
  cross?: NonNullable<RegistryArtifact["third_party"]>["feedback_cross_check"];
  reach?: NonNullable<RegistryArtifact["third_party"]>["feedback_reach"];
}) {
  if (!graph?.available) {
    return (
      <Refusal
        title="The feedback table was not read"
        reason={graph?.reason ?? "the keyed tier answers /feedbacks; without it, nothing"}
      />
    );
  }

  return (
    <Card className="mt-4">
      <CardHeader
        title="Who does the rating"
        eyebrow={graph.complete ? "Counted, not sampled" : "Incomplete walk"}
        aside={<Badge tone={three?.agree ? "neutral" : "warn"}>{three?.agree ? "Agreed" : "Not reconciled"}</Badge>}
      />

      {three?.available && (
        <>
          <p className="text-sm text-muted">{three.note}</p>
          {/* The same mark as the two registry counts above, for the same
              reason and now from the same component: three readings that will
              not be reconciled are a range, and a table of three rows carries
              the finding in the numbers and nothing in the shape.

              Three rather than two is where the extraction earned itself. The
              inline version labelled its ticks by alternating right and left,
              which works for a pair and collides here — 438, 510 and 547 sit
              inside a hundred. Above a pair the ticks go unlabelled and this
              list is the record. */}
          <Disagreement
            readings={three.readings.map((r) => ({
              who: r.route + (r.carried_forward ? " (carried forward)" : ""),
              how: `of ${count(r.of)}`,
              n: r.agents,
            }))}
            ariaSentence={
              `How many agents anyone has ever rated, three ways: ` +
              three.readings
                .map((r) => `${count(r.agents)} ${r.route}`)
                .join(", ") +
              `. ${count(three.low)} to ${count(three.high)}, a spread of ` +
              `${count(three.spread)}. None is chosen.`
            }
            spreadNote={
              <>
                <span className="tabular font-semibold text-warn">
                  {count(three.spread)}
                </span>{" "}
                apart — {count(three.low)} to {count(three.high)} on one quantity from one
                index, which is why the axis is drawn across the readings rather than from
                zero.
              </>
            }
          />
        </>
      )}

      {/* Concentration, as a shape.
          The two percentages below say the busiest address wrote 4% and the top
          five wrote 21%, and a reader has to hold both and subtract to see what
          the distribution actually is. It is a parts-of-a-whole with a bounded
          denominator, which is what `TallyStrip` is for.

          Scaled to `rows` — every feedback on the chain — rather than to the
          three parts, because that is the denominator the claim is about. The
          remainder is drawn in the neutral tone rather than a third colour:
          "everyone else" is not a finding, it is what is left. */}
      {graph.top_rater_share !== null && graph.top_five_rater_share !== null && (
        <div className="mb-5">
          <TallyStrip
            total={graph.rows}
            parts={[
              {
                label: "the busiest address",
                tone: "bg-brand",
                n: Math.round(graph.top_rater_share * graph.rows),
              },
              {
                label: "the next four",
                tone: "bg-brand/40",
                n: Math.round(
                  (graph.top_five_rater_share - graph.top_rater_share) * graph.rows,
                ),
              },
              {
                label: "everyone else",
                tone: "bg-neutral/30",
                n: Math.round((1 - graph.top_five_rater_share) * graph.rows),
              },
            ]}
            ariaSentence={
              `Of ${count(graph.rows)} feedback rows written by ` +
              `${count(graph.distinct_raters)} distinct addresses: ` +
              `${pct(graph.top_rater_share, 1)} by the busiest one, ` +
              `${pct(graph.top_five_rater_share, 1)} by the busiest five.`
            }
          />
          <p className="mt-2 mb-0 font-mono text-xs text-faint">
            {pct(graph.top_rater_share, 1)} by the busiest address ·{" "}
            {pct(graph.top_five_rater_share, 1)} by the busiest five · of{" "}
            {count(graph.rows)} rows from {count(graph.distinct_raters)} addresses
          </p>
        </div>
      )}

      <DataTable
        caption="The feedback table, walked in full"
        columns={["Metric", "Value", "Of"]}
        notes="prose"
        rows={[
          {
            label: "distinct addresses that wrote every feedback on this chain",
            value: count(graph.distinct_raters),
            note: `across ${count(graph.distinct_rated_agents)} agents`,
          },
          {
            label: "written by the single busiest address",
            value: pct(graph.top_rater_share, 1),
            note: `top five: ${pct(graph.top_five_rater_share, 1)}`,
          },
          {
            label: "anchored to a transaction anybody can open",
            value: count(graph.anchored),
            note: `of ${count(graph.rows)} rows`,
          },
          {
            label: "carrying any comment at all",
            value: count(graph.with_comment),
            note: `of ${count(graph.rows)} rows`,
          },
          {
            label: "declaring how the rating was measured",
            value: count(graph.declaring_a_method),
            note: `${count(graph.uris_decoded)} feedback URIs decoded; ${count(graph.declaring_known_defects)} also state known defects`,
          },
          { label: "revoked", value: count(graph.revoked), note: "" },
        ]}
      />
      <p className="mt-2 text-sm text-muted">
        {graph.note}
        {!graph.complete &&
          ` This walk reached ${count(graph.rows)} of ${count(graph.total_reported)} rows, and every share above divides by what was walked.`}
      </p>

      {cross?.available && (
        <p className="mt-3 font-mono text-xs text-faint">
          The same index also disagrees with itself about how many feedbacks exist:{" "}
          {count(cross.summed_over_agents)} summed across agent rows against{" "}
          {count(cross.counted_in_feedback_table)} in the feedback table,{" "}
          {/* The magnitude, for the reason the reconciliation block above gives:
              `difference` is `summed - counted` and is negative whenever the
              table leads, which it does. This line read "-38 apart" — the
              second instance of that defect on this page, found while fixing
              the first. */}
          {count(Math.abs(cross.difference ?? 0))} apart.
        </p>
      )}

      {/* What separates a count from a star rating, which the artifact says and
          nothing rendered.

          `feedback_reach` carries `anchored` and an example row — the block and
          the transaction that wrote it — and all eight of its fields were
          unrendered. The claim it supports is the one this whole section is
          for: every feedback in that total names a transaction a reader can
          open, so the number is checkable rather than merely reported. A claim
          like that with no example beside it is exactly the kind of assertion
          this page exists to stop making. */}
      {reach?.available && reach.anchored && reach.example_transaction_hash && (
        <p className="mt-3 text-sm text-muted">
          Every one of those rows names the transaction that wrote it, which is what
          separates this count from a star rating —{" "}
          <a
            href={`https://bscscan.com/tx/${reach.example_transaction_hash}`}
            className="font-mono text-xs break-all"
            target="_blank"
            rel="noreferrer"
          >
            {shortAddress(reach.example_transaction_hash, 10, 8)}
          </a>
          {reach.example_block_number !== undefined && (
            <> in block {count(reach.example_block_number)}</>
          )}
          , to pick one.
        </p>
      )}
    </Card>
  );
}

/**
 * The walk, and what it is still the only source for.
 *
 * Demoted rather than deleted, and the distinction is on the card. Two of its
 * shares are now asked for directly and proven; the six below have no filter
 * behind them at all, so a two-hour walk remains the only way to get them.
 * `carried_forward` says it was not taken on this run and `read_at` says when
 * it really was — because a census silently republished is a number claiming to
 * be current.
 */
function Census({ census }: { census?: NonNullable<RegistryArtifact["third_party"]>["census"] }) {
  if (!census) return null;
  if (!census.available) {
    return (
      <div className="mt-4">
        <Refusal title="No whole-population walk is on record" reason={census.reason ?? ""} />
      </div>
    );
  }
  return (
    <Card className="mt-4">
      <CardHeader
        title="The whole-population walk"
        eyebrow={census.complete ? "Complete" : "Incomplete"}
        aside={
          census.carried_forward ? (
            <Badge tone="warn">Carried forward</Badge>
          ) : (
            <Badge tone="neutral">Taken this run</Badge>
          )
        }
      />
      <DataTable
        caption="What only the walk answers"
        columns={["Metric", "Value"]}
        rows={[
          { label: "agents counted", value: count(census.counted) },
          { label: "distinct owners", value: count(census.distinct_owners) },
          { label: "distinct descriptions", value: count(census.distinct_descriptions) },
        ]}
      />
      {/* No page count in that sentence, and its absence is the correction.
          It read "2,848 pages", which appears in no artifact: it was the
          population divided by the page size at the moment somebody typed it,
          and the registry has minted agents on every day since. By the time
          this was found the same division gave 2,856.

          A count that drifts is worse than one that is absent, because it is
          the class of number `test_no_artifact_number_is_hardcoded_in_the_ui`
          structurally cannot catch: that guard builds its forbidden set out of
          values that ARE in the artifacts, so a literal that has stopped
          matching one is invisible to it by construction. The more wrong it
          gets, the less likely anything notices.

          `census.counted` is on this block and could carry it, but the page
          count is a fact about how the walk was done rather than about the
          registry, and the hour-or-two beside it already says what it costs. */}
      <p className="mt-2 text-sm text-muted">
        8004scan implements no filter for any of these, so they cannot be asked for the way the
        shares above were &mdash; every page of the registry, an hour or two, is the only route to
        them. This reading was{" "}
        {census.carried_forward
          ? `not taken on this build; it was carried forward from ${census.read_at ?? "a run recorded before readings were stamped"}`
          : "taken on this build"}
        .
      </p>
    </Card>
  );
}

function OurAgents({ ours }: { ours?: OwnIdentities }) {
  // Not an empty table. An artifact from a checkout that never registered
  // anything and an artifact from a run that registered nothing must not look
  // alike — the distinction `/vetting`'s two 404s exist to preserve.
  if (!ours || !ours.surveyed) {
    return (
      <Refusal
        title="No agent of ours is registered"
        reason={
          ours?.reason ||
          "Nothing has been recorded, so this is not a claim that the registry holds none of ours — it is a claim that nobody has looked."
        }
        floor="make identity-register"
      />
    );
  }

  // The record names its own explorer; this is only the floor under a record
  // that does not. It was `testnet.bscscan.com`, which was right while chapel
  // was the only place these four existed and became a wrong default the day
  // the emitter started preferring `vetting/identity/56.json` — a mainnet id
  // linked to a testnet explorer resolves to nothing.
  const explorer = ours.explorer || "https://bscscan.com";

  return (
    <>
      <Card>
        <CardHeader
          title={`${count(ours.agents.length)} identit${ours.agents.length === 1 ? "y" : "ies"} on chain`}
          eyebrow={
            <span className="font-mono normal-case">
              chain {ours.chain_id}
              {ours.block != null && ` · block ${ours.block.toLocaleString("en-US")}`}
              {/* How old this reading is. The emitter computes it on every
                  build from the record's mtime and nothing drew it, so the page
                  presented a reading of unknown age as current — which is the
                  one thing a record of a chain read must not do. The figure
                  it prints was named here and went stale on the next survey,
                  which is a smaller version of the same defect; what matters is
                  that it is a real age and not a placeholder. */}
              {ours.age_hours != null && ` · read ${hours(ours.age_hours)} ago`}
            </span>
          }
          aside={<Pill tone={statusTone(ours.verdict || "UNKNOWN")}>{ours.verdict || "UNKNOWN"}</Pill>}
        />
        {/* The whole tally, including the two that are zero.
            The contract declared `checked` and `registered` as rendered here
            and they were not: the guard matches a field by its leaf name, and
            "registered" appears in this file twice in ordinary prose — "285,599
            registered agents", "registered on BSC testnet". So the positive
            direction of that check has the same weakness as the negative one it
            was written to complement, and all four of these were unrendered.

            `failed` and `unknown` are both zero today, which is exactly when an
            unshown failure count is hardest to notice and most misleading the
            day it stops being zero. A verdict pill beside a tally that omits
            the failures is a verdict with no denominator. */}
        {ours.summary && (
          <p className="mt-1 mb-3 font-mono text-xs text-faint">
            {count(ours.summary.registered)} registered of {count(ours.summary.checked)}{" "}
            checked · {count(ours.summary.failed)} failed ·{" "}
            {count(ours.summary.unknown)} unknown
          </p>
        )}
        {ours.owner && (
          <p className="m-0 text-sm text-dim">
            Owned by{" "}
            <a
              className="font-mono text-xs"
              href={`${explorer}/address/${ours.owner}`}
              target="_blank"
              rel="noreferrer"
            >
              {shortAddress(ours.owner)}
            </a>
            {ours.signer && ours.signer.toLowerCase() !== ours.owner.toLowerCase() && (
              <>
                {" "}
                &mdash; registered by{" "}
                <a
                  className="font-mono text-xs"
                  href={`${explorer}/address/${ours.signer}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {shortAddress(ours.signer)}
                </a>
                , which holds the key, and handed over in a second transaction.
              </>
            )}
          </p>
        )}

        <div className="mt-4 grid gap-3">
          {ours.agents.map((agent) => (
            // `min-w-0`, and it is the fix `ListingCard` documents three
            // hundred lines up: a grid item defaults to `min-width: auto` and
            // refuses to shrink below its own min-content, so a row of mono
            // transaction links set this card's width to 463px inside a 390px
            // viewport and pushed the whole page 118px sideways. The two
            // tables below it were reported as overflowing too; they were
            // simply riding on this.
            <div
              key={agent.agent}
              className="min-w-0 rounded-md border border-glass-line bg-glass p-3"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <strong className="text-ink">{agent.name}</strong>
                <a
                  className="font-mono text-xs"
                  href={agent.agent_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  #{agent.agent_id}
                </a>
              </div>
              <p className="mt-1 mb-0 text-xs text-faint">
                {count(agent.token_uri_bytes)} byte card, held on chain ·{" "}
                {count(agent.gas_used)} gas
              </p>
              {/* `break-all` on the addresses for the other half of it: wrapping
                  the row is not enough when a single mono token is itself wider
                  than the card. */}
              <p className="mt-2 mb-0 flex flex-wrap gap-x-4 font-mono text-[11px] break-all">
                <a href={agent.register_url} target="_blank" rel="noreferrer">
                  register {shortAddress(agent.register_tx)}
                </a>
                <a href={agent.transfer_url} target="_blank" rel="noreferrer">
                  transfer {shortAddress(agent.transfer_tx)}
                </a>
              </p>
            </div>
          ))}
        </div>
      </Card>

      {ours.checks.length > 0 && (
        <div className="mt-4">
          <CheckList checks={ours.checks} />
        </div>
      )}
    </>
  );
}
