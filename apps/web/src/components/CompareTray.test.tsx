import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CompareTray } from "./CompareTray";
import { COMPARE_KEY } from "@/lib/compare";
import { serveArtifacts } from "@/test/harness";

/**
 * The tray, and the one thing it must refuse.
 *
 * `app/view.tsx` keeps Router out of the Overview's comparison because "there
 * is no in-range fraction and no adverse-selection cost to compare — and a zero
 * in those columns would read as a claim rather than an absence". That argument
 * does not weaken on a surface built for comparing; `ComparisonTable`'s rows
 * include both metrics, and `RouterArtifact` has neither field, so a mixed pair
 * would print em dashes under labels asserting the measurements exist.
 */

function stubStorage(initial?: string[]) {
  const store = new Map<string, string>();
  if (initial) store.set(COMPARE_KEY, JSON.stringify(initial));
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() {
      return store.size;
    },
  });
}

beforeEach(() => serveArtifacts());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("an empty tray", () => {
  it("renders nothing at all", () => {
    stubStorage();
    const { container } = render(<CompareTray />);
    // Not a collapsed bar, not a hint: nothing. It must cost no space on a
    // first visit, on every page of the site.
    expect(container).toBeEmptyDOMElement();
  });
});

describe("a tray with one agent", () => {
  it("names it and asks for one more, without offering to compare", async () => {
    stubStorage(["warden"]);
    render(<CompareTray />);

    await screen.findByRole("region", { name: "Compare tray" });
    expect(await screen.findByText("Warden")).toBeInTheDocument();
    expect(screen.getByLabelText("Comparison state")).toHaveTextContent("pick one more");
    expect(screen.queryByRole("button", { name: "Compare" })).not.toBeInTheDocument();
  });
});

describe("two liquidity agents", () => {
  it("offers the comparison and opens it", async () => {
    stubStorage(["warden", "grid"]);
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    render(<CompareTray />);

    const button = await screen.findByRole("button", { name: "Compare" }, { timeout: 5000 });
    await user.click(button);

    // `ComparisonTable`'s caption names both sides, so the table is attributed
    // rather than being two unlabelled columns of figures.
    expect(await screen.findByText(/Warden against Grid/)).toBeInTheDocument();
  });
});

describe("an allocation agent beside a liquidity one", () => {
  it("refuses rather than drawing blanks", async () => {
    stubStorage(["warden", "router"]);
    render(<CompareTray />);

    // By role, not by text: "not comparable" appears twice on purpose — once
    // as the live-region state and once as the refusal's own heading — and a
    // bare text query cannot tell a status line from an explanation.
    expect(
      await screen.findByRole("heading", { name: /not comparable/i }, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Comparison state")).toHaveTextContent("not comparable");
    expect(await screen.findByText(/lending market/)).toBeInTheDocument();

    // And it must not offer the comparison it just refused.
    expect(screen.queryByRole("button", { name: "Compare" })).not.toBeInTheDocument();
  });

  it("is a refusal, not an error", async () => {
    // `Refusal` carries no `role="alert"`; `ErrorNotice` does. The difference
    // is the whole vocabulary: nothing broke here.
    stubStorage(["warden", "router"]);
    render(<CompareTray />);

    await screen.findByRole("heading", { name: /not comparable/i }, { timeout: 5000 });
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });
});
