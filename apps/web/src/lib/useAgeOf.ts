"use client";

import { useEffect, useState } from "react";
import { ago } from "@/lib/format";

/**
 * The age of an instant, filled in after mount.
 *
 * Returns `null` on the first render — the one the server prerenders and the
 * browser hydrates — and the phrase after. That ordering is the whole point:
 * `ago()` reads the clock, the clock differs between build time and page load,
 * and a value that differs between the server's HTML and the client's first
 * render is a hydration mismatch. React error #418 is the one
 * `apps/web/scripts/check-pages.mjs` records 150 failed reproduction attempts
 * for; `lib/scenario.ts` documents the same shape from the other direction,
 * reading `location.search` in an effect because "a simulated page cannot
 * prerender".
 *
 * So callers render the absolute timestamp — stable, correct with JavaScript
 * off — and append this when it arrives.
 */
export function useAgeOf(iso: unknown): string | null {
  const [age, setAge] = useState<string | null>(null);
  useEffect(() => {
    setAge(ago(iso));
  }, [iso]);
  return age;
}
