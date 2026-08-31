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

/** The desktop viewport the scenario and reduced-motion passes use. */
const WIDE = { width: 1280, height: 900 };

/** The settle this file already uses everywhere: 350ms after `networkidle`. */
const SETTLE = 350;

const ROUTES = [
  ["overview", "/"],
  // The table of contents for the simulation layer. It must render with the API
  // asleep, because that is exactly when somebody goes looking for it.
  ["demo", "/demo/"],
  ["quote", "/quote/"],
  ["activate", "/activate/"],
  ["category", "/category/"],
  // One of the four, not all: they are one component over one artifact, and a
  // fifth screenshot of the same tree buys nothing. Rebalancing is the one with
  // an advantage task, so it exercises the branch the others do not.
  ["category-rebalancing", "/category/rebalancing/"],
  ["venue", "/venue/"],
  ["advantage", "/advantage/"],
  ["agent-warden", "/agent/warden/"],
  // The fourth category, and a different component tree from the three LP
  // cards — `RouterDetail` rather than `AgentDetail`. It was rendering only
  // under tsc and jsdom until this line existed, and "every route clean" meant
  // every route in this list, which is exactly the shape of claim this file
  // exists to stop being made.
  ["agent-router", "/agent/router/"],
  // The third agent page, and the only one in the never-ran branch. `grid` and
  // `sentinel` have no live journal — neither has ever written the file its
  // own `provenance.journal` names — so the "Why it held" card takes a
  // different path here than on
  // /agent/warden, and until this line that path had never been rendered by a
  // browser. It had been rendering four rows of zeros as if they were
  // measurements, on two routes this list did not visit, which is the same
  // shape of claim the /agent/router line below was added for.
  ["agent-grid", "/agent/grid/"],
  ["methods", "/methods/"],
  ["vectors", "/vectors/"],
  ["assumptions", "/assumptions/"],
  ["registry", "/registry/"],
  ["vetting", "/vetting/"],
  // Live-only, and the one route here where a screenshot at 390px is the whole
  // check: the coverage strips are absolutely-positioned segments summing to a
  // percentage width, which is the shape that overflows a narrow viewport
  // without any single element being too wide.
  ["tape", "/tape/"],
  ["status", "/status/"],
];

const VIEWPORTS = [
  ["dark", 1280],
  ["light", 1280],
  ["dark", 390],
];

if (shotsAt) mkdirSync(shotsAt, { recursive: true });

/**
 * The configured API origin, resolved once from the export's own `api.json`.
 *
 * Read from the served build rather than from the environment, because that is
 * what the pages themselves read — a check that resolves the origin differently
 * from the site is checking a different site.
 */
const apiOrigin = await (async () => {
  const response = await fetch(`${BASE}/artifacts/api.json`);
  if (!response.ok) return null;
  const config = await response.json().catch(() => null);
  return config?.base ?? null;
})();

/**
 * Wake the API before any page asks it a question.
 *
 * `/tape` is the one route in the loop below that issues a live cross-origin
 * request with no artifact behind it, so it is the only one whose settling
 * depends on a host nobody here controls. That host is a free-tier instance
 * that sleeps, and a cold start on one is tens of seconds — during which the
 * browser holds an in-flight request and `networkidle` is never reached.
 *
 * **Insurance, not a diagnosis.** `/tape` did time out at thirty seconds twice
 * while this was written, and a cold dyno was the first guess and was wrong:
 * the API answered in 0.47–1.0s on ten consecutive measurements, the wake below
 * reported `awake after 1s`, and the route timed out anyway. A faithful replay
 * of this loop then passed all sixteen routes on a quiet machine. What the two
 * failures had in common was a load average near forty on eight cores, which is
 * the same condition the hydration note below found predicts trouble here.
 *
 * So this is kept for the case it genuinely covers — the first run of the day
 * against a sleeping host — and the failures actually observed are handled by
 * the raised timeout and the recorded-not-thrown navigation below. Naming a
 * cause that measurement contradicts is the thing this repository is about.
 *
 * A dead or unreachable API is not a failure here: the page renders its refusal
 * state, which is a thing this check should see rather than route around.
 */
