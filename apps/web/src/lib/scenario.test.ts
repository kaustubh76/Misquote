import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { activeScenarioName, scenarioResponse, SCENARIO_PARAM } from "@/lib/scenario";

/**
 * The four things that stop a recorded answer being mistaken for a live one.
 *
 * `loadLive`'s own docstring forbids substituting a snapshot for a refusal —
 * "replacing a considered no with a stale yes, at the same URL, with nothing
 * saying which happened — which is the failure this repository is named after".
 * A simulation mode is that failure unless each of these holds.
 */
const at = (search: string) => {
  window.history.replaceState({}, "", `/quote/${search}`);
};

beforeEach(() => at(""));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("selecting a scenario", () => {
  it("is off unless the URL asks for one", () => {
    expect(activeScenarioName()).toBeNull();
  });

  it("reads the URL and nothing else", () => {
    // Not an env var, which bakes into the export and would ship a simulated
    // build; not localStorage, which would survive a reload of a clean URL and
    // make a simulated page indistinguishable to anyone who did not open it.
    at(`?${SCENARIO_PARAM}=quote-thin-tape`);
    expect(activeScenarioName()).toBe("quote-thin-tape");

    // jsdom here has no localStorage, which is why this is stubbed rather than
    // written to: the claim is that the reader never consults it, and a stub
    // that would answer if asked proves that better than an absent API does.
    const store = { getItem: vi.fn(() => "quote-thin-tape"), setItem: vi.fn() };
    vi.stubGlobal("localStorage", store);
    at("");
    expect(activeScenarioName()).toBeNull();
    expect(store.getItem).not.toHaveBeenCalled();
  });

  it("refuses a name it does not recognise rather than falling through to one", () => {
    // The failure this prevents is subtle: showing a reader some state they did
    // not select, while the banner tells them they did.
    at(`?${SCENARIO_PARAM}=../../etc/passwd`);
    expect(activeScenarioName()).toBeNull();

    at(`?${SCENARIO_PARAM}=`);
    expect(activeScenarioName()).toBeNull();
  });
});

describe("matching a recorded path", () => {
  const serve = (scenario: unknown) =>
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify(scenario), {
            status: 200,
            headers: { "content-type": "application/json" },
          })
      )
    );

  const fixture = {
    label: "A quote the tape cannot support",
    why: "because it is the hardest state to reach on demand",
    responses: {
      "/quote/eligibility/{address}": { status: 200, body: { held: 2 } },
      "/quote/job/{id}": { status: 200, body: { status: "done" } },
    },
  };

  it("answers for any address, because a demo types one no fixture can know", async () => {
    at(`?${SCENARIO_PARAM}=wallet-two-pools`);
    serve(fixture);

    const hit = await scenarioResponse("/quote/eligibility/0xabc");
    expect(hit?.body).toEqual({ held: 2 });
  });

  it("does not answer for a longer path that merely starts the same", async () => {
    // `/quote/job/{id}` must not answer for `/quote/job/{id}/stream`: the
    // stream is a different question and a scenario that stubbed one would
    // silently be answering the other.
    at(`?${SCENARIO_PARAM}=wallet-two-pools`);
    serve(fixture);

    expect(await scenarioResponse("/quote/job/abc/stream")).toBeUndefined();
  });

  it("is invisible for a path it does not declare", async () => {
    // Undefined rather than a miss-shaped answer, so a fixture stubbing only
    // the quote leaves the journal on the ordinary live-or-recorded path. That
    // mixed page is honest because `AnsweredBy` qualifies one answer, not the
    // page.
    at(`?${SCENARIO_PARAM}=wallet-two-pools`);
    serve(fixture);

    expect(await scenarioResponse("/journal/warden")).toBeUndefined();
  });

  it("ignores a file that does not say what it is", async () => {
    // The banner has to be able to name the state a reader is looking at. A
    // fixture with no label cannot be announced, so it is not honoured.
    at(`?${SCENARIO_PARAM}=unlabelled`);
    serve({ responses: { "/journal/{agent}": { status: 200, body: {} } } });

    expect(await scenarioResponse("/journal/warden")).toBeUndefined();
  });
});
