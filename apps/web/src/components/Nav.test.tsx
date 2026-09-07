import { WithWallet } from "@/test/harness";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Nav } from "./Nav";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

/**
 * jsdom lays nothing out: every element reports `scrollWidth === clientWidth
 * === 0`, so the overflow hook always sees a nav that fits and the fades never
 * render. That is why the *fade* is verified in the browser, by
 * `scripts/check-pages.mjs`, and what is verified here is the part jsdom can
 * actually see — that no route is dropped, and that the list a screen reader
 * walks is the whole list regardless of what is scrolled into view.
 *
 * Stated rather than left implicit, because a test that silently cannot fail is
 * worse than no test: it occupies the space where a real one would go.
 *
 * The list below is a deliberate second copy of `lib/routes.ts` rather than an
 * import of it. Importing would make the nav correct by definition — the two
 * would agree because they are the same array — and the drift this file exists
 * to catch is exactly the kind in the 404 test at the bottom, where a hand-kept
 * copy fell to six routes against eight. Adding a route means adding it here
 * too, and that second edit is the check.
 */
const ROUTES = [
  ["Overview", "/"],
  ["Demo", "/demo"],
  ["Agents", "/category"],
  ["Quote", "/quote"],
  ["Hire", "/activate"],
  ["Venue", "/venue"],
  ["Advantage", "/advantage"],
  ["Methods", "/methods"],
  ["Tick math", "/vectors"],
  ["Assumptions", "/assumptions"],
  ["Registry", "/registry"],
  ["Studio", "/studio"],
  ["Vetting", "/vetting"],
  ["Tape", "/tape"],
  ["Status", "/status"],
] as const;

beforeEach(() => {
  // The hook observes the list. jsdom has no ResizeObserver.
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

describe("every route is in the nav, whether or not it is on screen", () => {
  it("renders a link for every page", () => {
    render(<Nav />, { wrapper: WithWallet });
    const header = screen.getByRole("banner");

    for (const [label, href] of ROUTES) {
      expect(within(header).getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
  });

  it("scrolls rather than dropping links, so the count never depends on width", () => {
    // The failure this guards is the tempting fix for the same symptom: hiding
    // the overflowing links behind a breakpoint. That makes the bar tidy and
    // makes five of the seven pages unreachable, which is the state the fades
    // were added to get out of — not a state to formalise.
    render(<Nav />, { wrapper: WithWallet });
    const header = screen.getByRole("banner");
    // Every route, across both bands, plus the wordmark's link home.
    expect(within(header).getAllByRole("link")).toHaveLength(ROUTES.length + 1);
    for (const label of ["Primary", "Evidence"]) {
      const band = screen.getByRole("navigation", { name: label });
      expect(band.querySelector("ul")?.className).toContain("overflow-x-auto");
    }
  });

  it("marks the current page for assistive tech, not only with a colour", () => {
    render(<Nav />, { wrapper: WithWallet });
    const header = screen.getByRole("banner");
    expect(within(header).getByRole("link", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // In the other band, and still not marked — the two rows are one nav for
    // the purpose of "where am I".
    expect(
      within(header).getByRole("link", { name: "Status" }).getAttribute("aria-current"),
    ).toBeNull();
  });
});

describe("an agent detail page is somewhere, not nowhere", () => {
  it("marks Overview as the current section, not as the current page", async () => {
    // `/agent/warden` has no nav entry. The rule was exact-match plus a prefix
    // match that `href === "/"` short-circuited out of, so all three agent
    // pages — a third of the site's routes — highlighted nothing at all.
    vi.resetModules();
    vi.doMock("next/navigation", () => ({ usePathname: () => "/agent/warden" }));
    const { Nav: Detail } = await import("./Nav");

    render(<Detail />, { wrapper: WithWallet });
    const header = screen.getByRole("banner");
    const overview = within(header).getByRole("link", { name: "Overview" });

    // "true", not "page". Saying `aria-current="page"` here would tell a screen
    // reader the Overview link leads where the reader already is.
    expect(overview).toHaveAttribute("aria-current", "true");
    expect(
      within(header)
        .getAllByRole("link")
        .filter((a) => a.getAttribute("aria-current") === "page"),
    ).toHaveLength(0);
  });
});


describe("the 404 lists the site it is refusing to show", () => {
  it("names every route the nav does", async () => {
    // `not-found.tsx` kept its own copy of the route list and it drifted to six
    // against eight, omitting /vectors and /vetting — while the page said "this
    // site contains exactly the pages listed below and nothing else". A reader
    // who mistyped /vetting was told the site has no such page, on the one page
    // whose job is to say what the site does have.
    const { default: NotFound } = await import("@/app/not-found");
    render(<NotFound />, { wrapper: WithWallet });

    for (const [label, href] of ROUTES) {
      expect(screen.getByRole("link", { name: new RegExp(label) })).toHaveAttribute(
        "href",
        href,
      );
    }
    // And nothing beyond them, since the page claims to be exhaustive.
    const listed = screen
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"))
      .filter((h) => h && !h.startsWith("#"));
    expect(new Set(listed)).toEqual(new Set(ROUTES.map(([, href]) => href)));
  });
});
