/**
 * What hiring an agent costs, on the card where the choice is made.
 *
 * ## Why there was no price
 *
 * There was none to state. This marketplace does not quote per agent — the
 * buyer sets the escrow budget, and the hire form seeds it from whatever job
 * 56681 happened to escrow on mainnet. Four cards each showing a different
 * invented figure would be the misquote this project is named after, aimed at
 * its own storefront.
 *
 * So this states the arrangement instead, which is the true answer and is the
 * same on every card: **you set the escrow, and there is a fixed fee on top.**
 * A reader learns what they will be asked for and where each number comes from,
 * which is more than a number would have told them.
 *
 * Both figures are read, neither typed: the opening budget from
 * `registry.json`'s recorded mainnet hire, the fee from the advantage report's
 * `hire_cost`, which is the keystore's own `getRegistrationFeeInWei()` plus the
 * measured gas of a grant and a revoke.
 */

import Link from "next/link";
import { fixed, isNum } from "@/lib/format";

export interface HireTerms {
  /** The escrow the hire form opens on, in the payment token's smallest unit. */
  opening_budget?: number | null;
  /** Decimals of the payment token, so the budget can be shown as an amount. */
  budget_decimals?: number | null;
  /** The keystore fee plus grant/revoke gas, in BNB. */
  fee_bnb?: number | null;
}

/** The budget as a token amount. Integer division on a bigint, no float drift. */
function asAmount(smallest: number, decimals: number): string {
  const whole = BigInt(Math.round(smallest)) / 10n ** BigInt(decimals);
  const rest = BigInt(Math.round(smallest)) % 10n ** BigInt(decimals);
  if (rest === 0n) return whole.toString();
  const frac = rest.toString().padStart(decimals, "0").replace(/0+$/, "");
  return `${whole}.${frac}`;
}

export function HirePrice({ terms }: { terms?: HireTerms }) {
  if (!terms || (!isNum(terms.opening_budget) && !isNum(terms.fee_bnb))) return null;

  return (
    <p className="mt-3 mb-0 text-xs text-faint">
      <span className="text-dim">To hire: </span>
      {isNum(terms.opening_budget) && isNum(terms.budget_decimals) && (
        <>
          an escrow you set, opening at{" "}
          <span className="tabular font-mono text-ink">
            {asAmount(terms.opening_budget, terms.budget_decimals)}
          </span>{" "}
          of the payment token
        </>
      )}
      {isNum(terms.opening_budget) && isNum(terms.fee_bnb) && " · "}
      {isNum(terms.fee_bnb) && (
        <>
          <span className="tabular font-mono text-ink">{fixed(terms.fee_bnb, 6)} BNB</span> in
          key and gas fees
        </>
      )}
      . <Link href="/activate/">What that pays for →</Link>
    </p>
  );
}
