"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ThemeToggle } from "@/components/ThemeToggle";
import { type Route, routesIn } from "@/lib/routes";



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
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => {
      el.removeEventListener("scroll", measure);
      observer.disconnect();
    };
  }, [measure]);

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
          className="pointer-events-none absolute inset-y-0 left-0 z-10 w-8 bg-gradient-to-r from-bg to-transparent"
        />
      )}
      {end && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 right-0 z-10 w-8 bg-gradient-to-l from-bg to-transparent"
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
 * Two bands, because eleven routes fitted one strip and thirteen do not.
 *
 * The flat list was already a horizontal scroller with measured fades, and it
 * worked — but at 1280px the last label was cut mid-word, and a scroller is a
 * way to *survive* not fitting rather than a way to fit. The split is by what a
 * reader is doing: the top band is the product (look at the agents, get a
 * quote, hire one, browse the registry), the second is the evidence any of it
 * rests on.
 *
 * Every route stays a link in the document on every page. A disclosure that
 * unmounted the second band would be tidier and would break two things at once:
 * `check-pages.mjs` requires the current route's pill to be *visible*, and a
 * screen-reader user would lose seven routes behind a control they have to find
 * first. Nothing here is hidden; it is arranged.
 */
export function Nav() {
  const pathname = usePathname() ?? "/";

  return (
    <header className="sticky top-0 z-50 border-b border-line bg-bg/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-5 pt-3">
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
            <span className="absolute top-0 bottom-0 left-1/2 w-px -translate-x-1/2 bg-brand" />
          </span>
          Misquote
        </Link>

        <Band label="Primary" routes={routesIn("product")} pathname={pathname} />

        <div className="shrink-0">
          <ThemeToggle />
        </div>
      </div>

      <div className="mx-auto flex max-w-6xl items-center gap-4 px-5 pb-2">
        {/* Labelled "Evidence" rather than "Secondary": the distinction is what
            the pages are for, not which one matters. A reader auditing the tick
            math is not doing something secondary. */}
        <Band
          label="Evidence"
          routes={routesIn("evidence")}
          pathname={pathname}
          className="text-sm"
        />
      </div>
    </header>
  );
}
