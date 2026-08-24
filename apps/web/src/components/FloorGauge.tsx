import { count } from "@/lib/format";

/**
 * A floor, drawn.
 *
 * This site refuses to print a number when the evidence behind it is too thin,
 * and until now it said so only in words: "n = 18, floor 30". That is the
 * product's central move rendered as a footnote. Here it is a picture — a bar
 * that visibly does not reach a line — so a reader sees the shortfall before
 * they read the sentence, and sees *how far* short, which the sentence never
 * said.
 *
 * The scale is `max(observed, required) × 1.25`, so the floor mark is always on
 * screen with headroom on both sides. It is not `required` alone: a run with
 * twice the observations it needs would push its own bar off the end and read
 * as if it had failed.
 *
 * Colour is never the only signal, which is the rule `src/components/Pill.tsx`
 * sets out for this codebase. Short of the floor the bar is hatched at 135° —
 * the same texture as a withheld band and a not-built card — and clear of it
 * the bar is solid. Texture and length carry the verdict; the tint agrees with
 * them and is not asked to do the work alone.
 */
export function FloorGauge({
  label,
  observed,
  required,
  unit,
  format = count,
}: {
  label: string;
  observed: number;
  required: number;
  unit?: string;
  /**
   * How to write the two figures. Defaults to `count`, which rounds to a whole
   * number — right for observations and windows, and wrong for the one floor
   * that is a fraction: `in_range_floor` is 0.7 against an observed 0.058, and
   * `count` renders those as "1" and "0". A floor stated as a percentage has to
   * be read as one, so the caller passes `fraction`.
   */
  format?: (v: unknown) => string;
}) {
  const clears = observed >= required;
  const scale = Math.max(observed, required) * 1.25 || 1;
  const pct = (n: number) => `${Math.min(100, (n / scale) * 100)}%`;
  const suffix = unit ? ` ${unit}` : "";

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="text-dim">{label}</span>
        <span className={`tabular ${clears ? "text-good" : "text-warn"}`}>
          {format(observed)}
          {suffix} / floor {format(required)}
        </span>
      </div>

      {/* One `role="img"` with a full sentence, rather than three bare divs.
          The shortfall is the content; a screen reader that got "image, bar"
          would have been told there was a figure and not what it said. */}
      <div
        className="relative mt-1.5 h-3 rounded-full border border-glass-line bg-panel-2/60"
        role="img"
        aria-label={
          clears
            ? `${label}: ${format(observed)}${suffix}, clear of the floor of ${format(required)}.`
            : `${label}: ${format(observed)}${suffix}, short of the floor of ${format(required)}.`
        }
      >
        <div
          className={`absolute inset-y-0 left-0 rounded-full ${
            clears ? "bg-good/70" : "hatched border-r border-warn-line"
          }`}
          style={{
            width: pct(observed),
            ...(clears ? {} : { ["--hatch-tone" as string]: "var(--hatch-warn)" }),
          }}
        />
        {/* The floor itself: a full-height rule, not a tint boundary, because
            it is a threshold and a threshold has a position. */}
        <div
          className="absolute -top-0.5 -bottom-0.5 w-0.5 rounded-full bg-line-strong"
          style={{ left: pct(required) }}
        />
      </div>
    </div>
  );
}
