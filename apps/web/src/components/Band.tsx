import { FloorGauge } from "@/components/FloorGauge";
import { isNum, pct, signed } from "@/lib/format";

export interface BandSeries {
  label: string;
  p25: number;
  p50: number;
  p75: number;
  /** "agent" is the thing being sold; "baseline" is doing it yourself. */
  tone: "agent" | "baseline";
}

export interface BandProps {
  series: BandSeries[];
  /** False when the quote was withheld for want of history. */
  sufficient: boolean;
  /** The engine's own sentence about why it withheld. Rendered verbatim. */
  note?: string;

  /**
   * The floor the evidence fell short of, when the caller knows both numbers.
   *
   * Read only by the withheld branch, and optional there. Every figure in it
   * has to come from the artifact — `quote_detail.samples` against
   * `floors.min_observations`, `quote_detail.windows` against
   * `floors.min_windows`. A gauge drawn from a floor this component guessed
   * would put a fabricated threshold under a refusal, which is the one place
   * on this site where a made-up number would do the most damage.
   */
  floor?: { label: string; observed: number; required: number; unit?: string };
  /** Individual window returns, drawn as a rug behind the band. */
  returns?: number[];
  caption?: string;

  /**
   * Whether the two bands overlap, and by how much the medians differ, as
   * computed by the engine.
   *
   * Recomputing these here would put a second implementation of
   * `Comparison.ranges_overlap` and `Comparison.delta` in the browser, one
   * screen-inch from the verdict sentence Python wrote. They agree today; the
   * point is that they cannot be *made* to disagree. Passed in wherever the
   * artifact carries them, derived only as a fallback for a series pair the
   * engine never compared.
   */
  overlap?: boolean;
  deltaPp?: number;
}

const TONE = {
  agent: {
    fill: "bg-good/25",
    edge: "border-good-line",
    tick: "bg-good",
    text: "text-good",
    dot: "bg-good",
  },
  baseline: {
    fill: "bg-neutral/25",
    edge: "border-neutral-line",
    tick: "bg-neutral",
    text: "text-dim",
    dot: "bg-neutral",
  },
} as const;

/**
 * Domain covering the data, with 8% breathing room. Zero is *not* an anchor.
 *
 * It used to be: `[0, ...returns, ...percentiles]`. On a tape where the agents
 * quote around -233% against a baseline of -1.77%, that made the domain 275
 * percentage points wide to hold data spanning 7 — and every band collapsed to
 * a hairline. Warden's rendered at **0.0023%** of the axis.
 *
 * Zero earns a line when it falls inside the data (a range that straddles zero
 * means something different from one that clears it), and when it does not, the
 * caption says which side of it everything sits. Anchoring the axis to a value
 * no observation is near buys nothing and costs the whole chart.
 */
function domain(series: BandSeries[], returns: number[]): [number, number] {
  const values = [...returns.filter(isNum)];
  for (const s of series) values.push(s.p25, s.p50, s.p75);
  if (values.length === 0) return [-1, 1];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  if (lo === hi) return [lo - 1, hi + 1];
  const pad = (hi - lo) * 0.08;
  return [lo - pad, hi + pad];
}

/**
 * The observations, grouped by value, so a stack reads as a stack.
 *
 * `returns` is `windows × perturbations` — 20 × 3 on every current artifact —
 * and the three perturbations produce **identical** results for almost every
 * window: 0 of 60 differ on grid and sentinel, 3 of 60 on warden. Drawing 60
 * ticks therefore drew 20, three times over, at the same pixel.
 *
 * Rounding to 4 decimal places is what separates a genuinely distinct window
 * from float noise; at 2dp warden's 20 windows collapse to 5 values, which
 * would hide real structure.
 */
export interface Cluster {
  value: number;
  count: number;
}

export function cluster(returns: number[]): Cluster[] {
  const byValue = new Map<number, number>();
  for (const r of returns.filter(isNum)) {
    const key = Math.round(r * 1e4) / 1e4;
    byValue.set(key, (byValue.get(key) ?? 0) + 1);
  }
  return [...byValue.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => a.value - b.value);
}

