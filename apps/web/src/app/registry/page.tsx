"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { DataTable } from "@/components/DataTable";
import { Pill } from "@/components/Pill";
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
    escrow: { available: boolean; address?: string; reason?: string };
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
}

export default function RegistryPage() {
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
    <div aria-busy={state === null}>
      <h1 className="text-2xl font-semibold">Standards, and what they actually cost</h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        Every marketplace has a Hire button. This page is what is behind one when the hire
        is an on-chain job under ERC-8183, and what the ERC-8004 identity registry contains
        when you go and read it rather than quoting its size.
      </p>

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
          <section className="mt-10">
            <h2 className="mb-2 text-lg font-semibold">Hiring an agent, end to end</h2>
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
                <div className="flex flex-wrap gap-1.5">
                  {d.hire_flow.states.map((s) => (
                    <span
                      key={s}
                      className={`rounded-sm border px-2 py-0.5 font-mono text-xs ${
                        d.hire_flow.terminal_states.includes(s)
                          ? "border-line-strong bg-panel-2 text-dim"
                          : "border-line text-faint"
                      }`}
                    >
                      {s}
                    </span>
                  ))}
                </div>
                <p className="mt-2 mb-0 text-xs text-faint">
                  Shaded states are terminal.
                </p>
              </div>
            </Card>
          </section>

          {/* ----------------------------------------------------- the escrow -- */}
          <section className="mt-8">
            <h2 className="mb-4 text-lg font-semibold">The escrow contract</h2>
            {d.hire_flow.escrow.available ? (
              <Card>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="m-0 font-mono text-sm break-all">
                    {d.hire_flow.escrow.address}
                  </p>
                  <Pill tone="pass">Verified</Pill>
                </div>
                <p className="mt-3 mb-0 text-sm text-dim">
                  Carried only because a chain check confirmed it — bytecode present, and
                  the identity registry beside it answering as the contract we already
                  read. A table on a vendor&rsquo;s website is a claim, not a verification.
                </p>
              </Card>
            ) : (
              <Refusal
                title="No verified deployment"
                reason={d.hire_flow.escrow.reason ?? "The address has not been verified."}
                floor="registry/erc8183.py::escrow_address raises rather than returning a plausible address"
              />
            )}
          </section>

          {/* --------------------------------------------------- the registry -- */}
          <section className="mt-8">
            <h2 className="mb-4 text-lg font-semibold">ERC-8004 identity registry</h2>
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
          </section>

          {/* ------------------------------------------------------- the AACP -- */}
          {d.aacp.available && (
            <section className="mt-8">
              <h2 className="mb-4 text-lg font-semibold">TermiX AACP</h2>
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
            </section>
          )}
        </>
      )}
    </div>
  );
}
