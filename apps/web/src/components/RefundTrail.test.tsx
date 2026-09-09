import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { RefundTrail, type RefundTrailProof } from "@/components/RefundTrail";
import { readArtifact, readArtifactText } from "@/test/harness";

/**
 * The refund block, over the artifact the page actually reads.
 *
 * `refund_proof` is the only record in `hire_flow` about money coming back, and
 * it published `client`, `budget`, `gas_spent_wei`, `balance_before` and
 * `balance_after` to no view at all while its four siblings rendered the same
 * fields. Asserted against the real payload rather than a fixture, for the
 * reason `HireParties.test.tsx` gives: the defect was in the join between
 * emitter and view, and a fixture would have shared the view's assumptions.
 */

interface Registry {
  hire_flow: {
    deployments?: Record<string, { explorer: string; decimals: number }>;
    refund_proof?: RefundTrailProof & { ran?: boolean; chain_id?: number };
  };
}

const flow = readArtifact<Registry>("registry.json").hire_flow;
const refund = flow.refund_proof;

/** The chain's row, or undefined — `noUncheckedIndexedAccess` is on. */
function deploymentFor(proof: typeof refund) {
  if (!proof?.ran) return undefined;
  return flow.deployments?.[String(proof.chain_id)];
}

afterEach(cleanup);

describe("the refund, as a reader sees it", () => {
  it("carries a chain its units and explorer can be looked up from", () => {
    // The gap that forced the view to type `https://bscscan.com` as a literal:
    // every sibling proof block has published `chain_id` since it existed and
    // this one never did, so `chainMeta()` had nothing to resolve.
    if (!refund?.ran) return;
    expect(refund.chain_id).toBeTypeOf("number");
    expect(flow.deployments?.[String(refund.chain_id)]?.decimals).toBeTypeOf("number");
  });

  it("shows the balance move and calls it returned in full", () => {
    if (!refund?.ran) return;
    const dep = deploymentFor(refund);
    if (!dep) return;
    render(<RefundTrail proof={refund} decimals={dep.decimals} explorer={dep.explorer} />);

    // The claim is the arithmetic, so the arithmetic is what is asserted —
    // not that a pill with agreeable words rendered.
    const delta = BigInt(refund.balance_after!) - BigInt(refund.balance_before!);
    expect(delta).toBe(BigInt(refund.budget!));
    expect(screen.getByText("returned in full")).toBeInTheDocument();
    // Exact strings, not regexes: a regex also matches the wrapper whose text
    // content is the label plus its value, and `getByText` refuses two hits.
    expect(screen.getByText("Balance before")).toBeInTheDocument();
    expect(screen.getByText("Balance after")).toBeInTheDocument();
    // The sentence is assembled from several JSX nodes, so it belongs to the
    // paragraph rather than to any one element `getByText` can match.
    expect(screen.getByText(/The arithmetic\./).closest("p")?.textContent).toContain(
      "Every wei the escrow took came back"
    );
  });

  it("links the refunded party to the explorer the artifact names", () => {
    if (!refund?.ran || !refund.client) return;
    const dep = deploymentFor(refund);
    if (!dep) return;
    render(<RefundTrail proof={refund} decimals={dep.decimals} explorer={dep.explorer} />);
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      `${dep.explorer}/address/${refund.client}`
    );
  });

  it("refuses the verdict when the numbers disagree, whatever the flag says", () => {
    // The failure this exists to make visible. `refunded: true` beside a delta
    // that does not match the budget is the misquote this project is named
    // after, applied to its own escrow — so the pill is computed from the three
    // integers and never read off the record.
    render(
      <RefundTrail
        proof={{
          client: "0x" + "11".repeat(20),
          budget: 100,
          balance_before: "0",
          balance_after: "60",
        }}
        decimals={0}
      />
    );
    expect(screen.queryByText("returned in full")).not.toBeInTheDocument();
    expect(screen.getByText(/returned 60 of 100 wei/)).toBeInTheDocument();
    expect(screen.getByText(/do not match/)).toBeInTheDocument();
  });

  it("prints the balances the artifact file actually contains", () => {
    // The bug this pair of fields was born with. As JSON numbers they were the
    // only values in any artifact that changed on the way into a browser —
    // 105790336763253403 parsed as 105790336763253408 — so the block whose
    // argument is "check my arithmetic against the file" printed two numbers
    // the file does not contain. Both rounded by +5, so the delta stayed exact
    // and every assertion above still passed.
    //
    // Asserted against the raw bytes rather than the parsed object, because a
    // parsed object has already lost the thing under test.
    if (!refund?.ran) return;
    const raw = readArtifactText("registry.json");
    for (const value of [refund.balance_before, refund.balance_after]) {
      expect(typeof value).toBe("string");
      expect(raw).toContain(`"${value}"`);
      expect(BigInt(value!).toString()).toBe(value);
    }
  });

  it("still states the exact integers when the artifact names no decimals", () => {
    // Units are the artifact's to state. Without them the amounts are shown raw
    // rather than guessed — BSC's USDT is 18 decimals where Ethereum's is 6.
    render(
      <RefundTrail proof={{ budget: 100, balance_before: "0", balance_after: "100" }} />
    );
    expect(screen.getByText("returned in full")).toBeInTheDocument();
    expect(screen.getAllByText(/\(raw\)/).length).toBeGreaterThan(0);
  });
});