/**
 * How concentrated the observations are, as a sentence the chart can print.
 *
 * The interquartile range is the thing this component was built to draw, and on
 * the current tape it is 0.0062 percentage points inside an observed span of
 * 7.25 — 0.086%. Below the width of one pixel there is nothing to draw and a
 * box would be a lie, so the concentration is stated instead: how many of the
 * observations sit within a hair of the median, and how wide that hair is.
 *
 * Not exported: only this component uses it. It briefly was, and
 * `test_no_dead_exports` passed — because the word "concentration" appears in a
 * test's *title*. That guard matches a bare word anywhere in another file, so
 * prose satisfies it; worth knowing before trusting it to catch the next one.
 */
function concentration(
  returns: number[],
  median: number,
): { within: number; total: number; tolerance: number } | null {
  const values = returns.filter(isNum);
  if (values.length === 0) return null;
  const span = Math.max(...values) - Math.min(...values);
  // A hundredth of the observed span, floored so a perfectly flat set still
  // reports something rather than dividing by zero.
  const tolerance = Math.max(span / 100, 1e-4);
  const within = values.filter((v) => Math.abs(v - median) <= tolerance).length;
  return { within, total: values.length, tolerance };
}

function position(value: number, [lo, hi]: [number, number]): number {
  if (hi === lo) return 50;
  return ((value - lo) / (hi - lo)) * 100;
}

/**
 * A P25–P75 range, drawn.
 *
 * Assumption A5 is that a quote is a range and never a point estimate, because
 * "a single number implies a precision the data does not support". The card
 * page honoured that in the text — "36.88% to 38.72%" — and then had no way to
 * show it, so the range was something you read rather than something you saw.
 *
 * Two series share one axis on purpose. When the agent's band and the DIY
 * band overlap, the medians can sit far apart while the two strategies remain
 * indistinguishable at this sample size; that is exactly the misquote the
 * product argues against, and it is visible here without reading a word.
 *
 * Positioned elements rather than SVG: the bar has to be fluid across a 320px
 * phone and a wide desktop, and a stretched SVG distorts its own stroke widths
 * and text. Geometry is percentage-based, labels are real HTML, and the whole
 * thing carries a text equivalent for anyone who is not looking at it.
 */
