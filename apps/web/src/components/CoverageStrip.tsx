import { count } from "@/lib/format";

/**
 * What was read, drawn against what is claimed.
 *
 * `indexer/schema.sql` spends a paragraph on why the `covered` table exists,
 * and the sentence worth drawing is this one: a tape holding one day at each
 * end of a twenty-six-day gap "reported spanning 26 days and passed the
 * readiness gate. Every interrupted backfill produces that shape."
 *
 * No number catches that. `max(ts) - min(ts)` is 26 days and true; the swap
 * count is real; the first and last block are real. The hole is the only thing
 * wrong and it is the one thing a table of totals cannot show, because it is
 * not a value — it is a *gap between* values. So it is drawn.
 *
 * ## Why the hatch rather than a colour
 *
 * A hole is absence, and this site has exactly one texture for absence: 135°
 * hatching at `--hatch-none`, used by a withheld band, a not-built card, an
 * empty cost track and a loading skeleton. A reader who has seen any of those
 * has already learnt what this means. A red segment would say "error", which is
 * wrong — an unread range is not a fault, it is a range nobody has read yet.
 *
 * ## Zero blocks is not the same as no answer
 *
 * A database written before `covered` existed holds real events and no record
 * of what was fetched to find them. `api/tape.py` reports that as
 * `known: false` rather than as an empty run list, "because zero is a
 * measurement and this is the absence of one" — so this refuses to draw a strip
 * at all in that case rather than drawing an empty one, which would read as
 * "nothing was ever indexed".
 *
 * ## The widths are percentages of a range, not of the viewport
 *
 * Every segment is positioned against `[from, to]` spanning the whole claim, so
 * two strips on the same page are only comparable within themselves — which is
 * correct here, since two pools backfilled over different block ranges have no
 * shared axis. The block numbers are printed at both ends so the scale is
 * stated rather than implied.
 */
export interface Run {
  from_block: number;
  to_block: number;
}

/** A hole wide enough to be worth a mark, as a share of the whole claim. */
const MIN_VISIBLE_SHARE = 0.4;

export function CoverageStrip({
  runs,
  known,
  caption,
}: {
  runs: Run[];
  /** False when the database predates the coverage table. Not the same as empty. */
  known: boolean;
  caption: string;
}) {
  if (!known || runs.length === 0) {
    return (
      <div className="hatched hatched-wide rounded-md border border-glass-line p-4">
        <p className="m-0 text-sm text-dim">
          {known
            ? "No range is recorded as read for this pool."
            : "This database was written before coverage was recorded, so what was read cannot be reconstructed."}{" "}
          <span className="text-faint">
            That is an absence of a measurement, not a measurement of zero — so nothing
            here can vouch for the history below.
          </span>
        </p>
      </div>
    );
  }

  // Non-null after the guard above, but `noUncheckedIndexedAccess` cannot see
  // that through `runs.length === 0`, and widening the guard is cheaper than a
  // non-null assertion on the two values the whole scale is derived from.
  const first = runs[0]?.from_block ?? 0;
  const last = runs[runs.length - 1]?.to_block ?? 0;
  const span = Math.max(last - first, 1);
  const share = (blocks: number) => (blocks / span) * 100;

  // Runs and the gaps between them, in one ordered pass, so the strip is built
  // from the same list the caption counts rather than from a second traversal
  // that could disagree with it.
  const segments: Array<{ kind: "read" | "hole"; from: number; to: number }> = [];
  runs.forEach((run, index) => {
    const previous = runs[index - 1];
    if (previous && run.from_block > previous.to_block + 1) {
      segments.push({ kind: "hole", from: previous.to_block + 1, to: run.from_block - 1 });
    }
    segments.push({ kind: "read", from: run.from_block, to: run.to_block });
  });

  const holes = segments.filter((s) => s.kind === "hole");

  return (
    <figure className="m-0" role="group" aria-label={caption}>
      <div className="flex h-6 w-full overflow-hidden rounded-sm border border-glass-line">
        {segments.map((segment) => {
          const width = share(segment.to - segment.from + 1);
          return (
            <div
              key={`${segment.kind}-${segment.from}`}
              className={
                segment.kind === "read"
                  ? "h-full bg-brand/30"
                  : "hatched h-full border-x border-glass-line"
              }
              // A one-block hole in a two-million-block claim is 0.00005% and
              // would round to nothing — which is the case that matters most,
              // because a hole nobody can see is exactly the failure the
              // `covered` table exists to make visible. Read segments get no
              // floor: inflating one would overstate what was read.
              style={{
                width:
                  segment.kind === "hole"
                    ? `${Math.max(width, MIN_VISIBLE_SHARE)}%`
                    : `${width}%`,
              }}
            />
          );
        })}
      </div>

      <div className="mt-1.5 flex items-baseline justify-between gap-3 font-mono text-[11px] text-faint">
        <span className="tabular">{count(first)}</span>
        <span className="tabular">{count(last)}</span>
      </div>

      <figcaption className="mt-2 text-xs text-dim">
        {caption} —{" "}
        {holes.length === 0 ? (
          <span className="text-good">
            {runs.length === 1 ? "one unbroken run" : `${count(runs.length)} runs, no gaps`}
          </span>
        ) : (
          <span className="text-warn">
            {count(holes.length)} unread {holes.length === 1 ? "gap" : "gaps"} totalling{" "}
            {count(holes.reduce((sum, h) => sum + (h.to - h.from + 1), 0))} blocks
          </span>
        )}
      </figcaption>
    </figure>
  );
}
