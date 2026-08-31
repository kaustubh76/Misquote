/**
 * The session-key deployment, callable from the browser.
 *
 * This is a transcription of `packages/misquote/sessions/calls.py`, not a
 * redesign. That module read the deployed ABI and recorded two things no
 * reading of the ERC-8183 caps subset would have predicted, and both of them
 * are load-bearing here:
 *
 *   1. **`registerKey` is on the keyStoreController; `revokeKey` is on the
 *      keyStore.** A grant and its revoke go to *different addresses*.
 *   2. **`keyId = keccak256(publicKey)`.** It is derived, never chosen. A
 *      caller that invents an id registers a key it cannot find again, because
 *      `getKeys` returns ids and `getPublicKey` is keyed by them.
 *
 * ## What this actually enforces, said once and said here
 *
 * `registerKey` takes `validator` and `metadata`, and the allowlist and spend
 * cap live in those — not in any argument this file encodes. Every grant
 * observed on both deployments carries `validator = 0x0` and empty metadata,
 * which means **expiry is the only cap the chain enforces**. The UI must say
 * so at the point of signing rather than implying four caps it cannot deliver.
 * `capsEnforced()` exists so that claim is computed from the address being
 * sent, not from a comment.
 *
 * Addresses are the surveyed ones from `vetting/addresses/session-keys-{56,97}.json`,
 * both `PASS` on every check, with byte counts recorded against the code at
 * those addresses.
 */
import { keccak256, encodeAbiParameters, parseAbiParameters, type Address, type Hex } from "viem";

/** `uint40` is the expiry's width on chain — see the Python's note on why this matters. */
export const MAX_EXPIRY = 2n ** 40n - 1n;

/** The zero address, meaning "no permission validator module". */
export const NO_VALIDATOR: Address = "0x0000000000000000000000000000000000000000";

export interface Deployment {
  chainId: number;
  name: string;
  keyStore: Address;
  keyStoreController: Address;
  explorer: string;
}

/**
 * Only the two chains this repository has actually surveyed.
 *
 * A map rather than a fallback: a connected wallet on chain 1 must produce
 * "there is no deployment here", not a call to an address that means something
 * else entirely on that chain.
 */
export const DEPLOYMENTS: Record<number, Deployment> = {
  56: {
    chainId: 56,
    name: "BNB Smart Chain",
    keyStore: "0x6572427ED530BadcF7375Cf9A4709D8d2b0E7E0a",
    keyStoreController: "0x0834Ee2C9BdC3E3efF0a2dC34393D4B0e546A555",
    explorer: "https://bscscan.com",
  },
  97: {
    chainId: 97,
    name: "BNB Smart Chain Testnet",
    keyStore: "0x6b8361C29d05D498b1a12B54A37310f94171E94A",
    keyStoreController: "0xb530D1971f5453F3359518343F05D0AedFfF7e12",
    explorer: "https://testnet.bscscan.com",
  },
};

export function deploymentFor(chainId: number | undefined): Deployment | null {
  if (chainId === undefined) return null;
  return DEPLOYMENTS[chainId] ?? null;
}

export const KEYSTORE_ABI = [
  {
    name: "getKeys",
    type: "function",
    stateMutability: "view",
    inputs: [{ name: "user", type: "address" }],
    outputs: [{ type: "bytes32[]" }],
  },
  {
    name: "isValidKey",
    type: "function",
    stateMutability: "view",
    inputs: [
      { name: "user", type: "address" },
      { name: "keyId", type: "bytes32" },
    ],
    outputs: [{ type: "bool" }],
  },
  {
    name: "getExpiry",
    type: "function",
    stateMutability: "view",
    inputs: [
      { name: "user", type: "address" },
      { name: "keyId", type: "bytes32" },
    ],
    outputs: [{ type: "uint40" }],
  },
  {
    name: "getValidator",
    type: "function",
    stateMutability: "view",
    inputs: [
      { name: "user", type: "address" },
      { name: "keyId", type: "bytes32" },
    ],
    outputs: [{ type: "address" }],
  },
  {
    name: "revokeKey",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [
      { name: "user", type: "address" },
      { name: "keyId", type: "bytes32" },
    ],
    outputs: [],
  },
] as const;

