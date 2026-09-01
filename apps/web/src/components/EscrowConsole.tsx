"use client";

/**
 * The ERC-8183 hire, sent from this page by the reader's own wallet.
 *
 * Everything else on `/registry` is a recording: three proofs of runs that
 * happened elsewhere, with hashes you can check. This is the same seven calls
 * with nothing recorded — the wallet in the browser signs, the chain answers,
 * and the answer is whatever it is.
 *
 * ## Why the refusals are the feature
 *
 * On mainnet today `submit` reverts `0x15e5dd74` and `settle` reverts
 * `NotDecided()`. Those buttons are here anyway, enabled, because a console
 * that hides the calls that fail is the misquote this repository is named
 * after. Press them and the revert is printed with its selector and whatever
 * this repository has managed to resolve it to — which for one of the two is
 * still "unresolved", stated as that.
 *
 * ## What it will not do
 *
 * Name a human evaluator (`registerJob` demands the router — see
 * `EVALUATOR_IS_THE_ROUTER`), call a chain with no verified deployment, or
 * decode a status into a word `erc8183.py` has not confirmed.
 */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { formatUnits, keccak256, parseUnits, toHex, type Address } from "viem";
import {
  useAccount,
  useChainId,
  usePublicClient,
  useReadContract,
  useSwitchChain,
  useWaitForTransactionReceipt,
  useWriteContract,
} from "wagmi";
import { Button } from "@/components/Button";
import { Card, CardHeader } from "@/components/Card";
import { Pill } from "@/components/Pill";
import {
  ERC20_ABI,
  KERNEL_ABI,
  ROUTER_ABI,
  countdown,
  decodeJob,
  encodeGetJob,
  secondsUntil,
  selectorFrom,
  type EscrowDeployment,
  type JobReading,
} from "@/lib/escrow";

/** The token is 18 decimals, read once on mainnet and recorded in the artifact. */
const DECIMALS = 18;

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

type StepName =
  | "approve"
  | "createJob"
  | "setBudget"
  | "registerJob"
  | "fund"
  | "submit"
  | "settle"
  | "claimRefund";

