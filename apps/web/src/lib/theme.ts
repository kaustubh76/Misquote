export const THEME_KEY = "misquote.theme";

export type Theme = "auto" | "light" | "dark";

export const THEMES: readonly Theme[] = ["auto", "light", "dark"] as const;

export function isTheme(value: unknown): value is Theme {
  return typeof value === "string" && (THEMES as readonly string[]).includes(value);
}

/**
 * Apply a theme by setting (or clearing) `data-theme` on the root.
 *
 * "auto" *removes* the attribute rather than setting it to "auto". The palette
 * is built on CSS `light-dark()`, which reads `color-scheme`; a bare `:root`
 * declares `color-scheme: light dark` and so follows the OS. Only an explicit
 * choice pins it. So "auto" is the absence of an override, not a third palette.
 */
export function applyTheme(theme: Theme, root: HTMLElement): void {
  if (theme === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

export function readStoredTheme(): Theme {
  try {
    const raw = window.localStorage.getItem(THEME_KEY);
    return isTheme(raw) ? raw : "auto";
  } catch {
    // Private browsing, or storage disabled. Following the OS is a fine default
    // and is strictly better than failing to render.
    return "auto";
  }
}

export function storeTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* non-fatal; the choice just will not survive a reload */
  }
}

/**
 * Runs inline in <head>, before the first stylesheet, so a user who chose a
 * theme against their OS preference never sees the other one flash first.
 * Kept to one statement and wrapped in try/catch — it executes render-blocking,
 * so it must be small and must never throw.
 */
export const THEME_BOOT_SCRIPT = `try{var t=localStorage.getItem(${JSON.stringify(
  THEME_KEY,
)});if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}`;
