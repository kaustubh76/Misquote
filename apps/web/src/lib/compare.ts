/**
 * Which agents a reader has put side by side, across pages and across reloads.
 *
 * Storage follows `lib/theme.ts` exactly, because that file already worked out
 * the shape: a namespaced key, a narrowing read so nothing unvalidated comes
 * back out, and `try`/`catch` on both ends. Private browsing disables storage
 * entirely, and forgetting a selection is a much smaller failure than not
 * rendering.
 *
 * What is deliberately *not* copied is the boot script. The theme needs one
 * because a pinned theme would otherwise flash the other one before hydration;
 * a tray has no equivalent — it renders nothing until mounted, which is what
 * the consumer's `mounted` guard is for. Guessing the contents before hydration
 * would make the server's output disagree with the client's for no gain.
 */
export const COMPARE_KEY = "misquote.compare";

/** Two, and the ceiling is the point rather than a limit we happened to pick. */
export const COMPARE_LIMIT = 2;

/**
 * Not exported: the only thing needing narrowing is what comes out of storage,
 * and `readCompare` is the one place that happens.
 */
function isSlugList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string" && v.length > 0);
}

export function readCompare(): string[] {
  try {
    const raw = window.localStorage.getItem(COMPARE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return isSlugList(parsed) ? parsed.slice(0, COMPARE_LIMIT) : [];
  } catch {
    // Storage disabled, or a value some earlier version wrote in another shape.
    // An empty tray is a correct starting state either way.
    return [];
  }
}

export function storeCompare(slugs: string[]): void {
  try {
    window.localStorage.setItem(COMPARE_KEY, JSON.stringify(slugs.slice(0, COMPARE_LIMIT)));
  } catch {
    // Non-fatal; the selection just will not survive a reload.
  }
}

/**
 * Add or remove one agent, keeping the list at most `COMPARE_LIMIT` long.
 *
 * Adding a third **drops the oldest** rather than refusing. A tray that
 * silently ignores a click looks broken; one that refuses with a message costs
 * a message for a choice nobody needs help making. Sliding the window is the
 * behaviour a reader expects from a two-slot comparison, and it is reversible
 * in one more click.
 */
export function toggleCompare(slugs: readonly string[], slug: string): string[] {
  if (slugs.includes(slug)) return slugs.filter((s) => s !== slug);
  return [...slugs, slug].slice(-COMPARE_LIMIT);
}
