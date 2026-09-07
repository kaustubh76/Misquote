import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { HireEscrow } from "@/components/HireEscrow";
import type { EscrowDeployment } from "@/lib/escrow";
import {
  WithWallet,
  asWord,
  readArtifact,
  serveArtifacts,
  withConnectedWallet,
} from "@/test/harness";

/**
 * The guided hire, which is the surface a visitor meets.
 *
 * The console beside it is tested for sending every call in any order. What
 * matters here is different and is mostly about restraint: that a step nobody
 * can send is not offered, that a step nothing read is not called done, and
 * that hiring an agent means the money goes to somebody else.
 */

interface Registry {
  hire_flow: {
    deployments: Record<string, EscrowDeployment>;
    errors: Record<string, string>;
    mainnet_proof: { budget: number };
  };
  ours: { owner: string };
}

const registry = readArtifact<Registry>("registry.json");
const flow = registry.hire_flow;
const OWNER = registry.ours.owner;

const DECIMALS = "0x313ce567";
const BALANCE_OF = "0x70a08231";
const ALLOWANCE = "0xdd62ed3e";
const DISPUTE_WINDOW = "0x117f5f92";

/**
 * A visitor, deliberately not the operator.
 *
 * `RECORDED_CLIENT` — the harness's default — is the wallet that owns all four
 * ERC-8004 identities, so connecting it makes the reader and the agent's owner
 * the same address and the page correctly says so. That is a real case and it
 * is covered below; it is not the case these two tests are about.
 */
const VISITOR = "0x00000000000000000000000000000000000dEcaf" as const;

const AGENTS = [
  { slug: "warden", name: "Warden" },
  { slug: "grid", name: "Grid" },
];

const props = {
  deployments: flow.deployments,
  defaultBudget: flow.mainnet_proof.budget,
  errors: flow.errors,
  agents: AGENTS,
  owner: OWNER,
};

const wallet = (
  extra: { address?: `0x${string}`; disputeWindow?: bigint; balance?: bigint } = {},
) =>
  withConnectedWallet({
    address: extra.address,
    calls: {
      [DECIMALS]: asWord(18n),
      [BALANCE_OF]: asWord(extra.balance ?? 10n ** 18n),
      [ALLOWANCE]: asWord(0n),
      [DISPUTE_WINDOW]: asWord(extra.disputeWindow ?? 604_800n),
    },
  });

beforeEach(() => serveArtifacts());
afterEach(cleanup);

describe("with no wallet", () => {
  it("says what escrow is for instead of showing buttons that cannot send", async () => {
    render(<HireEscrow {...props} />, { wrapper: WithWallet });
    expect(
      await screen.findByText(/Connect a wallet to escrow a budget/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "createJob" })).not.toBeInTheDocument();
  });
});

describe("who delivers", () => {
  it("hires an agent rather than the visitor, and says the money goes elsewhere", async () => {
    render(<HireEscrow {...props} />, { wrapper: wallet({ address: VISITOR }) });
    // Both recorded mainnet runs named one address as client and provider. The
    // default here is the wallet that owns the agent, which is a different
    // party — that is the whole claim of a marketplace.
    await waitFor(() =>
      expect(document.body.textContent).toContain("Warden delivers, from"),
    );
  });

  it("offers every listed agent, and a labelled way to hire yourself", async () => {
    render(<HireEscrow {...props} />, { wrapper: wallet() });
    const choose = await screen.findByLabelText(/Who delivers/);
    expect(choose).toHaveDisplayValue("Warden");
    for (const agent of AGENTS) {
      expect(screen.getByRole("option", { name: agent.name })).toBeInTheDocument();
    }
    // Kept, because a full round trip in one wallet is what a demonstration
    // needs — and labelled, because it hires nobody.
    expect(screen.getByRole("option", { name: "Myself (demo)" })).toBeInTheDocument();
  });

  it("will not offer submit when somebody else is the provider", async () => {
    render(<HireEscrow {...props} />, { wrapper: wallet({ address: VISITOR }) });
    await waitFor(() =>
      expect(document.body.textContent).toContain("Warden delivers, from"),
    );
    // `submit` is the provider's signature. Offering it to the client is
    // offering a revert, and worse, it misdescribes who does the work.
    expect(screen.queryByRole("button", { name: "submit" })).not.toBeInTheDocument();
    await waitFor(() =>
      expect(document.body.textContent).toContain("submit is the provider's call"),
    );
  });
});

