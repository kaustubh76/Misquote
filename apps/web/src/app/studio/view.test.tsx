import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StudioView, type StudioArtifact } from "./view";
import { readArtifact, serveArtifacts, textFrom } from "@/test/harness";

vi.mock("next/navigation", () => ({ usePathname: () => "/studio" }));

afterEach(cleanup);

const studio = () => readArtifact<StudioArtifact>("studio.json");

/**
 * A live answer from `/studio/negotiate`, differing from the recorded one in
 * every field that matters.
 *
 * Deliberately not a copy of the artifact. The page has two paths to the same
 * renderer and the only way to prove it took the live one is for the live
 * values to be values the recorded envelope does not contain — the same reason
 * `serveArtifacts`' `overrides` exists.
 */
const LIVE = {
  envelope: {
    negotiation_hash: "0xfeed0000000000000000000000000000000000000000000000000000000000ff",
    provider_sig: "0xbeef1111111111111111111111111111111111111111111111111111111111111111",
    chain_id: 97,
    verifying_contract: "0xa206c0517B6371C6638CD9e4a42Cc9f02A33B0DE",
    response: { terms: { price: "100000000000000000", currency: "0xc70B8741B8B07A6d61E54fd4B20f22Fa648E5565" } },
  },
  recovered_signer: "0xdEaF6a182ECfb667073a85f3f1C32499D5B53e29",
  signed_over: "the negotiation hash as a hex string, EIP-191",
  binds_to_the_verified_kernel: true,
  denominated_in_the_kernels_token: true,
  chain_matches: true,
  not_covered: "This is the negotiation half.",
};

/** `loadLive` reads its base out of `api.json`, so the live route is stubbed there. */
function serveNegotiate(answer: { status: number; body: unknown }) {
  const api = readArtifact<{ base: string }>("api.json");
  const real = globalThis.fetch;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith(api.base)) {
        return new Response(JSON.stringify(answer.body), {
          status: answer.status,
          headers: { "content-type": "application/json" },
        });
      }
      return real(input, init);
    }),
  );
}

describe("Studio: the work that was built and wired to no reader", () => {
  it("renders the recorded envelope before anything is pressed", async () => {
    // The page's floor. With no API and no JavaScript-driven request, a reader
    // still sees a signature and who it recovers to — which is the whole
    // argument, and it must not depend on a free host being awake.
    serveArtifacts();
    const d = studio();
    render(<StudioView initial={d} />);

    expect(screen.getByText(/recorded earlier/)).toBeInTheDocument();
    // Not the full hash — the page shortens it. The lead is what identifies it.
    const hash = d.negotiation.negotiation_hash ?? "";
    expect(screen.getByTitle(hash)).toBeInTheDocument();
  });

  it("shows the signer and the identity owner as one address", async () => {
    // The single most checkable fact on the page: the agent proves it holds the
    // key that owns the ERC-8004 identity, rather than asserting it. If these
    // two ever render as different addresses the claim has quietly broken.
    serveArtifacts();
    const d = studio();
    render(<StudioView initial={d} />);

    expect(d.negotiation.recovered_signer?.toLowerCase()).toBe(d.identity.owner?.toLowerCase());
    expect(screen.getAllByTitle(d.negotiation.recovered_signer ?? "").length).toBeGreaterThan(0);
  });

  it("replaces the recorded envelope with a live one when the agent answers", async () => {
    serveNegotiate({ status: 200, body: LIVE });
    render(<StudioView initial={studio()} />);

    await userEvent.click(screen.getByRole("button", { name: /Ask for a signed quote/ }));

    await waitFor(() => expect(screen.getByText(/answered live/)).toBeInTheDocument());
    expect(screen.getByTitle(LIVE.envelope.negotiation_hash)).toBeInTheDocument();
    // And the recorded one is gone rather than shown beside it: two envelopes on
    // screen with one "answered live" label between them is unreadable.
    expect(screen.queryByText(/recorded earlier/)).not.toBeInTheDocument();
  });

  it("keeps the recorded envelope when the agent refuses, and says which happened", async () => {
    // The demo-day case. A free host that scales to zero will sometimes not
    // answer, and the page must show the refusal *and* the recorded evidence —
    // not swap the recording in as though it were fresh, which is the misquote.
    //
    // 503 rather than a refusal code on purpose: `lib/api.ts` folds every 5xx
    // into the artifact fallback and treats only a non-5xx `detail` body as
    // terminal, so this exercises the branch the sleeping host actually takes.
    // `api/studio.py` picks its two codes against exactly that behaviour.
    serveNegotiate({
      status: 503,
      body: {
        detail: {
          error: "the Agent Studio seller did not answer: URLError",
          remedy: "try again — the host scales to zero",
        },
      },
    });
    render(<StudioView initial={studio()} />);

    await userEvent.click(screen.getByRole("button", { name: /Ask for a signed quote/ }));

    await waitFor(() =>
      expect(screen.getByText(/did not answer in time/)).toBeInTheDocument(),
    );
    // Asserted on the envelope itself rather than on the "recorded earlier"
    // label, which the refusal's own remedy sentence also contains. The claim
    // being protected is that the *evidence* survives a failed live call, and
    // the hash is the evidence.
    expect(screen.getByTitle(studio().negotiation.negotiation_hash ?? "")).toBeInTheDocument();
  });

  it("names what this does not prove, from the artifact rather than from the page", async () => {
    // The half a judge checks. `not_done` is data for the same reason the
    // not-built ledger is: a page that can drop an admission by editing a
    // component is a page that will.
    serveArtifacts();
    const d = studio();
    render(<StudioView initial={d} />);

    for (const entry of d.not_done) {
      expect(screen.getByText(textFrom(entry.name))).toBeInTheDocument();
    }
    expect(d.not_done.length).toBeGreaterThan(0);
  });

  it("refuses rather than inventing when nothing has called the agent", async () => {
    // An artifact from a checkout that never ran `make studio-negotiate` and one
    // from a run that got no answer must not look alike — the distinction the
    // whole `Refusal` component exists to preserve.
    serveArtifacts();
    const d = studio();
    render(
      <StudioView
        initial={{
          ...d,
          negotiation: { available: false, reason: "nothing has called the agent" },
        }}
      />,
    );

    expect(screen.getByText(/Nothing has asked this agent for a quote/)).toBeInTheDocument();
  });
});