export function Band({
  series,
  sufficient,
  note,
  floor,
  returns = [],
  caption,
  overlap,
  deltaPp,
}: BandProps) {
  if (!sufficient) {
    return (
      <div className="rounded-md border border-warn-line bg-warn-bg/40 p-4">
        {/* The hatch used to be written here, inline, at 135° with its own 5px
            period — and separately in Ledger.tsx, and separately again as a
            grey `animate-pulse` in Skeleton.tsx. Three inventions of one idea.
            `.hatched` in globals.css is the single one now, at a single angle,
            so a reader who has learnt this texture on a not-built card has
            already learnt it here.

            Dashed rather than solid, and no median tick at all. A band without
            a median is a range nobody stood behind, which is exactly the claim:
            the shape of the answer is known and the number is not. Drawing a
            tick — even a faint one — would put a value on the page that the
            engine refused to state. */}
        <div
          className="hatched h-9 w-full rounded-sm border border-dashed border-warn-line/70"
          style={{ ["--hatch-tone" as string]: "var(--hatch-warn)" }}
          role="img"
          aria-label="No range: the quote was withheld."
        />
        <p className="mt-3 mb-0 text-sm text-warn">
          <span className="font-semibold">Quote withheld.</span>{" "}
          {/* The engine's own words. Paraphrasing a refusal is how it becomes
              an apology instead of a result. */}
          {note || "Not enough history to state a range that describes the strategy."}
        </p>
        {/* The shortfall, as a figure rather than a footnote. Only when the
            caller has both numbers — a gauge with a guessed floor would be the
            fabrication this whole branch exists to avoid. */}
        {floor && (
          <div className="mt-3">
            <FloorGauge
              label={floor.label}
              observed={floor.observed}
              required={floor.required}
              unit={floor.unit}
            />
          </div>
        )}
      </div>
    );
  }

  const scale = domain(series, returns);
  const zero = position(0, scale);
  const zeroInside = scale[0] < 0 && scale[1] > 0;

  const clusters = cluster(returns);
  const maxCount = Math.max(1, ...clusters.map((c) => c.count));
  const agent = series.find((s) => s.tone === "agent");
  const spread = agent ? concentration(returns, agent.p50) : null;

  // Percent is hardcoded, and a `unit` prop that would have changed it was
  // deleted rather than kept for a future caller. It reached only this string —
  // the spoken one. The axis ticks go through `pct()`, which writes "%" and
  // takes no unit, so `unit="bp"` would have had a screen reader read basis
  // points off a chart labelled in percent. Every series drawn here is a return
  // or a fraction; when one genuinely is not, the honest change is a unit that
  // reaches both halves at once, not this one.
  const description = series
    .map(
      (s) =>
        `${s.label}: P25 ${s.p25.toFixed(2)}%, median ${s.p50.toFixed(2)}%, P75 ${s.p75.toFixed(2)}%`,
    )
    .join("; ");

  return (
    <figure className="m-0">
      <div
        className="relative rounded-md border border-line bg-panel-2 px-3 py-3"
        role="img"
        aria-label={`${caption ? `${caption}. ` : ""}${description}`}
      >
        {/* Zero. Every metric here can legitimately be negative, and a range
            that straddles zero means something different from one that clears
            it — so the line is drawn rather than implied. */}
        {zeroInside && (
          <div
            className="pointer-events-none absolute inset-y-2 w-px bg-line-strong"
            style={{ left: `${zero}%` }}
            aria-hidden="true"
          />
        )}

        {/* An axis, because without one the bars encode a value the reader
            cannot decode. Two bands sharing a scale is the entire argument of
            this component — "these overlap, those do not" — and that argument
            is unreadable if the horizontal position means nothing. */}
        <div
          className="relative mb-2 h-4 border-b border-line text-[10px] text-faint"
          aria-hidden="true"
        >
          <span className="absolute left-0">{pct(scale[0], 1)}</span>
          {/* The zero *tick* is always drawn above; only its label is
              conditional. At 390px the committed Warden domain puts zero at 7%
              of a 330px axis — about 23px in — while "−3.6%" set at 10px runs to
              28px, so the two printed on top of each other and neither was
              legible. A label that close to an endpoint also adds nothing: the
              endpoint already says the scale starts just below zero. The line
              keeps carrying the meaning, which is where the meaning was. */}
          {zeroInside && zero > 14 && zero < 86 && (
            <span className="absolute -translate-x-1/2" style={{ left: `${zero}%` }}>
              0
            </span>
          )}
          <span className="absolute right-0">{pct(scale[1], 1)}</span>
        </div>

        <div className="space-y-2.5">
          {series.map((s) => {
            const tone = TONE[s.tone];
            const left = position(s.p25, scale);
            const right = position(s.p75, scale);
            const median = position(s.p50, scale);

            return (
              <div key={s.label}>
                {/* `flex-wrap`: the label and the range sit on one row until
                    they cannot. Task 3's band reads "-620.55% – -617.83%" —
                    twenty characters of tabular figures — and beside a label
                    the row exceeded 390px and pushed the page 57px sideways.
                    Wrapping is the right answer rather than truncating: the
                    figures are the point, and an annualised short-window
                    return is exactly the kind of number this project refuses
                    to round away. */}
                {/* `min-w-0` on the label, and it is load-bearing at 390px.
                    A flex item's default `min-width: auto` refuses to shrink
                    below its min-content width, so a series label like "pick
                    the pool whose flow is not one-way — PancakeSwap v3
                    WBNB/USDT 0.05%" pushed this row 45px wider than its
                    container, and the document with it. `flex-wrap` does not
                    help: it wraps between items, not inside one. This survived
                    only because the old 13px type left just enough room —
                    raising the base size to 16px is what exposed it, which is
                    the sort of latent break a type scale change is for. */}
                <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-3 text-xs">
                  <span className="flex min-w-0 items-center gap-1.5 text-dim">
                    <span
                      className={`inline-block h-2 w-2 shrink-0 rounded-full ${tone.dot}`}
                      aria-hidden="true"
                    />
                    <span className="min-w-0 break-words">{s.label}</span>
                  </span>
                  <span className={`tabular ${tone.text}`}>
                    {pct(s.p25)} – {pct(s.p75)}
                  </span>
                </div>

                <div className="relative h-6">
                  {/* The observations, stacked by value.
                      This was one `w-px` tick per element of `returns` — 60 of
                      them, landing on 20 positions, because the three
                      perturbations are identical for almost every window. The
                      result was a smear that read as one line. Height now
                      encodes how many observations share a value, so warden's
                      51-on-one-value is visibly a stack and its three outlying
                      windows are visibly three. */}
                  {s.tone === "agent" &&
                    clusters.map((c) => (
                      <div
                        key={c.value}
                        className="absolute bottom-0 w-px bg-faint/60"
                        style={{
                          left: `${position(c.value, scale)}%`,
                          height: `${Math.max(12, (c.count / maxCount) * 100)}%`,
                        }}
                        aria-hidden="true"
                      />
                    ))}

                  {/* No `Math.max(..., 0.4)`.
                      The clamp made a sub-pixel interquartile range render as a
                      1.3px box, which is the one thing this component must not
                      do: it drew a range where the data has none. Warden's IQR
                      is 0.0062pp against an observed span of 7.25 — 0.086% —
                      and it now renders at 0.086%, which is to say as the line
                      it is. The concentration sentence below carries what the
                      box used to imply. */}
                  <div
                    className={`band-draw absolute top-1/2 h-5 -translate-y-1/2 rounded-sm border ${tone.fill} ${tone.edge}`}
                    style={{ left: `${left}%`, width: `${right - left}%` }}
                  />
                  {/* No `title`: the median is already in the container's
                      aria-label and in the "median return" row of every table
                      beside this band, and a tooltip on a bare div reaches
                      neither keyboard nor touch. */}
                  <div
                    className={`band-tick absolute top-1/2 h-5 w-0.5 -translate-y-1/2 ${tone.tick}`}
                    style={{ left: `${median}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* What the box used to imply, said instead.
          The interquartile range is what this component draws, and on the
          current tape it is 0.0062pp inside an observed span of 7.25 — too
          narrow for a box to be anything but a lie about precision. So the
          concentration is stated: how many observations sit within a hundredth
          of the span of the median. That is the fact a reader wanted from the
          width, and it survives at any resolution. */}
      {/* Rendered whenever there is a distribution to describe — not only when
          it is concentrated. Gating on `within > 0` meant a well-spread quote,
          which is the case this component was built for, silently lost its
          caption and took the zero-side note with it. */}
      {spread && (
        <figcaption className="mt-2 text-xs text-dim">
          {spread.within === spread.total ? (
            <>
              All {spread.total} observations fall within {pct(spread.tolerance, 2)} of the
              median — the quote has no spread to draw.
            </>
          ) : spread.within > 0 ? (
            <>
              {spread.within} of {spread.total} observations fall within{" "}
              {pct(spread.tolerance, 2)} of the median.
            </>
          ) : (
            <>
              {spread.total} observations, spread wider than {pct(spread.tolerance, 2)}{" "}
              either side of the median.
            </>
          )}
          {/* One text node, not three. Interpolating the direction word mid
              sentence splits the DOM into "Every observation is " / "below" /
              " zero…", which reads identically and is unfindable by any test
              matching the sentence. */}
          {!zeroInside && ` Every observation is ${scale[1] < 0 ? "below" : "above"} zero, which is off this axis.`}
        </figcaption>
      )}

      {series.length === 2 &&
        (() => {
          const isOverlapping = overlap ?? overlaps(series[0]!, series[1]!);
          const delta = deltaPp ?? series[0]!.p50 - series[1]!.p50;
          return (
            <figcaption className="mt-2 text-xs text-dim">
              {isOverlapping ? (
                <>
                  The bands <strong className="text-warn">overlap</strong> — at this
                  sample size the two are not distinguishable, whatever the gap between
                  their medians.
                </>
              ) : (
                <>
                  The bands are <strong className="text-good">separated</strong> — the
                  gap survives the spread, not just the medians.{" "}
                  {signed(delta, 2, "pp")} at the median.
                </>
              )}
            </figcaption>
          );
        })()}

      {/* The description is the container's aria-label; repeating it here as
          off-screen text made every band announce itself twice. */}
    </figure>
  );
}

export function overlaps(a: BandSeries, b: BandSeries): boolean {
  return a.p25 <= b.p75 && b.p25 <= a.p75;
}
