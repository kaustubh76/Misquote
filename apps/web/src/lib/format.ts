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

/**
 * An amount with the unit it is denominated in.
 *
 * Every money figure on this site was rendered bare — `-186.74`, `0.02`,
 * `1,000.00` — and a reader supplies the missing unit from context. The context
 * says dollars. It is not dollars.
 *
 * `*_quote` means **token1**, which on the flagship pool is WBNB:
 * `CostModel.gas_quote` is documented as "3.0e-5 BNB, about two cents", and
 * `ranges.py` divides "net token1" by capital to get a return. So `-186.74` is
 * 186.74 BNB, roughly a hundred thousand dollars, and it was on the front page
 * looking like the price of a bicycle.
 *
 * The unit cannot be read off the pair name, which is the trap that makes this
 * a field rather than a regex. The label is `PancakeSwap v3 WBNB/USDT 0.05%`;
 * pairs are written base-first; the quote asset in the trading sense is USDT
 * and it is token0. Taking "the quote" from the label gives the one token these
 * figures are certainly *not* in. `PoolRef.quote_symbol` records token1 and a
 * test cross-checks it against both halves of the label.
 *
 * When `unit` is absent the figure renders bare, because an artifact written
 * before the emitter carried the field genuinely does not say what it is in,
 * and "we did not record it" beats a confident guess. When the *value* is
 * absent it renders as the em dash alone — never `— WBNB`, which would attach a
 * unit to a measurement that does not exist.
 *
 * The separator is a non-breaking space, so `186.74 WBNB` cannot wrap with
 * the figure on one line and its unit on the next — which is a bare number
 * again, in the layout where the cards are narrowest.
 */
export function money(v: unknown, unit?: string, decimals = 2): string {
  if (!isNum(v)) return EMPTY;
  const figure = amount(v, decimals);
  return unit ? `${figure}\u00a0${unit}` : figure;
}

/**
 * A bare dimensionless number, to a fixed number of decimals.
 *
 * The gap this fills is why it exists. Every formatter here covers a *kind* of
 * quantity — money, a percentage, a fraction, a count, a duration — and the
 * estimator block is none of them: σ per √hour, κ per tick, an r², a z-score.
 * So six call sites in `AgentDetail` wrote `e.sigma_per_sqrt_hour.toFixed(6)`
 * and went around the null-safety this file exists to provide.
 *
 * `amount()` was not usable for them: it goes through `toLocaleString`, which
 * groups thousands, and a κ of 3600.907 rendered `3,600.91` is a number with a
 * comma in it where the artifact has none.
 *
 * Not grouped, for the same reason. These are parameters, not amounts, and the
 * value on screen should be the value in the JSON.
 */
export function fixed(v: unknown, decimals = 2): string {
  if (!isNum(v)) return EMPTY;
  return v.toFixed(decimals);
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
