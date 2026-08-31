import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * An artifact, read from disk while the site is being built.
 *
 * **Server components only.** This imports `node:fs`; a `"use client"` module
 * that pulls it in is a defect, and `tests/web/test_client_boundary.py` is what
 * says so.
 *
 * ## Why the boundary needs a guard rather than care
 *
 * `lib/routes.ts` records the mirror-image mistake — importing a value out of a
 * client module into a server one — and notes that it fails at prerender rather
 * than at typecheck, with `TypeError: g.LINKS.map is not a function`. Loud, and
 * findable.
 *
 * This direction is quieter, and the `try/catch` below is why. Pulled into a
 * client graph, this does not throw: it returns `undefined`, every page seeded
 * from it falls back to its spinner, the fetch covers for it a moment later, and
 * the build stays green. The property would be gone and nothing would say so —
 * which is exactly how the export came to render no numbers for months.
 *
 * ## Why a miss is not an error
 *
 * A missing artifact is a state this site renders on purpose: "nothing has
 * generated the cards yet, run `make showcase-demo`". The client load owns that
 * path, and it is where the remedy text and the tests already live. Throwing
 * here would replace a page that tells a reader what to run with a build that
 * fails at them instead.
 *
 * The value is a *first paint*, never the truth. Every view that takes one keeps
 * its `useEffect`, so the fetch overwrites it — which is what preserves the
 * promise the agent route has carried since it was written: editing a JSON and
 * reloading still works.
 */
export function readArtifact<T>(name: string): T | undefined {
  const path = join(process.cwd(), "public", "artifacts", name);
  try {
    return JSON.parse(readFileSync(path, "utf8")) as T;
  } catch {
    return undefined;
  }
}

/**
 * Every scenario fixture on disk, read while the site is being built.
 *
 * **Server components only**, for the reason above.
 *
 * The list is *derived from the directory* rather than written down, which is
 * the same discipline the not-built ledger uses: a fixture that exists and is
 * not listed, or a name listed and long since deleted, are both states nobody
 * would notice. `/demo` renders whatever is here, so adding a fixture publishes
 * it and deleting one un-publishes it.
 *
 * The `label`/`why` requirement is not this function's invention — `scenario.ts`
 * already refuses to honour a fixture missing either, on the grounds that "a
 * file that does not describe itself is not a scenario". Applying the same bar
 * here keeps `/demo` from advertising a name the loader will decline.
 */
export interface ScenarioSummary {
  name: string;
  label: string;
  why: string;
  /** The API paths it answers for, so the page can say what it covers. */
  paths: string[];
  /**
   * Where this state is worth looking at.
   *
   * Carried by the fixture rather than derived from its paths: a fixture
   * stubbing `/quote/eligibility/{address}` could belong on `/quote` or on a
   * wallet page that does not exist, and guessing would send a reader somewhere
   * the state does not appear.
   */
  route: string;
}

export function readScenarios(): ScenarioSummary[] {
  const dir = join(process.cwd(), "public", "scenarios");
  let names: string[];
  try {
    names = readdirSync(dir).filter((f) => f.endsWith(".json"));
  } catch {
    return [];
  }

  const found: ScenarioSummary[] = [];
  for (const file of names.sort()) {
    try {
      const body = JSON.parse(readFileSync(join(dir, file), "utf8"));
      if (typeof body?.label !== "string" || typeof body?.why !== "string") continue;
      found.push({
        name: file.replace(/\.json$/, ""),
        label: body.label,
        why: body.why,
        paths: Object.keys(body.responses ?? {}),
        route: typeof body.route === "string" ? body.route : "",
      });
    } catch {
      // A malformed fixture is one the loader would refuse too. Skipping it
      // here shows the reader the same set the site can actually serve.
      continue;
    }
  }
  return found;
}
