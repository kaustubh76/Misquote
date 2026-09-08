import Link from "next/link";
import { formatEther, formatUnits } from "viem";
import { Pill } from "@/components/Pill";
import { Prose } from "@/components/Blocks";
import { partiesDiffer } from "@/lib/escrow";
import { shortAddress } from "@/lib/format";

/**
 * Who paid, who delivered, what it cost, and what would have counted as done.
 *
 * ## The four facts this page computed and never showed
 *
 * `registry_report.py` writes `client`, `provider`, `budget`, `gas_spent_wei`
 * and `success_criterion` on every proof block. All five were declared `""` in
 * `tests/web/test_artifact_contract.py` — emitted, rendered nowhere — for as
 * long as the contract has existed. Half of `hire_flow`'s 143 contracted fields
 * were in that state, on the page a marketplace is judged from.
 *
 * The two that matter most are the two addresses. A marketplace whose only
 * proven delivery is the buyer delivering to themselves is the misquote this
 * project is named after, applied to its own escrow — and a reader could not
 * have told, because the page showed `escrowed: true`, a job id and seven
 * transaction hashes, and neither party.
 *
 * `success_criterion` is the other half of the same omission. The rubric this
 * is built against says *hire an agent and evaluate the results*; the sentence
 * saying what would count as delivered was written for all four runs and shown
 * on none of them.
 *
 * ## Why the verdict is computed here rather than read
 *
 * `hire_mainnet.py` publishes a `two_party` boolean and this ignores it, for
 * the reason `partiesDiffer` gives at length: the fork record has had two
 * distinct parties since it was written and predates the flag, so a page
 * keying off the label would render this project's one genuine two-party
 * settlement as a self-hire. Addresses are the fact; the flag is a claim about
 * them, and `tests/registry/test_two_party_hire.py` is where a claim gets
 * checked against its fact.
 *
 * The consequence is that nothing here needs editing when the two-party mainnet
 * run lands. The verdict flips because the addresses do.
 */
export interface HireProofParties {
  client?: string | null;
  provider?: string | null;
  budget?: number | null;
  gas_spent_wei?: number | null;
  success_criterion?: string | null;
  /**
   * What `submit`'s 32 bytes commit to, when a run committed to anything.
   *
   * Null on both mainnet runs so far: they sent `keccak256("job-<id>")`, a hash
   * of the job's own id, which is a receipt for the transaction rather than a
   * commitment to work. `hire_mainnet.py --deliverable-file` hashes a published
   * file instead, and this renders the pair so a reader can fetch and re-hash.
   */
  deliverable?: {
    file?: string | null;
    bytes?: number | null;
    keccak256?: string | null;
    url?: string | null;
  } | null;
}

function Party({
  role,
  address,
  explorer,
}: {
  role: string;
  address?: string | null;
  explorer?: string;
}) {
  return (
    <span className="flex flex-col gap-0.5">
      <span className="text-faint">{role}</span>
      {address ? (
        explorer ? (
          <a
            className="font-mono text-ink underline decoration-line underline-offset-2"
            href={`${explorer}/address/${address}`}
            target="_blank"
            rel="noreferrer"
          >
            {shortAddress(address)}
          </a>
        ) : (
          <span className="font-mono text-ink">{shortAddress(address)}</span>
        )
      ) : (
        <span className="font-mono text-faint">not recorded</span>
      )}
    </span>
  );
}

