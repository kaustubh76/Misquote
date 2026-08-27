/**
 * Recorded API answers, selected by the URL, that can never be mistaken for live.
 *
 * ## What this is for
 *
 * The interesting states of this site are the ones a demo cannot reach. `/quote`
 * refuses when the tape cannot support a quote; `/activate` reads a capability
 * that says no module is verified; the journal 404s for an agent that has never
 * run. Every one of those is a considered answer from a service, every one is
 * the kind of thing this project exists to show, and none of them can be
 * produced on demand — the flagship `/quote` flow needs a running API and a
 * worker, and the exported site has neither.
 *
 * So the states are recorded and replayed. A scenario is a file of API
 * responses keyed by path, chosen with `?scenario=name`.
 *
 * ## The rule this must not break
 *
 * `lib/api.ts::loadLive` falls back to a snapshot on a network failure and on
 * 5xx, and **never on a refusal**, because "quietly substituting a precomputed
 * snapshot for 'the tape cannot support this quote' would replace a considered
 * no with a stale yes, at the same URL, with nothing saying which happened —
 * which is the failure this repository is named after."
 *
 * A simulation mode that made the site look like it works when the backend is
 * down would be exactly that failure, dressed as a feature. Four things stop it:
 *
 * 1. **A scenario is a different code path, not a different outcome.** It
 *    short-circuits above `apiBase()`, so under a scenario **no request is
 *    issued at all**. Simulated data cannot arrive by the route live data
 *    arrives by.
 * 2. **It can only produce `source: "simulated"`.** There is no branch that
 *    returns a scenario answer as `"live"` or `"artifact"`. The label is
 *    derived from *where the answer came from*, never from what came back —
 *    which is why it cannot be wrong.
 * 3. **A scenario may refuse, and its refusal is terminal**, exactly as a live
 *    one is. Refusals are the states most worth being able to show; a scenario
 *    that could only succeed would be a demo of the happy path, which is the
 *    thing every other marketplace already has.
 * 4. **It is never the default and never sticky.** Read from `location.search`
 *    only — not an env var, which would bake into the export; not
 *    `localStorage`, which would survive a reload of a clean URL and make a
 *    simulated page indistinguishable from a real one to anyone who did not
 *    open it themselves.
 *
 * A fifth falls out of the fourth: because the name is read from the URL in an
 * effect, a simulated page cannot prerender. The static export has no simulated
 * HTML in it at all.
 *
 * ## Why the fixtures live in `public/`
 *
 * `tests/web/test_artifact_contract.py::test_no_artifact_number_is_hardcoded_in_the_ui`
 * scans every non-test `.ts`/`.tsx` under `src/` for values that appear in the
 * published artifacts. Fixtures are artifact-shaped by construction and would
 * be flagged on sight. Under `public/` they are outside that scan's file glob —
 * structurally, rather than by an allowlist, which is the pattern this codebase
 * insists on: "a guard people edit to silence is a guard people stop reading".
 *
 * They are `public/scenarios/` rather than `public/artifacts/` because that
 * same test globs `public/artifacts/*.json` to *build* its forbidden set, and
 * fixture numbers have no business dictating what unrelated components write.
 */

/** The query parameter. One spelling, used by the reader and by the banner. */
export const SCENARIO_PARAM = "scenario";

export interface Scenario {
  name: string;
  /** Shown in the banner. What a reader is looking at. */
  label: string;
  /** Why this state is worth being able to reach. Shown under the label. */
  why: string;
  /**
   * Recorded answers, keyed by API path. A path segment written `{...}`
   * matches any single segment, so one fixture answers for any address a
   * demo types.
   */
  responses: Record<string, { status: number; body: unknown }>;
}

/**
 * The scenario named in the URL, or null.
 *
 * Null for a name nothing matches, deliberately — **not** the first entry.
 * Falling through to some scenario because the URL asked for another would be
 * showing a reader a state they did not select while telling them, in the
 * banner, that they did.
 */
export function activeScenarioName(): string | null {
  if (typeof window === "undefined") return null;
  const name = new URLSearchParams(window.location.search).get(SCENARIO_PARAM);
  return name && /^[a-z0-9-]{1,40}$/.test(name) ? name : null;
}

/** Cached per name for the page's lifetime, as `apiBase` caches `api.json`. */
const loaded = new Map<string, Scenario | null>();

export async function activeScenario(): Promise<Scenario | null> {
  const name = activeScenarioName();
  if (!name) return null;

  const hit = loaded.get(name);
  if (hit !== undefined) return hit;

  let scenario: Scenario | null = null;
  try {
    // Root-absolute, like every other fetch in this app. `src/test/harness.tsx`
    // throws on anything else, and the reason is in its message: a
    // page-relative path resolves against the current route and 404s
    // everywhere except "/".
    const response = await fetch(`/scenarios/${name}.json`, { cache: "no-store" });
    if (response.ok) {
      const body = (await response.json()) as Scenario;
      // A file that does not describe itself is not a scenario. The banner has
      // to be able to say what a reader is looking at.
      if (body && typeof body.label === "string" && typeof body.why === "string") {
        scenario = { ...body, name };
      }
    }
  } catch {
    scenario = null;
  }

  loaded.set(name, scenario);
  return scenario;
}

/**
 * Match a recorded path against a requested one, `{...}` matching any segment.
 *
 * Positional rather than by name: `/quote/eligibility/{address}` answers for
 * every address, because a demo types one and no fixture can know it in
 * advance. Segment counts must agree, so `/quote/job/{id}` does not answer for
 * `/quote/job/{id}/stream`.
 */
function matches(pattern: string, path: string): boolean {
  const a = pattern.split("?")[0]!.split("/");
  const b = path.split("?")[0]!.split("/");
  if (a.length !== b.length) return false;
  return a.every((segment, i) => (segment.startsWith("{") ? b[i] !== "" : segment === b[i]));
}

/**
 * The recorded answer for a path, or undefined if this scenario does not cover it.
 *
 * Undefined is the important return. A scenario is total for the paths it
 * declares and **invisible** for the ones it does not, so a fixture that only
 * stubs `/quote/eligibility/…` leaves the journal on the ordinary live-or-
 * recorded path. That mixed page is honest because `AnsweredBy` qualifies one
 * answer rather than the page — its docstring: "This qualifies one answer the
 * reader just asked for, not the page."
 */
export async function scenarioResponse(
  path: string
): Promise<{ status: number; body: unknown } | undefined> {
  const scenario = await activeScenario();
  if (!scenario) return undefined;

  const pattern = Object.keys(scenario.responses).find((p) => matches(p, path));
  return pattern === undefined ? undefined : scenario.responses[pattern];
}
