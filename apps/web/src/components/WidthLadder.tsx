"use client";

import { useState } from "react";
import { count, fraction } from "@/lib/format";

/**
 * One rung of `pools.json`'s width ladder, as this component reads it.
 *
 * `indistinguishable_from` is optional because it is younger than the artifact.
 * A checkout holding a `pools.json` written before `pools.separation()` existed
 * has bands and no ties, and the honest surface for that is a ladder that draws
 * but does not offer a comparison — not a comparison computed here to cover for
 * the absence.
 */
export interface LadderBand {
  width_ticks: number;
  p25: number;
  p50: number;
  p75: number;
  observations: number;
  sufficient: boolean;
  note: string;
  /** Every other width whose band overlaps this one. Emitted, never derived. */
  indistinguishable_from?: number[];
}

/**
 * The width ladder, drawn and answerable — which is what a table of it was not.
 *
 * `/venue` published seven bands per pool as three columns of figures and one
 * sentence about two of them. Everything an LP wants from that requires the
 * comparison the page argues for and never performed: *is ±80 actually better
 * than ±200, or do those two ranges overlap so completely that picking between
 * them is picking noise?* A reader could answer it — by holding "12.7% – 28.2%"
 * in their head and checking it against six other pairs of numbers, one row at
 * a time. Nobody does that, so the argument was made and never delivered.
 *
 * Selecting a rung delivers it. The chosen band lights up, every width its
 * range overlaps is marked **not separated**, and the rest are marked
 * **separated** — the same verdict `best_width` writes for the top two, now
 * available for whichever pair the reader is actually choosing between.
 *
 * ## The overlap rule is not implemented here
 *
 * `components/Band.tsx` states the rule this follows: recomputing Python's
 * `ranges_overlap` in the browser, one screen-inch from a verdict Python wrote,
 * gives two implementations that agree today and cannot be made to disagree
 * tomorrow. So the ties come out of the artifact —
 * `misquote.tearsheet.pools.separation()`, built on the same `WidthBand.overlaps`
 * that `best_width` uses — and this file only draws them. With no ties in the
 * artifact there is no selection to offer, and the ladder falls back to being a
 * drawn table.
 *
 * ## Why a `<table>` and not a `<figure>` of bars
 *
 * The figures are the answer and the chart is the comparison; both have to
 * survive. A `<figure>` would have meant a second copy of every number in a
 * table beside it, and `components/DataTable.tsx` cannot carry a shared axis or
 * a selectable row. So the rows are real table rows with a graphic in the range
 * cell: one structure, one copy of each number, a `<th scope="row">` naming
 * every rung, and a button that a keyboard reaches in document order.
 *
 * ## The axis fits the data, and is not clipped
 *
 * Fitted with 8% padding, the way `Band.tsx` fits its own domain and for the
 * reason recorded there — anchoring to a value no observation is near collapses
 * every band to a hairline. On the 0.25% pool the lower quartiles run into the
 * deep negative, and the bands drawn from them are long. That is the shape of
 * the measurement: annualising a bad day multiplies it by three hundred and
 * sixty-five. Clipping the axis at −100% would tidy the picture by deleting the
 * half of it that is a warning.
 */
