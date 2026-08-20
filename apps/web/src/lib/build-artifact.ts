import { readdirSync, readFileSync } from "node:fs";
import type { ArtifactCensus } from "@/lib/artifacts";
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
 * An artifact that publishes figures but records no commit.
 *
 * Not every file needs one, and the two that do not are named rather than
 * inferred — an artifact silently exempting itself is the thing this census
 * exists to catch.
 */
const EXEMPT: Record<string, string> = {
  "assumptions.json":
    "a projection of docs/ASSUMPTIONS.md and docs/REQUIREMENTS_MATRIX.md, not a run",
};

/** `build.git_sha` for most, top level for `build.json`, which *is* the stamp. */
function shaOf(blob: unknown): string | undefined {
  if (!blob || typeof blob !== "object") return undefined;
  const record = blob as { build?: { git_sha?: unknown }; git_sha?: unknown };
  const sha = record.build?.git_sha ?? record.git_sha;
  return typeof sha === "string" && sha.length > 0 ? sha : undefined;
}

/**
 * What every artifact on this site records about the tree that produced it.
 *
 * **Server components only**, for the same reason as `readArtifact` above.
 *
 * `/status` is a recording of one run of `make status`, not a live reading, and
 * it renders as a wall of verdicts with no way to tell how current they are.
 * On the tree this was written against, its gate read "agent advantage report:
 * 0/3 tasks on chain data" — recorded at `fa185b4` on 18 Aug and false since
 * the chain run landed, sitting under a green heading on a page whose entire
 * subject is what has and has not been checked.
 *
 * Regenerating it would fix that run and not the problem: the gate would go
 * stale again the next time an emitter ran, and nothing would say so. What the
 * page can do without another run is state what is on disk beside it. Six
 * artifacts publish replay results and record no commit at all — every file
 * behind `/`, `/advantage` and the three agent cards — which is also why
 * `go_no_go.py`'s own freshness check has reported UNVERIFIED for weeks. This
 * is the first surface that says so to a reader rather than to a terminal.
 *
 * Absent rather than empty on failure. A census that cannot read the directory
 * knows nothing, and rendering "0 artifacts, all stamped" would be a claim.
 */
export function censusArtifacts(): ArtifactCensus | undefined {
  const dir = join(process.cwd(), "public", "artifacts");

  let names: string[];
  try {
    names = readdirSync(dir).filter((n) => n.endsWith(".json")).sort();
  } catch {
    return undefined;
  }
  if (names.length === 0) return undefined;

  const census: ArtifactCensus = { total: names.length, stamped: [], unstamped: [], exempt: [] };

  for (const name of names) {
    if (name in EXEMPT) {
      census.exempt.push({ name, why: EXEMPT[name]! });
      continue;
    }
    const sha = shaOf(readArtifact(name));
    if (sha) census.stamped.push({ name, sha });
    else census.unstamped.push(name);
  }

  return census;
}
