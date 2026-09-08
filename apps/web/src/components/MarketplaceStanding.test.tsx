import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MarketplaceStanding, type Participation } from "@/components/MarketplaceStanding";
import { readArtifact } from "@/test/harness";

/**
 * The block is about what happened on a marketplace, and one thing did not.
 *
 * A field can be emitted and rendered nowhere — that is the defect the artifact
 * contract exists for, and it was true of half the hire flow until tonight. So
 * the Python test asserting the artifact carries `not_done` is not enough on its
 * own: these assert a reader actually sees it.
 */

const registry = readArtifact<{ aacp: { participation?: Participation } }>("registry.json");
const live = registry.aacp.participation;

afterEach(cleanup);

describe("against the real artifact", () => {
  it("never shows an empty order list when the read failed", () => {
    // A timeout on `/api/v1/orders` published `orders: []` once while an
    // escrowed order sat on the platform. "No orders" and "we could not look"
    // are different claims and only one of them is ever true by accident.
    render(<MarketplaceStanding p={{ orders: [], orders_unreadable: "ReadTimeout: timed out" }} />);
    expect(screen.getByText("could not be read")).toBeInTheDocument();
    expect(screen.getByText(/ReadTimeout/)).toBeInTheDocument();
  });

  it("shows each bid against what the buyer asked, and what it concedes", () => {
    if (!live?.bids?.length) return;
    render(<MarketplaceStanding p={live} />);
    for (const b of live.bids) {
      // The concession is the part worth seeing: every one of these briefs asks
      // for something adjacent to what the agent does.
      if (b.concession) expect(screen.getByText(new RegExp(b.concession.slice(0, 24).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))).toBeInTheDocument();
    }
  });

  it("names the order the escrow produced, with its on-chain id", () => {
    if (!live?.orders?.length) return;
    render(<MarketplaceStanding p={live} />);
    for (const o of live.orders) {
      // The chain order id is the one field a reader can check without this
      // project's cooperation, so it is rendered in full rather than shortened.
      if (o.chain_order_id) expect(screen.getByText(o.chain_order_id)).toBeInTheDocument();
    }
  });

  it("shows the counter that is still zero", () => {
    if (!live) return;
    render(<MarketplaceStanding p={live} />);
    // Orders is the one that has not moved, and it stays on the page.
    expect(screen.getByText("Orders")).toBeInTheDocument();
    expect(live.counters?.now?.activeOrders).toBe(0);
  });

  it("prints why it is still zero, in the emitter's own words", () => {
    if (!live) return;
    const { container } = render(<MarketplaceStanding p={live} />);
    expect(screen.getByText("Not done.")).toBeInTheDocument();
    // Every outstanding sentence, not just the first: the block exists to stop
    // one of them being dropped for looking bad.
    for (const why of live.not_done ?? []) expect(container.textContent).toContain(why);
  });

  it("names every published listing with its price", () => {
    if (!live?.listings?.length) return;
    render(<MarketplaceStanding p={live} />);
    for (const row of live.listings) {
      // `getAllBy`, because an agent name can legitimately appear twice: once
      // as a listing and once in the refusals. The first version used `getBy`
      // and failed on "grid" — which is how the emitter's own conflation of
      // "refused" with "already listed" was found.
      expect(screen.getAllByText(row.agent).length).toBeGreaterThan(0);
    }
    // Counted per price, not looked up singly: Grid and Router both sell at
    // $0.20, so `getByText` finds two and throws. Two agents at one price is
    // the honest state — they cause comparable work — and a test that could not
    // express it would push the prices apart to stay green.
    const byPrice = new Map<string, number>();
    for (const row of live.listings) {
      const key = `$${row.price_usdc}`;
      byPrice.set(key, (byPrice.get(key) ?? 0) + 1);
    }
    for (const [label, n] of byPrice) {
      expect(screen.getAllByText(label)).toHaveLength(n);
    }
  });

  it("shows a refusal when there is one, with its reason", () => {
    // The live artifact has no refusals any more — Router's was mine and wrong,
    // and `/agents/router` had served the comparison all along. So this uses a
    // synthetic one: the block must still be able to say an agent was held
    // back, or the day one is, nobody will see it.
    render(
      <MarketplaceStanding
        p={{ refused: { someagent: "its probe route has stopped answering" } }}
      />
    );
    expect(screen.getByText(/someagent/)).toBeInTheDocument();
    expect(screen.getByText(/stopped answering/)).toBeInTheDocument();
  });
});

describe("what it refuses to imply", () => {
  const done: Participation = {
    listings: [{ agent: "warden", listing_id: "l1", status: "PUBLISHED", price_usdc: "0.25" }],
    counters: {
      baseline: { activeOrders: 0, openBriefs: 0, savedListings: 0, campaignsTotal: 0 },
      now: { activeOrders: 0, openBriefs: 1, savedListings: 4, campaignsTotal: 1 },
    },
    not_done: ["the escrow transaction has never been sent"],
  };

  it("shows each counter against where it started, not just where it is", () => {
    render(<MarketplaceStanding p={done} />);
    // Four bookmarks we always had and four we just made look identical if only
    // the second number is shown.
    const text = screen.getByText("Saved").closest("div")?.textContent ?? "";
    expect(text).toContain("0");
    expect(text).toContain("4");
  });

  it("renders the absence instead of an empty frame when there is no record", () => {
    render(<MarketplaceStanding p={{ reason: "no marketplace record on disk" }} />);
    expect(screen.getByText(/no marketplace record on disk/)).toBeInTheDocument();
    expect(screen.queryByText("Orders")).not.toBeInTheDocument();
  });
});
