import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

/**
 * Static export, deliberately — and the property it was chosen for, stated
 * accurately.
 *
 * The page this replaces imported no framework and called no backend, so it
 * rendered identically when every server behind it was down, which is the state
 * a demo is most likely to find them in. `output: "export"` keeps half of that
 * through the rewrite and this comment used to claim all of it.
 *
 * **What is true.** `pnpm build` produces a directory any static server can
 * serve with no node process alive, and `public/artifacts/*.json` is copied
 * verbatim, so the Python emitters keep writing to the same path and the
 * artifacts stay readable — and editable — by hand. No page reaches a network
 * at load beyond its own JSON.
 *
 * **What was not.** Every view is `"use client"` and fetches after mount, so
 * "renders identically" did not survive: with JavaScript off, the built HTML
 * for `/agent/warden` was the nav and the word "warden", and no page showed a
 * figure. Nothing detected that for months, because every check in this
 * repository runs JavaScript — `check-pages.mjs` launches Chromium and then
 * waits for the fetch, and vitest is jsdom, which always runs effects.
 *
 * **Where it stands.** Two routes hold the property: `/` and `/agent/[slug]`,
 * which are the walk a reader takes — landing page, agent card, detail. Their
 * `page.tsx` reads the artifact from disk at build time and hands it down as a
 * first paint, and the client still fetches, so editing a JSON and reloading
 * still works. The other eight render their heading and lede and then need
 * JavaScript for every number, and `layout.tsx`'s `<noscript>` is what a reader
 * without it gets.
 *
 * `check-pages.mjs` now loads those two routes with `javaScriptEnabled: false`
 * and fails if the body text falls under a floor. That guard, not this comment,
 * is what keeps the claim honest — a comment cannot go red.
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