export function WidthLadder({
  bands,
  bestWidth,
  caption,
}: {
  /** Only the rungs that cleared the evidence floor. A refused ladder is the
      caller's branch to render, and it says so in words rather than in a blank
      chart — see `app/venue/view.tsx`. */
  bands: LadderBand[];
  /** The engine's leader, marked but never re-derived. */
  bestWidth: number | null;
  caption: string;
}) {
  const [selected, setSelected] = useState<number | null>(null);

  // Ties are a property of the artifact, not of this render. Every band has to
  // carry them or none does: a partial set would let a rung with no `ties` key
  // read as "separated from everything", which is the inversion the emitter's
  // docstring warns about.
  const comparable =
    bands.length > 1 && bands.every((b) => Array.isArray(b.indistinguishable_from));

  const chosen = comparable ? (bands.find((b) => b.width_ticks === selected) ?? null) : null;
  const ties = new Set(chosen?.indistinguishable_from ?? []);

  const values = bands.flatMap((b) => [b.p25, b.p75]);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = hi === lo ? 1 : (hi - lo) * 0.08;
  const scale: [number, number] = [lo - pad, hi + pad];
  const at = (v: number) => ((v - scale[0]) / (scale[1] - scale[0])) * 100;
  const zeroInside = scale[0] < 0 && scale[1] > 0;

  return (
    <div>
      {/* The axis, once, above the rows it scales. Without it the bars encode a
          value nobody can decode, and seven bands sharing one scale is the
          whole reason this is a chart rather than a column of ranges. */}
      <div
        className="relative mb-1 h-4 border-b border-line text-[10px] text-faint"
        aria-hidden="true"
      >
        <span className="absolute left-0">{fraction(scale[0])}</span>
        {zeroInside && at(0) > 14 && at(0) < 86 && (
          <span className="absolute -translate-x-1/2" style={{ left: `${at(0)}%` }}>
            0
          </span>
        )}
        <span className="absolute right-0">{fraction(scale[1])}</span>
      </div>

      <div role="region" aria-label={caption} tabIndex={0} className="overflow-x-auto rounded-sm">
        <table className="w-full border-collapse text-sm">
          <caption className="mb-2 text-left text-sm text-dim">{caption}</caption>
          <thead>
            <tr className="text-left text-xs font-semibold tracking-wide text-faint uppercase">
              <th scope="col" className="py-1.5 pr-3">
                Width
              </th>
              <th scope="col" className="py-1.5 pr-3">
                P25 – P75
              </th>
              <th scope="col" className="py-1.5">
                Median · windows
              </th>
            </tr>
          </thead>
          <tbody>
            {bands.map((band) => {
              const isChosen = chosen?.width_ticks === band.width_ticks;
              const tied = chosen !== null && ties.has(band.width_ticks);
              const clear = chosen !== null && !isChosen && !tied;

              // Three tones, and only ever while something is selected. With no
              // selection every band is drawn the same, because with no
              // selection there is no comparison and a coloured band would be
              // asserting a verdict nobody asked for.
              const fill = isChosen
                ? "bg-brand/30 border-brand-line"
                : tied
                  ? "bg-warn/25 border-warn-line"
                  : clear
                    ? "bg-good/25 border-good-line"
                    : "bg-neutral/25 border-neutral-line";
              const tick = isChosen
                ? "bg-brand"
                : tied
                  ? "bg-warn"
                  : clear
                    ? "bg-good"
                    : "bg-neutral";

              const rung = `±${count(band.width_ticks)} ticks`;
              // The spoken form of the row, because the band beside it is a
              // picture. Everything the graphic encodes is in here as words:
              // the range, the median, the sample size behind them, and — while
              // a rung is selected — the verdict this row now carries.
              const spoken = `${rung}: P25 ${fraction(band.p25)}, median ${fraction(
                band.p50
              )}, P75 ${fraction(band.p75)}, over ${count(band.observations)} windows${
                isChosen ? ", selected" : tied ? ", not separated from the selected width" : ""
              }`;

              return (
                <tr
                  key={band.width_ticks}
                  className={`border-t border-line align-middle ${
                    isChosen ? "bg-brand-bg/60" : ""
                  }`}
                >
                  <th scope="row" className="py-2 pr-3 text-left font-normal whitespace-nowrap">
                    {comparable ? (
                      <button
                        type="button"
                        aria-pressed={isChosen}
                        onClick={() => setSelected(isChosen ? null : band.width_ticks)}
                        className={`rounded-sm px-1.5 py-1 tabular transition-colors ${
                          isChosen
                            ? "bg-brand-bg font-medium text-brand"
                            : "text-ink hover:bg-panel-2"
                        }`}
                      >
                        {rung}
                      </button>
                    ) : (
                      <span className="tabular text-ink">{rung}</span>
                    )}
                  </th>

                  <td className="py-2 pr-3">
                    <div className="relative h-6 min-w-40" role="img" aria-label={spoken}>
                      {zeroInside && (
                        <div
                          className="pointer-events-none absolute inset-y-0 w-px bg-line-strong"
                          style={{ left: `${at(0)}%` }}
                          aria-hidden="true"
                        />
                      )}
                      {/* No minimum width. `Band.tsx` removed its own clamp
                          because a floor draws a range the data does not have,
                          and the flagship's tightest rung is 5.9 percentage
                          points inside an axis spanning 26 — narrow, and
                          genuinely that narrow.

                          And no `band-draw`, which is the site's own reveal for
                          exactly this shape. It is a scroll-driven `scaleX`:
                          `animation-timeline: view()` over `entry 10% cover
                          30%`, so a band is drawn short until it has scrolled
                          far enough in. `Band.tsx` can afford that because its
                          two series sit in one small box and enter together.
                          Seven rows are four hundred pixels tall, so at most
                          scroll positions the top rungs are at full length and
                          the bottom ones are not — measured at 2.9px against a
                          declared 15.4%. On a chart whose entire message is
                          *this band is longer than that one*, an animation that
                          shortens some rows and not others is not a flourish,
                          it is a wrong reading held for as long as somebody is
                          scrolling. */}
                      <div
                        className={`absolute top-1/2 h-5 -translate-y-1/2 rounded-sm border ${fill}`}
                        style={{ left: `${at(band.p25)}%`, width: `${at(band.p75) - at(band.p25)}%` }}
                      />
                      <div
                        className={`absolute top-1/2 h-5 w-0.5 -translate-y-1/2 ${tick}`}
                        style={{ left: `${at(band.p50)}%` }}
                      />
                    </div>
                    <span className="tabular mt-0.5 block text-xs text-dim">
                      {fraction(band.p25)} – {fraction(band.p75)}
                      {/* The verdict, beside the range it is a verdict about,
                          and in words rather than only in the band's colour —
                          a reader who cannot separate warn from good has the
                          whole answer in a channel they do not have.

                          This column and not the next one, because of the
                          phone. The table scrolls inside its own region at
                          390px and "Median · windows" is the half that goes
                          off-screen; the range is on-screen at every width, so
                          the payload of pressing a rung is too. */}
                      {tied && <span className="ml-2 text-warn">not separated</span>}
                      {clear && <span className="ml-2 text-good">separated</span>}
                    </span>
                  </td>

                  <td className="py-2 text-xs whitespace-nowrap text-dim">
                    <span className="tabular">{fraction(band.p50)}</span> ·{" "}
                    {count(band.observations)} windows
                    {band.width_ticks === bestWidth && " · leads"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {comparable && (
        <p className="mt-2 mb-0 max-w-[72ch] text-xs text-dim">
          {chosen === null ? (
            <>Pick a width to see which of the others it is actually distinguishable from.</>
          ) : ties.size === bands.length - 1 ? (
            <>
              &plusmn;{count(chosen.width_ticks)} overlaps every other width on this ladder — at
              this sample size there is no evidence it differs from any of them.
            </>
          ) : ties.size === 0 ? (
            <>
              &plusmn;{count(chosen.width_ticks)} overlaps none of the others — its band clears
              every one of them.
            </>
          ) : (
            <>
              &plusmn;{count(chosen.width_ticks)} is{" "}
              <strong className="text-warn">not separated</strong> from{" "}
              {[...ties].map((w) => `±${count(w)}`).join(", ")} — choosing between those is
              choosing noise. It <strong className="text-good">is</strong> separated from{" "}
              {bands
                .filter((b) => b.width_ticks !== chosen.width_ticks && !ties.has(b.width_ticks))
                .map((b) => `±${count(b.width_ticks)}`)
                .join(", ")}
              .
            </>
          )}
        </p>
      )}
    </div>
  );
}
