"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

/**
 * Client-side navigation replaces the document without a page load, so a screen
 * reader is told nothing: no title announcement, and focus stays wherever the
 * clicked link used to be. This restores both.
 *
 * The old page had the matching problem in miniature — it swapped
 * "Loading artifacts…" for three cards inside a region with no `aria-live`, so
 * the only signal that anything had happened was visual.
 */
export function RouteAnnouncer() {
  const pathname = usePathname();
  const first = useRef(true);

  useEffect(() => {
    if (first.current) {
      // Skip the initial mount: the document title already announced itself.
      first.current = false;
      return;
    }

    const heading = document.querySelector<HTMLElement>("main h1");
    if (heading) {
      heading.setAttribute("tabindex", "-1");
      heading.focus({ preventScroll: true });
    }

    const region = document.getElementById("route-announcer");
    if (region) region.textContent = `${heading?.textContent ?? document.title}, page loaded`;
  }, [pathname]);

  return (
    <div
      id="route-announcer"
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className="visually-hidden"
    />
  );
}
