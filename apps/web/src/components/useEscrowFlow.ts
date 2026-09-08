"use client";

/**
 * The ERC-8183 hire, as a hook, so two surfaces can send the same seven calls.
 *
 * This was the body of `EscrowConsole`, which is a developer's view of the
 * flow: eight buttons named after Solidity functions, all enabled, in the order
 * the chain accepts them. That view is worth keeping — an auditor wants to send
 * one call and read the revert — but it is not what someone arriving at a
 * marketplace to hire an agent should be handed.
 *
 * So the engine lives here and the two renderers are thin: `HireEscrow` walks a
 * reader through it one step at a time, and `EscrowConsole` keeps the raw list.
 * One implementation, because two would drift, and the thing that drifts is
 * always an argument — see `createJobArgs` for the one that already did.
 */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { formatUnits, keccak256, parseUnits, toHex, type Address, type Hex } from "viem";
import {
  useAccount,
  useChainId,
  usePublicClient,
  useReadContract,
  useSwitchChain,
  useWaitForTransactionReceipt,
  useWriteContract,
} from "wagmi";
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
  type EscrowDeployment,
  type JobReading,
} from "@/lib/escrow";

/**
 * What to use until `decimals()` answers, and the only place it is guessed.
 *
 * `chain/addresses.py` refuses to assume this and says why — BSC's USDT is 18
 * where Ethereum's is 6, and assuming wrong misprices by twelve orders of
 * magnitude. So the flow reads it and falls back only while the read is in
 * flight or refused, and says "assumed" on screen when it is doing that.
 */
const ASSUMED_DECIMALS = 18;

/**
 * Hours of expiry to open on, and it is not a round number for comfort.
 *
 * `submit` is refused unless `expiredAt` is further away than the policy's
 * dispute window — 604,800s on mainnet. `make hire-mainnet` carries the same
 * 192 for the same reason, a day clear of the boundary. This opened on twelve,
 * which is what job 56681 asked for and why its submit reverted.
 */
export const DEFAULT_HOURS = 192;

export type StepName =
  | "approve"
  | "createJob"
  | "setBudget"
  | "registerJob"
  | "fund"
  | "submit"
  | "settle"
  | "claimRefund";

/**
 * How far along a step is, and — the part that matters — how that is known.
 *
 * `chain` and `session` are deliberately different words. Three of these steps
 * leave a reading anybody can take: an allowance that covers the budget, a job
 * id that echoes back, a budget word above zero. Two do not. The router
 * publishes no `policyOf`, and `erc8183.py` has never confirmed that this
 * deployment orders its statuses the way the EIP lists them — which is why the
 * status is rendered as a number and not a word. So `registerJob` and `fund`
 * are known only because this browser watched them mine, and a stepper that
 * called that "done" in the same voice as the other three would be claiming a
 * reading it does not have.
 */
export type Stage =
  | { kind: "chain"; note: string }
  | { kind: "session"; note: string }
  | { kind: "next" }
  | { kind: "locked"; why: string }
  | { kind: "theirs"; who: string };

/**
 * What `submit`'s 32 bytes commit to, when they commit to something fetchable.
 *
 * The argument is opaque — `registry/hire.py` says so: "nothing on chain
 * interprets it, so this does not pretend to". That makes the hash worth
 * exactly as much as the thing a reader can fetch and re-derive it from, and
 * worth nothing without one. Both recorded mainnet runs sent
 * `keccak256("job-<id>")`, a hash of the job's own id, which is a receipt for
 * the transaction rather than a commitment to work; this console sent
 * `keccak256("deliverable")`, a hash of the literal word, and showed neither.
 *
 * `hire_mainnet.py --deliverable-file` already hashes real file bytes. This is
 * the same commitment from the browser.
 */
export interface Commitment {
  /** The 32 bytes `submit` sends. */
  hex: Hex;
  /** What was hashed, named the way a reader would ask for it. */
  label: string;
  /** Where those exact bytes can be fetched and re-hashed. */
  url: string;
  bytes: number;
}

