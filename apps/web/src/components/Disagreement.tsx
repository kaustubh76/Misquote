import { count as defaultFormat } from "@/lib/format";

/**
 * N readings of one quantity, drawn as the range they leave unresolved.
 *
 * ## Why an interval and not bars
 *
 * Carried from the block this was extracted from, because the reasoning is the
 * component: two bars from a shared zero are the honest picture of a 2%
 * disagreement and they are also **two identical bars** — the block would carry
 * its whole finding in the numbers and nothing in the mark. But readings that
 * will not be reconciled *are* a range, which is the one figure this entire
 * site is built to draw: the quantity is somewhere between them, and naming a
 * single number would be the misquote.
 *
 * ## The axis is magnified, and says so
 *
 * The domain is the readings plus 45% padding either side, not zero to the
 * largest — at true scale the marks would sit on top of each other. That zoom
 * is a reading aid only because it is stated: an unlabelled one is the
 * distortion this page criticises. `spreadNote` is not optional for that
 * reason; the caption carrying the spread as a share of the largest is what
 * keeps the magnification honest, and a second call site must not be able to
 * forget it.
 *
 * ## The gap is hatched neutral, never warm
 *
 * `Ledger.tsx` sets the rule: warm hatch means evidence exists and fell short,
 * neutral means nothing was ever there. This gap is neither a shortfall nor an
 * error — it is a region no method on the page speaks for, which is exactly
 * what `--hatch-none` means.
 *
 * ## No reading is chosen
 *
 * Every reading gets the same tick, the same weight and its own line naming the
 * method. The spoken description names them all and ends by saying none is
 * picked. That is the whole point: "nothing here can say which is right, and
 * picking the larger would be the misquote this project is named after."
 */
export interface Reading {
  /** Who or what produced it. */
  who: string;
  /** How — the method, named so a reader can weigh it. */
  how: string;
  n: number;
}

/**
 * Above this many readings the inline tick labels are dropped.
 *
 * Two labels alternate right and left of their ticks and never touch. Three do:
 * the feedback spread is 438 / 510 / 547 on a domain a hundred wide, so the
 * labels overlap into an unreadable smear. Above the pair the ticks go
 * `aria-hidden` and the list underneath carries every figure — which is
 * `AgentComparison`'s rule for when a mark is ranking rather than record, and
 * `Band`'s for dropping a label that collides rather than drawing it anyway.
 */
const LABELLED_UP_TO = 2;

export function Disagreement({
  readings,
  ariaSentence,
  spreadNote,
  format = defaultFormat,
}: {
  readings: Reading[];
  /** A full sentence naming every reading and saying none is chosen. */
  ariaSentence: string;
  /** What the magnification costs the reader, in words. Required — see above. */
  spreadNote: React.ReactNode;
  format?: (n: number | undefined) => string;
}) {
  if (readings.length < 2) return null;

  const values = readings.map((r) => r.n);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const pad = Math.max(1, (high - low) * 0.45);
  const span = high - low + pad * 2;
  const at = (n: number) => `${((n - (low - pad)) / span) * 100}%`;

  const ordered = [...readings].sort((a, b) => a.n - b.n);
  const labelled = ordered.length <= LABELLED_UP_TO;

  return (
    <figure className="m-0">
      <div className="relative h-12" role="img" aria-label={ariaSentence}>
        {/* The unresolved span. */}
        <div
          className="hatched absolute top-1/2 h-6 -translate-y-1/2 rounded-sm border border-line-strong"
          style={{ left: at(low), width: `${((high - low) / span) * 100}%` }}
        />
        {ordered.map((reading, i) => (
          <div
            key={reading.who}
            aria-hidden={labelled ? undefined : "true"}
            className="absolute top-1/2 h-8 w-0.5 -translate-y-1/2 bg-brand"
            style={{ left: at(reading.n) }}
          >
            {labelled && (
              <span
                className={`absolute -top-1 whitespace-nowrap font-mono text-xs text-ink ${
                  i === 0 ? "right-2 text-right" : "left-2"
                }`}
              >
                {format(reading.n)}
              </span>
            )}
          </div>
        ))}
      </div>

      {/* Every figure in words, in order, each naming its method. This is the
          record; the mark above is the shape. */}
      <ul className="m-0 mt-2 list-none space-y-1 p-0">
        {ordered.map((reading) => (
          <li key={reading.who} className="font-mono text-xs break-words text-faint">
            {format(reading.n)} · {reading.who} — {reading.how}
          </li>
        ))}
      </ul>

      <figcaption className="mt-4 border-t border-line pt-3 text-sm text-dim">
        {spreadNote}
      </figcaption>
    </figure>
  );
}
