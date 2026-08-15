import { readFileSync } from "node:fs";
import { join } from "node:path";
import { vi } from "vitest";

const ARTIFACTS = join(process.cwd(), "public", "artifacts");

/**
 * Serve the real generated artifacts to a page under test.
 *
 * Every view fetches its data at runtime, so a page test that stubs the data
 * proves only that the component can render the shape the test author imagined.
 * These read the same files `make artifacts` writes and the browser requests,
 * which is what makes a page test capable of catching an emitter change.
 */
export function serveArtifacts(options: { missing?: string[] } = {}) {
  const missing = new Set(options.missing ?? []);

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
            `404 everywhere except "/".`,
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

      try {
        const body = readFileSync(join(ARTIFACTS, name), "utf8");
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
    }),
  );
}

export function readArtifact<T>(name: string): T {
  return JSON.parse(readFileSync(join(ARTIFACTS, name), "utf8")) as T;
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
