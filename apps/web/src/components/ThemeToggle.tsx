"use client";

import { useEffect, useState } from "react";
import { applyTheme, readStoredTheme, storeTheme, THEMES, type Theme } from "@/lib/theme";

const LABEL: Record<Theme, string> = {
  auto: "System",
  light: "Light",
  dark: "Dark",
};

const GLYPH: Record<Theme, string> = {
  auto: "◐",
  light: "☀",
  dark: "☾",
};

/**
 * Three states, as a radio group rather than a two-way switch.
 *
 * A binary toggle cannot express "follow the OS", so it silently converts every
 * visitor into someone with a pinned preference the first time they touch it.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("auto");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setTheme(readStoredTheme());
    setMounted(true);
  }, []);

  function choose(next: Theme) {
    setTheme(next);
    storeTheme(next);
    applyTheme(next, document.documentElement);
  }

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="inline-flex items-center gap-0.5 rounded-md border border-line bg-panel p-0.5"
    >
      {THEMES.map((option) => {
        // Before hydration we cannot know the stored choice, so nothing is
        // marked selected. Rendering a guess here would make the server output
        // disagree with the client and produce a hydration mismatch.
        const selected = mounted && theme === option;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={selected}
            title={`${LABEL[option]} theme`}
            onClick={() => choose(option)}
            className={[
              "cursor-pointer rounded-sm px-2 py-1 text-xs leading-none transition-colors",
              selected ? "bg-neutral-bg text-ink" : "text-faint hover:text-ink",
            ].join(" ")}
          >
            <span aria-hidden="true">{GLYPH[option]}</span>
            <span className="visually-hidden">{LABEL[option]}</span>
          </button>
        );
      })}
    </div>
  );
}
