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
 * actually see — which routes are in the document, and that the list a screen
 * reader walks is the whole of whichever bands are showing.
 *
 * Stated rather than left implicit, because a test that silently cannot fail is
 * worse than no test: it occupies the space where a real one would go.
 *
 * The lists below are a deliberate second copy of `lib/routes.ts` rather than an
 * import of it. Importing would make the nav correct by definition — the two
 * would agree because they are the same array — and the drift this file exists
 * to catch is exactly the kind in the 404 test at the bottom, where a hand-kept
 * copy fell to six routes against eight. Adding a route means adding it here
 * too, and that second edit is the check.
 */
const PRODUCT = [
  ["Overview", "/"],
  ["Demo", "/demo"],
  ["Agents", "/category"],
  ["Quote", "/quote"],
  ["Simulate", "/simulate"],
  ["Hire", "/activate"],
  ["Registry", "/registry"],
  ["Studio", "/studio"],
] as const;

const EVIDENCE = [
  ["Advantage", "/advantage"],
  ["Methods", "/methods"],
  ["Assumptions", "/assumptions"],
  ["Tick math", "/vectors"],
  ["Venue", "/venue"],
  ["Vetting", "/vetting"],
  ["Tape", "/tape"],
  ["Status", "/status"],
] as const;

/** Every page, for the 404 — which claims to be exhaustive and must stay so. */
const ROUTES = [...PRODUCT, ...EVIDENCE] as const;

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

describe("outside the evidence section, the nav is the product and one way in", () => {
  it("renders a link for every product page", () => {
    render(<Nav />, { wrapper: WithWallet });
    const header = screen.getByRole("banner");

    for (const [label, href] of PRODUCT) {
      expect(within(header).getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
  });

  it("shows the way into the evidence section rather than its eight pages", () => {
    // The point of the change this asserts: sixteen tabs across two rows was
    // the first thing a reader saw, and none of them said which was the
    // product. The eight are not gone — `not-found` still lists them, the
    // landing rail still links them, and the band below returns the moment the
    // reader is in the section — they are simply not competing with the eight
    // that answer "what is this".
    render(<Nav />, { wrapper: WithWallet });
    const header = screen.getByRole("banner");

    expect(within(header).getByRole("link", { name: "Evidence" })).toHaveAttribute(
      "href",
      "/#evidence",
    );
    for (const [label] of EVIDENCE) {
      expect(within(header).queryByRole("link", { name: label })).toBeNull();
    }
    expect(screen.queryByRole("navigation", { name: "Evidence" })).toBeNull();
  });

  it("scrolls rather than dropping links, so the count never depends on width", () => {
    // The failure this guards is the tempting fix for the same symptom: hiding
    // the overflowing links behind a breakpoint. That makes the bar tidy and
    // makes the pages unreachable, which is the state the fades were added to
    // get out of — not a state to formalise.
    render(<Nav />, { wrapper: WithWallet });
    const header = screen.getByRole("banner");
    // The product routes, the Evidence pill, and the wordmark's link home.
    expect(within(header).getAllByRole("link")).toHaveLength(PRODUCT.length + 2);
    const band = screen.getByRole("navigation", { name: "Primary" });
    expect(band.querySelector("ul")?.className).toContain("overflow-x-auto");
  });

  it("marks the current page for assistive tech, not only with a colour", () => {
    render(<Nav />, { wrapper: WithWallet });
    const header = screen.getByRole("banner");
    expect(within(header).getByRole("link", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // A way *to* the section is not a page in it, and no pathname can equal
    // `/#evidence` — so this link is never the current one, on any route.
    expect(
      within(header).getByRole("link", { name: "Evidence" }).getAttribute("aria-current"),
    ).toBeNull();
  });
});

describe("inside the evidence section, the band comes back", () => {
  it("names all eight and marks the one being read", async () => {
    vi.resetModules();
    vi.doMock("next/navigation", () => ({ usePathname: () => "/status/" }));
    const { Nav: OnStatus } = await import("./Nav");

    render(<OnStatus />, { wrapper: WithWallet });
    const header = screen.getByRole("banner");

    // The trailing slash matters: the export sets `trailingSlash: true`, so
    // `usePathname()` returns `/status/` while every href is written `/status`.
    // Comparing them raw hides the band on exactly the routes that need it.
    const band = screen.getByRole("navigation", { name: "Evidence" });
    expect(band.querySelector("ul")?.className).toContain("overflow-x-auto");
    for (const [label, href] of EVIDENCE) {
      expect(within(header).getByRole("link", { name: label })).toHaveAttribute("href", href);
    }

    // `check-pages.mjs` fails a route whose pill is missing or off screen, and
    // it looks in whichever band holds it. This is the half jsdom can see.
    expect(within(header).getByRole("link", { name: "Status" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // One affordance at a time: the band is right there, so the pill that leads
    // to its index is not also rendered.
    expect(within(header).queryByRole("link", { name: "Evidence" })).toBeNull();
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
  it("names every route, including the ones the nav no longer shows", async () => {
    // `not-found.tsx` kept its own copy of the route list and it drifted to six
    // against eight, omitting /vectors and /vetting — while the page said "this
    // site contains exactly the pages listed below and nothing else". A reader
    // who mistyped /vetting was told the site has no such page, on the one page
    // whose job is to say what the site does have.
    //
    // Load-bearing twice over now that the nav shows the evidence routes only
    // inside their own section: this page is where the whole sixteen are named
    // unconditionally, so a route dropped from the nav is still a route the
    // site admits to having.
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
