import { count, fraction } from "@/lib/format";

/**
 * A share, and the interval it is worth at the sample size that produced it.
 *
 * `registry.json` publishes six Wilson 95% intervals over one sample of 400
 * agent cards, next to a comment in `src/app/registry/view.tsx` saying that a
 * share of a few hundred out of ~280,000 "is not a point, and printing it as
 * one is the false precision this page exists to criticise". The page then
 * printed one of them as the text "34.8%" and dropped the other five. This
 * draws all six.
 *
 * ## Why this is not `src/components/Band.tsx`
 *
 * `Band` is built for a return distribution, and six of its mechanisms are
 * wrong here: it fits its domain to the data with padding, where a share is
 * bounded and fitting it would draw 89% and 94% at opposite ends of a card; it
 * has a zero rule that can never be inside a 0-100 domain; it draws a rug of
 * window observations, and there are no windows; its two tones mean "the agent"
 * and "doing it yourself", which six survey shares are neither of; and its
 * caption fires an overlap sentence about strategy indistinguishability at
 * exactly two series.
 *
 * The one that settles it is the seventh. `Band`'s accessible description says
 * "P25 ..., median ..., P75 ..." — and **a Wilson interval is not a quartile
 * range and a share is not a median**. Reusing it would put a factually wrong
 * sentence into the one channel a reader who cannot see the chart has. `Band`
 * deleted its own `unit` prop over the same class of defect: a fix that does
 * not reach the spoken half is not a fix. So this is a sibling, the way
 * `RouterArtifact` is a sibling of `AgentArtifact` rather than a variant of it.
 *
 * ## The axis is 0 to 100 and nothing else
 *
 * A share is bounded, so the bounds are the axis. Every bar is the same
 * `sampled` cards, which is what makes the rows comparable to each other rather
 * than only to themselves — the rule `src/components/GateHistogram.tsx` learned
 * when three gates scaled to their own maximum and drew "every gate blocked
 * every decision".
 *
 * ## Nothing is clamped
 *
 * The placeholder rate is 0 of 400 and its interval runs to 0.95%, which is
 * 0.95% of this axis and renders as the sliver it is. `Band` removed its own
 * minimum-width clamp for exactly this reason: a floor on the width draws a
 * range the data does not have.
 */
export interface ShareInterval {
  /** The key the emitter published, e.g. `resolvable`. */
  key: string;
  /** What it counts, in the words the emitter's own report already uses. */
  label: string;
  /** The numerator, out of `sampled`. Never reconstructed from a percentage. */
  n: number;
  /** The 95% Wilson bounds, as fractions in [0, 1]. */
  low: number;
  high: number;
}

/**
 * A share written to enough places to say what it is.
 *
 * At one decimal, the placeholder upper bound — 0.0095 — renders as "1.0%",
 * rounding a bound *up* past the round number it sits below, on the one row
 * whose whole point is that none observed is not the same as none existing.
 * Anything under one percent keeps a second place; everything else stays at
 * one, because six rows of "89.21%" is precision the sample does not have
 * either.
 *
 * Written `v * 100 < 1` rather than comparing against a hundredth directly,
 * because that value is one some artifact on this site carries and
 * `tests/web/test_artifact_contract.py` reads every one of them as a literal
 * that may not appear in a component.
 */
function share(v: number): string {
  return fraction(v, v > 0 && v * 100 < 1 ? 2 : 1);
}

export function ShareIntervals({
  rows,
  sampled,
  caption,
}: {
  rows: ShareInterval[];
  /** The denominator every row shares. Stated by the caller, never inferred. */
  sampled: number;
  caption: string;
}) {
  if (rows.length === 0 || sampled <= 0) return null;

  return (
    <figure className="m-0" role="group" aria-label={caption}>
      {/* The axis is the whole domain, not the data's extent. `aria-hidden`
          because every bar below spells its own numbers out in full. */}
      <div
        className="relative mb-3 h-4 border-b border-line text-[10px] text-faint"
        aria-hidden="true"
      >
        <span className="absolute left-0">0%</span>
        <span className="absolute left-1/2 -translate-x-1/2">50%</span>
        <span className="absolute right-0">100%</span>
      </div>

      <ul className="m-0 list-none space-y-3 p-0">
        {rows.map((row) => {
          const point = row.n / sampled;
          return (
            <li key={row.key}>
              {/* `flex-wrap` and `min-w-0` together, both for the reason
                  `Band.tsx` documents: a flex item defaults to `min-width:
                  auto` and refuses to shrink below its content, and wrapping
                  happens between items rather than inside one. */}
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-3 text-xs">
                <span className="min-w-0 break-words text-dim">{row.label}</span>
                <span className="tabular text-ink">
                  {share(row.low)} – {share(row.high)}
                </span>
              </div>

              {/* One `role="img"` per bar carrying a whole sentence — the
                  pattern `src/components/FloorGauge.tsx` and the `/status` gate
                  strip both use. A bare div announces as "image" and tells a
                  reader there was a figure without telling them what it said. */}
              <div
                className="relative h-5 rounded-sm border border-glass-line bg-panel-2/60"
                role="img"
                aria-label={
                  `${row.label}: ${count(row.n)} of ${count(sampled)} sampled, ` +
                  `${share(point)}. At this sample size the 95% confidence interval ` +
                  `runs from ${share(row.low)} to ${share(row.high)}.`
                }
              >
                {/* The interval. `band-draw` and `band-tick` are already named
                    in the `prefers-reduced-motion` block in globals.css, so
                    this component introduces no motion of its own to forget. */}
                <div
                  className="band-draw absolute inset-y-0 rounded-sm border border-neutral-line bg-neutral/25"
                  style={{
                    left: `${row.low * 100}%`,
                    width: `${(row.high - row.low) * 100}%`,
                  }}
                />
                {/* The point estimate — the number every other marketplace
                    would print on its own — drawn as a tick inside the range it
                    came with, in the brand colour, which is the mark
                    `src/components/TickRule.tsx` makes at glyph scale. */}
                <div
                  className="band-tick absolute inset-y-0 w-0.5 bg-brand"
                  style={{ left: `${point * 100}%` }}
                />
              </div>

              <p className="mt-1 mb-0 text-xs text-faint">
                {count(row.n)} of {count(sampled)} · {share(point)}
              </p>
            </li>
          );
        })}
      </ul>

      <figcaption className="mt-4 border-t border-line pt-3 text-xs text-dim">
        Every bar is the same {count(sampled)} cards, so the rows are comparable to
        each other and not only to themselves. The tick is the share observed; the
        bar is what {count(sampled)} observations support.
        {rows.some((r) => r.n === 0) && (
          <>
            {" "}
            A row at zero still has a bar: none of the {count(sampled)} was one, which
            is a different claim from none of the registry being one.
          </>
        )}
      </figcaption>
    </figure>
  );
}
