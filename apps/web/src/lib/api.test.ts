import { afterEach, describe, expect, it, vi } from "vitest";
import { apiBase, RefusalError } from "@/lib/api";

// `loadLive` is imported per test via `await import`, not at the top: `apiBase`
// memoises the config for the page's lifetime and each case configures a
// different world, so the module cache is reset between them and a top-level
// binding would keep pointing at the first instance. `apiBase` and
// `RefusalError` are imported statically because the override test bypasses the
// cache and `instanceof` needs a stable class identity to compare against.

/**
 * The fallback rule is the whole point of this module, so it is what is tested.
 *
 * `loadLive` may substitute a precomputed artifact for a live answer in exactly
 * two cases — the host was unreachable, or it returned a 5xx — because in both
 * of those nothing was answered. It may never do so for a refusal, which *is*
 * an answer, and swapping a considered "the evidence cannot support this" for a
 * stale snapshot at the same URL is the failure this repository is named after.
 */

const CONFIG = { base: "https://api.example.test", routes: {} };

function serve(handler: (url: string) => Response | Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => handler(String(input))));
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  // `apiBase` memoises for the page's lifetime, and each test configures a
  // different world. Clearing the injected override is not enough — the module
  // cache has to go too.
  vi.resetModules();
  delete (globalThis as { __MISQUOTE_API__?: string }).__MISQUOTE_API__;
});

describe("apiBase", () => {
  it("is null when nothing is configured, and does not guess the site origin", async () => {
    serve((url) =>
      url.endsWith("/artifacts/api.json") ? json({ base: null, routes: {} }) : json({}, 404),
    );
    const { apiBase: fresh } = await import("@/lib/api");
    expect(await fresh()).toBeNull();
  });

  it("takes the injected override, so a built export can be repointed", async () => {
    (globalThis as { __MISQUOTE_API__?: string }).__MISQUOTE_API__ = "https://elsewhere.test/";
    expect(await apiBase()).toBe("https://elsewhere.test");
  });
});

describe("loadLive", () => {
  it("labels a live answer as live", async () => {
    serve((url) =>
      url.endsWith("/artifacts/api.json") ? json(CONFIG) : json({ swaps: 252923 }),
    );
    const { loadLive: fresh } = await import("@/lib/api");

    const got = await fresh<{ swaps: number }>("/tape");
    expect(got.ok && got.source).toBe("live");
    expect(got.ok && got.value.swaps).toBe(252923);
  });

  it("does NOT fall back when the service refuses", async () => {
    // The refusal names a remedy. Falling back here would replace it with a
    // snapshot and lose the one field a reader could act on.
    serve((url) => {
      if (url.endsWith("/artifacts/api.json")) return json(CONFIG);
      if (url.includes("/artifacts/")) return json({ swaps: 1 });
      return json(
        {
          detail: {
            error: "the tape covers 3h and a quote needs 24h",
            remedy: "make indexer",
            note: "This is an absence, not a fault.",
          },
        },
        409,
      );
    });
    const { loadLive: fresh, RefusalError: Refusal } = await import("@/lib/api");

    const got = await fresh("/quote", { fallback: "warden.json" });
    expect(got.ok).toBe(false);
    if (got.ok) return;

    expect(got.error).toBeInstanceOf(Refusal);
    expect(got.error.kind).toBe("refused");
    expect((got.error as RefusalError).remedy).toBe("make indexer");
    expect((got.error as RefusalError).status).toBe(409);
  });

  it("falls back to the artifact when the host is unreachable, and says so", async () => {
    serve((url) => {
      if (url.endsWith("/artifacts/api.json")) return json(CONFIG);
      if (url.includes("/artifacts/")) return json({ swaps: 99 });
      throw new TypeError("network down");
    });
    const { loadLive: fresh } = await import("@/lib/api");

    const got = await fresh<{ swaps: number }>("/tape", { fallback: "warden.json" });
    expect(got.ok && got.source).toBe("artifact");
    expect(got.ok && got.value.swaps).toBe(99);
  });

  it("falls back on a 5xx, because nothing was answered", async () => {
    serve((url) => {
      if (url.endsWith("/artifacts/api.json")) return json(CONFIG);
      if (url.includes("/artifacts/")) return json({ swaps: 7 });
      return json({ detail: { error: "boom", remedy: "retry" } }, 503);
    });
    const { loadLive: fresh } = await import("@/lib/api");

    const got = await fresh<{ swaps: number }>("/tape", { fallback: "warden.json" });
    expect(got.ok && got.source).toBe("artifact");
  });

  it("refuses rather than inventing a value when there is no fallback", async () => {
    serve((url) => (url.endsWith("/artifacts/api.json") ? json({ base: null }) : json({}, 404)));
    const { loadLive: fresh } = await import("@/lib/api");

    const got = await fresh("/wallet/0x0/positions");
    expect(got.ok).toBe(false);
    expect(!got.ok && got.error.kind).toBe("network");
  });
});
