"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ROUTES } from "@/lib/routes";



/**
 * Where the reader is: on this page, or somewhere under it.
 *
 * `/agent/warden` has no nav entry of its own, and the earlier rule — exact
 * match, plus a prefix match that `href === "/"` short-circuits out of —
 * returned nothing for it. So the three agent detail pages, which are a third
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

export function Nav() {
  const pathname = usePathname() ?? "/";
  const { ref, start, end } = useOverflowEdges<HTMLUListElement>(pathname);

  return (
    <header className="sticky top-0 z-50 border-b border-line bg-bg/85 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center gap-4 px-5 py-3">
        <Link
          href="/"
          className="shrink-0 font-mono text-sm font-semibold tracking-tight text-ink no-underline"
        >
          Misquote
        </Link>

        {/* Overflows to a horizontal scroll rather than wrapping or truncating,
            so every route stays reachable at 320px. */}
        <nav aria-label="Primary" className="relative min-w-0 flex-1">
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
            {ROUTES.map((link) => {
              const active = activeness(pathname, link.href);
              return (
                <li key={link.href} className="shrink-0">
                  <Link
                    href={link.href}
                    aria-current={
                      active === "page" ? "page" : active === "section" ? "true" : undefined
                    }
                    className={[
                      "block rounded-sm px-2.5 py-1.5 text-sm no-underline transition-colors",
                      active ? "bg-neutral-bg text-ink" : "text-dim hover:text-ink",
                    ].join(" ")}
                  >
                    {link.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="shrink-0">
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
