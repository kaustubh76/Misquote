import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

/**
 * Static export, deliberately.
 *
 * The page this replaces earned its keep by importing no framework and calling
 * no backend, so it rendered identically when every server behind it was down —
 * which is the state a demo is most likely to find them in. `output: "export"`
 * keeps that property through the rewrite: `pnpm build` produces `out/`, a
 * directory of files that any static server (including `python3 -m http.server`)
 * can serve with no node process alive.
 *
 * `public/artifacts/*.json` is copied verbatim into `out/`, so the Python
 * emitters keep writing to the same path they always did and the artifacts stay
 * readable — and editable — by hand.
 */
const nextConfig: NextConfig = {
  output: "export",

  // Pinned explicitly. Next walks up looking for a lockfile and finds a stray
  // one in the home directory, which sits above this repo — it would silently
  // trace from the wrong root.
  outputFileTracingRoot: fileURLToPath(new URL("../..", import.meta.url)),

  // Static export has no image optimiser to call at runtime.
  images: { unoptimized: true },

  // Emit `about/index.html` rather than `about.html`, so a plain file server
  // resolves `/about` without rewrite rules.
  trailingSlash: true,

  typescript: { ignoreBuildErrors: false },
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
