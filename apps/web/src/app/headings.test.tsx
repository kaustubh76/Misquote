import {
  cleanup,
  render as rtlRender,
  screen,
  waitFor,
  type RenderOptions,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WithWallet, readArtifact, serveArtifacts } from "@/test/harness";

/**
 * `/registry` mounts an on-chain console, and wagmi's hooks throw outside a
 * `WagmiProvider` rather than returning a disconnected state. In the app
 * `layout.tsx` wraps the whole body, so a page rendered without one is a test
 * artefact rather than a state a visitor can reach — hence the wrapper.
 *
 * Only that page pays for it. Wrapping every render cost more than it looks:
 * the assumptions page renders thousands of nodes and went from 2.2s to 5.0s,
 * which under file parallelism was three timeouts against a 15s limit. The
 * provider is cheap per mount and not cheap per ten thousand of them.
 */
function render(ui: React.ReactElement, options?: RenderOptions) {
  const needsWallet = ui.type === RegistryPage;
  return rtlRender(ui, { wrapper: needsWallet ? WithWallet : undefined, ...options });
}


import AdvantagePage from "./advantage/page";
import CategoryIndexPage from "./category/page";
import AssumptionsPage from "./assumptions/page";
import MethodsPage from "./methods/page";
import OverviewPage from "./page";
import RegistryPage from "./registry/page";
import StatusPage from "./status/page";
import VectorsPage from "./vectors/page";
import VenuePage from "./venue/page";
import VettingPage from "./vetting/page";
import { AgentDetail } from "@/components/AgentDetail";
import { RouterDetail } from "@/components/RouterDetail";
import type { RouterArtifact } from "@/lib/artifacts";
import { CategoryView } from "./category/[slug]/view";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

beforeEach(() => serveArtifacts());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const VIEWS = [
  ["Overview", <OverviewPage key="o" />],
  ["Advantage", <AdvantagePage key="a" />],
  ["Methods", <MethodsPage key="m" />],
  ["Assumptions", <AssumptionsPage key="as" />],
  ["Registry", <RegistryPage key="r" />],
  ["Status", <StatusPage key="s" />],
  // Absent since /vetting was built, so the page added most recently was the
  // one page whose heading outline nothing checked.
  ["Vetting", <VettingPage key="v" />],
  ["Vectors", <VectorsPage key="vec" />],
  ["Venue", <VenuePage key="ven" />],
  ["Agent detail", <AgentDetail key="ad" slug="warden" />],
  // The other half of `/agent/[slug]`, and it was missing for the same reason
  // /vetting was: the list grew by page and this one is a component the page
  // branches to. It had no `<h1>` at all — the built route carried eight `<h2>`
  // and no document title, because it opened with a `CardHeader`, which is a
  // `Heading` at whatever depth it finds itself. Nothing rendered it, so
  // nothing counted.
  [
    "Router detail",
    <RouterDetail key="rd" data={readArtifact<RouterArtifact>("router.json")} />,
  ],
  ["Categories", <CategoryIndexPage key="c" />],
  // The view, not the page: `[slug]/page.tsx` is an async server component
  // taking a `params` promise, which cannot be rendered here the way a sync one
  // can. `AgentDetail` above is in this list for the same reason.
  ["Category detail", <CategoryView key="cd" slug="rebalancing" />],
] as const;

const level = (el: Element) => Number(el.tagName[1]);

async function settled(container: HTMLElement) {
  await waitFor(() =>
    expect(container.querySelector("[aria-busy='true']")).not.toBeInTheDocument(),
  );
  return [...container.querySelectorAll("h1, h2, h3, h4, h5, h6")];
}

describe.each(VIEWS)("%s outline", (_name, element) => {
  it("has exactly one h1", async () => {
    const { container } = render(element);
    const headings = await settled(container);
    expect(headings.filter((h) => level(h) === 1)).toHaveLength(1);
  });

  it("never skips a level", async () => {
    const { container } = render(element);
    const headings = await settled(container);

    let previous = 0;
    for (const heading of headings) {
      const current = level(heading);
      if (previous) {
        expect(
          current,
          `"${heading.textContent}" jumps from h${previous} to h${current}`,
        ).toBeLessThanOrEqual(previous + 1);
      }
      previous = current;
    }
  });

  /**
   * The assertion that actually catches the defect this test exists for.
   *
   * Seventeen card headings used to render at the *same* level as the section
   * heading introducing them — a card was a sibling of its own title. A
   * "no skipped levels" rule sails straight past that, because a duplicate is
   * not a skip. The structural claim is the one worth making: everything
   * inside a Section sits strictly below that Section's own title.
   *
   * Keyed on `data-heading-scope` rather than on `<section>`, because `Card`
   * renders a `<section>` by default and would otherwise trip this.
   */
  it("nests every heading inside a Section below that Section's title", async () => {
    const { container } = render(element);
    await settled(container);

    for (const section of container.querySelectorAll("[data-heading-scope]")) {
      const headings = [...section.querySelectorAll("h1, h2, h3, h4, h5, h6")];
      const [title, ...inner] = headings;
      if (!title) continue;

      for (const heading of inner) {
        expect(
          level(heading),
          `"${heading.textContent}" is h${level(heading)} inside a section titled ` +
            `"${title.textContent}" (h${level(title)}) — a card must not be a sibling of its own heading`,
        ).toBeGreaterThan(level(title));
      }
    }
  });
});

describe("the outline test is looking at something", () => {
  it("finds a real, multi-level outline on a page that has one", async () => {
    const { container } = render(<MethodsPage />);
    const headings = await settled(container);

    expect(headings.length).toBeGreaterThan(4);
    // If Section stopped providing context, every heading below the h1 would be
    // an h2 and this would fail.
    expect(new Set(headings.map(level)).size).toBeGreaterThan(2);
    expect(screen.getAllByRole("heading").length).toBe(headings.length);
  });
});
