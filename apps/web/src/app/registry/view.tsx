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
import { load, type Loaded } from "@/lib/artifacts";
import { count, shortAddress } from "@/lib/format";

interface Step {
  call: string;
  sender: string;
  contract: string;
  why: string;
  is_erc8183: boolean;
}

interface RegistryArtifact {
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
    identity_registry: Record<string, string>;
    reputation_registry: Record<string, string>;
    reputation_note: string;
    substantive_share?: number;
    sampled_at_block?: number;
    sampled_ids?: number[];
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

export function RegistryView() {
  const [state, setState] = useState<Loaded<RegistryArtifact> | null>(null);

  useEffect(() => {
    let live = true;
    load<RegistryArtifact>("registry.json").then((r) => {
      if (live) setState(r);
    });
    return () => {
      live = false;
    };
  }, []);

  const d = state?.ok ? state.value : null;

  return (
    <Loadable loading={state === null} what="the registry sample">
      <h1 className="text-2xl font-semibold">Standards, and what they actually cost</h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        Every marketplace has a Hire button. This page is what is behind one when the hire
        is an on-chain job under ERC-8183, and what the ERC-8004 identity registry contains
        when you go and read it rather than quoting its size.
      </p>
      {/* The second half of that sentence promises a survey that this run may
          not have made — `identity.surveyed` is false without an RPC, and the
          section below then renders a refusal directly under a claim to have
          read it. Said here rather than left to be discovered two sections
          down. */}
      {d && !d.identity.surveyed && (
        <p className="mt-2 max-w-[68ch] text-sm text-warn">
          This run did not read the registry — the ERC-8183 half below needs no network and
          is complete; the ERC-8004 half says why it is missing rather than estimating it.
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
          {/* ------------------------------------------------- the hire flow -- */}
          <Section title="Hiring an agent, end to end" className="mt-10" headingClassName="mb-2 text-lg font-semibold">
            <p className="mb-5 max-w-[68ch] text-sm text-dim">
              The interesting number is not the total. It is how many of these the person
              doing the hiring has to sign.
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
                      {step.is_erc8183 && (
                        <span className="ml-2 text-[10px] tracking-wide text-faint uppercase">
                          8183
                        </span>
                      )}
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
                  A table on a vendor&rsquo;s website is a claim, not a verification. What
                  follows was read from the chain and written down — including the parts
                  that are still unverified.
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
                <DataTable
                  caption="Registry survey"
                  rows={[
                    {
                      label: "substantive agent cards",
                      value:
                        d.identity.substantive_share !== undefined
                          ? `${(100 * d.identity.substantive_share).toFixed(1)}%`
                          : "—",
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
          {d.aacp.available && (
            <Section title="TermiX AACP">
              <Card>
                {d.aacp.shares_our_identity_registry && (
                  <div className="mb-4 rounded-md border border-good-line bg-good-bg/40 p-4">
                    <p className="m-0 text-sm text-good">
                      <strong>The same contract, byte for byte.</strong> This marketplace
                      was already reading TermiX&rsquo;s identity registry before either
                      side knew about the other — both followed ERC-8004 to the address it
                      deploys at on BNB Chain.
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
                  <p className="mt-4 mb-0 text-xs text-faint">{d.aacp.note}</p>
                )}
              </Card>
            </Section>
          )}

          {d.build && <BuildStamp className="mt-10" build={d.build} />}
        </>
      )}
    </Loadable>
  );
}
