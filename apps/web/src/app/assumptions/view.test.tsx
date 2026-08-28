import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { asRendered, readArtifact, serveArtifacts } from "@/test/harness";
import AssumptionsPage from "./page";

vi.mock("next/navigation", () => ({ usePathname: () => "/assumptions" }));

interface Entry {
  id: string;
  title: string;
  kind: string;
}
interface Sheet {
  entries: Entry[];
  sections: Record<string, unknown[]>;
}

const sheet = () => readArtifact<Sheet>("assumptions.json");

beforeEach(() => serveArtifacts());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

async function loaded() {
  const view = render(<AssumptionsPage />);
  await screen.findByRole("navigation", { name: "Assumptions index" });
  return view;
}

const index = () => screen.getByRole("navigation", { name: "Assumptions index" });

/**
 * The index's links to *entries*, as against its links to sections.
 *
 * These assertions used to read every link in the index and assume it was an
 * entry, which was true while the index listed nothing else. It also lists the
 * named sections now — they were the only content on the page unreachable from
 * it — and those are deliberately not filtered, because a verdict filter
 * narrows entries and a section is not an entry.
 *
 * Scoped by id rather than by a test-only attribute: the ids are the artifact's
 * own, so this cannot drift from what the page links to.
 */
const entryLinks = () => {
  const ids = new Set(sheet().entries.map((e) => e.id));
  return within(index())
    .getAllByRole("link")
    .filter((a) => ids.has((a.getAttribute("href") ?? "").slice(1)));
};

describe("the index says what each entry is, not just that it exists", () => {
  it("gives every entry its title, not a bare id", async () => {
    // It was 48 chips reading "A1 A2 A3 …" in one flat run, on a page of about
    // 19,000px. An id alone is nothing to recognise, and the artifact has
    // carried the title all along.
    await loaded();
    const links = entryLinks();
    expect(links).toHaveLength(sheet().entries.length);

    for (const entry of sheet().entries) {
      const link = links.find((a) => a.getAttribute("href") === `#${entry.id}`)!;
      expect(link).toBeDefined();
      // `asRendered`, because these titles are markdown like everything else
      // this repository emits — thirty-two of them end in "**fixed 17 Aug
      // 2026**" — and the index renders them through `Prose`. Comparing the
      // raw string to the DOM would fail against output that is right.
      expect(link.textContent).toContain(asRendered(entry.title));
    }
  });

  it("groups by kind, with counts that come from the artifact", async () => {
    await loaded();
    const counts = new Map<string, number>();
    for (const e of sheet().entries) counts.set(e.kind, (counts.get(e.kind) ?? 0) + 1);

    // Named per kind rather than asserting a total, so a failure says which
    // group is wrong. The numbers are counted from the artifact here for the
    // same reason the view counts them there: hardcoding "13 defects" fails
    // for the wrong reason the next time the matrix gains an entry.
    for (const [kind, n] of counts) {
      if (kind === "assumption") expect(within(index()).getByText(`Assumptions (${n})`)).toBeInTheDocument();
      if (kind === "defect") expect(within(index()).getByText(`Defects (${n})`)).toBeInTheDocument();
      if (kind === "gap") expect(within(index()).getByText(`Gaps (${n})`)).toBeInTheDocument();
    }
  });
});

describe("the index reaches everything on the page", () => {
  it("links the named sections, not only the entries", async () => {
    // These five were the only blocks on the page the index never reached, so
    // a reader could jump to any of seventy assumptions and to none of the
    // sections that frame them.
    await loaded();
    for (const [key, blocks] of Object.entries(sheet().sections)) {
      if (blocks.length === 0) continue;
      const link = within(index())
        .getAllByRole("link")
        .find((a) => a.getAttribute("href") === `#${key}`);
      expect(link, `no index link for section ${key}`).toBeDefined();
    }
  });

  it("anchors a section on its own heading, not below it", async () => {
    // The anchor was a `<span id>` inside the Card, under the title — so a
    // deep link landed past the heading of the thing it linked to. `Section`'s
    // own `id` prop puts it on the `<section>` and brings `.scroll-anchor`.
    await loaded();
    const [key] = Object.entries(sheet().sections).find(([, b]) => b.length > 0)!;
    const target = document.getElementById(key)!;
    expect(target.tagName).toBe("SECTION");
    expect(target.className).toContain("scroll-anchor");
  });
});