describe("when the operator hires their own agent", () => {
  it("says the two parties are one address rather than pretending otherwise", async () => {
    // The default harness wallet owns the identities, so choosing Warden still
    // makes client and provider the same address. Saying "Warden delivers"
    // there would be the misquote.
    render(<HireEscrow {...props} />, { wrapper: wallet() });
    expect(await screen.findByText(/You are both client and provider/)).toBeInTheDocument();
  });
});

describe("the stepper", () => {
  it("offers exactly one call, and names the rest as waiting", async () => {
    render(<HireEscrow {...props} />, { wrapper: wallet() });
    // The console offers eight at once. Here the allowance reads zero, so the
    // first thing to do is approve, and nothing after it is pressable yet.
    expect(await screen.findByRole("button", { name: "approve" })).toBeInTheDocument();
    for (const later of ["createJob", "setBudget", "registerJob", "fund"]) {
      expect(screen.queryByRole("button", { name: later })).not.toBeInTheDocument();
    }
    // Exactly one row names what it is waiting for. Repeating it on every
    // later row read as four warnings rather than one queue.
    expect(await screen.findAllByText(/needs approve first/)).toHaveLength(1);
  });

  it("never says settle is anyone here's to send", async () => {
    render(<HireEscrow {...props} />, { wrapper: wallet() });
    await screen.findByRole("button", { name: "approve" });
    expect(screen.queryByRole("button", { name: "settle" })).not.toBeInTheDocument();
    expect(screen.getByText(/EvaluatorRouter, once its policy decides/)).toBeInTheDocument();
  });

  it("does not offer a refund when there is no job to reclaim", async () => {
    render(<HireEscrow {...props} />, { wrapper: wallet() });
    await screen.findByRole("button", { name: "approve" });
    expect(screen.queryByRole("button", { name: /Claim it back/ })).not.toBeInTheDocument();
  });
});

describe("when the wallet cannot cover the budget", () => {
  // The defect this suite exists to prevent a second time. The helper shipped
  // exported and called by nothing — `test_no_dead_exports` caught it, and a
  // commit message had already claimed the door was open.
  it("offers a way to get the payment token instead of a greyed button", async () => {
    render(<HireEscrow {...props} />, { wrapper: wallet({ balance: 0n }) });

    expect(await screen.findByText(/more of the payment token/)).toBeInTheDocument();
    const buy = await screen.findByRole("link", { name: /Buy it on PancakeSwap/ });
    expect(buy).toHaveAttribute(
      "href",
      `https://pancakeswap.finance/swap?chain=bsc&outputCurrency=${flow.deployments["56"]!.erc20}`,
    );
    // The address itself, copyable, because a deeplink is not a substitute for
    // knowing which token you are buying.
    expect(screen.getByText(flow.deployments["56"]!.erc20)).toBeInTheDocument();
  });

  it("says nothing when the wallet already holds enough", async () => {
    render(<HireEscrow {...props} />, { wrapper: wallet() });
    await screen.findByRole("button", { name: "approve" });
    expect(screen.queryByText(/more of the payment token/)).not.toBeInTheDocument();
  });
});

describe("the expiry", () => {
  it("says nothing when the default clears the window it read", async () => {
    render(<HireEscrow {...props} />, { wrapper: wallet() });
    await screen.findByRole("button", { name: "approve" });
    expect(screen.queryByText(/will not reach submit/)).not.toBeInTheDocument();
  });

  // Chapel's dispute window is a day, so 192 hours clears it too; a window
  // wider than the default is what makes the warning appear.
  it("warns before the signature when the expiry cannot reach submit", async () => {
    render(<HireEscrow {...props} />, {
      wrapper: wallet({ disputeWindow: 60n * 60n * 24n * 30n }),
    });
    expect(await screen.findByText(/will not reach submit/)).toBeInTheDocument();
    // And it is not fatal: the budget still escrows.
    expect(screen.getByText(/only the delivery is refused/)).toBeInTheDocument();
  });
});
