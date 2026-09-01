/**
 * The ERC-8183 deployment, as much of it as a browser needs to send a job.
 *
 * ## Why the addresses are not in this file
 *
 * `sessionKeys.ts` hardcodes the keystore addresses and that was fine when one
 * contract was involved. A hire touches four, on two chains, and `erc8183.py`
 * is where an address is admitted after being read off a chain — so a second
 * copy here would be a second thing to be wrong, and the wrong one would be the
 * one users send money to. They arrive as `hire_flow.deployments` in
 * `registry.json` instead, and a chain with no entry gets a refusal rather than
 * a call to an address that means something else there.
 *
 * ## Why `getJob` is decoded by hand
 *
 * There is no `getJob` entry in the Python ABI either, and for a reason worth
 * preserving: the deployment returns a struct whose field *order* was recovered
 * from readings, not from a published interface. `registry/hire.py::read_job`
 * therefore returns words and names only the offsets it has confirmed. This
 * does the same, against the same offsets, so the browser cannot claim to know
 * more about the struct than the rest of the repository does.
 *
 * Nothing here turns a status into a name. `STATES` in `erc8183.py` is the
 * EIP's list and no reading has confirmed this deployment uses that ordering,
 * so the number is shown as a number.
 */

import type { Address, Hex } from "viem";

/**
 * As JSON carries it: addresses are strings here and are cast at the one place
 * they become call arguments. A `0x${string}` in this interface would be a
 * claim the artifact cannot make — nothing validates the shape on the way in.
 */
export interface EscrowDeployment {
  chain_id: number;
  name: string;
  explorer: string;
  kernel: string;
  router: string;
  policy: string;
  erc20: string;
}

/**
 * Offsets into `getJob`'s return, confirmed against job 56681 on mainnet.
 *
 * Word 0 is the ABI head offset — the thing that made an earlier existence
 * check say `true` for every id that had never existed.
 */
export const JOB_WORD = {
  id: 1,
  client: 2,
  provider: 3,
  evaluator: 4,
  budget: 6,
  expiredAt: 7,
  status: 8,
} as const;

export interface JobReading {
  id: bigint;
  client: Address;
  provider: Address;
  evaluator: Address;
  budget: bigint;
  expiredAt: bigint;
  status: number;
  /** The id echoing back is what proves the job exists; a non-empty answer does not. */
  exists: boolean;
}

const word = (raw: Hex, index: number): string =>
  raw.slice(2 + index * 64, 2 + (index + 1) * 64);

const asAddress = (w: string): Address => `0x${w.slice(24)}` as Address;

/** `getJob(uint256)`, the one call this file encodes rather than declares. */
export const GET_JOB_SELECTOR = "0xbf22c457";

export function encodeGetJob(jobId: bigint): Hex {
  return `${GET_JOB_SELECTOR}${jobId.toString(16).padStart(64, "0")}` as Hex;
}

export function decodeJob(raw: Hex, jobId: bigint): JobReading | null {
  // Nine words is the shortest answer carrying every offset named above. A
  // shorter one is not a job with missing fields, it is not a job.
  if (!raw || raw.length < 2 + 9 * 64) return null;
  const id = BigInt(`0x${word(raw, JOB_WORD.id)}`);
  return {
    id,
    client: asAddress(word(raw, JOB_WORD.client)),
    provider: asAddress(word(raw, JOB_WORD.provider)),
    evaluator: asAddress(word(raw, JOB_WORD.evaluator)),
    budget: BigInt(`0x${word(raw, JOB_WORD.budget)}`),
    expiredAt: BigInt(`0x${word(raw, JOB_WORD.expiredAt)}`),
    status: Number(BigInt(`0x${word(raw, JOB_WORD.status)}`)),
    exists: id === jobId && jobId > 0n,
  };
}

/**
 * The calls, with the argument counts that were searched for rather than assumed.
 *
 * `submit` is the one to look at: the EIP describes two arguments and the
 * deployment takes three. A client written from the standard encodes two words,
 * hits a selector that does not exist and reverts with no reason string.
 */
export const KERNEL_ABI = [
  {
    name: "createJob",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [
      { name: "provider", type: "address" },
      { name: "evaluator", type: "address" },
      { name: "expiredAt", type: "uint256" },
      { name: "description", type: "string" },
      { name: "hook", type: "address" },
    ],
    outputs: [{ type: "uint256" }],
  },
  {
    name: "setBudget",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [
      { name: "jobId", type: "uint256" },
      { name: "amount", type: "uint256" },
      { name: "optParams", type: "bytes" },
    ],
    outputs: [],
  },
  {
    name: "fund",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [
      { name: "jobId", type: "uint256" },
      { name: "expectedBudget", type: "uint256" },
      { name: "optParams", type: "bytes" },
    ],
    outputs: [],
  },
  {
    name: "submit",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [
      { name: "jobId", type: "uint256" },
      { name: "deliverable", type: "bytes32" },
      { name: "optParams", type: "bytes" },
    ],
    outputs: [],
  },
  {
    name: "jobCounter",
    type: "function",
    stateMutability: "view",
    inputs: [],
    outputs: [{ type: "uint256" }],
  },
  {
    name: "claimRefund",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [{ name: "jobId", type: "uint256" }],
    outputs: [],
  },
] as const;

export const ROUTER_ABI = [
  {
    name: "registerJob",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [
      { name: "jobId", type: "uint256" },
      { name: "policy", type: "address" },
    ],
    outputs: [],
  },
  {
    name: "settle",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [
      { name: "jobId", type: "uint256" },
      { name: "evidence", type: "bytes" },
    ],
    outputs: [],
  },
] as const;

export const ERC20_ABI = [
  {
    name: "allowance",
    type: "function",
    stateMutability: "view",
    inputs: [
      { name: "owner", type: "address" },
      { name: "spender", type: "address" },
    ],
    outputs: [{ type: "uint256" }],
  },
  {
    name: "balanceOf",
    type: "function",
    stateMutability: "view",
    inputs: [{ name: "account", type: "address" }],
    outputs: [{ type: "uint256" }],
  },
  {
    name: "approve",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [
      { name: "spender", type: "address" },
      { name: "amount", type: "uint256" },
    ],
    outputs: [{ type: "bool" }],
  },
] as const;

/**
 * `registerJob` names the evaluator, and it must be the EvaluatorRouter itself.
 *
 * Name a third wallet and it reverts `RouterNotEvaluator()`, so no policy is
 * ever set, so `fund` reverts `PolicyNotSet()` — two unnamed selectors, one
 * cause, neither of them about money. A client written from the EIP names a
 * human evaluator and fails two transactions after the mistake, which is why
 * this is a constant and not a form field.
 */
export const EVALUATOR_IS_THE_ROUTER = true;

/** Seconds remaining until `expiredAt`, floored at zero. */
export function secondsUntil(expiredAt: bigint, now: number): number {
  return Math.max(0, Number(expiredAt) - Math.floor(now / 1000));
}

export function countdown(seconds: number): string {
  if (seconds <= 0) return "now";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${s}s` : `${s}s`;
}
