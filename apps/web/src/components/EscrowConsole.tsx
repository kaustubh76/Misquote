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
  POLICY_ABI,
  ROUTER_ABI,
  clearsDisputeWindow,
  countdown,
  createJobArgs,
  decodeJob,
  encodeGetJob,
  secondsUntil,
  selectorFrom,
  type EscrowDeployment,
  type JobReading,
} from "@/lib/escrow";

/**
 * What to use until `decimals()` answers, and the only place it is guessed.
 *
 * `chain/addresses.py` refuses to assume this and says why — BSC's USDT is 18
 * where Ethereum's is 6, and assuming wrong misprices by twelve orders of
 * magnitude. So the console reads it and falls back only while the read is in
 * flight or refused, and says "assumed" on screen when it is doing that.
 */
const ASSUMED_DECIMALS = 18;

/**
 * Hours of expiry to open on, and it is not a round number for comfort.
 *
 * `submit` is refused unless `expiredAt` is further away than the policy's
 * dispute window — 604,800s on mainnet. `make hire-mainnet` carries the same
 * 192 for the same reason, a day clear of the boundary. This console opened on
 * twelve, which is what job 56681 asked for and why its submit reverted.
 */
const DEFAULT_HOURS = 192;

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

  const decimals = useReadContract({
    abi: ERC20_ABI,
    address: token,
    functionName: "decimals",
    query: { enabled: Boolean(deployment) },
  });

  // `decimals()` is a uint8 and viem hands it back as a number.
  const read = decimals.data;
  const units = typeof read === "number" ? read : ASSUMED_DECIMALS;
  const unitsAssumed = typeof read !== "number";

  const [jobId, setJobId] = useState(String(defaultJob ?? ""));
  const [provider, setProvider] = useState("");
  // Seeded from what the recorded mainnet run actually escrowed, so the
  // console opens on a figure this repository has spent rather than a round
  // number typed into a component.
  // `null` means "the reader has not typed a budget", which is not the same as
  // an empty one. It matters because the seed is a *token amount* and the scale
  // it is rendered at arrives later: `decimals()` is a chain read, so the first
  // paint has only ASSUMED_DECIMALS. Seeding a string once, at eighteen, left a
  // six-decimal token showing a figure twelve orders of magnitude out and — via
  // `amount` below — sending it. Holding the raw smallest-unit value and
  // formatting on render means the field corrects itself when the token answers.
  const [typedBudget, setTypedBudget] = useState<string | null>(null);
  const budget =
    typedBudget ?? (defaultBudget ? formatUnits(BigInt(defaultBudget), units) : "");
  // 192, the same default `make hire-mainnet` carries, and for the same
  // reason: `submit` is refused unless `expiredAt` is further away than the
  // policy's dispute window. Eight fork runs identical but for the expiry put
  // the boundary between 168h and 169h against a 604,800s window. Twelve hours
  // was job 56681, whose submit reverted `SubmissionTooLate()` — and this
  // console reported that revert as a fact about mainnet rather than as a
  // consequence of its own default.
  const [hours, setHours] = useState(String(DEFAULT_HOURS));
  const [deliverable, setDeliverable] = useState("deliverable");
  const [lastCall, setLastCall] = useState<StepName | null>(null);
  const [now, setNow] = useState(() => Date.now());

  // A job id that is not a number is not job zero, and the difference used to
  // be invisible: the field accepted anything and the reads silently asked
  // about an id that never exists.
  const jobIdIsNumeric = /^\d+$/.test(jobId.trim());
  const job = BigInt(jobIdIsNumeric ? jobId.trim() : "0");
  // `units` belongs in this list. Without it the amount stayed at whatever
  // scale the first render assumed, so a token that answered `decimals()` late
  // was approved, budgeted and funded at the wrong magnitude.
  const amount = useMemo(() => {
    try {
      return parseUnits(budget || "0", units);
    } catch {
      return 0n;
    }
  }, [budget, units]);

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

  // How many jobs this deployment has seen. Read so that `createJob` can hand
  // the id back — see the effect below.
  const counter = useReadContract({
    abi: KERNEL_ABI,
    address: kernel,
    functionName: "jobCounter",
    query: { enabled: Boolean(deployment) },
  });

  // Read rather than assumed: the two deployments disagree (604,800s on
  // mainnet, 86,400s on chapel) and the expiry rule below is stated in terms of
  // whichever one this chain actually carries.
  const disputeWindow = useReadContract({
    abi: POLICY_ABI,
    address: policy,
    functionName: "disputeWindow",
    // No retry. This is a constant on a deployed contract: an answer that does
    // not decode once will not decode on the fourth attempt, and the backoff
    // buys nothing but a component that keeps re-rendering while it waits.
    query: { enabled: Boolean(deployment), retry: false },
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

  // `createJob` returns the new id to a caller that can read the return value.
  // A wallet cannot — `writeContract` resolves to a hash, not a result — so the
  // console did the one thing worse than not knowing: it left the id field on
  // whatever had been typed, and the next seven buttons acted on a different
  // job. `jobCounter()` after the receipt is the same read `hire_mainnet.py`
  // does, and the newest job is the one just created.
  useEffect(() => {
    if (lastCall !== "createJob" || !receipt.isSuccess) return;
    void counter.refetch().then((fresh) => {
      const made = fresh.data;
      if (typeof made === "bigint" && made > 0n) setJobId(made.toString());
    });
    // `counter` is a fresh object each render; refetching on the receipt alone
    // is the intent, and depending on it would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastCall, receipt.isSuccess]);

  const state = reading.data ?? null;
  const expiresIn = state ? secondsUntil(state.expiredAt, now) : null;
  // Depending on `expiresIn` tore the interval down and rebuilt it on every
  // tick, because ticking is what changes it. The condition is what the effect
  // actually cares about: whether there is a countdown on screen at all.
  const counting = expiresIn !== null && expiresIn > 0;
  useEffect(() => {
    if (!counting) return;
    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, [counting]);

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
          call: "createJob(provider, router, expiredAt, description, router)",
          hint: "Evaluator and hook are both the EvaluatorRouter. Naming a wallet reverts RouterNotEvaluator(); a zero hook reverts HookRequired().",
          run: () =>
            write.writeContract({
              abi: KERNEL_ABI,
              address: kernel,
              functionName: "createJob",
              // The evaluator, the hook and the timestamp rule all live in
              // `createJobArgs`, with the reverts each of them earns. They were
              // five literals here, and one of them — the hook — was wrong for
              // the whole life of this component.
              args: createJobArgs({
                provider: (provider || address) as Address,
                router,
                hours: Number(hours || DEFAULT_HOURS),
                description: "Misquote: does hiring an agent beat doing it yourself",
                nowMs: Date.now(),
              }),
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
          hint: "Three arguments, not the two the EIP describes. Accepted only when the expiry clears the dispute window.",
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

  const windowSeconds = disputeWindow.data as bigint | undefined;
  const submitWindow =
    windowSeconds === undefined || !/^\d+(\.\d+)?$/.test(hours.trim())
      ? null
      : {
          seconds: windowSeconds.toString(),
          hours: Math.round(Number(windowSeconds) / 3600),
          clears: clearsDisputeWindow(Number(hours), windowSeconds),
        };

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
            <Field label="Budget (token)" value={budget} onChange={setTypedBudget} width="w-28" />
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
              <strong className="text-ink">
                {hours || "0"}h will not reach submit.
              </strong>{" "}
              This policy&rsquo;s dispute window reads{" "}
              <span className="font-mono">{submitWindow.seconds}s</span> (
              {submitWindow.hours}h), and <span className="font-mono">submit</span>{" "}
              is refused unless the expiry is further out than that &mdash; it
              reverts <span className="font-mono">0x15e5dd74</span>. Steps 1&ndash;5
              still work; only the delivery does not.
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
            {balance.data !== undefined && (
              <span className="font-mono text-faint">
                you hold {formatUnits(balance.data as bigint, units)}
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