export interface FlowStep {
  name: StepName;
  call: string;
  hint: string;
  /** Set when the call cannot be sent from here; the string is the reason. */
  disabled?: string;
  run: () => void;
  stage: Stage;
}

export interface EscrowFlowInput {
  /** `hire_flow.deployments` — keyed by chain id as a string, as JSON has it. */
  deployments?: Record<string, EscrowDeployment>;
  /** The job the recorded runs used, so it opens on something real. */
  defaultJob?: number;
  /** The budget that run escrowed, in the token's smallest unit. */
  defaultBudget?: number;
  /**
   * Who delivers. Blank means the connected wallet, which is what both mainnet
   * proofs did — job 56681 and 56718 name one address as client and provider.
   * A marketplace hires somebody else, so `HireEscrow` seeds this with the
   * address that owns the agent being hired.
   */
  initialProvider?: string;
}

export function useEscrowFlow({
  deployments,
  defaultJob,
  defaultBudget,
  initialProvider = "",
}: EscrowFlowInput) {
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
  const [provider, setProvider] = useState(initialProvider);
  // `null` means "the reader has not typed a budget", which is not the same as
  // an empty one. The seed is a *token amount* and the scale it renders at
  // arrives later, so holding the raw smallest-unit value and formatting on
  // render means the field corrects itself when the token answers.
  const [typedBudget, setTypedBudget] = useState<string | null>(null);
  const budget =
    typedBudget ?? (defaultBudget ? formatUnits(BigInt(defaultBudget), units) : "");
  const [hours, setHours] = useState(String(DEFAULT_HOURS));
  const [deliverable, setDeliverable] = useState("deliverable");
  // Set by whichever surface can name a fetchable file. `EscrowConsole` never
  // does — an auditor is testing the call, not delivering — so it keeps hashing
  // the text field and this stays null there.
  const [commitment, setCommitment] = useState<Commitment | null>(null);
  /** The exact 32 bytes `submit` will send, so a surface can show them first. */
  const deliverableHash: Hex = commitment?.hex ?? keccak256(toHex(deliverable));
  const [lastCall, setLastCall] = useState<StepName | null>(null);
  const [mined, setMined] = useState<Partial<Record<StepName, string>>>({});
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

  const reading = useQuery({
    queryKey: ["erc8183-job", chainId, jobId, receipt.isSuccess],
    enabled: Boolean(deployment && publicClient && job > 0n),
    refetchInterval: 12_000,
    queryFn: async (): Promise<JobReading | null> => {
      if (!deployment || !publicClient) return null;
      const { data } = await publicClient.call({ to: kernel, data: encodeGetJob(job) });
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
  // mainnet, 86,400s on chapel) and the expiry rule is stated in terms of
  // whichever one this chain actually carries.
  const disputeWindow = useReadContract({
    abi: POLICY_ABI,
    address: policy,
    functionName: "disputeWindow",
    // No retry. This is a constant on a deployed contract: an answer that does
    // not decode once will not decode on the fourth attempt.
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
    if (!receipt.isSuccess || !lastCall) return;
    setMined((seen) => (seen[lastCall] ? seen : { ...seen, [lastCall]: write.data }));
    if (lastCall !== "createJob") return;
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
  // tick, because ticking is what changes it.
  const counting = expiresIn !== null && expiresIn > 0;
  useEffect(() => {
    if (!counting) return;
    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, [counting]);

  const isClient =
    Boolean(state && address) && state!.client.toLowerCase() === address!.toLowerCase();

  // How much of the payment token is missing, if any. The console stated this
  // as a refusal and stopped — "this wallet does not hold that much" — which is
  // the one place a marketplace must not stop, because it is the step where a
  // stranger with a funded wallet is turned away.
  const held = balance.data as bigint | undefined;
  const shortfall = held !== undefined && amount > 0n && held < amount ? amount - held : null;
  const providerAddress = (provider || address || "").toLowerCase();
  const youDeliver = Boolean(address) && providerAddress === address!.toLowerCase();

  const windowSeconds = disputeWindow.data as bigint | undefined;
  const submitWindow =
    windowSeconds === undefined || !/^\d+(\.\d+)?$/.test(hours.trim())
      ? null
      : {
          seconds: windowSeconds.toString(),
          hours: Math.round(Number(windowSeconds) / 3600),
          clears: clearsDisputeWindow(Number(hours), windowSeconds),
        };

  const send = (name: StepName, run: () => void) => () => {
    setLastCall(name);
    run();
  };

  // What a reading can and cannot settle. `approved`, `created` and `budgeted`
  // come off the chain; the other two are only what this browser watched.
  const covered =
    allowance.data !== undefined && (allowance.data as bigint) >= amount && amount > 0n;
  const created = Boolean(state?.exists);
  const budgeted = Boolean(state?.exists && state.budget > 0n);

  const done = (name: StepName): Stage | null => {
    if (name === "approve" && covered)
      return { kind: "chain", note: "the allowance already covers this budget" };
    if (name === "createJob" && created)
      return { kind: "chain", note: `job ${state!.id.toString()} reads back` };
    if (name === "setBudget" && budgeted)
      return { kind: "chain", note: `the job carries ${formatUnits(state!.budget, units)}` };
    if (mined[name])
      return { kind: "session", note: "mined here — no reading confirms it" };
    return null;
  };

  const ORDER: StepName[] = [
    "approve",
    "createJob",
    "setBudget",
    "registerJob",
    "fund",
    "submit",
    "settle",
  ];

  const definitions: Omit<FlowStep, "stage">[] = deployment
    ? [
        {
          name: "approve",
          call: "approve(kernel, budget)",
          hint: "The token, not the escrow. Skipped if the allowance already covers it.",
          disabled: covered ? "allowance already covers this budget" : undefined,
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
              // `createJobArgs`, with the reverts each of them earns.
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
          hint: "Before registerJob. The other order is the one chapel sent, and its fund reverted.",
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
            shortfall !== null
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
              args: [job, deliverableHash, "0x"],
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

  // The first step in the canonical order that nothing says is finished.
  const nextUp = ORDER.find((name) => !done(name));

  const steps: FlowStep[] = definitions.map((step) => {
    const finished = done(step.name);
    let stage: Stage;
    if (finished) stage = finished;
    else if (step.name === "settle")
      stage = { kind: "theirs", who: "the EvaluatorRouter, once its policy decides" };
    else if (step.name === "submit" && !youDeliver)
      stage = { kind: "theirs", who: "whoever you hired — submit is the provider's call" };
    else if (step.name === "claimRefund")
      stage = step.disabled
        ? { kind: "locked", why: step.disabled }
        : { kind: "next" };
    else if (step.name === nextUp) stage = { kind: "next" };
    else {
      const blocker = ORDER.slice(0, ORDER.indexOf(step.name)).find((n) => !done(n));
      // Only the step directly behind the queue names what it is waiting for.
      // Every later row would repeat the same sentence, which reads as four
      // warnings rather than one queue.
      const immediate =
        nextUp !== undefined &&
        blocker === nextUp &&
        ORDER.indexOf(step.name) === ORDER.indexOf(nextUp) + 1;
      stage = blocker
        ? { kind: "locked", why: immediate ? `needs ${blocker} first` : "" }
        : { kind: "next" };
    }
    return { ...step, stage };
  });

  return {
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
    youDeliver,
    budget,
    setTypedBudget,
    hours,
    setHours,
    submitWindow,
    deliverable,
    setDeliverable,
    commitment,
    setCommitment,
    deliverableHash,
    state,
    expiresIn,
    isClient,
    balance: held,
    shortfall,
    reading,
    steps,
    nextUp,
    send,
    write,
    receipt,
    lastCall,
  };
}
