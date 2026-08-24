import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { COMPARE_KEY, COMPARE_LIMIT, readCompare, storeCompare, toggleCompare } from "@/lib/compare";

/**
 * The storage half of the tray, where every interesting case is a bad value
 * coming back out of `localStorage` — written by an earlier version, by another
 * tab, or by nothing at all.
 *
 * An in-memory store, because this jsdom does not supply one — the same stub
 * `ThemeToggle.test.tsx` uses, for the same reason. `lib/compare.ts` treats a
 * missing or throwing `localStorage` as an empty tray rather than an error, so
 * the module survives its absence; the test needs a real one to assert the
 * selection is persisted at all.
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

beforeEach(stubStorage);
afterEach(() => vi.unstubAllGlobals());

describe("readCompare", () => {
  it("is empty when nothing was ever stored", () => {
    expect(readCompare()).toEqual([]);
  });

  it("refuses a value that is not a list of slugs", () => {
    // The shape a previous version might have written, or a hand-edited entry.
    localStorage.setItem(COMPARE_KEY, JSON.stringify({ warden: true }));
    expect(readCompare()).toEqual([]);
  });

  it("refuses a list with a non-string in it", () => {
    localStorage.setItem(COMPARE_KEY, JSON.stringify(["warden", 3]));
    expect(readCompare()).toEqual([]);
  });

  it("refuses malformed JSON rather than throwing", () => {
    localStorage.setItem(COMPARE_KEY, "{not json");
    expect(readCompare()).toEqual([]);
  });

  it("truncates a stored list longer than the limit", () => {
    localStorage.setItem(COMPARE_KEY, JSON.stringify(["a", "b", "c"]));
    expect(readCompare()).toHaveLength(COMPARE_LIMIT);
  });
});

describe("toggleCompare", () => {
  it("adds and removes", () => {
    expect(toggleCompare([], "warden")).toEqual(["warden"]);
    expect(toggleCompare(["warden"], "warden")).toEqual([]);
  });

  it("drops the oldest rather than refusing a third", () => {
    // A tray that ignored the click would look broken; sliding the window is
    // what a reader expects from two slots, and it is one click to reverse.
    expect(toggleCompare(["a", "b"], "c")).toEqual(["b", "c"]);
  });

  it("does not duplicate an agent already chosen", () => {
    expect(toggleCompare(["a", "b"], "a")).toEqual(["b"]);
  });
});

describe("storeCompare", () => {
  it("round-trips through storage", () => {
    storeCompare(["warden", "grid"]);
    expect(readCompare()).toEqual(["warden", "grid"]);
  });

  it("never writes more than the limit", () => {
    storeCompare(["a", "b", "c", "d"]);
    expect(readCompare()).toHaveLength(COMPARE_LIMIT);
  });
});


describe("when storage is unavailable", () => {
  it("reads as an empty tray rather than throwing", () => {
    // Private browsing, or a browser with storage disabled. Forgetting a
    // selection is a far smaller failure than not rendering the site.
    vi.stubGlobal("localStorage", undefined);
    expect(readCompare()).toEqual([]);
  });

  it("swallows a failed write", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: () => {
        throw new Error("QuotaExceededError");
      },
    });
    expect(() => storeCompare(["warden"])).not.toThrow();
  });
});
