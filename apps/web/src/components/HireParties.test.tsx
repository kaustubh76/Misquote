import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { HireParties, type HireProofParties } from "@/components/HireParties";
import { readArtifact } from "@/test/harness";

/**
 * The block that says who was hired, over the artifact the page actually reads.
 *
 * `registry.json` published `client`, `provider`, `budget`, `gas_spent_wei` and
 * `success_criterion` on every proof and the page rendered none of them — a
 * marketplace showing `escrowed: true` and seven transaction hashes while
 * withholding both parties. These assert the fixed version against the real
 * payload rather than a fixture, because the defect was in the join between
 * emitter and view and a fixture would have shared the view's assumptions.
 */

interface Registry {
  hire_flow: {
    deployments?: Record<string, { explorer: string; decimals: number }>;
    proof?: HireProofParties & { chain_id?: number };
    fork_proof?: HireProofParties & { chain_id?: number };
    mainnet_proof?: HireProofParties & { chain_id?: number };
    submit_proof?: HireProofParties & { chain_id?: number };
  };
}

const registry = readArtifact<Registry>("registry.json");
const flow = registry.hire_flow;

afterEach(cleanup);

describe("the recorded mainnet runs, as a reader sees them", () => {
  it("names both parties and says they are one wallet", () => {
    const proof = flow.mainnet_proof!;
    render(<HireParties proof={proof} decimals={18} explorer="https://bscscan.com" />);

    // Not "does it render an address" — that the *same* address appears under
    // both roles is the fact, and the reason it is called out in words.
    expect(proof.client).toBeTruthy();
    expect(proof.client!.toLowerCase()).toBe(proof.provider!.toLowerCase());
    expect(screen.getByText("Paid by")).toBeInTheDocument();
    expect(screen.getByText("Delivered by")).toBeInTheDocument();
    expect(screen.getByText(/one wallet on both sides/)).toBeInTheDocument();
  });

  it("prints what would have counted as done", () => {
    const proof = flow.submit_proof!;
    const { container } = render(<HireParties proof={proof} decimals={18} />);
    expect(screen.getByText("Done when.")).toBeInTheDocument();
    // The emitter's own sentence, matched as a substring rather than a regex:
    // these criteria contain `submit()` and `settle()`, and the parentheses
    // are capture groups that match a different string than the one printed.
    expect(container.textContent).toContain(proof.success_criterion!);
  });

  it("says the 32 bytes committed to nothing, on the run that sent them", () => {
    const proof = flow.submit_proof!;
    expect(proof.deliverable?.keccak256 ?? null).toBeNull();
    render(<HireParties proof={proof} decimals={18} submitted />);
    expect(screen.getByText(/No deliverable recorded/)).toBeInTheDocument();
  });

  it("says nothing about a deliverable for a run that never submitted", () => {
    // Job 56681 called `submit` and reverted `SubmissionTooLate()`; chapel
    // never called it at all. The first version of this block printed "this
    // run sent a hash of the job's own id" under all four proofs, which was
    // true of exactly one of them — a sentence sitting beside three records it
    // does not describe.
    render(<HireParties proof={flow.mainnet_proof!} decimals={18} submitted={false} />);
    expect(screen.queryByText(/No deliverable recorded/)).not.toBeInTheDocument();
    // The rest of the block is still there; only the claim it cannot support
    // is gone.
    expect(screen.getByText("Paid by")).toBeInTheDocument();
  });
});

describe("the fork run, which is the positive case", () => {
  it("calls two distinct parties two parties", () => {
    const proof = flow.fork_proof!;
    expect(proof.client!.toLowerCase()).not.toBe(proof.provider!.toLowerCase());
    render(<HireParties proof={proof} decimals={18} />);
    expect(screen.getByText("two parties")).toBeInTheDocument();
  });

  it("links no address anywhere, because that chain is gone", () => {
    render(<HireParties proof={flow.fork_proof!} decimals={18} />);
    // Anvil accounts pointed at BscScan would resolve to unrelated mainnet
    // addresses — a live link is worse than no link here. Scoped to explorer
    // links: the block carries an in-site link too, and asserting "no links"
    // would pass for the wrong reason the day that one moves.
    const explorerLinks = screen
      .queryAllByRole("link")
      .filter((a) => (a.getAttribute("href") ?? "").includes("/address/"));
    expect(explorerLinks).toHaveLength(0);
  });

  it("does link them on a chain a reader can check", () => {
    render(
      <HireParties proof={flow.mainnet_proof!} decimals={18} explorer="https://bscscan.com" />
    );
    const [link] = screen
      .queryAllByRole("link")
      .filter((a) => (a.getAttribute("href") ?? "").includes("/address/"));
    expect(link).toHaveAttribute("href", `https://bscscan.com/address/${flow.mainnet_proof!.client}`);
  });
});

describe("what it refuses to claim", () => {
  it("does not guess a provider the record never named", () => {
    render(<HireParties proof={flow.proof!} />);
    expect(screen.getByText("no provider recorded")).toBeInTheDocument();
    expect(screen.queryByText(/one wallet on both sides/)).not.toBeInTheDocument();
    expect(screen.queryByText("two parties")).not.toBeInTheDocument();
  });

  it("omits the budget rather than assume decimals for it", () => {
    // `decimals` unset is the state while the deployment table is missing, and
    // 0.1 rendered as 100000000000000000 is the misprice this project refuses
    // to make elsewhere.
    const { container } = render(<HireParties proof={flow.mainnet_proof!} />);
    expect(container.textContent).not.toMatch(/Escrowed/);
  });

  it("renders nothing at all for a proof that never ran", () => {
    const empty: HireProofParties = {};
    const { container } = render(<HireParties proof={empty} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows a deliverable and its file when a run commits to one", () => {
    // No record carries this yet — `hire_mainnet.py --deliverable-file` writes
    // it. Asserted now so the path is exercised before the run that needs it,
    // rather than discovered broken on the one run that costs money.
    render(
      <HireParties
        proof={{
          client: "0x0c501EE1924bfb91a028DB4BcD68f4861B0Ff6eE",
          provider: "0xdEaF6a182ECfb667073a85f3f1C32499D5B53e29",
          deliverable: {
            file: "apps/web/public/artifacts/warden.json",
            bytes: 5340,
            keccak256: "0x" + "ab".repeat(32),
            url: "https://example.invalid/warden.json",
          },
        }}
      />
    );
    expect(screen.getByText("two parties")).toBeInTheDocument();
    expect(screen.getByText(/5,340 bytes/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /warden\.json/ })).toBeInTheDocument();
    expect(screen.queryByText(/No deliverable committed/)).not.toBeInTheDocument();
  });
});
