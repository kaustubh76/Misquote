import { readFileSync } from "node:fs";
import { join } from "node:path";
import { vi } from "vitest";

const ARTIFACTS = join(process.cwd(), "public", "artifacts");

/**
 * One read per artifact per worker, rather than one per fetch.
 *
 * Every view fetches its data on mount, so a page test triggers a `readFileSync`
 * of the file it renders — and `assumptions.json` is 181,816 bytes. `/assumptions`
 * has eleven tests and each one re-read all of it, synchronously, on a thread
 * vitest also runs three other suites on.
 *
 * That was the flake. `vitest.config.ts` blamed re-serialisation and raised
 * `testTimeout` to 15s over it, and the raise did not hold: the `/assumptions`
 * suites still failed one to three times per full run, always under file
 * parallelism, and always passing on a rerun or with `--no-file-parallelism`.
 * The config's own note says a flake "teaches people to rerun rather than to
 * read", which is exactly what a timeout raise teaches.
 *
 * Safe to memoise because the artifacts do not change during a run: nothing in
 * the suite writes to `public/artifacts`, and a test that wants different bytes
 * passes `overrides`, which is checked before this map is ever consulted.
 */
const FILES = new Map<string, string>();

function artifactBody(name: string): string {
  const hit = FILES.get(name);
  if (hit !== undefined) return hit;
  const body = readFileSync(join(ARTIFACTS, name), "utf8");
  FILES.set(name, body);
  return body;
}

/**
 * Serve the real generated artifacts to a page under test.
 *
 * Every view fetches its data at runtime, so a page test that stubs the data
 * proves only that the component can render the shape the test author imagined.
 * These read the same files `make artifacts` writes and the browser requests,
 * which is what makes a page test capable of catching an emitter change.
 */
/**
 * What the current test declared missing or overridden.
 *
 * Read by the `@/lib/build-artifact` mock in `vitest.setup.ts`, so a page's
 * **build-time** read sees the same bytes its runtime fetch will. In production
 * those two are the same file by construction; without this they were not, and
 * that gap is a race every prerendering page under test could lose.
 *
 * Module-level rather than passed around, because the code that has to consult
 * it is a server-only module a test never touches directly.
 */
let declared: { missing: Set<string>; overrides: Record<string, unknown> } = {
  missing: new Set(),
  overrides: {},
};

/**
 * The artifact a prerender should see, or `MISSING` when the test removed it.
 *
 * Exists so `readArtifact` can be made to agree with `fetch`. A page seeded from
 * disk while the fetch serves a fixture paints the real data first, and any
 * "is it ready?" signal fires against that paint — so assertions run against
 * whichever of the two the timing happened to deliver. Where the committed
 * artifact agrees with the fixture, the test passes by luck.
 *
 * That cost two real flakes: `/vectors` waiting on `aria-busy`, which is false
 * on the first paint when `initial` is supplied, and `/registry` finding the
 * four "register" links of the committed artifact where its fixture declared
 * one. Both read as selector problems and were timing.
 */
export const MISSING = Symbol("artifact removed by this test");

export function prerenderedArtifact(
  name: string
): unknown | typeof MISSING | undefined {
  if (declared.missing.has(name)) return MISSING;
  if (name in declared.overrides) return declared.overrides[name];
  return undefined;
}

export function serveArtifacts(
  options: { missing?: string[]; overrides?: Record<string, unknown> } = {}
) {
  const missing = new Set(options.missing ?? []);
  const overrides = options.overrides ?? {};
  declared = { missing, overrides };

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);

      // Matched as a full path, deliberately. Matching on the basename made
      // every request look correct regardless of its prefix, which is how a
      // page-relative "artifacts/warden.json" — 404 on every route but "/" —
      // passed the whole suite while the built site showed an error state.
      if (!url.startsWith("/artifacts/")) {
        throw new Error(
          `fetch("${url}") is not root-absolute. Artifact requests must start ` +
            `with "/artifacts/", or they resolve against the current route and ` +
            `404 everywhere except "/".`
        );
      }
      const name = url.slice("/artifacts/".length);

      if (missing.has(name)) {
        return new Response("<!DOCTYPE html><title>404</title>", {
          status: 404,
          statusText: "Not Found",
          headers: { "content-type": "text/html" },
        });
      }

      // A mutated body, for asserting that a figure is *read* rather than
      // restated: change the artifact and the page must change with it.
      if (name in overrides) {
        return new Response(JSON.stringify(overrides[name]), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }

      try {
        const body = artifactBody(name);
        return new Response(body, {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      } catch {
        return new Response("<!DOCTYPE html><title>404</title>", {
          status: 404,
          statusText: "Not Found",
          headers: { "content-type": "text/html" },
        });
      }
    })
  );
}

export function readArtifact<T>(name: string): T {
  // Parsed fresh from a cached string, deliberately. Callers mutate what they
  // get back to build `overrides`, so handing out a shared object would let one
  // test's edit reach the next one.
  return JSON.parse(artifactBody(name)) as T;
}

/**
 * A matcher for text taken verbatim out of an artifact.
 *
 * Artifact strings are prose, and prose contains regex metacharacters — the
 * kappa label is `kappa = 0.0500/tick (provisional default; fit r^2 = 0.00)`,
 * where the parentheses become a capture group and the caret an anchor. Passed
 * to `new RegExp` unescaped it matches nothing, and the test fails against
 * correct output. Escape, then match as a substring.
 */
export function textFrom(value: string): RegExp {
  return new RegExp(value.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&"));
}
