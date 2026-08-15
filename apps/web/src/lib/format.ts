/**
 * Formatters, all null-safe.
 *
 * The page these replace printed `num(v, 6)` for every figure, so a fee total
 * rendered as `865.430184` — six decimals of a dollar amount, which reads as
 * precision the number does not have. Worse, `undefined` fell through the same
 * path and was compared with `>`, so a missing value came out styled as a loss.
 *
 * The rule here: a value that is absent renders as an em dash and carries no
 * judgement colour. "We do not know" and "it is bad" are different claims.
 */

export const EMPTY = "—";

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/**
 * A money-ish quantity, to two decimals.
 *
 * This is a display rounding and nothing more. The artifact carries the full
 * precision and is the citable source — an earlier version of this comment
 * promised "full precision in the title", which nothing implemented, and the
 * helper written for it sat exported with no importers. Putting it back would
 * mean hiding a figure behind a hover, which is the affordance `Pill` and
 * `Band` had their `title` attributes removed for.
 */
export function amount(v: unknown, decimals = 2): string {
  if (!isNum(v)) return EMPTY;
  return v.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** A percentage already expressed in percentage points (37.74 -> "37.74%"). */
export function pct(v: unknown, decimals = 2): string {
  if (!isNum(v)) return EMPTY;
  return `${v.toFixed(decimals)}%`;
}

/** A fraction in [0,1] rendered as a percentage (0.5956 -> "59.6%"). */
export function fraction(v: unknown, decimals = 1): string {
  if (!isNum(v)) return EMPTY;
  return `${(100 * v).toFixed(decimals)}%`;
}

/** Signed, with an explicit sign character so the direction survives greyscale. */
export function signed(v: unknown, decimals = 2, suffix = ""): string {
  if (!isNum(v)) return EMPTY;
  const sign = v > 0 ? "+" : v < 0 ? "−" : "±";
  return `${sign}${Math.abs(v).toFixed(decimals)}${suffix}`;
}

export function count(v: unknown): string {
  if (!isNum(v)) return EMPTY;
  return Math.round(v).toLocaleString("en-US");
}

export function hours(v: unknown, decimals = 1): string {
  if (!isNum(v)) return EMPTY;
  return `${v.toFixed(decimals)}h`;
}

/**
 * Which judgement class a signed value earns.
 *
 * Returns `"none"` — not `"neg"` — when the value is missing or not finite.
 * The bug this replaces was `net > 0 ? "pos" : "neg"`, under which `undefined`
 * took the false branch and a placeholder dash was painted in the loss colour.
 */
export type Sign = "pos" | "neg" | "zero" | "none";

export function signOf(v: unknown): Sign {
  if (!isNum(v)) return "none";
  if (v > 0) return "pos";
  if (v < 0) return "neg";
  return "zero";
}

export const SIGN_CLASS: Record<Sign, string> = {
  pos: "text-good",
  neg: "text-bad",
  zero: "text-dim",
  none: "text-faint",
};

/** Shorten a 0x address for display without hiding that it is an address. */
export function shortAddress(addr: string, lead = 6, tail = 4): string {
  if (!/^0x[0-9a-fA-F]{40}$/.test(addr)) return addr;
  return `${addr.slice(0, lead)}…${addr.slice(-tail)}`;
}

/** An ISO timestamp as something a human reads, with the raw value preserved. */
export function timestamp(iso: unknown): string {
  if (typeof iso !== "string") return EMPTY;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
