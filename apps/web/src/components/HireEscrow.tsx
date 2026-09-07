"use client";

/**
 * Hiring an agent, one call at a time, with the money in escrow.
 *
 * ## Why this exists beside `EscrowConsole`
 *
 * The flow was reachable only as eight buttons named after Solidity functions,
 * all enabled at once, six screens down `/registry`, defaulting to hiring
 * *yourself*. That is the right surface for an auditor and the wrong one for
 * everybody else: nothing said which call came next, what any of them cost, or
 * who the other party was — and the two calls a visitor cannot send were
 * offered in the same weight as the five they can.
 *
 * Both views drive `useEscrowFlow`, so this is a second way to look at one
 * implementation and not a second implementation.
 *
 * ## The provider is the agent, and that is the claim
 *
 * Both recorded mainnet runs name one address as client *and* provider — job
 * 56681 and job 56718 — which proved the flow and hired nobody. Here the
 * provider defaults to the wallet that owns the agent being hired, so the money
 * is escrowed to a different party. The consequence is honest and visible:
 * `submit` is then that party's call and this page will not offer it. "Hire
 * myself" is kept because a full round trip in one wallet is what a
 * demonstration needs, and it is labelled as what it is.
 *
 * ## What it will not do
 *
 * Claim a step is done when nothing read it back. Three of the seven leave a
 * reading — an allowance, a job id echoing, a budget word — and two do not, so
 * those two say "sent here" rather than "done". See `Stage`.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { formatUnits } from "viem";
import { bsc } from "wagmi/chains";
import { Button } from "@/components/Button";
import { Card, CardHeader } from "@/components/Card";
import { EscrowField } from "@/components/EscrowField";
import { Pill } from "@/components/Pill";
import { useEscrowFlow, type Stage } from "@/components/useEscrowFlow";
import {
  countdown,
  paymentTokenMarket,
  selectorFrom,
  type EscrowDeployment,
} from "@/lib/escrow";
import { shortAddress } from "@/lib/format";

export interface HireableAgent {
  slug: string;
  name: string;
}

interface Props {
  deployments?: Record<string, EscrowDeployment>;
  defaultBudget?: number;
  errors?: Record<string, string>;
  /** The four agents this marketplace lists. */
  agents?: HireableAgent[];
  /** `ours.owner` — the wallet holding all four ERC-8004 identities. */
  owner?: string;
}

/**
 * Which agent the reader picked, from `?agent=`.
 *
 * Read in an effect rather than at render, for the reason `lib/scenario.ts`
 * gives: the export is static and prerendered, so reading `location` during
 * render produces HTML that disagrees with the client.
 */
function useChosenAgent(): string | null {
  const [slug, setSlug] = useState<string | null>(null);
  useEffect(() => {
    const value = new URLSearchParams(window.location.search).get("agent");
    setSlug(value && /^[a-z0-9-]{1,32}$/.test(value) ? value : null);
  }, []);
  return slug;
}

const SELF = "__self__";

function StageChip({ stage }: { stage: Stage }) {
  if (stage.kind === "chain") return <Pill tone="pass">done</Pill>;
  // A different word on purpose: this browser watched it mine, and no reading
  // confirms it. Saying "done" in both cases would be the misquote.
  if (stage.kind === "session") return <Pill tone="info">sent</Pill>;
  if (stage.kind === "theirs") return <Pill tone="none">not yours</Pill>;
  if (stage.kind === "locked") return <Pill tone="none">waiting</Pill>;
  return <Pill tone="unverified">next</Pill>;
}

function stageNote(stage: Stage): string {
  switch (stage.kind) {
    case "chain":
    case "session":
      return stage.note;
    case "locked":
      // Empty for the ordinary case, so the row falls back to saying what the
      // call does. Repeating "needs approve first" on four consecutive rows
      // told the reader nothing the "waiting" chip had not already said.
      return stage.why;
    case "theirs":
      return stage.who;
    default:
      return "";
  }
}

