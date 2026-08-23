"use client";

import { BuildStamp, type Build } from "@/components/BuildStamp";
import { Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import { useEffect, useState } from "react";
import { Badge } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { DataTable } from "@/components/DataTable";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import Link from "next/link";
import { Pill, statusTone } from "@/components/Pill";
import { load, type Loaded } from "@/lib/artifacts";
import { count, shortAddress } from "@/lib/format";

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

export interface RegistryArtifact {
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
  };
  aacp: {
    available: boolean;
    chain_id?: number;
    shares_our_identity_registry?: boolean;
    contracts?: Record<string, string>;
    note?: string;
    reason?: string;
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
          {/* --------------------------------------------- the deliverable -- */}
          {gate && (
            <Section
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
          <Section title="Hiring an agent, end to end" className="mt-10" headingClassName="mb-2 text-lg font-semibold">
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
          <Section title="The escrow contract">
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
          <Section title="ERC-8004 identity registry">
            {d.identity.surveyed ? (
              <Card>
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
              <ThirdPartyListings
                agents={d.identity.agents ?? []}
                population={d.identity.population}
              />
            )}

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
          <Section title="TermiX AACP">
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
