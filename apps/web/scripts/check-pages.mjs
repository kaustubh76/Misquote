/**
 * Load the built site in a real browser and fail on what jsdom cannot see.
 *
 *     node scripts/check-pages.mjs [--shots DIR]
 *
 * This exists because the whole suite was green while every route but "/" was
 * silently rendering its error state. The artifact fetch used a page-relative
 * path — `artifacts/warden.json` — and with `trailingSlash: true` every route
 * is a directory, so from `/agent/warden/` it resolved to
 * `/agent/warden/artifacts/warden.json` and 404'd.
 *
 * Nothing caught it. The jsdom page tests stub `fetch` and matched on the
 * basename, so the prefix was invisible to them. The static export returned 200
 * for every *page*, because the page was fine; it was the data underneath that
 * was missing, and the UI correctly reported "not generated". A screenshot was
 * the first thing that showed it.
 *
 * So this checks the two properties only a browser knows:
 *   - no console errors or failed requests on any route, in either theme
 *   - no horizontal overflow, including at 390px
 *
 * Exits non-zero on either. Optionally writes screenshots for a human to look
 * at, which is the other half of not shipping a UI nobody has seen.
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.CHECK_BASE ?? "http://localhost:8099";
const shotsAt = process.argv.includes("--shots")
  ? process.argv[process.argv.indexOf("--shots") + 1]
  : null;

const ROUTES = [
  ["overview", "/"],
  ["advantage", "/advantage/"],
  ["agent-warden", "/agent/warden/"],
  ["methods", "/methods/"],
  ["assumptions", "/assumptions/"],
  ["registry", "/registry/"],
  ["status", "/status/"],
];

const VIEWPORTS = [
  ["dark", 1280],
  ["light", 1280],
  ["dark", 390],
];

if (shotsAt) mkdirSync(shotsAt, { recursive: true });

const browser = await chromium.launch();
const failures = [];

for (const [colorScheme, width] of VIEWPORTS) {
  const context = await browser.newContext({
    viewport: { width, height: 900 },
    colorScheme,
    deviceScaleFactor: shotsAt ? 2 : 1,
  });
  const page = await context.newPage();

  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(`uncaught: ${e}`));
  page.on("requestfailed", (r) => problems.push(`request failed: ${r.url()}`));
  page.on("response", (r) => {
    if (r.status() >= 400) problems.push(`${r.status()} ${r.url()}`);
  });

  for (const [name, path] of ROUTES) {
    const tag = `${name}-${colorScheme}-${width}`;
    problems.length = 0;

    await page.goto(BASE + path, { waitUntil: "networkidle" });
    // The views fetch after mount; give the render a beat to settle.
    await page.waitForTimeout(350);

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );

    if (shotsAt) {
      await page.screenshot({ path: `${shotsAt}/${tag}.png`, fullPage: width >= 1280 });
    }

    if (problems.length) failures.push(`${tag}: ${problems.slice(0, 4).join(" | ")}`);
    if (overflow > 0) failures.push(`${tag}: ${overflow}px of horizontal overflow`);

    console.log(
      `  ${overflow === 0 && problems.length === 0 ? "ok  " : "FAIL"}  ${tag.padEnd(30)}` +
        `  overflow=${overflow}px  problems=${problems.length}`,
    );
  }

  await context.close();
}

await browser.close();

if (failures.length) {
  console.error(`\n  ${failures.length} failure(s):`);
  for (const f of failures) console.error(`    ${f}`);
  process.exit(1);
}
console.log("\n  every route clean in both themes and at 390px.");
