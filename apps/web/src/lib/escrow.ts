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

/**
 * The one thing the policy is asked, and the reason it is asked rather than typed.
 *
 * `submit` is refused unless `expiredAt` is further away than this window —
 * `hire.py`'s `SUBMIT_NEEDS_EXPIRY_BEYOND_DISPUTE_WINDOW`, measured over eight
 * fork runs that put the boundary between 168h and 169h. The two deployments
 * disagree about it (mainnet 604,800s, chapel 86,400s), so a console that
 * hardcoded either would mislead on the other. `verify_erc8183.py:228` reads the
 * same accessor, and it returns a `uint64`.
 */
export const POLICY_ABI = [
  {
    name: "disputeWindow",
    type: "function",
    stateMutability: "view",
    inputs: [],
    outputs: [{ type: "uint64" }],
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
  // Read, not assumed. `chain/addresses.py` is blunt about why: BSC's USDT and
  // USDC are 18 decimals where Ethereum's are 6, and "assuming 6 here would
  // misprice every position by twelve orders of magnitude", so the Python side
  // reads `decimals()` and records what came back. A browser that types 18 into
  // a constant is making the assumption that file exists to refuse.
  {
    name: "decimals",
    type: "function",
    stateMutability: "view",
    inputs: [],
    outputs: [{ type: "uint8" }],
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

/**
 * The four-byte selector of a revert, when there is one to be sure of.
 *
 * ## Two ways to get this wrong, and both were live
 *
 * It began as `/0x[0-9a-f]{8}\b/i` over the error message. The `\b` was wrong
 * in the one case that matters: viem attaches the **ABI-encoded payload**, so
 * the character after the eight digits is `0` — a word character — and the
 * meaning silently never rendered, on exactly the reverts the `submit` and
 * `settle` buttons exist to show.
 *
 * Dropping the `\\b` and taking the first match was worse. A wallet error
 * quotes the *calldata* too, and calldata begins with the function selector, so
 * a failed `submit` that never reached the chain rendered
 * `0x9e63798d — unresolved in this repository`. That is not a missing answer,
 * it is a confident wrong one: the selector of the function we called, offered
 * as the reason it failed. A test caught it by making the transport fail.
 *
 * So a selector is returned only when something says it is revert data:
 * viem's structured `data`/`raw` on the error or one of its causes, or a
 * message that names it as a revert. Otherwise **undefined**, and the console
 * shows the failure without naming it — which is the honest answer when the
 * call never got far enough to be refused by anything.
 */
const SELECTOR = /(0x[0-9a-f]{8})/i;

const ANCHORED: readonly RegExp[] = [
  // "…reverted with the following signature:\n0x8e78f0cb"
  /signature:\s*"?(0x[0-9a-f]{8})/i,
  // "…reverted with data 0x8e78f0cb0000…", and viem's "reverted." forms. The
  // bounded gap is what keeps this from reaching the calldata further down.
  /revert(?:ed)?[\s\S]{0,60}?(0x[0-9a-f]{8})/i,
  // What this repository's own records store: ContractCustomError: ('0x…', …)
  /ContractCustomError[\s\S]{0,40}?(0x[0-9a-f]{8})/i,
];

function fromMessage(message: string): string | undefined {
  for (const pattern of ANCHORED) {
    const found = message.match(pattern);
    if (found?.[1]) return found[1].toLowerCase();
  }
  // A message that is nothing but a selector is unambiguous.
  const bare = message.trim();
  return SELECTOR.test(bare) && bare.length === 10 ? bare.toLowerCase() : undefined;
}

export function selectorFrom(error: unknown): string | undefined {
  if (typeof error === "string") return fromMessage(error);

  // viem nests the cause chain; the payload hangs off whichever link knew it.
  const seen = new Set<unknown>();
  let node: unknown = error;
  while (node && typeof node === "object" && !seen.has(node)) {
    seen.add(node);
    const { data, raw } = node as { data?: unknown; raw?: unknown };
    for (const value of [data, raw]) {
      if (typeof value === "string" && /^0x[0-9a-f]{8}/i.test(value)) {
        return value.slice(0, 10).toLowerCase();
      }
    }
    node = (node as { cause?: unknown }).cause;
  }

  const message = (error as { message?: unknown } | null)?.message;
  return typeof message === "string" ? fromMessage(message) : undefined;
}

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

/**
 * Whether an expiry this many hours out can reach `submit`.
 *
 * Strictly greater, not >=: the 168h run was refused against a 604,800s window
 * and 169h was accepted, so the boundary is exclusive.
 */
export function clearsDisputeWindow(hours: number, windowSeconds: bigint): boolean {
  return hours * 3600 > Number(windowSeconds);
}

/**
 * The five arguments to `createJob`, and the two the EIP will lead you to get wrong.
 *
 * They were built inline in the console, and one of them was wrong for as long
 * as the console existed: the hook was passed as `address(0)`, which the EIP
 * describes as the natural way to say *no hook* and which this deployment
 * reverts — `0x55c45de1 HookRequired()`. `registry/hire.py:352` had defaulted it
 * to the router and refused to build the call otherwise since the day that
 * revert was isolated; the browser never learned. So `createJob` from this site
 * could not succeed, and the console decoded its own bug out of
 * `hire_flow.errors` and printed it as though the chain had surprised it.
 *
 * Both the evaluator and the hook are the EvaluatorRouter, and neither is a
 * choice: naming a wallet as evaluator reverts `RouterNotEvaluator()` two
 * transactions later, at `registerJob`.
 *
 * `expiredAt` is an absolute unix timestamp, not a duration — a past or zero
 * value reverts `0xf7a0748c`.
 */
export function createJobArgs(input: {
  provider: Address;
  router: Address;
  hours: number;
  description: string;
  nowMs: number;
}): readonly [Address, Address, bigint, string, Address] {
  const { provider, router, hours, description, nowMs } = input;
  return [
    provider,
    // evaluator
    router,
    BigInt(Math.floor(nowMs / 1000) + Math.floor(hours * 3600)),
    description,
    // hook
    router,
  ] as const;
}

/**
 * Where a visitor gets the token the kernel settles in.
 *
 * ## The wall this exists to put a door in
 *
 * The kernel does not take BNB. It takes one ERC-20, chosen by whoever deployed
 * it, and `fund` reverts without it. So a judge arriving with a funded wallet
 * hit a greyed button reading *"this wallet does not hold that much of the
 * payment token"* — accurate, and a dead end: no faucet, no link, no address to
 * copy, nothing anywhere on the site saying what to do next. The one place this
 * repository recorded that the token is *buyable* was a TypeScript docstring the
 * browser never renders.
 *
 * It is buyable, and cheaply: `registry.json` records the swap that proved it —
 * 0.2058 of the token for 0.0003 BNB, and job 56681 was escrowed with what it
 * bought.
 *
 * ## Mainnet only, and that is the honest direction
 *
 * Chapel's payment token is the same contract shape with no market behind it:
 * owner-minted, no faucet among its selectors, and no pool to buy from. Sending
 * someone to a testnet to avoid spending twenty cents would send them somewhere
 * strictly harder, so this returns null there and the caller says so.
 */
export function paymentTokenMarket(
  deployment: EscrowDeployment | undefined,
): { url: string; token: string } | null {
  if (!deployment || deployment.chain_id !== 56) return null;
  return {
    token: deployment.erc20,
    url: `https://pancakeswap.finance/swap?chain=bsc&outputCurrency=${deployment.erc20}`,
  };
}
