import { describe, expect, it } from "vitest";
import { readArtifact } from "@/test/harness";
import { countdown, decodeJob, encodeGetJob, secondsUntil, JOB_WORD } from "@/lib/escrow";
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
  };
}

const mainnet = readArtifact<Registry>("registry.json").hire_flow.mainnet_proof;
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

  it("reads the expiry the refund is waiting on", () => {
    const job = decodeJob(raw, BigInt(mainnet.job_id))!;
    expect(job.expiredAt).toBeGreaterThan(0n);
    // Twelve hours after creation, which is what the run asked for.
    expect(secondsUntil(job.expiredAt, Number(job.expiredAt) * 1000)).toBe(0);
    expect(secondsUntil(job.expiredAt, (Number(job.expiredAt) - 3600) * 1000)).toBe(3600);
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
