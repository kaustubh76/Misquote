import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { EscrowConsole } from "@/components/EscrowConsole";
import { WithWallet, readArtifact, serveArtifacts } from "@/test/harness";

interface Registry {
  hire_flow: {
    deployments: Record<string, never>;
    mainnet_proof: { job_id: number; budget: number };
  };
}

const registry = readArtifact<Registry>("registry.json").hire_flow;

beforeEach(() => serveArtifacts());
afterEach(cleanup);

describe("with no wallet connected", () => {
  it("invites a connection instead of showing buttons that cannot send", async () => {
    render(
      <EscrowConsole
        deployments={registry.deployments}
        defaultJob={registry.mainnet_proof.job_id}
        defaultBudget={registry.mainnet_proof.budget}
      />,
      { wrapper: WithWallet },
    );

    expect(await screen.findByText(/Connect a wallet in the nav/)).toBeInTheDocument();
    // The point of the gate: no step is reachable, so nothing can be pressed
    // into a wallet that is not there.
    expect(screen.queryByRole("button", { name: "claimRefund" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "fund" })).not.toBeInTheDocument();
  });

  it("still names itself, so the section does not read as empty", async () => {
    render(<EscrowConsole deployments={registry.deployments} />, { wrapper: WithWallet });
    expect(await screen.findByText("Send it yourself")).toBeInTheDocument();
  });
});

describe("the deployments it was handed", () => {
  it("carries both surveyed chains, so a testnet wallet is not refused", () => {
    expect(Object.keys(registry.deployments).sort()).toEqual(["56", "97"]);
  });
});