describe("the filter", () => {
  it("narrows to one kind and says how many are left", async () => {
    const user = userEvent.setup();
    await loaded();
    const defects = sheet().entries.filter((e) => e.kind === "defect");

    await user.click(screen.getByRole("radio", { name: /^Defects/ }));

    await waitFor(() =>
      expect(
        screen.getByText(`Showing ${defects.length} of ${sheet().entries.length} entries.`),
      ).toBeInTheDocument(),
    );
    expect(entryLinks()).toHaveLength(defects.length);
  });

  it("announces the count in a live region, since the cards it removes are below the fold", async () => {
    const user = userEvent.setup();
    await loaded();
    await user.click(screen.getByRole("radio", { name: /^Gaps/ }));
    // Named: `Loadable` puts an unnamed `role="status"` on this page too, and
    // an unnamed query would take whichever came first.
    expect(
      screen.getByRole("status", { name: "Filter result" }).textContent,
    ).toMatch(/Showing \d+ of \d+ entries/);
  });

  it("matches on id as well as title", async () => {
    const user = userEvent.setup();
    await loaded();
    await user.type(screen.getByLabelText(/Filter by id or title/), "P-1");

    const links = entryLinks();
    expect(links.length).toBeGreaterThan(0);
    // P-1, P-10, P-11 all contain "P-1"; none of the A-series does.
    for (const link of links) expect(link.getAttribute("href")).toMatch(/^#P-1/);
  });

  it("states an empty result rather than rendering a blank page", async () => {
    const user = userEvent.setup();
    await loaded();
    await user.type(screen.getByLabelText(/Filter by id or title/), "zzzzz");

    // An empty list under a filter is indistinguishable from an artifact that
    // failed to load, so it has to say which it is.
    expect(screen.getByText(/No entry matches that filter/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /clear the filter/ })).toBeInTheDocument();
  });

  it("behaves like the radiogroup it says it is", async () => {
    // The APG contract: one tab stop, arrows move, movement is selection.
    // `ThemeToggle` announced this role while doing none of it, which is why
    // `ChipGroup` exists rather than a second hand-rolled copy.
    const user = userEvent.setup();
    await loaded();
    const group = screen.getByRole("radiogroup", { name: "Filter by kind" });
    const radios = within(group).getAllByRole("radio");

    expect(radios.filter((r) => r.getAttribute("tabindex") === "0")).toHaveLength(1);
    radios[0]!.focus();
    await user.keyboard("{ArrowRight}");
    expect(radios[1]).toHaveAttribute("aria-checked", "true");
    expect(radios[0]).toHaveAttribute("aria-checked", "false");
  });
});

describe("arriving from a citation", () => {
  it("marks the entry in words, not only in a border colour", async () => {
    // `Pill.tsx` states the rule this broke: colour is the third signal, never
    // the only one. `:target` is a border tint, and the view's programmatic
    // focus does not reliably satisfy `:focus-visible` for a reader who
    // arrived by clicking — so a mouse user had colour alone to find one card
    // among forty-eight.
    window.location.hash = "#P-1";
    await loaded();

    const card = document.getElementById("P-1")!;
    await waitFor(() => expect(within(card).getByText(/followed a citation here/)).toBeInTheDocument());
  });

  it("never marks an entry the reader did not arrive at", async () => {
    window.location.hash = "#P-1";
    await loaded();
    await waitFor(() =>
      expect(screen.getAllByText(/followed a citation here/)).toHaveLength(1),
    );
  });

  it("clears an active filter on a same-page citation click", async () => {
    // The failure this prevents: filter to Gaps, then follow a citation inside
    // an entry body to A5 — `Blocks` linkifies them, so the sheet cites itself
    // — and land on a page with no A5 on it and nothing saying a filter is why.
    //
    // Driven by a `hashchange` on the *mounted* component, deliberately. The
    // first version of this test called `cleanup()` and re-rendered, which
    // resets `useState("all")` on its own: it passed with the filter-clearing
    // deleted, which a mutation run caught. Remounting is also not what the
    // browser does here — following a hash link inside a Next page changes the
    // hash and remounts nothing.
    const user = userEvent.setup();
    await loaded();
    await user.click(screen.getByRole("radio", { name: /^Gaps/ }));
    expect(within(index()).queryByRole("link", { name: /A5/ })).not.toBeInTheDocument();

    window.location.hash = "#A5";
    window.dispatchEvent(new HashChangeEvent("hashchange"));

    await waitFor(() =>
      expect(screen.getByRole("radio", { name: /^All/ })).toHaveAttribute("aria-checked", "true"),
    );
    expect(within(index()).getByRole("link", { name: /A5/ })).toBeInTheDocument();
    expect(within(document.getElementById("A5")!).getByText(/followed a citation here/)).toBeInTheDocument();
  });
});

describe("the named sections", () => {
  it("are reachable by anchor, like every other block on the page", async () => {
    // They carried no id at all, so they were the only content here that a
    // link could not point at.
    await loaded();
    for (const key of Object.keys(sheet().sections)) {
      if (sheet().sections[key]!.length === 0) continue;
      expect(document.getElementById(key)).toBeInTheDocument();
    }
  });
});
