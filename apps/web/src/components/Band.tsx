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
  /** Individual window returns, drawn as a rug behind the band. */
  returns?: number[];
  unit?: string;
  caption?: string;
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

/** Domain covering every band, always including zero, with 8% breathing room. */
function domain(series: BandSeries[], returns: number[]): [number, number] {
  const values = [0, ...returns.filter(isNum)];
  for (const s of series) values.push(s.p25, s.p50, s.p75);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  if (lo === hi) return [lo - 1, hi + 1];
  const pad = (hi - lo) * 0.08;
  return [lo - pad, hi + pad];
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
  returns = [],
  unit = "%",
  caption,
}: BandProps) {
  if (!sufficient) {
    return (
      <div className="rounded-md border border-warn-line bg-warn-bg/50 p-4">
        <div
          className="h-9 w-full rounded-sm border border-warn-line/60"
          style={{
            backgroundImage:
              "repeating-linear-gradient(135deg, transparent, transparent 5px, var(--warn-line) 5px, var(--warn-line) 6px)",
          }}
          role="img"
          aria-label="No range: the quote was withheld."
        />
        <p className="mt-3 text-sm text-warn">
          <span className="font-semibold">Quote withheld.</span>{" "}
          {/* The engine's own words. Paraphrasing a refusal is how it becomes
              an apology instead of a result. */}
          {note || "Not enough history to state a range that describes the strategy."}
        </p>
      </div>
    );
  }

  const scale = domain(series, returns);
  const zero = position(0, scale);

  const description = series
    .map(
      (s) =>
        `${s.label}: P25 ${s.p25.toFixed(2)}${unit}, median ${s.p50.toFixed(2)}${unit}, P75 ${s.p75.toFixed(2)}${unit}`,
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
        {scale[0] < 0 && scale[1] > 0 && (
          <div
            className="pointer-events-none absolute inset-y-2 w-px bg-line-strong"
            style={{ left: `${zero}%` }}
            aria-hidden="true"
          />
        )}

        <div className="space-y-2.5">
          {series.map((s) => {
            const tone = TONE[s.tone];
            const left = position(s.p25, scale);
            const right = position(s.p75, scale);
            const median = position(s.p50, scale);

            return (
              <div key={s.label}>
                <div className="mb-1 flex items-baseline justify-between gap-3 text-xs">
                  <span className="flex items-center gap-1.5 text-dim">
                    <span
                      className={`inline-block h-2 w-2 rounded-full ${tone.dot}`}
                      aria-hidden="true"
                    />
                    {s.label}
                  </span>
                  <span className={`tabular ${tone.text}`}>
                    {pct(s.p25)} – {pct(s.p75)}
                  </span>
                </div>

                <div className="relative h-6">
                  {/* The rug: every individual window return behind the band,
                      so the reader sees a distribution rather than three of its
                      order statistics. */}
                  {s.tone === "agent" &&
                    returns.map((r, i) => (
                      <div
                        key={i}
                        className="absolute top-1/2 h-3 w-px -translate-y-1/2 bg-faint/35"
                        style={{ left: `${position(r, scale)}%` }}
                        aria-hidden="true"
                      />
                    ))}

                  <div
                    className={`absolute top-1/2 h-5 -translate-y-1/2 rounded-sm border ${tone.fill} ${tone.edge}`}
                    style={{
                      left: `${left}%`,
                      width: `${Math.max(right - left, 0.4)}%`,
                    }}
                  />
                  <div
                    className={`absolute top-1/2 h-5 w-0.5 -translate-y-1/2 ${tone.tick}`}
                    style={{ left: `${median}%` }}
                    title={`median ${pct(s.p50)}`}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {series.length === 2 && (
        <figcaption className="mt-2 text-xs text-dim">
          {overlaps(series[0]!, series[1]!) ? (
            <>
              The bands <strong className="text-warn">overlap</strong> — at this sample
              size the two are not distinguishable, whatever the gap between their
              medians.
            </>
          ) : (
            <>
              The bands are <strong className="text-good">separated</strong> — the gap
              survives the spread, not just the medians.{" "}
              {signed(series[0]!.p50 - series[1]!.p50, 2, "pp")} at the median.
            </>
          )}
        </figcaption>
      )}

      <p className="visually-hidden">{description}</p>
    </figure>
  );
}

export function overlaps(a: BandSeries, b: BandSeries): boolean {
  return a.p25 <= b.p75 && b.p25 <= a.p75;
}
