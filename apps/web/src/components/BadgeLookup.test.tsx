import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BadgeLookup } from "@/components/BadgeLookup";

const BASE = "https://api.example.test";

beforeEach(() => vi.stubGlobal("__MISQUOTE_API__", BASE));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const serve = (body: unknown, status = 200) =>
  vi.stubGlobal("fetch", vi.fn(async () => json(body, status)));

async function ask(address = "0xabc") {
  await userEvent.type(screen.getByLabelText(/Look up one address/), address);
  await userEvent.click(screen.getByRole("button", { name: "Check" }));
}

/**
 * The two absences, which are the reason this route exists.
 *
 * `api/vetting.py` sends a different 404 for each: a pool we verified and never
 * vetted is a gap in our own work, and a pool we never verified is a refusal to
 * index it at all. Both are 404s and collapsing them would make the surface
 * pointless, so both are asserted separately here.
 */
describe("BadgeLookup", () => {
  it("distinguishes a pool we never vetted from one we never verified", async () => {
    serve(
      {
        detail: {
          error: "no badge recorded for '0xabc'",
          remedy: "make vet",
          note: "This is a pool this repository has verified and not vetted. The absence is ours.",
        },
      },
      404,
    );
    render(<BadgeLookup />);
    await ask();

    await waitFor(() => expect(screen.getByText(/no badge recorded for/)).toBeInTheDocument());
    expect(screen.getByText(/The absence is ours/)).toBeInTheDocument();
  });

  it("says so differently when nothing has ever looked at the address", async () => {
    serve(
      {
        detail: {
          error: "no verified pool at '0xdead'",
          remedy: "record it in chain/addresses.py and run `make vet`",
          note: "It has no badge because nothing has ever looked at it.",
        },
      },
      404,
    );
    render(<BadgeLookup />);
    await ask("0xdead");

    await waitFor(() =>
      expect(screen.getByText(/nothing has ever looked at it/)).toBeInTheDocument(),
    );
  });

  it("renders a found badge with its checks and its verdict", async () => {
    serve({
      pool: "0x36696169c63e42cd08ce11f5deebbcebae652050",
      chain_id: 56,
      verdict: { called: true, label: "PASS" },
      checks: [
        {
          name: "factory resolves it",
          status: "PASS",
          detail: "getPool() agrees with the address",
          provenance: "P-6",
        },
      ],
    });
    render(<BadgeLookup />);
    await ask();

    await waitFor(() => expect(screen.getByText(/factory resolves it/)).toBeInTheDocument());
    // Two: the badge's own verdict, and the one check's status. `getByText`
    // throws on the ambiguity, and the count is the more useful assertion —
    // a badge that rendered its verdict and lost its checks would still satisfy
    // a one-element check.
    expect(screen.getAllByText("PASS")).toHaveLength(2);
  });

  it("survives a check the service sent without a provenance", async () => {
    serve({
      pool: "0xabc",
      chain_id: 56,
      verdict: { called: true, label: "PASS" },
      // No `provenance`. Every badge on disk carries one; a service running a
      // different version of the repository is not bound by that.
      checks: [{ name: "protocol fee read", status: "PASS", detail: "feeProtocol 3400" }],
    });
    render(<BadgeLookup />);
    await ask();

    await waitFor(() => expect(screen.getByText(/protocol fee read/)).toBeInTheDocument());
  });

  it("never substitutes the published aggregate for a lookup", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("down"); }));
    render(<BadgeLookup />);
    await ask();

    await waitFor(() => expect(screen.getByText(/No live service answered/)).toBeInTheDocument());
  });
});
