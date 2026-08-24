"use client";

import { useCallback, useEffect, useState } from "react";
import { COMPARE_KEY, readCompare, storeCompare, toggleCompare } from "@/lib/compare";

/**
 * Put this agent in the tray, or take it out.
 *
 * `aria-pressed` rather than a checkbox or a radio: this is a toggle button
 * whose two states are "in the comparison" and "not", which is exactly what
 * `aria-pressed` describes. `ChipGroup`'s `radiogroup` was the other candidate
 * and is wrong here — that is single-select, and a tray holds two.
 *
 * Renders a stable label before mount. The selection lives in `localStorage`,
 * which the server cannot read, so claiming "Added" during SSR would make the
 * server's markup disagree with the client's. Same `mounted` guard as
 * `ThemeToggle`, same reason.
 */
export function CompareToggle({ slug, name }: { slug: string; name: string }) {
  const [mounted, setMounted] = useState(false);
  const [selected, setSelected] = useState(false);

  const sync = useCallback(() => setSelected(readCompare().includes(slug)), [slug]);

  useEffect(() => {
    setMounted(true);
    sync();
  }, [sync]);

  // The tray removes agents too, and a chip removed there must un-press the
  // button here. Storage events cover other tabs; this covers this one.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === COMPARE_KEY) sync();
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener("misquote:compare", sync);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("misquote:compare", sync);
    };
  }, [sync]);

  const onClick = () => {
    const next = toggleCompare(readCompare(), slug);
    storeCompare(next);
    setSelected(next.includes(slug));
    // Same-tab notification. `storage` fires only in *other* tabs, so without
    // this the tray and the buttons drift apart on the page you are looking at.
    window.dispatchEvent(new Event("misquote:compare"));
  };

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={mounted ? selected : false}
      className={[
        "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
        mounted && selected
          ? "border-brand-line bg-brand-bg text-brand"
          : "border-line bg-panel text-dim hover:border-brand hover:text-brand",
      ].join(" ")}
    >
      {mounted && selected ? "In comparison" : "Compare"}
      <span className="visually-hidden"> {name}</span>
    </button>
  );
}
