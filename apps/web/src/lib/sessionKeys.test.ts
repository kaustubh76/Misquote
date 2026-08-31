import { describe, expect, it } from "vitest";
import { toFunctionSelector } from "viem";
import {
  MAX_EXPIRY,
  NO_VALIDATOR,
  capsEnforced,
  checkExpiry,
  deploymentFor,
  encodeGrantParams,
  grantArgs,
  keyId,
} from "@/lib/sessionKeys";

/**
 * The browser's encoder, checked against a transaction that is already mined.
 *
 * `lib/sessionKeys.ts` is a transcription of `packages/misquote/sessions/calls.py`,
 * and a transcription is exactly the kind of change that typechecks perfectly
 * and encodes the wrong thing — a swapped argument order, a `bytes32` where a
 * `bytes` belongs, an expiry silently narrowed. None of those would fail a
 * build, and all of them would fail at someone's wallet.
 *
 * So the fixture is not hand-written and is not this file's own output. Every
 * value below was read off **chapel transaction
 * `0x8eb79bf6ce1514196a4aa965859294e3c25d3938654b868321eab2fb821da7f8`**, the
 * `registerKey` that granted the session key the `/activate` proofs are built
 * on, via `eth_getTransactionByHash`. It succeeded on chain, which is the
 * strongest statement available about whether its calldata was correct.
 *
 * Its recorded shape agrees with `vetting/identity/session-keys-97.json` on
 * every field they share: `session_key_id`, `expiry_ts`, and
 * `registration_fee_wei` as the transaction's value.
 */
const MINED = {
  to: "0xb530d1971f5453f3359518343f05d0aedfff7e12",
  valueWei: 725_716_783_448_241n,
  keyId: "0xcfd64839e7931bd16a4fed20ddd97a7a2d2dd4765bcbe19b50966be8883b91e9",
  expiry: 1_787_988_930n,
  publicKey:
    "0x04bde08f7b84e0949890a67e4545319f08c996e4843439cf514db1ff9295fda769ce0c773c9475013b1a76c4ceade8d5dd10bc89cfa439d64c6670d39501615b5b",
  input:
    "0x" +
    "c08eadaacfd64839e7931bd16a4fed20ddd97a7a2d2dd4765bcbe19b50966be8" +
    "883b91e900000000000000000000000000000000000000000000000000000000" +
    "0000000000000000000000000000000000000000000000000000000000000000" +
    "000000a000000000000000000000000000000000000000000000000000000000" +
    "000000c000000000000000000000000000000000000000000000000000000000" +
    "6a928bc200000000000000000000000000000000000000000000000000000000" +
    "0000000000000000000000000000000000000000000000000000000000000000" +
    "0000004104bde08f7b84e0949890a67e4545319f08c996e4843439cf514db1ff" +
    "9295fda769ce0c773c9475013b1a76c4ceade8d5dd10bc89cfa439d64c6670d3" +
    "9501615b5b000000000000000000000000000000000000000000000000000000" +
    "00000000",
} as const;

describe("the grant encoder agrees with a transaction that is already mined", () => {
  it("derives the key id the chain recorded", () => {
    // `keccak256(publicKey)`, never a chosen id. If this drifts, a granted key
    // becomes unfindable: `getKeys` returns ids and `getPublicKey` is keyed by
    // them.
    expect(keyId(MINED.publicKey)).toBe(MINED.keyId);
  });

  it("uses the selector the mined call used", () => {
    const selector = toFunctionSelector(
      "registerKey(bytes32,address,bytes,bytes,uint40)",
    );
    expect(MINED.input.slice(0, 10)).toBe(selector);
  });

  it("encodes the same arguments, in the same order", () => {
    const encoded = encodeGrantParams({
      publicKey: MINED.publicKey,
      expiry: MINED.expiry,
    });
    // The mined input minus its 4-byte selector. Compared lowercased because
    // the RPC returns lowercase hex and viem does not.
    const minedParams = `0x${MINED.input.slice(10)}`.toLowerCase();
    expect(encoded.toLowerCase()).toBe(minedParams);
  });

  it("sends to the controller, which is not the keystore", () => {
    // The correction that reading the ABI produced, and the one a demo built
    // from the published plan alone would have discovered at transaction time.
    const chapel = deploymentFor(97);
    expect(chapel?.keyStoreController.toLowerCase()).toBe(MINED.to);
    expect(chapel?.keyStore.toLowerCase()).not.toBe(MINED.to);
  });

  it("grants with no validator, which is why the caps are not enforced", () => {
    const [, validator, metadata] = grantArgs({
      publicKey: MINED.publicKey,
      expiry: MINED.expiry,
    });
    expect(validator).toBe(NO_VALIDATOR);
    expect(metadata).toBe("0x");
    // The claim the UI is required to make beside the button.
    expect(capsEnforced(validator)).toBe(false);
  });
});

describe("the expiry is refused before a wallet ever sees it", () => {
  it("accepts the expiry the mined grant used", () => {
    expect(() => checkExpiry(MINED.expiry)).not.toThrow();
  });

  it("refuses one that does not fit uint40", () => {
    // Not a style check. Expiry is the only cap the chain enforces, so an
    // expiry that wraps converts the single real guarantee into an unbounded
    // one — which is why this refuses rather than truncating.
    expect(() => checkExpiry(MAX_EXPIRY + 1n)).toThrow(/never dies/);
  });

  it("refuses zero and negatives, which would read as no expiry at all", () => {
    expect(() => checkExpiry(0n)).toThrow(/uint40/);
    expect(() => checkExpiry(-1n)).toThrow(/uint40/);
  });
});

describe("only surveyed chains have a deployment", () => {
  it("answers for the two this repository checked", () => {
    expect(deploymentFor(56)?.keyStore).toMatch(/^0x[0-9a-fA-F]{40}$/);
    expect(deploymentFor(97)?.keyStore).toMatch(/^0x[0-9a-fA-F]{40}$/);
  });

  it("returns null elsewhere rather than reusing an address", () => {
    // An address means something different on every chain. A fallback here
    // would call *something* on Ethereum mainnet, and "0 keys" would be
    // indistinguishable from "wrong network".
    expect(deploymentFor(1)).toBeNull();
    expect(deploymentFor(undefined)).toBeNull();
  });
});
