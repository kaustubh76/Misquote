import { afterEach, describe, expect, it, vi } from "vitest";
import { apiBase, loadLive, postLive, RefusalError } from "@/lib/api";

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

/**
 * A scenario is a different code path, not a different outcome of the same one.
 *
 * This is the guarantee the whole simulation design rests on, and it is worth
 * asserting directly rather than inferring from the label: if a scenario ever
 * reached the network, a simulated page and a live one would differ only by a
 * string, and the string is set by the code being tested.
 */
describe("a scenario answers before the network is consulted", () => {
  const at = (search: string) => window.history.replaceState({}, "", `/quote/${search}`);

  const fixture = {
    label: "A quote the tape cannot support",
    why: "because it is the hardest state to reach on demand",
    responses: {
      "/quote/eligibility/{address}": { status: 200, body: { held: 2 } },
      "POST /quote": {
        status: 409,
        body: { detail: { error: "the tape supports 6 windows", remedy: "index more history" } },
      },
    },
  };

  /** Answers for the scenario file and records everything else it is asked for. */
  const serveScenarioOnly = () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        if (url.includes("/scenarios/")) {
          return new Response(JSON.stringify(fixture), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }
        throw new Error(`a scenario must not reach ${url}`);
      })
    );
    return calls;
  };

  afterEach(() => {
    at("");
    vi.unstubAllGlobals();
  });

  it("issues no request to the API, even with one configured and reachable", async () => {
    vi.stubGlobal("__MISQUOTE_API__", "https://api.example.test");
    at("?scenario=wallet-two-pools");
    const calls = serveScenarioOnly();

    const got = await loadLive<{ held: number }>("/quote/eligibility/0xabc");

    expect(got.ok && got.value).toEqual({ held: 2 });
    expect(calls.filter((u) => u.includes("api.example.test"))).toHaveLength(0);
  });

  it("labels the answer simulated, and cannot label it anything else", async () => {
    vi.stubGlobal("__MISQUOTE_API__", "https://api.example.test");
    at("?scenario=wallet-two-pools");
    serveScenarioOnly();

    const got = await loadLive<unknown>("/quote/eligibility/0xabc");

    expect(got.ok && got.source).toBe("simulated");
  });

  it("short-circuits a POST too, which is the path the flagship flow takes", async () => {
    // The assertion whose absence was the defect.
    //
    // `scenarioResponse` was reachable only from `loadLive`, and `/quote`'s
    // submission was a raw `fetch` below `apiBase()`. So the one fixture written
    // for the most important refusal on the site — `quote-thin-tape`, keyed
    // `"POST /quote"` — could never match, and a page showing the simulation
    // banner issued a real request to production.
    //
    // Nothing caught it: the browser gate loaded that URL with `needle: null`
    // and asserted zero API contact, which held *because nothing was ever
    // submitted*. A check reporting its own inability to run as a pass — P-30.
    vi.stubGlobal("__MISQUOTE_API__", "https://api.example.test");
    at("?scenario=quote-thin-tape");
    const calls = serveScenarioOnly();

    const got = await postLive<unknown>("POST /quote", { pool: "0xabc" });

    expect(got.ok).toBe(false);
    expect(!got.ok && got.error).toBeInstanceOf(RefusalError);
    expect(!got.ok && got.error.message).toContain("the tape supports 6 windows");
    // The load-bearing half, and this time it is not vacuous: a POST *was*
    // attempted, and it still reached nothing.
    expect(calls.filter((u) => u.includes("api.example.test"))).toHaveLength(0);
  });

  it("cannot label a posted scenario answer anything but simulated", async () => {
    vi.stubGlobal("__MISQUOTE_API__", "https://api.example.test");
    at("?scenario=wallet-two-pools");
    serveScenarioOnly();

    // `wallet-two-pools` does not declare `POST /quote`, so this falls through
    // to the ordinary route — the invisibility rule, checked on the new path.
    const declared = await postLive<{ held: number }>("/quote/eligibility/0xabc", {});
    expect(declared.ok && declared.source).toBe("simulated");
  });

  it("does not fall back for a submission, because a stale 202 is a job nobody queued", async () => {
    // `loadLive` may answer from an artifact; a POST may not. Replaying a
    // recorded job id would hand the caller a poller that never resolves.
    at("");
    vi.stubGlobal("__MISQUOTE_API__", "");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));

    const got = await postLive<unknown>("POST /quote", { pool: "0xabc" });

    expect(got.ok).toBe(false);
    expect(!got.ok && got.error.message).toContain("no precomputed fallback");
  });

  it("returns a scenario refusal as terminal, never replacing it with a fallback", async () => {
    // The rule this file's own docstring sets, applied to the new path: a
    // refusal is the service answering, and substituting a snapshot for it is
    // "replacing a considered no with a stale yes".
    at("?scenario=quote-thin-tape");
    serveScenarioOnly();

    const got = await loadLive<unknown>("POST /quote", { fallback: "journal.json" });

    expect(got.ok).toBe(false);
    expect(!got.ok && got.error).toBeInstanceOf(RefusalError);
    expect(!got.ok && got.error.message).toContain("the tape supports 6 windows");
  });

  it("leaves a path the scenario does not declare on the ordinary route", async () => {
    // A fixture stubbing only the quote must not swallow the journal. The
    // mixed page is honest because `AnsweredBy` qualifies one answer, not the
    // page.
    vi.stubGlobal("__MISQUOTE_API__", "https://api.example.test");
    at("?scenario=wallet-two-pools");
    const calls = serveScenarioOnly();

    await loadLive<unknown>("/journal/warden").catch(() => undefined);

    // It tried the API, which is the point: the scenario was invisible here.
    expect(calls.some((u) => u.includes("api.example.test/journal/warden"))).toBe(true);
  });
});
