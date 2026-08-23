import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * The polling fallback is what is tested, and that is the right way round.
 *
 * `EventSource` does not exist in jsdom and cannot be stubbed by the `fetch`
 * mock the rest of this suite uses. Polling is also the production fallback —
 * a buffering proxy makes the stream unreadable, which is exactly when this
 * path runs — and it is the harder of the two to get right, because it has to
 * decide for itself when a job is finished.
 */

const CONFIG = { base: "https://api.example.test", routes: {} };

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("subscribe", () => {
  it("polls until a terminal state and then stops asking", async () => {
    const statuses = [
      { status: "running", progress: { done: 1, total: 2 }, events: 2 },
      { status: "running", progress: { done: 2, total: 2 }, events: 3 },
      { status: "refused", progress: {}, events: 4 },
    ];
    let call = 0;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: RequestInfo | URL) => {
        if (String(url).endsWith("/artifacts/api.json")) return json(CONFIG);
        return json(statuses[Math.min(call++, statuses.length - 1)]);
      }),
    );

    const { subscribe } = await import("@/lib/stream");
    const seen: string[] = [];
    const finished: string[] = [];

    await new Promise<void>((resolve) => {
      subscribe(
        "job1",
        {
          onEvent: (e) => seen.push(e.kind),
          onFinished: (e) => {
            finished.push(e.kind);
            resolve();
          },
          onError: () => resolve(),
        },
        { eventSource: null, pollMs: 1 },
      );
    });

    expect(finished).toEqual(["refused"]);
    // A refusal is delivered, not swallowed: it is the honest answer, and a
    // watcher that only reported `done` would leave the reader waiting forever.
    expect(seen).toContain("refused");

    const before = call;
    await new Promise((r) => setTimeout(r, 20));
    expect(call, "kept polling after a terminal state").toBe(before);
  });

  it("reports the same status once, not on every tick", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: RequestInfo | URL) =>
        String(url).endsWith("/artifacts/api.json")
          ? json(CONFIG)
          : json({ status: "running", progress: { done: 1, total: 9 }, events: 2 }),
      ),
    );

    const { subscribe } = await import("@/lib/stream");
    const seen: number[] = [];
    const stop = subscribe(
      "job1",
      { onEvent: (e) => seen.push(e.seq), onFinished: () => {}, onError: () => {} },
      { eventSource: null, pollMs: 1 },
    );

    await new Promise((r) => setTimeout(r, 30));
    stop();

    // The event count is the sequence: an unchanged log means nothing new
    // happened, and re-firing would make a quiet job look busy.
    expect(seen).toEqual([2]);
  });

  it("stops when unsubscribed, so navigating away does not leave a loop", async () => {
    let call = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: RequestInfo | URL) => {
        if (String(url).endsWith("/artifacts/api.json")) return json(CONFIG);
        call++;
        return json({ status: "running", progress: {}, events: call + 1 });
      }),
    );

    const { subscribe } = await import("@/lib/stream");
    const stop = subscribe(
      "job1",
      { onEvent: () => {}, onFinished: () => {}, onError: () => {} },
      { eventSource: null, pollMs: 1 },
    );

    await new Promise((r) => setTimeout(r, 15));
    stop();
    const after = call;
    await new Promise((r) => setTimeout(r, 25));

    expect(call, "the poll loop outlived its subscriber").toBe(after);
  });

  it("says so when no API is configured rather than watching nothing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ base: null, routes: {} })));

    const { subscribe } = await import("@/lib/stream");
    const errors: string[] = [];

    await new Promise<void>((resolve) => {
      subscribe(
        "job1",
        {
          onEvent: () => {},
          onFinished: () => {},
          onError: (m) => {
            errors.push(m);
            resolve();
          },
        },
        { eventSource: null, pollMs: 1 },
      );
    });

    expect(errors[0]).toContain("make api-config");
  });
});
