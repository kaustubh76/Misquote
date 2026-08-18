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

  // Overridable so `make web-check` builds somewhere other than the `.next` a
  // running `make web` is serving from. Sharing it broke the dev server on
  // every check with `Cannot find module './393.js'`. Necessary but not
  // sufficient — see the note on the `web-check` target.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",

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

  // There is no ESLint in this app, and this line says so rather than
  // configuring one. `package.json` carried a `"lint": "eslint ."` script for
  // the whole life of the front-end while `eslint` was in no dependency list
  // and no config file existed anywhere — so it had never once run, and the
  // only way to find that out was to type it. The script is gone.
  //
  // What stands in for it: `tsc --noEmit` under strict, plus the guards in
  // `tests/web/`, which check the things a general-purpose linter would not —
  // that a comment naming a file names one that exists, that an artifact still
  // matches the Python it is a copy of, that no `.tsx` writes a raw `<h2>`,
  // that every exported function is reachable. Adding ESLint later is a fine
  // decision; inheriting a script that pretends it is already here is not.
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
