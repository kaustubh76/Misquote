import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeToggle } from "./ThemeToggle";
import { THEME_KEY } from "@/lib/theme";

/**
 * An in-memory store, because this jsdom does not supply one.
 *
 * `lib/theme.ts` already treats a missing or throwing `localStorage` as "follow
 * the OS" rather than as an error — private browsing must not break the site —
 * so the component survives its absence. The test needs a real one to assert
 * that the choice is persisted at all.
 */
function stubStorage() {
  const store = new Map<string, string>();
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

beforeEach(() => {
  stubStorage();
  document.documentElement.removeAttribute("data-theme");
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("data-theme");
});

/**
 * The group declared `role="radiogroup"` and behaved like three buttons.
 *
 * All three were tab stops and the arrow keys did nothing, so a screen-reader
 * user in forms mode met a widget that did not do what its role promised —
 * which is worse than an undeclared role, because the promise is what they
 * navigate by.
 */
describe("ThemeToggle is the radiogroup it says it is", () => {
  it("is a single tab stop", async () => {
    render(<ThemeToggle />);
    const radios = screen.getAllByRole("radio");

    const stops = radios.filter((r) => r.getAttribute("tabindex") === "0");
    expect(stops).toHaveLength(1);
  });

  it("moves selection with the arrow keys, and wraps", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);
    const radios = screen.getAllByRole("radio");

    radios[0]!.focus();
    await user.keyboard("{ArrowRight}");
    expect(radios[1]).toHaveAttribute("aria-checked", "true");
    expect(radios[1]).toHaveFocus();

    // Movement is selection, per APG — not "focus now, choose later".
    await user.keyboard("{ArrowRight}");
    expect(radios[2]).toHaveAttribute("aria-checked", "true");

    await user.keyboard("{ArrowRight}");
    expect(radios[0]).toHaveAttribute("aria-checked", "true");
  });

  it("jumps to the ends with Home and End", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);
    const radios = screen.getAllByRole("radio");

    radios[0]!.focus();
    await user.keyboard("{End}");
    expect(radios[2]).toHaveAttribute("aria-checked", "true");

    await user.keyboard("{Home}");
    expect(radios[0]).toHaveAttribute("aria-checked", "true");
  });

  it("persists the choice and pins the document", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);

    await user.click(screen.getByRole("radio", { name: "Dark" }));
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");

    // "auto" is the *absence* of an override, not a third palette — the CSS
    // uses light-dark(), which reads color-scheme.
    await user.click(screen.getByRole("radio", { name: "System" }));
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("names every option in words, not only by glyph", () => {
    render(<ThemeToggle />);
    for (const name of ["System", "Light", "Dark"]) {
      expect(screen.getByRole("radio", { name })).toBeInTheDocument();
    }
  });
});