function Field({
  label,
  value,
  onChange,
  placeholder,
  width = "w-full",
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  width?: string;
}) {
  return (
    <label className="block text-xs">
      <span className="text-faint">{label}</span>
      <input
        className={`mt-1 block ${width} rounded-sm border border-line bg-panel px-2 py-1.5 font-mono text-xs text-ink`}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

export function EscrowConsole({ deployments, defaultJob, defaultBudget, errors }: Props) {
  // The server render and the first client render must match, and a connected
  // wallet is only knowable in the browser. Same gate as `ConnectButton`.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const { address, isConnected } = useAccount();
  const chainId = useChainId();
  const { switchChain } = useSwitchChain();
  const publicClient = usePublicClient({ chainId });

  const deployment = deployments?.[String(chainId)];
  // The one place strings from an artifact become call arguments.
  const kernel = deployment?.kernel as Address;
  const router = deployment?.router as Address;
  const policy = deployment?.policy as Address;
  const token = deployment?.erc20 as Address;
  const [jobId, setJobId] = useState(String(defaultJob ?? ""));
  const [provider, setProvider] = useState("");
  // Seeded from what the recorded mainnet run actually escrowed, so the
  // console opens on a figure this repository has spent rather than a round
  // number typed into a component.
  const [budget, setBudget] = useState(
    defaultBudget ? formatUnits(BigInt(defaultBudget), DECIMALS) : "",
  );
  const [hours, setHours] = useState("12");
  const [deliverable, setDeliverable] = useState("deliverable");
  const [lastCall, setLastCall] = useState<StepName | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const job = BigInt(/^\d+$/.test(jobId) ? jobId : "0");
  const amount = useMemo(() => {
    try {
      return parseUnits(budget || "0", DECIMALS);
    } catch {
      return 0n;
    }
  }, [budget]);

  const write = useWriteContract();
  const receipt = useWaitForTransactionReceipt({ hash: write.data });

  // One second, only while a countdown is on screen.
  const reading = useQuery({
    queryKey: ["erc8183-job", chainId, jobId, receipt.isSuccess],
    enabled: Boolean(deployment && publicClient && job > 0n),
    refetchInterval: 12_000,
    queryFn: async (): Promise<JobReading | null> => {
      if (!deployment || !publicClient) return null;
      const { data } = await publicClient.call({
        to: kernel,
        data: encodeGetJob(job),
      });
      return data ? decodeJob(data, job) : null;
    },
  });

  const allowance = useReadContract({
    abi: ERC20_ABI,
    address: token,
    functionName: "allowance",
    args: address && deployment ? [address, kernel] : undefined,
    query: { enabled: Boolean(address && deployment), refetchInterval: 12_000 },
  });

  const balance = useReadContract({
    abi: ERC20_ABI,
    address: token,
    functionName: "balanceOf",
    args: address ? [address] : undefined,
    query: { enabled: Boolean(address && deployment), refetchInterval: 12_000 },
  });

  const state = reading.data ?? null;
  const expiresIn = state ? secondsUntil(state.expiredAt, now) : null;
  useEffect(() => {
    if (expiresIn === null || expiresIn <= 0) return;
    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, [expiresIn]);

  const isClient =
    Boolean(state && address) && state!.client.toLowerCase() === address!.toLowerCase();

  const send = (name: StepName, run: () => void) => () => {
    setLastCall(name);
    run();
  };


  const steps: {
    name: StepName;
    call: string;
    hint: string;
    disabled?: string;
    run: () => void;
  }[] = deployment
    ? [
        {
          name: "approve",
          call: "approve(kernel, budget)",
          hint: "The token, not the escrow. Skipped if the allowance already covers it.",
          disabled:
            allowance.data !== undefined && (allowance.data as bigint) >= amount && amount > 0n
              ? "allowance already covers this budget"
              : undefined,
          run: () =>
            write.writeContract({
              abi: ERC20_ABI,
              address: token,
              functionName: "approve",
              args: [kernel, amount],
            }),
        },
        {
          name: "createJob",
          call: "createJob(provider, router, expiredAt, description, 0x0)",
          hint: "The evaluator is the EvaluatorRouter, not a person. Naming a wallet reverts RouterNotEvaluator().",
          run: () =>
            write.writeContract({
              abi: KERNEL_ABI,
              address: kernel,
              functionName: "createJob",
              args: [
                (provider || address) as Address,
                router,
                BigInt(Math.floor(Date.now() / 1000) + Number(hours || "12") * 3600),
                "Misquote: does hiring an agent beat doing it yourself",
                "0x0000000000000000000000000000000000000000" as Address,
              ],
            }),
        },
        {
          name: "setBudget",
          call: "setBudget(jobId, amount, 0x)",
          hint: "Before registerJob. The other order reverts.",
          run: () =>
            write.writeContract({
              abi: KERNEL_ABI,
              address: kernel,
              functionName: "setBudget",
              args: [job, amount, "0x"],
            }),
        },
        {
          name: "registerJob",
          call: "registerJob(jobId, policy)",
          hint: "On the router. Without it fund() reverts PolicyNotSet().",
          run: () =>
            write.writeContract({
              abi: ROUTER_ABI,
              address: router,
              functionName: "registerJob",
              args: [job, policy],
            }),
        },
        {
          name: "fund",
          call: "fund(jobId, expectedBudget, 0x)",
          hint: "The money moves here. A budget of exactly zero is the only one it refuses.",
          disabled:
            balance.data !== undefined && (balance.data as bigint) < amount
              ? "this wallet does not hold that much of the payment token"
              : undefined,
          run: () =>
            write.writeContract({
              abi: KERNEL_ABI,
              address: kernel,
              functionName: "fund",
              args: [job, amount, "0x"],
            }),
        },
        {
          name: "submit",
          call: "submit(jobId, deliverable, 0x)",
          hint: "Three arguments, not the two the EIP describes. Reverts 0x15e5dd74 on mainnet today.",
          run: () =>
            write.writeContract({
              abi: KERNEL_ABI,
              address: kernel,
              functionName: "submit",
              args: [job, keccak256(toHex(deliverable)), "0x"],
            }),
        },
        {
          name: "settle",
          call: "settle(jobId, 0x)",
          hint: "On the router. Reverts NotDecided() until the policy decides, which on mainnet it does not.",
          run: () =>
            write.writeContract({
              abi: ROUTER_ABI,
              address: router,
              functionName: "settle",
              args: [job, "0x"],
            }),
        },
        {
          name: "claimRefund",
          call: "claimRefund(jobId)",
          hint: "The way out when nobody settles. Opens at expiredAt and not a second before.",
          disabled:
            state && !isClient
              ? "only the client that funded this job can claim it"
              : expiresIn !== null && expiresIn > 0
                ? `not until the expiry — ${countdown(expiresIn)} to go`
                : undefined,
          run: () =>
            write.writeContract({
              abi: KERNEL_ABI,
              address: kernel,
              functionName: "claimRefund",
              args: [job],
            }),
        },
      ]
    : [];

  const revert = write.error?.message ?? "";
  const selector = selectorFrom(write.error);
  const meaning = selector && errors ? errors[selector] : undefined;

  return (
    <Card>
      <CardHeader
        title="Send it yourself"
        eyebrow="Your wallet, your money, this page"
      />

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
            <Field label="Job id" value={jobId} onChange={setJobId} width="w-28" />
            <Field label="Budget (token)" value={budget} onChange={setBudget} width="w-28" />
            <Field label="Expiry (hours)" value={hours} onChange={setHours} width="w-24" />
            <Field
              label="Provider (blank = you)"
              value={provider}
              onChange={setProvider}
              placeholder={address}
              width="w-full max-w-[26rem]"
            />
            <Field
              label="Deliverable"
              value={deliverable}
              onChange={setDeliverable}
              width="w-40"
            />
          </div>

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
                  budget {formatUnits(state.budget, DECIMALS)}
                </span>
                <span className="font-mono text-faint">
                  {expiresIn && expiresIn > 0
                    ? `expires in ${countdown(expiresIn)}`
                    : "expired — refundable"}
                </span>
                {isClient && <Pill tone="info">you funded this</Pill>}
              </>
            )}
            {balance.data !== undefined && (
              <span className="font-mono text-faint">
                you hold {formatUnits(balance.data as bigint, DECIMALS)}
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
                  <span className="font-mono break-all text-faint">{step.call}</span> — {step.hint}
                  {step.disabled && (
                    <span className="block text-faint">{step.disabled}</span>
                  )}
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
