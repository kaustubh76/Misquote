"use client";

import { useRef } from "react";

export interface Chip<T extends string> {
  value: T;
  label: string;
  /** Shown after the label, in the dim tone. A count, usually. */
  meta?: string;
}

/**
 * One choice from a few, as a radio group that behaves like one.
 *
 * Extracted from `ThemeToggle`, which had already made this mistake once and
 * fixed it: the element said `role="radiogroup"` while all three buttons were
 * tab stops and the arrow keys did nothing, so a screen-reader user in forms
 * mode met a group that did not behave like the role it announced. APG wants
 * one tab stop for the whole group, arrow keys to move between options, and
 * movement to *be* selection.
 *
 * Sharing it rather than writing it a second time for the assumption filter,
 * because the second copy is where the arrow keys quietly go missing again —
 * and a wrong keyboard contract is invisible to everything except a keyboard.
 * `ThemeToggle` keeps its own copy for now: it has a pre-hydration case that
 * has nothing to do with filtering, where no option may be marked selected
 * because guessing would make the server output disagree with the client.
 */
export function ChipGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly Chip<T>[];
  value: T;
  onChange: (next: T) => void;
}) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(event: React.KeyboardEvent, index: number) {
    const last = options.length - 1;
    let next: number | null = null;

    if (event.key === "ArrowRight" || event.key === "ArrowDown")
      next = index === last ? 0 : index + 1;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp")
      next = index === 0 ? last : index - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    if (next === null) return;

    event.preventDefault();
    const option = options[next];
    if (!option) return;
    onChange(option.value);
    buttons.current[next]?.focus();
  }

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="flex flex-wrap items-center gap-1"
    >
      {options.map((option, i) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            ref={(node) => {
              buttons.current[i] = node;
            }}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            onKeyDown={(event) => onKeyDown(event, i)}
            onClick={() => onChange(option.value)}
            className={[
              "cursor-pointer rounded-sm border px-2.5 py-1 text-xs transition-colors",
              selected
                ? "border-accent bg-neutral-bg text-ink"
                : "border-line text-dim hover:border-accent hover:text-ink",
            ].join(" ")}
          >
            {option.label}
            {option.meta && (
              // Part of the button's accessible name on purpose: "Defects 13"
              // is the useful thing to hear, and a visually-hidden duplicate
              // would make it "Defects 13 13".
              <span className={selected ? "ml-1.5 text-dim" : "ml-1.5 text-faint"}>
                {option.meta}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
