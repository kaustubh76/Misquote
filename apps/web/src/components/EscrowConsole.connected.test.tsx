import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { EscrowConsole } from "@/components/EscrowConsole";
import type { EscrowDeployment } from "@/lib/escrow";
import {
  asWord,
  jobWordsWith,
  readArtifact,
  serveArtifacts,
  withConnectedWallet,
} from "@/test/harness";

/**
 * The console with a wallet attached, which nothing could reach until now.
 *
 * `WithWallet` uses the production config, whose only connector is `injected()`,
 * and jsdom injects nothing — so every earlier test rendered the "connect a
 * wallet" branch and the eight buttons, the countdown, the client check and the
 * revert decoding were all untested. These use wagmi's mock connector over a
 * transport that answers `eth_call` from the recorded mainnet job.
 */

interface Registry {
  hire_flow: {
    deployments: Record<string, EscrowDeployment>;
    errors: Record<string, string>;
    mainnet_proof: { job_id: number; budget: number; job_words: string[] };
  };
}

const flow = readArtifact<Registry>("registry.json").hire_flow;
const mainnet = flow.mainnet_proof;

const GET_JOB = "0xbf22c457";
const BALANCE_OF = "0x70a08231";
const ALLOWANCE = "0xdd62ed3e";

const HOUR = 3600n;
const now = () => BigInt(Math.floor(Date.now() / 1000));

function consoleWith(
  expiredAt: bigint,
  extra: { address?: `0x${string}`; sendError?: Error; balance?: bigint } = {},
) {
  const { address, sendError, balance = 10n ** 18n } = extra;
  return withConnectedWallet({
    address,
    sendError,
    calls: {
      [GET_JOB]: jobWordsWith(mainnet.job_words, { 7: expiredAt }),
      [BALANCE_OF]: asWord(balance),
      [ALLOWANCE]: asWord(0n),
    },
  });
}

const props = {
  deployments: flow.deployments,
  defaultJob: mainnet.job_id,
  defaultBudget: mainnet.budget,
  errors: flow.errors,
};

beforeEach(() => serveArtifacts());
afterEach(cleanup);

describe("a connected wallet that funded the job", () => {
  it("offers every call in the flow, in the order the chain accepts them", async () => {
    render(<EscrowConsole {...props} />, { wrapper: consoleWith(now() + HOUR) });

    for (const call of [
      "approve",
      "createJob",
      "setBudget",
      "registerJob",
      "fund",
      "submit",
      "settle",
      "claimRefund",
    ]) {
      expect(await screen.findByRole("button", { name: call })).toBeInTheDocument();
    }
  });

  it("reads the job back and shows the status as a number, not a word", async () => {
    render(<EscrowConsole {...props} />, { wrapper: consoleWith(now() + HOUR) });

    expect(
      await screen.findByText(`job ${mainnet.job_id} exists`, { exact: false }),
    ).toBeInTheDocument();
    // `erc8183.py` has never confirmed this deployment uses the EIP's state
    // ordering, so a word here would be the first place we pretend otherwise.
    expect(screen.getByText(/status 1 \(unnamed\)/)).toBeInTheDocument();
    expect(screen.getByText(/you funded this/)).toBeInTheDocument();
  });

  it("refuses the refund before the expiry, and says how long is left", async () => {
    render(<EscrowConsole {...props} />, { wrapper: consoleWith(now() + 2n * HOUR) });

    expect(
      await screen.findByText(/not until the expiry — 1h/),
    ).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "claimRefund" })).toBeDisabled();
  });

  it("enables the refund once the expiry has passed", async () => {
    render(<EscrowConsole {...props} />, { wrapper: consoleWith(now() - HOUR) });

    expect(await screen.findByRole("button", { name: "claimRefund" })).toBeEnabled();
    expect(screen.getByText(/expired — refundable/)).toBeInTheDocument();
  });
});

describe("a connected wallet that did not fund the job", () => {
  const stranger = "0x1111111111111111111111111111111111111111" as const;

  it("will not offer to claim someone else's escrow", async () => {
    render(<EscrowConsole {...props} />, {
      wrapper: consoleWith(now() - HOUR, { address: stranger }),
    });

    expect(await screen.findByRole("button", { name: "claimRefund" })).toBeDisabled();
    expect(
      screen.getByText(/only the client that funded this job can claim it/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/you funded this/)).not.toBeInTheDocument();
  });
});

describe("a wallet that cannot cover the budget", () => {
  it("disables fund and says which of the two things is missing", async () => {
    render(<EscrowConsole {...props} />, {
      wrapper: consoleWith(now() + HOUR, { balance: 0n }),
    });

    expect(
      await screen.findByText(/does not hold that much of the payment token/),
    ).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "fund" })).toBeDisabled();
  });
});

describe("when a call does not reach the chain", () => {
  it("reports the failure without inventing a reason for it", async () => {
    // The mock connector sends writes over real HTTP rather than through the
    // stub transport, so this exercises the one thing that most needs it: a
    // call that never arrived. It used to render
    // `0x9e63798d — unresolved in this repository` — the selector of `submit`
    // itself, scraped out of the calldata and offered as the refusal.
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();

    render(<EscrowConsole {...props} />, { wrapper: consoleWith(now() + HOUR) });
    await user.click(await screen.findByRole("button", { name: "submit" }));

    expect(await screen.findByText(/Refused/)).toBeInTheDocument();
    await waitFor(() => {
      expect(document.body.textContent).not.toContain("unresolved in this repository");
      expect(document.body.textContent).not.toContain("0x9e63798d");
    });
  });
});
