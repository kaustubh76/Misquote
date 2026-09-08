"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ConnectButton } from "@/components/ConnectButton";
import { type Route, isEvidenceRoute, routesIn } from "@/lib/routes";



/**
 * Where the reader is: on this page, or somewhere under it.
 *
 * `/agent/warden` has no nav entry of its own, and the earlier rule — exact
 * match, plus a prefix match that `href === "/"` short-circuits out of —
 * returned nothing for it. So the agent detail pages, which are a large share
 * of the site's routes, highlighted **no nav item at all**, and a reader who
 * followed a card into one had nothing telling them where they had landed.
 * `scripts/check-pages.mjs` now fails on a page that marks nothing.
 *
 * Those pages belong to the Overview: it is the only place that links to them,
 * and each one links back with "← All agents". So Overview is marked, as a
 * *section* rather than as the page.
 *
 * The distinction is kept in ARIA rather than flattened. `aria-current="page"`
 * means *this is the page you are on*, and saying that on `/agent/warden`
 * would tell a screen-reader user the Overview link leads where they already
 * are. `aria-current="true"` is the weaker "current item in this set", which is
 * what an ancestor section is. They look identical; they do not sound identical.
 */
type Activeness = "page" | "section" | null;

function activeness(pathname: string, href: string): Activeness {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === href) return "page";
  if (href === "/") return path.startsWith("/agent/") ? "section" : null;
  return path.startsWith(`${href}/`) ? "section" : null;
}

/**
 * Which ends of the nav have links scrolled out of sight.
 *
 * The nav overflows to a horizontal scroller so that no route is dropped at a
 * narrow width. That part worked. What did not: the scrollbar is hidden
 * (`scrollbar-width: none`), so at 390px the bar read "Misquote · Overview ·
 * Advantage" and stopped — with **no indication that five more pages existed**.
 * Methods, Assumptions, Registry, Vetting and Status were reachable only by
 * guessing that the strip could be swiped. On a narrow desktop window, where
 * there is no swipe and no scrollbar, they were not reachable at all without
 * knowing to hold shift while scrolling.
 *
 * `make web-check` could not catch it: the page's horizontal overflow is 0,
 * which is exactly what the scroller is for. The bug is that the affordance was
 * removed along with the scrollbar, and only a screenshot shows that.
 *
 * So the ends are measured and faded. Two pixels of arithmetic rather than a
 * threshold: `scrollLeft` is fractional after a swipe, and `scrollWidth` is
 * rounded, so an exact comparison leaves the fade on forever at one end.
 */
function useOverflowEdges<T extends HTMLElement>(current: string) {
  const ref = useRef<T>(null);
  const [edges, setEdges] = useState({ start: false, end: false });

  const measure = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    setEdges({ start: el.scrollLeft > 2, end: el.scrollLeft < max - 2 });
  }, []);

  /**
   * Bring the current page into view, on mount and on navigation.
   *
   * The fades say "there is more"; they do not say "you are over there". At
   * 390px `/status` showed `Misquote · Overview · Advantage` with **nothing
   * highlighted** — the active pill was two screens to the right — so the one
   * question a nav answers without being asked, *which page am I on*, had no
   * answer at the width where it is hardest to reconstruct from the content.
   *
   * `scrollLeft` is set directly rather than calling `scrollIntoView`, which
   * also scrolls the nearest scrollable *ancestor*: on a page already scrolled
   * down, that jumps the document to the top on every navigation.
   */
  const revealCurrent = useCallback(() => {
    const el = ref.current;
    // `[aria-current]`, not `[aria-current="page"]` — an agent detail page marks
    // Overview as the current *section*, and that is exactly the case where the
    // reader most needs the highlight brought into view.
    const current = el?.querySelector<HTMLElement>("[aria-current]");
    if (!el || !current) return;

    const left = current.offsetLeft;
    const right = left + current.offsetWidth;
    const pad = 32; // clears the fade, so the active pill is never half under it
    if (left - pad < el.scrollLeft) el.scrollLeft = Math.max(0, left - pad);
    else if (right + pad > el.scrollLeft + el.clientWidth)
      el.scrollLeft = right + pad - el.clientWidth;
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    measure();
    el.addEventListener("scroll", measure, { passive: true });
    // Width changes with the viewport and, on first paint, with the font the
    // labels land in. A resize listener alone misses the second.
    //
    // The observer re-reveals as well as re-measuring, and that is a fix rather
    // than tidying. `revealCurrent` otherwise runs only on navigation, so
    // anything that narrows this band *after* that — the connect button
    // appearing on hydration, then widening again when the balance arrives —
    // pushes the active link out of view with nothing to bring it back. At
    // 390px the whole strip is about one link wide, and the gate caught exactly
    // this on ten routes at once: "the current page's nav link is scrolled out
    // of view", on every page, in the narrow dark pass only.
    const observer = new ResizeObserver(() => {
      measure();
      revealCurrent();
    });
    observer.observe(el);
    return () => {
      el.removeEventListener("scroll", measure);
      observer.disconnect();
    };
  }, [measure, revealCurrent]);

  // Keyed on the route, not run once on mount. The nav survives client-side
  // navigation, so `aria-current` moves under a component that never
  // remounts — and mount-only reveal would work exactly once, on a hard load.
  useEffect(() => {
    revealCurrent();
    measure();
  }, [current, revealCurrent, measure]);

  return { ref, ...edges };
}