export function HireParties({
  proof,
  explorer,
  decimals,
  submitted,
  symbol = "token",
}: {
  proof: HireProofParties;
  /**
   * Whether this run's `submit` actually mined, which decides whether there is
   * a commitment to say anything about at all.
   *
   * The first draft of this block printed "this run sent a hash of the job's
   * own id" under every proof, and it was true of exactly one of the four:
   * chapel never called `submit`, job 56681 called it and reverted
   * `SubmissionTooLate()`, and the fork sent `keccak256("deliverable")` — the
   * same placeholder this site's own console used to send. A sentence that is
   * true beside the record it was written for and false beside the other three
   * is the defect this repository keeps finding, so the claim is narrowed to
   * what each record can support.
   */
  submitted?: boolean;
  /** The proof's own chain explorer. A fork's addresses link nowhere. */
  explorer?: string;
  /** From `hire_flow.deployments[chain].decimals`, read and never assumed. */
  decimals?: number;
  symbol?: string;
}) {
  const differ = partiesDiffer(proof.client, proof.provider);
  const committed = proof.deliverable?.keccak256;

  // Nothing to draw rather than an empty frame: the chapel record names a
  // client and no provider, and a block that rendered "not recorded" twice
  // would be worse than the absence.
  if (!proof.client && !proof.provider && !proof.success_criterion) return null;

  return (
    <div className="mt-4 border-t border-line pt-4">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3 text-xs">
        <Party role="Paid by" address={proof.client} explorer={explorer} />
        <span aria-hidden="true" className="pb-0.5 text-faint">
          →
        </span>
        <Party role="Delivered by" address={proof.provider} explorer={explorer} />

        {differ === true && <Pill tone="pass">two parties</Pill>}
        {differ === false && <Pill tone="unverified">one wallet on both sides</Pill>}
        {differ === null && proof.client && <Pill tone="none">no provider recorded</Pill>}

        {typeof proof.budget === "number" && decimals !== undefined && (
          <span className="flex flex-col gap-0.5">
            <span className="text-faint">Escrowed</span>
            <span className="tabular font-mono text-ink">
              {formatUnits(BigInt(proof.budget), decimals)} {symbol}
            </span>
          </span>
        )}

        {typeof proof.gas_spent_wei === "number" && (
          <span className="flex flex-col gap-0.5">
            <span className="text-faint">Gas</span>
            <span className="tabular font-mono text-ink">
              {formatEther(BigInt(proof.gas_spent_wei))} BNB
            </span>
          </span>
        )}
      </div>

      {/* The half of "hire an agent and evaluate the results" that this page
          computed and did not print. */}
      {proof.success_criterion && (
        <p className="mt-3 mb-0 max-w-[70ch] text-xs text-dim">
          <strong className="text-ink">Done when.</strong>{" "}
          <Prose text={proof.success_criterion} />
        </p>
      )}

      {/* What the 32 bytes are. `hire.py` is blunt that nothing on chain
          interprets them, which is exactly why the record tying them to a
          fetchable file is worth printing — and why its absence is too. */}
      {committed ? (
        <p className="mt-3 mb-0 max-w-[70ch] text-xs text-dim">
          <strong className="text-ink">Committed to</strong>{" "}
          {proof.deliverable?.url ? (
            <a
              className="underline"
              href={proof.deliverable.url}
              target="_blank"
              rel="noreferrer"
            >
              {proof.deliverable?.file}
            </a>
          ) : (
            <span className="font-mono text-ink">{proof.deliverable?.file}</span>
          )}
          {typeof proof.deliverable?.bytes === "number" && (
            <> · {proof.deliverable.bytes.toLocaleString()} bytes</>
          )}
          <span className="mt-1 block font-mono break-all text-faint">{committed}</span>
          <span className="block">
            keccak256 of those bytes. Fetch the file and re-hash it; nothing here
            has to be trusted for that.
          </span>
        </p>
      ) : (
        submitted && (
          <p className="mt-3 mb-0 max-w-[70ch] text-xs text-faint">
            <span className="text-dim">No deliverable recorded.</span> This
            run&rsquo;s <span className="font-mono">submit</span> mined 32 bytes
            that commit to no published file, so there is nothing a reader can
            fetch and re-hash.{" "}
            <Link href="/activate/">The hire flow</Link> commits to the hired
            agent&rsquo;s published artifact instead.
          </p>
        )
      )}
    </div>
  );
}
