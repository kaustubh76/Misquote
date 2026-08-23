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
 *   - every link on every route resolves, anchors included — `Cite` builds
 *     links out of artifact prose with a regex, and renders one to an
 *     assumption that does not exist exactly like one that does
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
  ["quote", "/quote/"],
  ["activate", "/activate/"],
  ["venue", "/venue/"],
  ["advantage", "/advantage/"],
  ["agent-warden", "/agent/warden/"],
  // The fourth category, and a different component tree from the three LP
  // cards — `RouterDetail` rather than `AgentDetail`. It was rendering only
  // under tsc and jsdom until this line existed, and "every route clean" meant
  // every route in this list, which is exactly the shape of claim this file
  // exists to stop being made.
  ["agent-router", "/agent/router/"],
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
  // The URL and the top of the stack, because React error #418 — a hydration
  // mismatch — shows up here roughly once per sixty loads on a different route
  // each time, and has never reproduced on demand: not in five dedicated
  // attempts at a single route, not across 120 loads of a faithful replay of
  // this loop, and not once under `next dev`, which reports no hydration
  // warning on any route at all.
  //
  // The URL was added first and settled one question — it does fire on the
  // route it is reported against, not on the previous one still hydrating. The
  // frames are here so the *next* occurrence identifies the component instead
  // of costing another afternoon of failing to reproduce it. Minified, but a
  // chunk name and an offset are enough to find it.
  page.on("pageerror", (e) => {
    const frames = (e.stack ?? "").split("\n").slice(1, 4).map((l) => l.trim()).join(" <- ");
    problems.push(`uncaught on ${page.url()}: ${e}${frames ? ` [${frames}]` : ""}`);
  });
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
    // Every band in the header, not just the first. The nav is two rows now —
    // product on top, evidence below — and querying only `Primary` would have
    // reported "no nav link marked aria-current" on all seven evidence routes,
    // which is the guard failing rather than the nav. Widened rather than
    // relaxed: the current pill must still be *visible inside its own
    // scroller*, and that is now checked on whichever band holds it.
    const navCurrent = await page.evaluate(() => {
      const lists = [...document.querySelectorAll("header nav[aria-label] ul")];
      const list = lists.find((ul) => ul.querySelector("[aria-current]"));
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
  // `Router`, from `index.json.not_built[0].name` — not `PancakeSwap`, which
  // only reaches this page through `SourceBanner`'s *chain* branch. The moment
  // a run was regenerated from a synthetic tape the banner switched to "a
  // generated tape", the pool name vanished, and the needle failed for a reason
  // that had nothing to do with prerendering. A needle has to survive the data.
  ["/", 2000, "Router"],
  // The interactive half of /quote needs JavaScript — it is an input — but the
  // explanation of why a quote is a job rather than a request must not. The
  // needle is that sentence, because a prerender that dropped it would leave a
  // reader with a form and no account of what pressing it costs.
  ["/quote/", 1200, "not a button that returns a number"],
  // The absence *is* the content here, so the needle is the sentence that
  // states it. A prerender that dropped the refusal and left the plan would
  // read as an activation page that works.
  ["/activate/", 1800, "no Hire button"],
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
  // Router has no in-range fraction; its page leads with the boundary.
  ["/agent/router/", 1200, "hurdle"],
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

// --- every link goes somewhere -----------------------------------------------
//
// `ed60489` reported "107 link targets, all of which resolve". That was an
// audit, in a commit message, true once. Nothing here has ever checked that a
// link goes anywhere — this script tested console errors, overflow, nav state,
// titles and prerendering, and would pass a site where every link 404'd.
//
// `Cite` is what makes it load-bearing. It linkifies `A6`, `P-1` and `V-13`
// straight out of artifact prose with a regex, so an emitter can write a
// citation to an assumption that does not exist and the page renders it
// identically to a live one — a confident little link to nothing, on the sheet
// the site's whole argument rests on. `tests/web/test_citations.py` checks the
// artifacts against the sheet; this checks what was actually rendered.
//
// JavaScript on, deliberately. The no-JS pass above proves the export carries
// its content; this wants the *superset*, including any link a view only draws
// once its fetch lands.
const linkCtx = await browser.newContext();
const linkPage = await linkCtx.newPage();

/** target -> the routes that link to it, for naming the source of a dead one. */
const targets = new Map();

for (const [, path] of ROUTES) {
  await linkPage.goto(BASE + path, { waitUntil: "networkidle" });
  await linkPage.waitForTimeout(350);

  const hrefs = await linkPage.evaluate(() =>
    [...document.querySelectorAll("a[href]")].map((a) => a.getAttribute("href")),
  );

  for (const href of hrefs) {
    if (!href || href.startsWith("http") || href.startsWith("mailto:") || href === "#") continue;
    // A bare fragment resolves against the page it is on.
    const target = href.startsWith("#") ? path + href : href;
    if (!target.startsWith("/")) continue;
    (targets.get(target) ?? targets.set(target, new Set()).get(target)).add(path);
  }
}

await linkCtx.close();

/** The served HTML for a path, fetched once. */
const documents = new Map();
async function documentAt(path) {
  if (!documents.has(path)) {
    const res = await fetch(BASE + path);
    documents.set(path, res.ok ? await res.text() : null);
  }
  return documents.get(path);
}

let dead = 0;
for (const [target, sources] of [...targets].sort()) {
  const [path, hash] = target.split("#");
  // Every route is a directory under `trailingSlash: true`, and `Cite` writes
  // `/assumptions#A6` with no slash — which the server redirects. Following it
  // here rather than rewriting: a link a browser resolves is not dead.
  const html = await documentAt(path);
  const from = [...sources].join(", ");

  if (html === null) {
    failures.push(`dead link: ${target} does not resolve (linked from ${from})`);
    dead += 1;
  } else if (hash && !html.includes(`id="${hash}"`)) {
    failures.push(`dead anchor: ${target} — the page has no ${hash} (linked from ${from})`);
    dead += 1;
  }
}

console.log(
  `  ${dead === 0 ? "ok  " : "FAIL"}  ${"links resolve".padEnd(30)}` +
    `  ${targets.size} distinct targets across ${ROUTES.length} routes, ${dead} dead`,
);

// --- interaction, in a real browser ------------------------------------------
//
// Everything else here loads a page and looks at it. Nothing anywhere in this
// repository has ever clicked, typed or pressed a key in a real browser: the
// component tests are jsdom, which has no layout and its own scheduling, and
// this script only ever navigated by URL.
//
// That gap hid a live defect on the site's core mechanism. `/assumptions` is
// where every citation lands; following one from a filtered page is supposed to
// clear the filter, mark the entry and scroll to it. The filter cleared and the
// other two silently did not — React batches the state updates, so the reveal
// looked for its target in a DOM that was still filtered, found nothing, and
// returned. **The jsdom test for exactly this scenario passed throughout.**
// Measured in Chromium: the entry was marked `false` and left 2,340px away.
//
// So this pass exists, and it starts with the case that proved it was needed.
const live = await browser.newContext();
const page2 = await live.newPage();

await page2.goto(BASE + "/assumptions/", { waitUntil: "networkidle" });
await page2.waitForTimeout(400);
await page2.getByRole("radio", { name: /^Gaps/ }).click();
await page2.waitForTimeout(200);

const hiddenWhileFiltered = await page2.evaluate(() => !document.getElementById("A5"));
await page2.evaluate(() => {
  window.location.hash = "#A5";
});

// Polled, not slept. A flat 600ms was enough on most runs and not on all of
// them: the reveal clears a filter, re-renders 55 entries and *then* scrolls,
// and on a slow run the scroll had not landed when the assertion read it —
// reporting `scrolled=false` for a mechanism that works. A check that fails
// once in a few runs teaches people to re-run it until it passes, which is
// worse than not having it.
//
// The timeout is the assertion. If the scroll never lands, this throws and the
// read below still records what the page ended up doing.
await page2
  .waitForFunction(
    () => {
      const el = document.getElementById("A5");
      return !!el && Math.abs(el.getBoundingClientRect().top) < 400;
    },
    { timeout: 5000 },
  )
  .catch(() => {});

const revealed = await page2.evaluate(() => {
  const el = document.getElementById("A5");
  if (!el) return { found: false, marked: false, near: false };
  return {
    found: true,
    marked: el.innerText.includes("followed a citation here"),
    near: Math.abs(el.getBoundingClientRect().top) < 400,
  };
});

// The premise first: if the filter stopped hiding A5, this proves nothing.
if (!hiddenWhileFiltered) {
  failures.push("citation reveal: A5 was not hidden by the Gaps filter, so the test proves nothing");
}
for (const [ok, what] of [
  [revealed.found, "the filter did not clear"],
  [revealed.marked, "the entry was not marked as the one followed to"],
  [revealed.near, "the reader was not scrolled to the entry"],
]) {
  if (!ok) failures.push(`citation reveal: ${what}`);
}
const revealOk = hiddenWhileFiltered && revealed.found && revealed.marked && revealed.near;
console.log(
  `  ${revealOk ? "ok  " : "FAIL"}  ${"interact citation reveal".padEnd(30)}` +
    `  cleared=${revealed.found} marked=${revealed.marked} scrolled=${revealed.near}`,
);

await live.close();
await browser.close();

if (failures.length) {
  console.error(`\n  ${failures.length} failure(s):`);
  for (const f of failures) console.error(`    ${f}`);
  process.exit(1);
}
console.log(`\n  every route clean in both themes and at 390px, with ${titles.size} distinct titles.`);