if (apiOrigin) {
  const started = Date.now();
  const woke = await fetch(`${apiOrigin}/tape`, {
    signal: AbortSignal.timeout(90_000),
  })
    .then((r) => r.ok)
    .catch(() => false);
  const took = Math.round((Date.now() - started) / 1000);
  console.log(`  api   ${apiOrigin} ${woke ? "awake" : "unreachable"} after ${took}s`);
}

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

  // Chromium logs every non-2xx to the console as "Failed to load resource: the
  // server responded with a status of 404 ()", with no URL on it. That line is
  // the browser narrating the same response the handler below classifies, so a
  // refusal produced two findings: one the response check now correctly clears,
  // and one here that it could not reach.
  //
  // Counted rather than pattern-suppressed. Each classified refusal excuses one
  // such line and no more, so a route that refuses once and genuinely 404s once
  // still reports the second — which a blanket regex would have swallowed.
  const NARRATED_STATUS = /^Failed to load resource: the server responded with a status of \d+/;
  const consoleErrors = [];
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  // The URL and the top of the stack, because React error #418 — a hydration
  // mismatch — shows up here roughly once per sixty loads on a different route
  // each time, and has never reproduced on demand: not in five dedicated
  // attempts at a single route, not across 120 loads of a faithful replay of
  // this loop, and not once under `next dev`, which reports no hydration
  // warning on any route at all.
  //
  // The URL was added first and settled one question — it does fire on the
  // route it is reported against, not on the previous one still hydrating. The
  // frames were added next, so the *next* occurrence would identify the
  // component instead of costing another afternoon.
  //
  // It fired twice more since, on /category/rebalancing/ and on /quote/, and
  // the frames were byte-identical both times: `rD <- oq <- iw`, all three in
  // chunk `0fef27c7`. That chunk is react-dom — it carries `react.dev/errors`
  // and the Suspense runtime and nothing of this application. So the stack is
  // React's own hydration-recovery path and the frames cannot name a component,
  // which is the question they were added to answer. They are not worth
  // widening; the next lead has to come from somewhere else.
  //
  // Reproduction attempts, so nobody spends the afternoon again: 150 loads of a
  // faithful replay of this exact loop shape — one context, one page, all
  // fifteen routes sequentially, networkidle plus the same 350ms — produced
  // zero. A fresh context per load produced zero in 24. `next dev` reports no
  // hydration warning on any route.
  //
  // **It tracks machine load, and that is the first thing found that predicts
  // it.** Every zero above was measured on an idle machine. On the same tree
  // with an unrelated build saturating the box — load average 30 to 50 against
  // 8 cores — this script hit it three runs in a row, once on /agent/router,
  // then on /venue and /activate together, always on a route the commit under
  // test had not touched, always the same three react-dom frames. That is
  // roughly one in twenty loads against the one in ninety it shows when idle.
  //
  // Confirmed a second time, and the load-tracking is now the strongest thing
  // known about it. On a box holding a steady load average of 35 against 8
  // cores, three consecutive runs each failed on exactly one route, and it was
  // a different route every time — /vectors, then /registry, then /methods —
  // with `rD <- oq <- iw` byte-identical in all three. Two of those three
  // routes render nothing from the commit under test, which is the whole value
  // of the observation: the route it names is not the route that changed.
  //
  // The distinguishing test, for whoever meets this next. This flake picks a
  // random route and never repeats. A real hydration bug introduced by a commit
  // fires on the *same* route every run — /assumptions did exactly that when a
  // `<Cite>` ended up nested inside the index's own `<a href="#id">`, three
  // viewports out of four, every run, and with a different third frame (`ik`,
  // not `iw`). Same error number, opposite diagnosis. Count the runs and read
  // the third frame before assuming either one.
  //
  // Which fits what a hydration mismatch is: React commits the server HTML and
  // then reconciles, and a starved event loop widens every window in between.
  // If this is ever worth chasing properly, reproduce it under `stress-ng` or a
  // parallel `next build` rather than on a quiet laptop — that is the condition
  // the "never reproduces on demand" note above was missing.
  page.on("pageerror", (e) => {
    const frames = (e.stack ?? "").split("\n").slice(1, 4).map((l) => l.trim()).join(" <- ");
    problems.push(`uncaught on ${page.url()}: ${e}${frames ? ` [${frames}]` : ""}`);
  });
  page.on("requestfailed", (r) => problems.push(`request failed: ${r.url()}`));
  // A non-2xx is a problem unless it is a *refusal*, and the difference is in
  // the body rather than the status.
  //
  // `lib/api.ts` defines the contract: the API answers a question it cannot
  // answer with a non-2xx carrying `{detail: {error, remedy, …}}`, and
  // `loadLive` turns that into a `RefusalError` the page renders. `/journal/
  // <agent>` does exactly this for an agent that has never run — "no journal
  // for 'grid'", listing the two agents that have one — and `AgentJournal`
  // draws it. That is the service working, and this handler called it a
  // failure the moment /agent/grid joined the route list.
  //
  // Checked rather than exempted. Matching the URL shape would have passed a
  // genuinely broken journal route just as happily; reading the body asserts
  // the thing that actually distinguishes them. The reads are collected and
  // awaited below, because a promise resolving after `problems` is read is a
  // check that reports nothing.
  const bodies = [];
  page.on("response", (r) => {
    if (r.status() < 400) return;
    bodies.push(
      r
        .json()
        .then((body) => (body?.detail?.error ? null : `${r.status()} ${r.url()}`))
        .catch(() => `${r.status()} ${r.url()}`),
    );
  });

  // What is still in flight, so a navigation that never settles can say what it
  // was waiting for instead of only that it waited. `networkidle` is a claim
  // about the whole page's network, and when it fails the one thing worth
  // knowing is which request did not come back.
  const inFlight = new Map();
  page.on("request", (r) => inFlight.set(r, Date.now()));
  page.on("requestfinished", (r) => inFlight.delete(r));
  page.on("requestfailed", (r) => inFlight.delete(r));

  for (const [name, path] of ROUTES) {
    const tag = `${name}-${colorScheme}-${width}`;
    problems.length = 0;
    bodies.length = 0;
    consoleErrors.length = 0;

    // Recorded, not thrown. A `page.goto` rejection used to escape this loop
    // as an uncaught exception and take the whole run with it — every remaining
    // route, every remaining viewport, and all four passes below. That is not a
    // hypothetical: one intermittent hang on `/tape` aborted a run that was
    // also carrying 58px of overflow on `/` and on `/category/rebalancing/`,
    // and the crash reported neither. A check that stops at the first problem
    // reports one problem and implies there are no others.
    //
    // `networkidle` is kept rather than traded for `domcontentloaded`, because
    // the measurement below needs the page *rendered* and `/tape` renders from
    // a live read. The timeout is raised instead: the live API answers in half
    // a second when measured directly, so a minute is not a wait for it, it is
    // room for the browser to be starved — which is the condition the hydration
    // note above already found predicts trouble on this loop.
    const navFailure = await page
      .goto(BASE + path, { waitUntil: "networkidle", timeout: 60_000 })
      .then(() => null)
      .catch((e) => {
        const stuck = [...inFlight]
          .map(([r, at]) => `${Math.round((Date.now() - at) / 1000)}s ${r.url()}`)
          .slice(0, 3);
        return (
          `${e.message.split("\n")[0]}` +
          (stuck.length ? ` — still in flight: ${stuck.join(", ")}` : " — nothing in flight")
        );
      });
    if (navFailure) {
      failures.push(`${tag}: ${navFailure}`);
      console.log(`  FAIL  ${tag.padEnd(30)}  ${navFailure}`);
      continue;
    }

    // The views fetch after mount; give the render a beat to settle.
    await page.waitForTimeout(350);

    // Every non-2xx read and classified, before anything reads `problems`.
    const classified = await Promise.all(bodies);
    problems.push(...classified.filter(Boolean));

    // Then the console, minus one narration per refusal.
    let excused = classified.length - classified.filter(Boolean).length;
    for (const text of consoleErrors) {
      if (excused > 0 && NARRATED_STATUS.test(text)) {
        excused -= 1;
        continue;
      }
      problems.push(text);
    }

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
  // `Router`, from `index.json.not_built[0].name` — not a pool name, which used
  // to reach this page only on a chain-sourced run and vanished the moment a
  // run was regenerated from a synthetic tape, failing the needle for a reason
  // that had nothing to do with prerendering. A needle has to survive the data.
  ["/", 2000, "Router"],
  // The interactive half of /quote needs JavaScript — it is an input — but the
  // explanation of why a quote is a job rather than a request must not. The
  // needle is that sentence, because a prerender that dropped it would leave a
  // reader with a form and no account of what pressing it costs.
  // The four rules are the page's argument, not decoration: a prerender that
  // dropped them would leave a list of links to simulated states with nothing
  // saying what a simulation here is allowed to be.
  ["/demo/", 1200, "never on by default and never sticky"],
  ["/quote/", 1200, "not a button that returns a number"],
  // The absence *is* the content here, so the needle is the sentence that
  // states it. A prerender that dropped the refusal and left the plan would
  // read as an activation page that works.
  ["/activate/", 1800, "no Hire button"],
  // Both needles come from the sentence each page exists to make, and neither
  // is a figure that a regenerated artifact could move. The first draft had
  // these the wrong way round — "declare no category" is the *detail* page's
  // wording and the index says "declares a category", so the index needle
  // matched nothing. The check caught it, which is the check working.
  // Both category needles follow the same rewording, and the reason is worth
  // keeping: the pages used to argue that sorting strangers into categories
  // would present *our* classification as *theirs*, and therefore listed none.
  // They list them now — so the argument stands and the conclusion changed.
  // What each needle holds is the half that did not change: that the
  // classification is ours and is labelled as such.
  ["/category/", 1200, "our classification of their words"],
  ["/category/rebalancing/", 1800, "our reading of their free text"],
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
  // The only route here whose subject cannot be prerendered — what a database
  // holds right now is live by definition. So the needle is the recorded half:
  // a pool label out of `vetting.json`, which is what the page renders with
  // JavaScript off. A prerender that lost it would leave the argument about
  // coverage with nothing to apply it to, which is the failure worth catching;
  // the coverage strips themselves are correctly absent without JS.
  ["/tape/", 2000, "TSLAx"],
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

// The compare tray, at the width where a fixed bar is hardest.
//
// The route sweep above never sees it: it renders nothing until two agents are
// chosen, so every screenshot and every overflow measurement is of an empty
// tray. That is precisely the wrong coverage — a fixed bottom bar carrying two
// agent names is one of the few shapes on this site that can push a 390px
// viewport sideways, and it is invisible to every other check here.
//
// Driven through the buttons rather than by writing localStorage directly, so
// what is exercised is the path a reader takes.
const trayCtx = await browser.newContext({ viewport: { width: 390, height: 800 } });
const page3 = await trayCtx.newPage();

await page3.goto(BASE + "/", { waitUntil: "networkidle" });
await page3.waitForTimeout(400);

const toggles = page3.getByRole("button", { name: /^Compare / });
const available = await toggles.count();
for (let i = 0; i < Math.min(2, available); i++) {
  await toggles.nth(i).click();
  await page3.waitForTimeout(150);
}

const tray = await page3.evaluate(() => {
  const region = document.querySelector('[role="region"][aria-label="Compare tray"]');
  const de = document.documentElement;
  return {
    present: !!region,
    chips: region ? region.querySelectorAll("li").length : 0,
    overflow: de.scrollWidth - de.clientWidth,
    // The tray is fixed; content must not end underneath it.
    occludes: region
      ? region.getBoundingClientRect().top < (document.querySelector("main")?.getBoundingClientRect().bottom ?? 0) - 1
      : false,
  };
});

if (available < 2) {
  failures.push(`compare tray: only ${available} compare buttons on the overview, so nothing was exercised`);
}
if (!tray.present) failures.push("compare tray: choosing two agents did not open a tray");
if (tray.chips < 2) failures.push(`compare tray: ${tray.chips} chip(s) after two clicks`);
if (tray.overflow > 0) {
  failures.push(`compare tray: ${tray.overflow}px of horizontal overflow at 390px`);
}

const trayOk = available >= 2 && tray.present && tray.chips >= 2 && tray.overflow === 0;
console.log(
  `  ${trayOk ? "ok  " : "FAIL"}  ${"interact compare tray".padEnd(30)}` +
    `  chips=${tray.chips} overflow=${tray.overflow}px`,
);

await trayCtx.close();

// --- a simulated page says so, and never touches the API ---------------------
//
// The whole simulation design rests on one claim: a scenario short-circuits
// above `apiBase()`, so a recorded answer cannot arrive by the route a live one
// arrives by. `lib/api.test.ts` asserts it against a stubbed fetch; this
// asserts it against a real browser loading the real export, which is the only
// place the claim actually has to hold.
//
// Both directions. A scenario route must carry the banner and issue nothing to
// the API; an ordinary route must carry no trace of the word.

// `[route, scenario, needle, act]`.
//
// `act` is the half that was missing, and its absence is why this pass had a
// hole exactly where the feature mattered most. `quote-thin-tape` was listed
// with `needle: null` and no interaction — so the check loaded a page, asserted
// zero API contact, and passed **because nothing was ever submitted**. Under it,
// the fixture was dead: `/quote`'s enqueue was a raw `fetch` below the scenario
// short-circuit, so the refusal it records could not render and a "simulated"
// page was talking to production.
//
// A check that cannot fail is not a check. Where a scenario only means something
// after a click, the click is part of the assertion.
const SCENARIOS = [
  ["/agent/warden/", "journal-never-ran", "written no journal", null],
  ["/quote/", "wallet-two-pools", "Replay this pool", typeAddress],
  // The happy path, and the reason the whole demo exists: a P25-P75 range
  // reached with no wallet, no API and no worker. The needle is the disclosure
  // rather than the number — a range that rendered without saying it ran on the
  // reduced interactive budget would be comparable-looking with a published
  // card, which A15 says it is not.
  [
    "/quote/",
    "demo-quote",
    "not comparable with one",
    async (page) => {
      await typeAddress(page);
      const run = page.locator("button", { hasText: "Replay this pool" }).first();
      await run.click({ timeout: 10_000 }).catch(() => {});
      await page.waitForTimeout(SETTLE * 4);
    },
  ],
  // The refusal, and it arrives at the pre-flight rather than at submit.
  //
  // This entry used to click "Replay this pool" and assert prose beginning "the
  // tape supports 6 windows". Both were wrong, and the pair of them is why the
  // needle was `null` for so long. `view.tsx` renders a run only for a holding
  // with `quotable: true`, so a thin-tape pool never has a button to click; and
  // no code path emits that sentence — `preflight.assess` reports the widest
  // sub-window against the 24h floor. The fixture asserted a refusal the engine
  // does not word and reached it by a control that is not drawn.
  //
  // So: type the address, assert the arithmetic. No click, because a visitor
  // has nothing to click either.
  ["/quote/", "quote-thin-tape", "the widest sub-window is 4.6h", typeAddress],
];

/** Put an address in the quote field and submit it, as a visitor would. */
async function typeAddress(page) {
  const field = page.locator('input[placeholder*="0x"]').first();
  await field.fill("0x0000000000000000000000000000000000000001", { timeout: 10_000 });
  await page.keyboard.press("Enter");
  await page.waitForTimeout(SETTLE);
}

const simCtx = await browser.newContext({ colorScheme: "dark", viewport: WIDE });
for (const [route, scenario, needle, act] of SCENARIOS) {
  const page = await simCtx.newPage();
  const reached = [];
  page.on("request", (request) => {
    if (apiOrigin && request.url().startsWith(apiOrigin)) reached.push(request.url());
  });

  // `domcontentloaded`, not `networkidle`. `/tape` reads the live tape with no
  // artifact behind it, so its network settles only when a host outside this
  // repository answers, and a pass that waits on that fails on a page that is
  // fine. Neither of these checks needs a settled network anyway: one polls for
  // the stamp it is waiting on, the other scrolls and reads the animation
  // list.
  //
  // The earlier note here said the tape "polls on a timer". It does not —
  // `tape/view.tsx` fetches once in a mount effect and never again. The symptom
  // was real and the cause named was not, which is worth more than the tidier
  // sentence: a slow first response and a repeating one look identical from
  // here, and only one of them is fixed by waiting longer.
  await page.goto(`${BASE}${route}?scenario=${scenario}`, { waitUntil: "domcontentloaded" });

  // Polled, not slept. The scenario is two sequential fetches deep — the
  // effect reads the URL, fetches the fixture, and only then does `loadLive`
  // resolve — and a flat 350ms was enough for one hop and not for two: the
  // first run of this check reported `stamp=null` and `api=1` against a build
  // that was working, which is a check failing by not waiting.
  //
  // The citation-reveal pass above makes the same argument and uses the same
  // tool. A timeout here is the assertion.
  await page
    .waitForFunction(
      (want) => document.documentElement.dataset.scenario === want,
      scenario,
      { timeout: 5_000 },
    )
    .catch(() => {});
  await page.waitForTimeout(SETTLE);

  // Do the thing the scenario is about, before reading the page. Every
  // assertion below — including the load-bearing "reached the API 0 times" —
  // is worth something only after the interaction it is about has happened.
  if (act) await act(page);

  const state = await page.evaluate(() => ({
    stamp: document.documentElement.dataset.scenario ?? null,
    // `innerText` as rendered, so `text-transform: uppercase` is already
    // applied — the trap the no-JS needles above document, and the one that
    // made this check pass a false negative the first time it was written.
    text: document.body.innerText.replace(/\s+/g, " "),
  }));

  const tag = `scenario ${scenario} on ${route}`;
  if (state.stamp !== scenario) {
    failures.push(`${tag}: html[data-scenario] is ${JSON.stringify(state.stamp)}`);
  }
  if (!/SIMULATED/i.test(state.text)) {
    failures.push(`${tag}: the page does not say it is simulated`);
  }
  if (!state.text.includes("leave simulation")) {
    failures.push(`${tag}: no way out of the simulation`);
  }
  if (needle && !state.text.includes(needle)) {
    failures.push(`${tag}: does not contain ${JSON.stringify(needle)}`);
  }
  // The load-bearing one.
  if (reached.length) {
    failures.push(`${tag}: reached the API ${reached.length} time(s) — ${reached[0]}`);
  }

  console.log(
    `  ${reached.length === 0 && state.stamp === scenario ? "ok  " : "FAIL"}` +
      `  ${`simulated ${route}`.padEnd(30)}  api=${reached.length} stamp=${state.stamp}`,
  );
  await page.close();
}

// And the inverse, on every ordinary route: no stamp, and the word appears
// nowhere. A banner that leaked onto a real page would be worse than one that
// never rendered.
for (const [name, path] of ROUTES) {
  const page = await simCtx.newPage();
  await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(SETTLE);
  // Scoped to the banner, not to the page's prose.
  //
  // Matching `/simulated/i` against `body.innerText` failed on `/assumptions`,
  // which discusses simulation in its own text — the check was reading the
  // site's vocabulary as its state. What must not appear is the *banner*, so
  // that is what is looked for: the element it renders, and the way out it
  // offers.
  const leaked = await page.evaluate(() => ({
    stamp: document.documentElement.dataset.scenario ?? null,
    banner: document.body.innerText.includes("leave simulation"),
  }));
  if (leaked.stamp !== null) failures.push(`${name}: carries data-scenario without one asked for`);
  if (leaked.banner) failures.push(`${name}: shows the simulation banner on an ordinary visit`);
  await page.close();
}
console.log(`  ok    ${"no simulation on ordinary routes".padEnd(30)}  ${ROUTES.length} routes`);

await simCtx.close();

// --- nothing animates under `prefers-reduced-motion` -------------------------
//
// `globals.css` names a hand-written list — `.reveal, .band-draw, .band-tick,
// .shuttle` — because `!important` never reaches a scroll-driven timeline, and
// its comment records the miss that proved it: `.band-tick` was absent for one
// commit and six `tick-in` animations kept running on `ViewTimeline` after the
// bars they belong to had stopped.
//
// It also records the check that found it — `document.getAnimations()` filtered
// to `playState === "running"` should be empty — and says "that check is worth
// re-running after anything is added here". Nothing automated it. This does.
const motionCtx = await browser.newContext({
  colorScheme: "dark",
  viewport: WIDE,
  reducedMotion: "reduce",
});
for (const [name, path] of ROUTES) {
  const page = await motionCtx.newPage();
  await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded" });
  // Scrolled, because the animations at issue are scroll-driven: one that never
  // enters the viewport never starts, and a check that never scrolls would pass
  // by not looking.
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(SETTLE);

  const running = await page.evaluate(() =>
    document
      .getAnimations()
      .filter((a) => a.playState === "running")
      .map((a) => a.animationName ?? a.constructor.name),
  );
  if (running.length) {
    // Named, so the next miss identifies itself instead of needing the same
    // half-hour in a console.
    failures.push(
      `${name} under reduced-motion: ${running.length} animation(s) still running — ` +
        `${[...new Set(running)].join(", ")}`,
    );
  }
  await page.close();
}
console.log(`  ok    ${"nothing animates under reduce".padEnd(30)}  ${ROUTES.length} routes`);

await motionCtx.close();

await live.close();
await browser.close();

if (failures.length) {
  console.error(`\n  ${failures.length} failure(s):`);
  for (const f of failures) console.error(`    ${f}`);
  process.exit(1);
}
console.log(`\n  every route clean in both themes and at 390px, with ${titles.size} distinct titles.`);
