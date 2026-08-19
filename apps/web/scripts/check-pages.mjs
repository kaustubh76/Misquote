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
 * So this checks the properties only a browser knows:
 *   - no console errors or failed requests on any route, in either theme
 *   - no horizontal overflow, including at 390px
 *   - the current page is marked in the nav, and is actually on screen — the
 *     nav is a hidden-scrollbar scroller, so at 390px the active pill sat two
 *     screens to the right of the visible strip and nothing was highlighted
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
  ["venue", "/venue/"],
  ["advantage", "/advantage/"],
  ["agent-warden", "/agent/warden/"],
  ["methods", "/methods/"],
  ["vectors", "/vectors/"],
  ["assumptions", "/assumptions/"],
  ["registry", "/registry/"],
  ["vetting", "/vetting/"],
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
const titles = new Map();

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

    // The nav overflows to a horizontal scroller at narrow widths, so the
    // current page's pill can sit outside the visible strip. At 390px /status
    // showed "Misquote · Overview · Advantage" with nothing highlighted: the
    // nav answered "what else is there" and not "where am I". Only a real
    // browser can check this — jsdom lays nothing out, so `offsetLeft` and
    // `clientWidth` are 0 there and any assertion passes vacuously.
    const navCurrent = await page.evaluate(() => {
      const list = document.querySelector('nav[aria-label="Primary"] ul');
      const current = list?.querySelector("[aria-current]");
      if (!list || !current) return { found: false, visible: false };
      const l = list.getBoundingClientRect();
      const c = current.getBoundingClientRect();
      return { found: true, visible: c.left >= l.left - 1 && c.right <= l.right + 1 };
    });
    const navProblem = !navCurrent.found
      ? "no nav link marked aria-current"
      : !navCurrent.visible
        ? "the current page's nav link is scrolled out of view"
        : null;
    if (navProblem) failures.push(`${tag}: ${navProblem}`);

    // Every route shipped the same <title> once, because all of them were
    // client components and none could export metadata. Seven identical tab
    // labels, seven identical history entries, and a route announcer reading
    // the wrong page name back to a screen reader.
    const title = await page.title();
    const seen = titles.get(title);
    if (seen && seen !== name) {
      failures.push(`${name} and ${seen} share the title "${title}"`);
    }
    titles.set(title, name);

    if (shotsAt) {
      await page.screenshot({ path: `${shotsAt}/${tag}.png`, fullPage: width >= 1280 });
    }

    if (problems.length) failures.push(`${tag}: ${problems.slice(0, 4).join(" | ")}`);
    if (overflow > 0) failures.push(`${tag}: ${overflow}px of horizontal overflow`);

    // The per-line verdict has to include everything the run can fail on, or a
    // route prints "ok" and the summary at the bottom disagrees with it.
    const clean = overflow === 0 && problems.length === 0 && !navProblem;
    console.log(
      `  ${clean ? "ok  " : "FAIL"}  ${tag.padEnd(30)}` +
        `  overflow=${overflow}px  problems=${problems.length}` +
        (navProblem ? `  nav=${navProblem}` : ""),
    );
  }

  await context.close();
}

// --- the property `next.config.ts` claims, with JavaScript off ---------------
//
// `output: "export"` is justified in `next.config.ts` by the page it replaced
// having "rendered identically when every server behind it was down". The
// rewrite lost that and nothing noticed for months, because every check in this
// repository runs with JavaScript on: this script launches Chromium and then
// waits 350ms *for the fetch*, and the vitest suite is jsdom, which always runs
// effects.
//
// So the claim could not go stale detectably. This is the check that makes it
// detectable, and every route holds the property now.
//
// **The floor is per route and the needle matters more.** A floor only catches a
// page that collapses to its heading; it cannot catch a page that renders its
// prose and loses its numbers. `/methods` is the case that proves it — it never
// gated on the artifact, so it prerendered its entire argument with an em dash
// where every figure belonged, and a global floor would have called that fine.
// Its needle carries a value for that reason.
//
// Needles are matched against whitespace-collapsed `innerText`, so they must not
// straddle a span boundary that emits no space, and each is a string the view
// produces only from artifact data — never from its own lede.
//
// They are also matched **as rendered**: `innerText` applies `text-transform`,
// so an eyebrow written `min_observations` in the JSX arrives here as
// `MIN_OBSERVATIONS`. Three of these were wrong on the first run for exactly
// that reason, which is why they were read off the built page rather than
// guessed from the source.
const NO_JS = [
  // route, minimum characters of body text, a string that must be present
  ["/", 2000, "PancakeSwap"],
  ["/venue/", 3000, "PancakeV3PoolDeployer"],
  ["/advantage/", 2500, "COUNTERFACTUAL"],
  // 2,509 characters before the conversion against 2,746 after — the floor here
  // is nearly useless and the needle is the whole guard.
  ["/methods/", 2600, "MIN_OBSERVATIONS = 30"],
  ["/vectors/", 2000, "fee_growth_inside"],
  // The sheet every citation on the site points into, inlined. A prerendered
  // `/venue` whose P-1 link lands on a page needing JavaScript is a dead link.
  ["/assumptions/", 50000, "none filtered out"],
  ["/registry/", 2500, "JOB STATES"],
  ["/vetting/", 3500, "factory resolves it"],
  ["/status/", 3000, "kill switch"],
  ["/agent/warden/", 2000, "in range"],
];

const noJs = await browser.newContext({ javaScriptEnabled: false });
const bare = await noJs.newPage();

for (const [path, floor, needle] of NO_JS) {
  await bare.goto(BASE + path, { waitUntil: "domcontentloaded" });
  const text = (await bare.evaluate(() => document.body.innerText)).replace(/\s+/g, " ").trim();

  if (text.length < floor) {
    failures.push(`${path} without JS: ${text.length} chars of body text, floor is ${floor}`);
  }
  if (!text.includes(needle)) {
    failures.push(`${path} without JS: does not contain ${JSON.stringify(needle)}`);
  }
  const ok = text.length >= floor && text.includes(needle);
  console.log(`  ${ok ? "ok  " : "FAIL"}  ${`no-js ${path}`.padEnd(30)}  ${text.length} chars`);
}

await noJs.close();
await browser.close();

if (failures.length) {
  console.error(`\n  ${failures.length} failure(s):`);
  for (const f of failures) console.error(`    ${f}`);
  process.exit(1);
}
console.log(`\n  every route clean in both themes and at 390px, with ${titles.size} distinct titles.`);
