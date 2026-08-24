"use client";

import { useEffect, useRef, useState } from "react";
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
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    setTheme(readStoredTheme());
    setMounted(true);
  }, []);

  function choose(next: Theme) {
    setTheme(next);
    storeTheme(next);
    applyTheme(next, document.documentElement);
  }

  /**
   * Arrow-key traversal, because the group says `role="radiogroup"`.
   *
   * It said so already and did none of it: all three buttons were tab stops
   * and the arrow keys did nothing, so a screen-reader user in forms mode met
   * a group that did not behave like the role it announced. APG wants one tab
   * stop, arrow keys to move, and movement to *be* selection.
   */
  function onKeyDown(event: React.KeyboardEvent, index: number) {
    const last = THEMES.length - 1;
    let next: number | null = null;

    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = index === last ? 0 : index + 1;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = index === 0 ? last : index - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    if (next === null) return;

    event.preventDefault();
    choose(THEMES[next]!);
    buttons.current[next]?.focus();
  }

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="inline-flex items-center gap-0.5 rounded-md border border-glass-line bg-glass p-0.5"
    >
      {THEMES.map((option, i) => {
        // Before hydration we cannot know the stored choice, so nothing is
        // marked selected. Rendering a guess here would make the server output
        // disagree with the client and produce a hydration mismatch.
        const selected = mounted && theme === option;
        return (
          <button
            key={option}
            ref={(node) => {
              buttons.current[i] = node;
            }}
            type="button"
            role="radio"
            aria-checked={selected}
            // Roving tabindex: one stop for the whole group. Before hydration
            // nothing is selected, so the first option holds the stop rather
            // than leaving the group unreachable.
            tabIndex={selected || (!mounted && i === 0) ? 0 : -1}
            onKeyDown={(event) => onKeyDown(event, i)}
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
