import { describe, expect, it } from "vitest";
import { readArtifact } from "@/test/harness";
import {
  countdown,
  decodeJob,
  encodeGetJob,
  secondsUntil,
  selectorFrom,
  JOB_WORD,
} from "@/lib/escrow";
import type { Hex } from "viem";

/**
 * The browser's job decoder, held against the reading Python already published.
 *
 * `registry/hire.py::read_job` returns words and names only the offsets it has
 * confirmed, because the struct's field order was recovered from readings and
 * not from an interface. `lib/escrow.ts` repeats those offsets in TypeScript,
 * and a second copy of an unverified layout is exactly the kind of thing that
 * drifts silently — so it is checked against `mainnet_proof.job_words`, which
 * is the actual answer chain 56 gave for the actual funded job.
 */

interface Registry {
  hire_flow: {
    mainnet_proof: {
      job_id: number;
      client: string;
      provider: string;
      evaluator: string;
      budget: number;
      job_words: string[];
    };
    refund_proof: {
      expires_at: number;
      status_before: number;
    };
  };
}

const flow = readArtifact<Registry>("registry.json").hire_flow;
const mainnet = flow.mainnet_proof;
const refund = flow.refund_proof;
const raw = `0x${mainnet.job_words.map((w) => w.slice(2)).join("")}` as Hex;

describe("the job words mainnet actually returned", () => {
  it("decodes to the same job the Python record describes", () => {
    const job = decodeJob(raw, BigInt(mainnet.job_id));
    expect(job).not.toBeNull();
    expect(job!.exists).toBe(true);
    expect(job!.id).toBe(BigInt(mainnet.job_id));
    expect(job!.client.toLowerCase()).toBe(mainnet.client.toLowerCase());
    expect(job!.provider.toLowerCase()).toBe(mainnet.provider.toLowerCase());
    expect(job!.evaluator.toLowerCase()).toBe(mainnet.evaluator.toLowerCase());
    expect(job!.budget).toBe(BigInt(mainnet.budget));
  });

  it("says a job does not exist when the id does not echo back", () => {
    // The mistake this guards: ABI head offsets are non-zero on every return,
    // so "the answer is non-empty" said `true` for an id that never existed.
    const job = decodeJob(raw, 10n ** 9n);
    expect(job!.exists).toBe(false);
  });

  it("refuses an answer too short to carry the offsets it reads", () => {
    expect(decodeJob("0x" as Hex, 1n)).toBeNull();
    expect(decodeJob(`0x${"00".repeat(32)}` as Hex, 1n)).toBeNull();
  });

  it("reads the expiry the refund waited on, to the second", () => {
    // Offsets 7 and 8 were the two this file named and nothing else did —
    // `expiredAt` had only `> 0` on it and `status` was never asserted at all.
    // The refund record is an independent read of the same job: `claim_refund.py`
    // decoded it with Python's own offsets before deciding whether the window
    // was open. If the two sides ever disagree about which word is which, both
    // still return plausible integers and neither raises.
    const job = decodeJob(raw, BigInt(mainnet.job_id))!;
    expect(Number(job.expiredAt)).toBe(refund.expires_at);
    expect(job.status).toBe(refund.status_before);
  });

  it("counts down to that expiry rather than past it", () => {
    const job = decodeJob(raw, BigInt(mainnet.job_id))!;
    expect(secondsUntil(job.expiredAt, Number(job.expiredAt) * 1000)).toBe(0);
    expect(secondsUntil(job.expiredAt, (Number(job.expiredAt) - 3600) * 1000)).toBe(3600);
    // Past the expiry it floors rather than going negative, which is what makes
    // the refund button enable instead of showing a negative countdown.
    expect(secondsUntil(job.expiredAt, (Number(job.expiredAt) + 99) * 1000)).toBe(0);
  });
});

describe("encodeGetJob", () => {
  it("pads the id to a full word", () => {
    expect(encodeGetJob(56681n)).toBe(
      `0xbf22c457${(56681).toString(16).padStart(64, "0")}`,
    );
    expect(encodeGetJob(56681n)).toHaveLength(10 + 64);
  });
});

describe("the offsets themselves", () => {
  it("keeps word 0 out, because it is the ABI head and not a field", () => {
    expect(Object.values(JOB_WORD)).not.toContain(0);
  });
});

describe("countdown", () => {
  it("says now rather than a negative", () => {
    expect(countdown(0)).toBe("now");
    expect(countdown(-5)).toBe("now");
  });

  it("drops seconds once there are hours", () => {
    expect(countdown(3600 + 120)).toBe("1h 2m");
    expect(countdown(125)).toBe("2m 5s");
    expect(countdown(9)).toBe("9s");
  });
});

describe("selectorFrom", () => {
  const WRONG_STATUS = "0x8e78f0cb";
  /** `submit(uint256,bytes32,bytes)` — the selector of the call, not of a revert. */
  const SUBMIT = "0x9e63798d";

  it("reads viem's ABI-encoded revert payload", () => {
    // The first bug: the old pattern required a word boundary after eight hex
    // digits, and this format continues with `0`.
    const message = `The contract function "submit" reverted.\n\nError: reverted with data ${WRONG_STATUS}${"00".repeat(32)}`;
    expect(selectorFrom(message)).toBe(WRONG_STATUS);
  });

  it("reads the signature line viem prints for an unknown custom error", () => {
    expect(
      selectorFrom(
        'The contract function "settle" reverted with the following signature:\n0x17be5b7b\n\nUnable to decode signature',
      ),
    ).toBe("0x17be5b7b");
  });

  it("reads the form this repository's own records store", () => {
    expect(
      selectorFrom(`ContractCustomError: ('${WRONG_STATUS}', '${WRONG_STATUS}')`),
    ).toBe(WRONG_STATUS);
  });

  it("takes the payload off the error object before reading any prose", () => {
    const error = Object.assign(new Error("execution reverted"), {
      cause: { data: `${WRONG_STATUS}${"00".repeat(32)}` },
    });
    expect(selectorFrom(error)).toBe(WRONG_STATUS);
  });

  it("does not offer the function's own selector as the reason it failed", () => {
    // The second bug, and the worse one. A write that never reached the chain
    // produced `0x9e63798d — unresolved in this repository`: the selector of
    // `submit`, scraped out of the calldata, presented as the refusal. A
    // missing answer is recoverable; a confident wrong one is not.
    const message = `HTTP request failed.\n\nURL: https://bsc-dataseed.bnbchain.org\nRequest body: {"method":"eth_sendTransaction","params":[{"data":"${SUBMIT}${"00".repeat(64)}"}]}`;
    expect(selectorFrom(message)).toBeUndefined();
  });

  it("says nothing when there is nothing to say", () => {
    expect(selectorFrom(undefined)).toBeUndefined();
    expect(selectorFrom(null)).toBeUndefined();
    expect(selectorFrom("User rejected the request.")).toBeUndefined();
    expect(selectorFrom({})).toBeUndefined();
  });

  it("lowercases, because the artifact keys it looks up are lowercase", () => {
    expect(selectorFrom("reverted with data 0x8E78F0CB")).toBe(WRONG_STATUS);
  });

  it("accepts a message that is only a selector", () => {
    expect(selectorFrom(`  ${WRONG_STATUS} `)).toBe(WRONG_STATUS);
  });
});