export function HireEscrow({ deployments, defaultBudget, errors, agents = [], owner }: Props) {
  const chosen = useChosenAgent();
  const [pick, setPick] = useState<string | null>(null);
  // The URL chooses until the reader does. `pick` starting null rather than at
  // a default is what lets `?agent=` win without an effect that fights it.
  //
  // With no `?agent=` this falls to the first listed agent rather than to
  // "myself". Defaulting to a self-hire would make the page open on the one
  // arrangement that hires nobody — which is what both recorded mainnet runs
  // did, and the thing this surface exists to stop being the default.
  const selected =
    pick ?? (agents.some((a) => a.slug === chosen) ? chosen : agents[0]?.slug) ?? SELF;
  const agent = agents.find((a) => a.slug === selected);

  const flow = useEscrowFlow({
    deployments,
    defaultBudget,
    // No `defaultJob`. The console opens on the recorded job because an auditor
    // wants to read it back; someone hiring is creating a new one, and seeding
    // a job id somebody else funded would have them act on it by accident.
    initialProvider: "",
  });
  const {
    mounted,
    isConnected,
    chainId,
    switchChain,
    deployment,
    units,
    unitsAssumed,
    jobId,
    provider,
    setProvider,
    youDeliver,
    budget,
    setTypedBudget,
    hours,
    setHours,
    submitWindow,
    state,
    expiresIn,
    balance,
    shortfall,
    steps,
    send,
    write,
    receipt,
    lastCall,
  } = flow;

  // Choosing an agent sets the provider; choosing "myself" clears it back to
  // the connected wallet, which is what a blank provider means.
  useEffect(() => {
    setProvider(selected !== SELF && owner ? owner : "");
    // `setProvider` is stable; re-running on the choice is the whole intent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, owner]);

  const revert = write.error?.message ?? "";
  const selector = selectorFrom(write.error);
  const meaning = selector && errors ? errors[selector] : undefined;

  const market = paymentTokenMarket(deployment);
  const title = agent ? `Hire ${agent.name}` : "Hire an agent";

  if (!mounted || !isConnected) {
    return (
      <Card>
        <CardHeader title={title} eyebrow="ERC-8183 escrow · a job with a budget" />
        <p className="mt-2 mb-0 max-w-[62ch] text-sm text-dim">
          Connect a wallet to escrow a budget against a job. The money sits in
          the contract until the work is delivered, and comes back to you if
          nobody delivers.
        </p>
      </Card>
    );
  }

  if (!deployment) {
    return (
      <Card>
        <CardHeader title={title} aside={<Pill tone="fail">Wrong network</Pill>} />
        <p className="mt-2 mb-4 max-w-[62ch] text-sm text-dim">
          No verified ERC-8183 deployment on chain {chainId}. The addresses this
          page sends to were read off BNB Smart Chain and its testnet; there is
          nothing to call here.
        </p>
        <Button onClick={() => switchChain({ chainId: bsc.id })}>
          Switch to BNB Smart Chain
        </Button>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title={title}
        eyebrow={`${deployment.name} · ERC-8183 escrow`}
        aside={
          state?.exists ? (
            <Pill tone="pass">job {state.id.toString()}</Pill>
          ) : (
            <Pill tone="none">no job yet</Pill>
          )
        }
      />

      <div className="mt-4 flex flex-wrap items-end gap-4">
        <label className="block text-xs">
          <span className="text-faint">Who delivers</span>
          <select
            className="mt-1 block w-52 rounded-sm border border-line bg-panel px-2 py-1.5 text-xs text-ink"
            value={selected}
            onChange={(event) => setPick(event.target.value)}
          >
            {agents.map((a) => (
              <option key={a.slug} value={a.slug}>
                {a.name}
              </option>
            ))}
            <option value={SELF}>Myself (demo)</option>
          </select>
        </label>
        <EscrowField
          label="Budget (token)"
          value={budget}
          onChange={setTypedBudget}
          width="w-28"
        />
        <EscrowField label="Expiry (hours)" value={hours} onChange={setHours} width="w-24" />
      </div>

      {/* Who the other party is, in the one sentence that changes what the
          reader can press. */}
      <p className="mt-3 mb-0 max-w-[70ch] text-xs text-dim">
        {youDeliver ? (
          <>
            You are both client and provider. That is what both recorded mainnet
            runs did &mdash; it proves the flow and hires nobody &mdash; and it is
            the only way to press every step from one wallet.
          </>
        ) : (
          <>
            {agent?.name} delivers, from{" "}
            <span className="font-mono">{shortAddress(provider)}</span>. You can
            send the five calls that escrow the budget;{" "}
            <span className="font-mono">submit</span> is signed by whoever you
            hired, and <span className="font-mono">settle</span> by the router.
          </>
        )}
      </p>

      {submitWindow !== null && !submitWindow.clears && (
        <p className="mt-3 mb-0 max-w-[70ch] text-xs text-dim">
          <strong className="text-ink">{hours || "0"}h will not reach submit.</strong>{" "}
          This policy&rsquo;s dispute window reads {submitWindow.hours}h, and the
          expiry has to be further out than that. The budget still escrows; only
          the delivery is refused.
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-4 text-xs">
        {state?.exists && (
          <>
            <span className="font-mono text-faint">status {state.status} (unnamed)</span>
            <span className="font-mono text-faint">
              escrowed {formatUnits(state.budget, units)}
            </span>
            <span className="font-mono text-faint">
              {expiresIn && expiresIn > 0
                ? `expires in ${countdown(expiresIn)}`
                : "expired — refundable"}
            </span>
          </>
        )}
        {balance !== undefined && (
          <span className="font-mono text-faint">
            you hold {formatUnits(balance, units)}
            {unitsAssumed && " (decimals assumed)"}
          </span>
        )}
      </div>

      {/* The wall this marketplace had, with a door in it.

          The kernel settles in one ERC-20 chosen by whoever deployed it, not in
          BNB, so a visitor with a funded wallet reached step five and found
          `fund` greyed: "this wallet does not hold that much of the payment
          token". True, and the end of the road — no faucet, no address to copy,
          no link, and nothing anywhere on this site saying what to do about it.

          It is buyable, and this repository already knew: `registry.json`
          records the swap that proved it and job 56681 was escrowed with what
          it bought. That lived in a docstring the browser never renders. */}
      {shortfall !== null && (
        <div className="mt-4 border-t border-line pt-4">
          <p className="m-0 max-w-[70ch] text-sm text-ink">
            <strong>
              You need {formatUnits(shortfall, units)} more of the payment token.
            </strong>{" "}
            The escrow settles in one ERC-20 chosen by whoever deployed the
            kernel, not in BNB.
          </p>
          {market ? (
            <>
              <p className="mt-2 mb-0 max-w-[70ch] text-xs text-dim">
                It trades on PancakeSwap. The swap{" "}
                <Link href="/registry/#hired">recorded on the proofs page</Link>{" "}
                bought enough for a hire several times over, for a fraction of a
                cent of BNB.
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <Button href={market.url} size="sm">
                  Buy it on PancakeSwap ↗
                </Button>
                <code className="rounded-sm border border-line bg-panel px-2 py-1 font-mono text-xs break-all text-faint">
                  {market.token}
                </code>
              </div>
            </>
          ) : (
            /* Chapel's token is the same shape with no market behind it —
               owner-minted, no faucet among its selectors, nothing to buy from.
               "Switch to testnet" would send someone somewhere strictly harder. */
            <p className="mt-2 mb-0 max-w-[70ch] text-xs text-dim">
              This chain&rsquo;s payment token is owner-minted, with no faucet and
              nowhere to buy it. The hire completes on BNB Smart Chain, where the
              token trades.
            </p>
          )}
        </div>
      )}

      <ol className="mt-4 mb-0 grid list-none gap-2 p-0">
        {steps
          // `claimRefund` is not a step of the hire — it is what happens when
          // there isn't one. It gets its own row below, and only once there is
          // a job to reclaim.
          .filter((step) => step.name !== "claimRefund")
          .map((step, index) => {
            const actionable = step.stage.kind === "next" && !step.disabled;
            return (
              <li key={step.name} className="flex flex-wrap items-center gap-3">
                <span className="tabular w-5 shrink-0 font-mono text-xs text-faint">
                  {index + 1}
                </span>
                <span className="w-24 shrink-0">
                  <StageChip stage={step.stage} />
                </span>
                {actionable ? (
                  <Button
                    size="sm"
                    disabled={write.isPending}
                    onClick={send(step.name, step.run)}
                  >
                    {write.isPending && lastCall === step.name
                      ? "Check your wallet…"
                      : receipt.isLoading && lastCall === step.name
                        ? "Mining…"
                        : step.name}
                  </Button>
                ) : (
                  <span className="w-28 shrink-0 font-mono text-xs text-faint">
                    {step.name}
                  </span>
                )}
                <span className="min-w-0 text-xs break-words text-dim">
                  {stageNote(step.stage) || step.hint}
                  {step.disabled && step.stage.kind === "next" && (
                    <span className="block text-faint">{step.disabled}</span>
                  )}
                </span>
              </li>
            );
          })}
      </ol>

      {state?.exists && (
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-4">
          {steps
            .filter((step) => step.name === "claimRefund")
            .map((step) => (
              <span key={step.name} className="flex flex-wrap items-center gap-3">
                <Button
                  size="sm"
                  tone="secondary"
                  disabled={Boolean(step.disabled) || write.isPending}
                  onClick={send(step.name, step.run)}
                >
                  {write.isPending && lastCall === step.name ? "Check your wallet…" : "Claim it back"}
                </Button>
                <span className="min-w-0 text-xs break-words text-dim">
                  {step.disabled ?? "The escrow returns to you. This is the answer to “what if nobody ever delivers”."}
                </span>
              </span>
            ))}
        </div>
      )}

      {(write.data || write.error) && (
        <dl className="mt-5 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 border-t border-line pt-4 text-xs">
          {write.data && (
            <>
              <dt className="text-faint">{lastCall}</dt>
              <dd className="m-0">
                <a
                  className="font-mono break-all underline"
                  href={`${deployment.explorer}/tx/${write.data}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {write.data}
                </a>
                {receipt.isSuccess && " · mined"}
              </dd>
            </>
          )}
          {write.error && (
            <>
              <dt className="text-faint">Refused</dt>
              <dd className="m-0 text-bad">
                {revert.split("\n")[0]}
                {selector && (
                  <span className="block text-faint">
                    {selector} — {meaning ?? "unresolved in this repository"}
                  </span>
                )}
              </dd>
            </>
          )}
        </dl>
      )}

      {/* What the money buys, and what it does not.
          A visitor who funds a job was told nothing about what arrives or when
          — the stepper ends at a greyed `submit` marked "not yours" and stops.
          Four sentences, because the landing page was once 84% ledger and prose
          is what that cost. */}
      <div className="mt-5 border-t border-line pt-4 text-xs text-dim">
        <p className="m-0 max-w-[70ch]">
          <strong className="text-ink">What the escrow buys.</strong> The budget
          sits in the kernel until {agent ? agent.name : "the provider"} submits a
          deliverable, and comes back to you at the expiry if nobody does. No
          process here watches for funded jobs and signs that submission yet
          &mdash; it is on the{" "}
          <Link href="/status/">not-built ledger</Link>, and the escrow, the
          refund and the submission are each proven on mainnet from a signer
          rather than from a service.
        </p>
        <p className="mt-2 mb-0 max-w-[70ch]">
          {agent ? `${agent.name}'s` : "This agent's"} work on this pool already
          exists and needs no hire to read:{" "}
          {agent && <Link href={`/agent/${agent.slug}/`}>its tearsheet</Link>}
          {agent && " · "}
          <Link href="/advantage/">the same task run without it</Link>.
        </p>
      </div>

      <p className="mt-4 mb-0 text-xs text-faint">
        Job id <span className="font-mono">{jobId || "—"}</span>. Every call and
        every revert, unguided, is on{" "}
        <a href="/registry/#escrow" className="underline">
          the registry page
        </a>
        .
      </p>
    </Card>
  );
}