/**
 * One band of the nav: its own scroller, its own fades, its own reveal.
 *
 * Extracted rather than duplicated because both bands need the whole of
 * `useOverflowEdges` — a band that fits at 1280px does not fit at 390px, and
 * the fade and the scroll-into-view are exactly as load-bearing on the second
 * row as on the first.
 */
function Band({
  label,
  routes,
  pathname,
  className = "",
}: {
  label: string;
  routes: readonly Route[];
  pathname: string;
  className?: string;
}) {
  const { ref, start, end } = useOverflowEdges<HTMLUListElement>(pathname);

  return (
    <nav aria-label={label} className={`relative min-w-0 flex-1 ${className}`}>
      {/* The affordance the hidden scrollbar took away. `aria-hidden` and
          `pointer-events-none`: this is a hint that content continues, and
          a screen reader already has the full list — it never scrolled. */}
      {start && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 left-0 z-10 w-8 bg-gradient-to-r from-glass to-transparent"
        />
      )}
      {end && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 right-0 z-10 w-8 bg-gradient-to-l from-glass to-transparent"
        />
      )}
      {/* `overflow-x: auto` computes overflow-y to auto as well, so the box
          clips on both axes and ate the 2px focus ring at its 2px offset.
          The padding makes room inside the scroll box; the negative margin
          puts the layout back. CSS-only, so `make web-check` is its only
          guard. */}
      <ul
        ref={ref}
        className="flex list-none items-center gap-1 overflow-x-auto p-1.5 -m-1.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {routes.map((link) => {
          const active = activeness(pathname, link.href);
          return (
            <li key={link.href} className="shrink-0">
              <Link
                href={link.href}
                aria-current={
                  active === "page" ? "page" : active === "section" ? "true" : undefined
                }
                className={[
                  "block rounded-md px-2.5 py-1.5 text-sm no-underline transition-colors",
                  // The active pill was `bg-neutral-bg text-ink` — the same
                  // grey as every tint on the site, so "where am I" was
                  // carried by a background one shade off the header. Brand
                  // is the only colour here that is not a verdict, which is
                  // what makes it safe to use for position.
                  active
                    ? "bg-brand-bg font-medium text-brand"
                    : "text-dim hover:bg-panel-2 hover:text-ink",
                ].join(" ")}
              >
                {link.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/**
 * The way into the evidence section from anywhere that is not already in it.
 *
 * A `Route` rather than a hand-rolled `<Link>` so it goes through `Band` and
 * inherits the whole of it — the pill styling, the scroller, the overflow fades
 * and the scroll-into-view. A second pill built by hand beside the band is a
 * second thing to keep in step with those, and it would sit *outside* the
 * scroller at 390px, which is the width the scroller exists for.
 *
 * It targets the landing page's own rail rather than a hub page of its own:
 * eight cards each already carrying a live figure out of its artifact, which is
 * what somebody deciding whether to audit anything actually wants to see.
 *
 * `activeness()` can never mark it — no pathname equals `/#evidence` — and that
 * is correct rather than a gap. It is a way *to* the section, not a page in it.
 */
const EVIDENCE_ENTRY: Route = { href: "/#evidence", label: "Evidence", group: "product" };

/**
 * One band, and a second that appears only inside the section it belongs to.
 *
 * Both bands used to render on every route, so the first thing a reader saw was
 * sixteen tabs across two rows with nothing saying which of them was the
 * product. A site whose argument is that its numbers can be checked still has
 * to answer *what is this* before it answers *how do I check it*, and sixteen
 * peers answer neither.
 *
 * So the product band is always present, and the evidence band is a section
 * nav: it renders on the eight evidence routes and nowhere else. The entry
 * point is the `Evidence` pill below, which goes to the landing page's own rail
 * — eight cards already carrying a live figure each, which is a better index
 * than eight labels.
 *
 * This is not the disclosure that was refused here before. That objection was
 * that unmounting the band everywhere would hide seven routes behind a control
 * a screen-reader user has to find first, and break `check-pages.mjs`, which
 * requires the current route's pill to be *visible*. Neither applies: on an
 * evidence route the whole band is in the document exactly as it was, the guard
 * looks for `aria-current` across whichever band holds it, and `not-found.tsx`
 * still enumerates all sixteen routes from `ROUTES`. Nothing is unreachable;
 * the second row is simply not shown to someone who has not asked for it.
 */
export function Nav() {
  const pathname = usePathname() ?? "/";
  const inEvidence = isEvidenceRoute(pathname);

  // Exactly one evidence affordance at a time. Off the section, that is the
  // pill; inside it, the band itself — which sits directly below and names all
  // eight, so keeping the pill as well would be a link to the index of the row
  // underneath it.
  const product = inEvidence
    ? routesIn("product")
    : [...routesIn("product"), EVIDENCE_ENTRY];

  return (
    <header className="sticky top-0 z-50 border-b border-glass-line bg-glass backdrop-blur">
      {/* Wraps, and that is load-bearing at 390px rather than cosmetic.
          
          Adding the connect button put a third `shrink-0` item on this row, and
          the route band — `min-w-0 flex-1` — is what gives way. At 390px it was
          squeezed narrower than a single pill, so the current page's link could
          not be shown inside its own scroller no matter where it scrolled to.
          The browser gate reported "the current page's nav link is scrolled out
          of view" on ten routes at once, which read as a scroll bug and was a
          width bug: there was nowhere to scroll it *to*.
          
          So below `sm` the band takes a row of its own at full width, and the
          logo shares the top row with the wallet and theme controls. Above
          `sm` the order and the layout are exactly what they were. */}
      <div
        className={`mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-5 pt-3 ${inEvidence ? "" : "pb-2"}`}
      >
        {/* A mark, not just a word. The wordmark was one of nine grey items in
            a horizontal strip and did not read as the way home. The glyph is
            the same P25-P75 band the favicon draws — a range with a median
            tick — which is the one shape this product is about. */}
        <Link
          href="/"
          className="flex shrink-0 items-center gap-2 font-mono text-sm font-semibold tracking-tight text-ink no-underline"
        >
          <span
            aria-hidden="true"
            className="relative inline-block h-4 w-6 rounded-sm bg-brand/25 ring-1 ring-brand-line"
          >
            {/* The median. */}
            <span className="absolute top-0 bottom-0 left-1/2 w-px -translate-x-1/2 bg-brand" />
            {/* P25 and P75. The glyph is a band and a band has ends; without
                these it was a box with a line in it, which is a different
                figure. Matches app/icon.svg. */}
            <span className="absolute top-0.5 bottom-0.5 left-0 w-px bg-brand-line" />
            <span className="absolute top-0.5 right-0 bottom-0.5 w-px bg-brand-line" />
          </span>
          Misquote
        </Link>

        {/* Wrapped rather than given a width class, because `Band` renders
            `flex-1` on its own root and `flex: 1 1 0%` sets a flex-basis that
            beats any `w-full` passed in — measured at 45.7px against a 60.3px
            pill, which is why the first attempt at this changed nothing. The
            wrapper is the flex item and carries the widths; inside a block
            parent the nav's own `flex-1` is inert. */}
        <div className="order-last w-full min-w-0 sm:order-none sm:w-auto sm:flex-1">
          <Band label="Primary" routes={product} pathname={pathname} />
        </div>

        {/* The connect button before the theme toggle, because it is the
            product's primary action and the toggle is a preference. `ml-auto`
            only while the band is on its own row, so the pair sits against the
            right edge opposite the wordmark instead of floating beside it. */}
        <div className="ml-auto flex shrink-0 items-center gap-3 sm:ml-0">
          <ConnectButton />
          <ThemeToggle />
        </div>
      </div>

      {/* Labelled "Evidence" rather than "Secondary": the distinction is what
          the pages are for, not which one matters. A reader auditing the tick
          math is not doing something secondary.

          Rendered only inside the section, and the padding moves with it — the
          row carried the header's bottom padding, so dropping the row on the
          other nine routes left the wordmark sitting flush against the border
          until `pb-2` moved onto the row above. */}
      {inEvidence && (
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-5 pb-2">
          <Band
            label="Evidence"
            routes={routesIn("evidence")}
            pathname={pathname}
            className="text-sm"
          />
        </div>
      )}
    </header>
  );
}