export const CONTROLLER_ABI = [
  {
    name: "getRegistrationFeeInWei",
    type: "function",
    stateMutability: "view",
    inputs: [],
    outputs: [{ type: "uint256" }],
  },
  {
    name: "registerKey",
    type: "function",
    stateMutability: "payable",
    inputs: [
      { name: "keyId", type: "bytes32" },
      { name: "validator", type: "address" },
      { name: "metadata", type: "bytes" },
      { name: "publicKey", type: "bytes" },
      { name: "expiry", type: "uint40" },
    ],
    outputs: [],
  },
] as const;

/**
 * `keccak256(publicKey)` — how the SDK derives a key's id.
 *
 * Derived, never chosen. See the module note.
 */
export function keyId(publicKey: Hex): Hex {
  return keccak256(publicKey);
}

/**
 * Whether a grant's caps are enforced by the chain, computed from the validator.
 *
 * The answer is currently `false` on every grant either deployment has seen,
 * and the UI is required to say so. Computed rather than asserted so that if a
 * verified validator module ever ships, the claim changes on its own.
 */
export function capsEnforced(validator: Address): boolean {
  return validator.toLowerCase() !== NO_VALIDATOR.toLowerCase();
}

/**
 * Reject an expiry that does not fit `uint40`, before it reaches a wallet.
 *
 * The Python refuses here for a reason worth repeating: an expiry that wraps is
 * a grant that never dies, and expiry is the *only* cap the chain enforces. A
 * silent wrap would turn the one real guarantee into the one unbounded one.
 */
export function checkExpiry(expiry: bigint): void {
  if (expiry <= 0n || expiry > MAX_EXPIRY) {
    throw new Error(
      `expiry ${expiry} does not fit uint40. A grant whose expiry wraps is a ` +
        `grant that never dies, which is the one cap whose failure mode is unbounded.`,
    );
  }
}

/**
 * The calldata `registerKey` will receive, for asserting against the Python.
 *
 * Not used to send — `useWriteContract` encodes from the ABI. It exists so a
 * test can compare this encoder against `sessions/calls.py::grant_call` and
 * against the recorded chapel transactions, which are known-good.
 */
export function grantArgs(params: {
  publicKey: Hex;
  expiry: bigint;
  validator?: Address;
  metadata?: Hex;
}): readonly [Hex, Address, Hex, Hex, number] {
  checkExpiry(params.expiry);
  // `uint40` is under 48 bits, so viem represents it as a `number` rather than
  // a bigint, and the ABI types follow. The conversion is lossless — 2**40-1 is
  // ~1.1e12 against a safe-integer ceiling of ~9.0e15 — and `checkExpiry` above
  // has already refused anything that would not fit.
  return [
    keyId(params.publicKey),
    params.validator ?? NO_VALIDATOR,
    params.metadata ?? "0x",
    params.publicKey,
    Number(params.expiry),
  ] as const;
}

/** The ABI-encoded tail of a `registerKey` call, for the calldata parity test. */
export function encodeGrantParams(params: {
  publicKey: Hex;
  expiry: bigint;
  validator?: Address;
  metadata?: Hex;
}): Hex {
  const [kid, validator, metadata, publicKey, expiry] = grantArgs(params);
  return encodeAbiParameters(
    parseAbiParameters("bytes32, address, bytes, bytes, uint40"),
    [kid, validator, metadata, publicKey, expiry],
  );
}

/** A short `0x1234…abcd` for display. Never used to build a call. */
export function shortHex(value: string, lead = 6, tail = 4): string {
  if (value.length <= lead + tail + 2) return value;
  return `${value.slice(0, lead)}…${value.slice(-tail)}`;
}
