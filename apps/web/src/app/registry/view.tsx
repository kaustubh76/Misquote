"use client";

import { BuildStamp, type Build } from "@/components/BuildStamp";
import { Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import { useEffect, useState } from "react";
import { Badge } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { DataTable } from "@/components/DataTable";
import { SectionRail } from "@/components/SectionRail";
import { ShareIntervals, type ShareInterval } from "@/components/ShareIntervals";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { CheckList, type CheckRow } from "@/components/CheckList";
import { CardSkeleton } from "@/components/Skeleton";
import Link from "next/link";
import { Pill, statusTone } from "@/components/Pill";
import { RegistrySearch } from "@/components/RegistrySearch";
import { load, type Loaded } from "@/lib/artifacts";
import { count, fixed, isNum, shortAddress } from "@/lib/format";

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
        {population ? population.toLocaleString() : "the"} registered agents, not across the
        oldest few hundred. These are listings, not tearsheets: each one repeats what its
        registration claims and what our own reading of it found, and carries{" "}
        <strong>no performance figure</strong>. Our four agents are quoted because their
        policies can be replayed on real history. These cannot be, so they are not quoted —
        and that is the difference the rest of this site exists to make visible.
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
  reason?: string;
  chain_id: number;
  verdict?: string;
  owner?: string;
  signer?: string;
  registry?: string;
  block?: number | null;
  explorer?: string;
  read_at?: string;
  record?: string;
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
    /** A 95% Wilson interval per share. A share from a few hundred of ~280,000
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
    reconciliation?: {
      ours: number;
      ours_method: string;
      theirs: number;
      theirs_method: string;
      difference: number;
      /** Already in percentage points: `0.69` means 0.69%. */
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
  build?: Build;
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
                      Three real tasks, run with and without an agent.
                    </p>
                    {/* Verbatim from the gate. The track's criterion is
                        encoded in `go_no_go.py` as a check that executes —
                        three tasks, distinct baselines, and amber until the
                        tape is chain-sourced — so this reads that verdict
                        instead of restating the criterion beside it. */}
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
                These four are ours, registered on BSC testnet and transferred to
                the address this project publishes as its own &mdash; and held to{" "}
                <em>the same</em> <code className="font-mono text-xs">assess()</code>{" "}
                that decides whether a stranger&rsquo;s listing counts as substantive.
              </>
            }
          >
            <OurAgents ours={d.ours} />
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
                          {caveat ? finding.slice(caveat[0].length).replace(/^:\s*/, "") : finding}
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
                floor="registry/erc8183.py::escrow_address raises rather than returning a plausible address"
              />
            )}
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
                        Every card in one sample of {count(sampled)}, checked six ways.
                        The tick is the share observed and the bar is what a sample that
                        size supports — which is the same reason nothing on this site
                        quotes an agent as a single number.
                      </p>
                      <ShareIntervals
                        rows={rows}
                        sampled={sampled}
                        caption="What the sample supports, per check"
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
                        const ci = intervals?.substantive;
                        // The interval, never omitted when we have it: a share
                        // this size is a range, and the range is the honest half.
                        return ci
                          ? `${of} · 95% CI ${(100 * ci.low).toFixed(0)}–${(100 * ci.high).toFixed(0)}%`
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

                `third_party.reconciliation` has been in the artifact since the
                survey learned to cross-check itself and no page read it —
                including its note, which is the only sentence in this
                repository that says out loud where the project's name comes
                from. It renders verbatim, because a paraphrase of a refusal is
                how it becomes an apology.

                Drawn as an interval rather than as two bars, and that was a
                correction. Two bars from a shared zero are the honest picture
                of a 0.66% disagreement and they are also two identical bars —
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

              const low = Math.min(rec.ours, rec.theirs);
              const high = Math.max(rec.ours, rec.theirs);
              const pad = Math.max(1, (high - low) * 0.45);
              const span = high - low + pad * 2;
              const at = (n: number) => `${((n - (low - pad)) / span) * 100}%`;

              const ends = [
                { who: "8004scan", n: rec.theirs, how: rec.theirs_method },
                { who: "this repository", n: rec.ours, how: rec.ours_method },
              ].sort((a, b) => a.n - b.n);

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

                  <div
                    className="relative h-12"
                    role="img"
                    aria-label={
                      `Two counts of the same registry: ${count(rec.theirs)} by ` +
                      `${rec.theirs_method}, and ${count(rec.ours)} by ${rec.ours_method}. ` +
                      `${count(rec.difference)} apart, ${fixed(rec.difference_pct, 2)}% of ` +
                      `the larger. Neither is chosen.`
                    }
                  >
                    {/* The unresolved span. Hatched in the neutral tone, not
                        the warm one: `Ledger.tsx` sets that rule — warm means
                        evidence exists and fell short, neutral means nothing
                        was ever there. This gap is neither a shortfall nor an
                        error; it is a region no method on this page speaks
                        for, which is what the hatch means. */}
                    <div
                      className="hatched absolute top-1/2 h-6 -translate-y-1/2 rounded-sm border border-line-strong"
                      style={{ left: at(low), width: `${((high - low) / span) * 100}%` }}
                    />
                    {ends.map((end, i) => (
                      <div
                        key={end.who}
                        className="absolute top-1/2 h-8 w-0.5 -translate-y-1/2 bg-brand"
                        style={{ left: at(end.n) }}
                      >
                        <span
                          className={`absolute -top-1 whitespace-nowrap font-mono text-xs text-ink ${
                            i === 0 ? "right-2 text-right" : "left-2"
                          }`}
                        >
                          {count(end.n)}
                        </span>
                      </div>
                    ))}
                  </div>

                  <ul className="m-0 mt-2 list-none space-y-1 p-0">
                    {ends.map((end) => (
                      <li
                        key={end.who}
                        className="font-mono text-xs break-words text-faint"
                      >
                        {count(end.n)} · {end.who} — {end.how}
                      </li>
                    ))}
                  </ul>

                  <p className="mt-5 mb-0 border-t border-line pt-4 text-sm">
                    <span className="tabular font-semibold text-warn">
                      {count(rec.difference)}
                    </span>{" "}
                    <span className="text-dim">
                      apart — {fixed(rec.difference_pct, 2)}% of the larger, which is
                      why the axis above is drawn across the two counts rather than
                      from zero. At true scale the marks would sit on top of each
                      other.
                    </span>
                  </p>
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
          <Section id="aacp" title="TermiX AACP">
            {!d.aacp.available ? (
              <Refusal
                title="No AACP contract table was read"
                reason={d.aacp.reason ?? "the report recorded no reason"}
                floor="registry/aacp.py raises NoDeployment rather than defaulting — TermiX documents chains 56 and 8453 only."
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
                )}
                {d.aacp.note && (
                  <p className="mt-4 mb-0 text-xs text-faint">
                    {/* The chain is part of the claim. The table is chain 56's
                        and the page never said so, which on a project with a
                        testnet mirror is a reading somebody could mis-attribute. */}
                    chain {d.aacp.chain_id} · {d.aacp.note}
                  </p>
                )}
              </Card>
            )}
          </Section>

          {d.build && <BuildStamp className="mt-10" build={d.build} />}
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

  const explorer = ours.explorer || "https://testnet.bscscan.com";

  return (
    <>
      <Card>
        <CardHeader
          title={`${count(ours.agents.length)} identit${ours.agents.length === 1 ? "y" : "ies"} on chain`}
          eyebrow={
            <span className="font-mono normal-case">
              chain {ours.chain_id}
              {ours.block != null && ` · block ${ours.block.toLocaleString("en-US")}`}
            </span>
          }
          aside={<Pill tone={statusTone(ours.verdict || "UNKNOWN")}>{ours.verdict || "UNKNOWN"}</Pill>}
        />
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
            <div
              key={agent.agent}
              className="rounded-md border border-glass-line bg-glass p-3"
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
              <p className="mt-2 mb-0 flex flex-wrap gap-x-4 font-mono text-[11px]">
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

        {ours.read_at && (
          <p className="mt-4 mb-0 text-xs text-faint">
            read back {ours.read_at}
            {ours.record && ` · ${ours.record}`}
          </p>
        )}
      </Card>

      {ours.checks.length > 0 && (
        <div className="mt-4">
          <CheckList checks={ours.checks} />
        </div>
      )}
    </>
  );
}
