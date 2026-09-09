import { formatEther, formatUnits } from "viem";
import { Pill } from "@/components/Pill";
import { shortAddress } from "@/lib/format";

/**
 * The money going back, and the arithmetic that proves it did.
 *
 * ## What this block withheld
 *
 * `refund_proof` is the only record in `hire_flow` about money **returning**,
 * and it was the only one whose parties and figures reached no view.
 * `registry_report.py` publishes `client`, `budget`, `gas_spent_wei` and —
 * uniquely on this block — `balance_before` and `balance_after`; all six were
 * declared `""` in `tests/web/test_artifact_contract.py`. Its four sibling
 * proof blocks have rendered the same fields through `HireParties.tsx` since
 * that component existed.
 *
 * The page showed `refunded: true`, a job id and a status transition. The
 * numbers behind the claim were one level down in the same file:
 *
 *     balance_before  105790336763253403
 *     balance_after   205790336763253403
 *     budget          100000000000000000
 *
 * `balance_after - balance_before == budget`, exactly. An escrow returning
 * every wei it took is the safety property a marketplace is judged on, and it
 * was computed, published, and shown to nobody.
 *
 * The two balances arrive as **text**. As JSON numbers they were the only
 * values in any artifact a browser silently changed - `...403` parsed as
 * `...408` - so the first version of this component printed figures that were
 * not in the file it tells the reader to check. Both rounded the same way,
 * which is the only reason the verdict below stayed correct while the numbers
 * beside it were wrong.
 *
 * ## Why the verdict is arithmetic and not the flag
 *
 * The record also carries `refunded: true`. This ignores it, for the reason
 * `partiesDiffer` gives in `lib/escrow.ts`: the numbers are the fact and the
 * flag is a claim about them. `refunded: true` printed beside a delta that did
 * not match the budget would be this project's own name applied to its own
 * escrow — and a reader could not have caught it, because the delta was not on
 * the page to check.
 *
 * So the pill is computed here. It reads "returned in full" only when three
 * integers agree, and says what it found when they do not.
 *
 * A separate component from `HireParties` rather than a mode of it: a refund
 * has one party and no `success_criterion`, so the "paid by → delivered by"
 * frame has nothing to put on either side.
 */
export interface RefundTrailProof {
  client?: string | null;
  budget?: number | null;
  /** Text, not a number: a uint256 this large changes value as a double. */
  balance_before?: string | null;
  /** Text, not a number: a uint256 this large changes value as a double. */
  balance_after?: string | null;
  gas_spent_wei?: number | null;
}

function Figure({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <span className="flex flex-col gap-0.5">
      <span className="text-faint">{label}</span>
      <span className="tabular font-mono text-ink">{value}</span>
    </span>
  );
}

export function RefundTrail({
  proof,
  explorer,
  decimals,
  symbol = "token",
}: {
  proof: RefundTrailProof;
  /** The refund's own chain explorer, from `hire_flow.deployments[chain]`. */
  explorer?: string;
  /** From `hire_flow.deployments[chain].decimals`, read and never assumed. */
  decimals?: number;
  symbol?: string;
}) {
  const { balance_before: before, balance_after: after, budget } = proof;

  const measurable =
    typeof before === "string" && typeof after === "string" && typeof budget === "number";
  const delta = measurable ? BigInt(after) - BigInt(before) : null;
  const whole = delta !== null && delta === BigInt(budget as number);

  // Nothing to draw rather than a frame of "not recorded": a rehearsal that
  // recorded no balances has nothing this block can say.
  if (!proof.client && !measurable) return null;

  // Units are the artifact's to state. Without them the integers are still
  // exact and still comparable, so the claim survives; only the pretty amount
  // is withheld. BSC's USDT is 18 decimals where Ethereum's is 6, and guessing
  // misprices by twelve orders of magnitude.
  const amount = (v: string | number) =>
    decimals === undefined ? `${v} (raw)` : `${formatUnits(BigInt(v), decimals)} ${symbol}`;

  return (
    <div className="mt-4 border-t border-line pt-4">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3 text-xs">
        <span className="flex flex-col gap-0.5">
          <span className="text-faint">Returned to</span>
          {proof.client ? (
            explorer ? (
              <a
                className="font-mono text-ink underline decoration-line underline-offset-2"
                href={`${explorer}/address/${proof.client}`}
                target="_blank"
                rel="noreferrer"
              >
                {shortAddress(proof.client)}
              </a>
            ) : (
              <span className="font-mono text-ink">{shortAddress(proof.client)}</span>
            )
          ) : (
            <span className="font-mono text-faint">not recorded</span>
          )}
        </span>

        {measurable && (
          <>
            <Figure label="Balance before" value={amount(before)} />
            <span aria-hidden="true" className="pb-0.5 text-faint">
              →
            </span>
            <Figure label="Balance after" value={amount(after)} />
            <Figure label="Escrowed" value={amount(budget)} />
            {whole ? (
              <Pill tone="pass">returned in full</Pill>
            ) : (
              <Pill tone="fail">
                returned {delta!.toString()} of {budget} wei
              </Pill>
            )}
          </>
        )}

        {/*
          BNB is named rather than read, unlike `decimals` and `explorer` two
          lines up, because `hire_flow.deployments` carries no gas symbol —
          both chains it describes (56 and 97) are BNB Smart Chain, so there is
          nothing here to disagree with. The day this block renders a refund on
          a third chain, the emitter grows the field and this reads it.
        */}
        {typeof proof.gas_spent_wei === "number" && (
          <Figure label="Gas" value={`${formatEther(BigInt(proof.gas_spent_wei))} BNB`} />
        )}
      </div>

      {measurable && (
        <p className="mt-3 mb-0 max-w-[70ch] text-xs text-dim">
          <strong className="text-ink">The arithmetic.</strong> Balance after minus
          balance before is {delta!.toString()} wei, against an escrowed budget of{" "}
          {budget} wei
          {whole
            ? " — the same number. Every wei the escrow took came back."
            : " — which do not match, and the record's own `refunded` flag says otherwise."}
        </p>
      )}
    </div>
  );
}
