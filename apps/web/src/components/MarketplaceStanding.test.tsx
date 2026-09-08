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
    expect(container.textContent).toContain(live.not_done);
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
      expect(screen.getByText(`$${row.price_usdc}`)).toBeInTheDocument();
    }
  });

  it("keeps the refusal a reader can open", () => {
    if (!live?.refused) return;
    render(<MarketplaceStanding p={live} />);
    // Router is not for sale because nothing serves a venue comparison, and
    // that reason is on the page rather than only in a commit message.
    expect(screen.getByText(/router/)).toBeInTheDocument();
  });
});

describe("what it refuses to imply", () => {
  const done: Participation = {
    listings: [{ agent: "warden", listing_id: "l1", status: "PUBLISHED", price_usdc: "0.25" }],
    counters: {
      baseline: { activeOrders: 0, openBriefs: 0, savedListings: 0, campaignsTotal: 0 },
      now: { activeOrders: 0, openBriefs: 1, savedListings: 4, campaignsTotal: 1 },
    },
    not_done: "the escrow transaction has never been sent",
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
