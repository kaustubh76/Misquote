import { readFileSync } from "node:fs";
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
