"use client";

/**
 * The ERC-8183 hire, every call, in the order the chain accepts them.
 *
 * This is the auditor's view. `HireEscrow` is the one a visitor meets: same
 * seven calls, one at a time, with the agent named. Both drive `useEscrowFlow`,
 * so there is one implementation of the flow and two ways to look at it.
 *
 * ## Why the refusals are the feature
 *
 * `settle` reverts `NotDecided()` on mainnet today. The button is here anyway,
 * enabled, because a console that hides the calls that fail is the misquote
 * this repository is named after. Press it and the revert is printed with its
 * selector and whatever this repository has managed to resolve it to — which
 * for three of the twelve is still "unresolved", stated as that.
 *
 * ## What it will not do
 *
 * Name a human evaluator (`registerJob` demands the router — see
 * `EVALUATOR_IS_THE_ROUTER`), send a zero hook (`createJobArgs`), call a chain
 * with no verified deployment, or decode a status into a word `erc8183.py` has
 * not confirmed.
 */

import { formatUnits } from "viem";
import { Button } from "@/components/Button";
import { Card, CardHeader } from "@/components/Card";
import { Pill } from "@/components/Pill";
import { EscrowField } from "@/components/EscrowField";
import { useEscrowFlow } from "@/components/useEscrowFlow";
import { countdown, selectorFrom, type EscrowDeployment } from "@/lib/escrow";

interface Props {
  /** `hire_flow.deployments` — keyed by chain id as a string, as JSON has it. */
  deployments?: Record<string, EscrowDeployment>;
  /** The job the recorded runs used, so the console opens on something real. */
  defaultJob?: number;
  /** The budget that run escrowed, in the token's smallest unit. */
  defaultBudget?: number;
  /** `hire_flow.errors` — selector to meaning, for decoding a revert honestly. */
  errors?: Record<string, string>;
}

export function EscrowConsole({ deployments, defaultJob, defaultBudget, errors }: Props) {
  const flow = useEscrowFlow({ deployments, defaultJob, defaultBudget });
  const {
    mounted,
    isConnected,
    address,
    chainId,
    switchChain,
    deployment,
    units,
    unitsAssumed,
    jobId,
    setJobId,
    jobIdIsNumeric,
    provider,
    setProvider,
    budget,
    setTypedBudget,
    hours,
    setHours,
    submitWindow,
    deliverable,
    setDeliverable,
    state,
    expiresIn,
    isClient,
    balance,
    reading,
    steps,
    send,
    write,
    receipt,
    lastCall,
  } = flow;

  const revert = write.error?.message ?? "";
  const selector = selectorFrom(write.error);
  const meaning = selector && errors ? errors[selector] : undefined;

  return (
    <Card>
      <CardHeader title="Send it yourself" eyebrow="Your wallet, your money, this page" />

      {!mounted || !isConnected ? (
        <p className="mt-4 mb-0 text-sm text-dim">
          Connect a wallet in the nav to send these calls. Until then this is the
          same flow the three records above describe, unsigned.
        </p>
      ) : !deployment ? (
        <p className="mt-4 mb-0 text-sm text-dim">
          No verified ERC-8183 deployment on chain {chainId}.{" "}
          <button
            className="underline"
            type="button"
            onClick={() => switchChain({ chainId: 56 })}
          >
            Switch to BNB Smart Chain
          </button>
          .
        </p>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap items-end gap-4">
            <EscrowField label="Job id" value={jobId} onChange={setJobId} width="w-28" />
            <EscrowField
              label="Budget (token)"
              value={budget}
              onChange={setTypedBudget}
              width="w-28"
            />
            <EscrowField
              label="Expiry (hours)"
              value={hours}
              onChange={setHours}
              width="w-24"
            />
            <EscrowField
              label="Provider (blank = you)"
              value={provider}
              onChange={setProvider}
              placeholder={address}
              width="w-full max-w-[26rem]"
            />
            <EscrowField
              label="Deliverable"
              value={deliverable}
              onChange={setDeliverable}
              width="w-40"
            />
          </div>

          {jobId.trim() !== "" && !jobIdIsNumeric && (
            <p className="mt-3 mb-0 text-xs text-bad">
              &ldquo;{jobId}&rdquo; is not a job id. Every read and every call
              below acts on job 0, which never exists.
            </p>
          )}

          {/* Stated before the signature rather than after the revert. The
              console used to let a twelve-hour job through and then report
              `SubmissionTooLate()` as though the chain had surprised it. */}
          {submitWindow !== null && !submitWindow.clears && (
            <p className="mt-3 mb-0 text-xs text-dim">
              <strong className="text-ink">{hours || "0"}h will not reach submit.</strong>{" "}
              This policy&rsquo;s dispute window reads{" "}
              <span className="font-mono">{submitWindow.seconds}s</span> (
              {submitWindow.hours}h), and <span className="font-mono">submit</span> is
              refused unless the expiry is further out than that &mdash; it reverts{" "}
              <span className="font-mono">0x15e5dd74</span>. Steps 1&ndash;5 still work;
              only the delivery does not.
            </p>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-4 text-xs">
            <Pill tone={state?.exists ? "pass" : "none"}>
              {reading.isLoading
                ? "reading…"
                : state?.exists
                  ? `job ${state.id.toString()} exists`
                  : "no such job"}
            </Pill>
            {state?.exists && (
              <>
                {/* A number, because `erc8183.py` has never confirmed this
                    deployment uses the EIP's ordering and a word here would be
                    the first place in the repository to pretend otherwise. */}
                <span className="font-mono text-faint">status {state.status} (unnamed)</span>
                <span className="font-mono text-faint">
                  budget {formatUnits(state.budget, units)}
                </span>
                <span className="font-mono text-faint">
                  {expiresIn && expiresIn > 0
                    ? `expires in ${countdown(expiresIn)}`
                    : "expired — refundable"}
                </span>
                {isClient && <Pill tone="info">you funded this</Pill>}
              </>
            )}
            {balance !== undefined && (
              <span className="font-mono text-faint">
                you hold {formatUnits(balance, units)}
                {unitsAssumed && " (decimals assumed)"}
              </span>
            )}
          </div>

          <ol className="mt-4 mb-0 grid list-none gap-2 p-0">
            {steps.map((step, index) => (
              <li key={step.name} className="flex flex-wrap items-center gap-3">
                <span className="tabular w-5 shrink-0 font-mono text-xs text-faint">
                  {index + 1}
                </span>
                <Button
                  size="sm"
                  tone={step.name === "claimRefund" ? "primary" : "secondary"}
                  disabled={Boolean(step.disabled) || write.isPending}
                  onClick={send(step.name, step.run)}
                >
                  {write.isPending && lastCall === step.name
                    ? "Check your wallet…"
                    : receipt.isLoading && lastCall === step.name
                      ? "Mining…"
                      : step.name}
                </Button>
                <span className="min-w-0 text-xs break-words text-dim">
                  <span className="font-mono break-all text-faint">{step.call}</span> —{" "}
                  {step.hint}
                  {step.disabled && <span className="block text-faint">{step.disabled}</span>}
                </span>
              </li>
            ))}
          </ol>

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
        </>
      )}
    </Card>
  );
}
