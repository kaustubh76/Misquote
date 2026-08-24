/*
 * A loading state that says what is missing.
 *
 * These were grey `animate-pulse` rectangles — the generic shape, which on this
 * site is also the wrong shape. Every card here resolves to a band: a P25–P75
 * interval with a median tick. So the skeleton is that figure with the parts
 * that are not known yet left out — a hatched interval, no tick, no edges.
 *
 * The hatch is not decoration. It is the site's texture for "there is
 * deliberately nothing here", at 135° wherever it appears — a withheld band, a
 * not-built card, an empty cost track — so a reader who has seen one has seen
 * all of them. A skeleton is the same claim with "yet" on the end.
 *
 * `aria-hidden` throughout, and deliberately: `src/components/LoadingStatus.tsx`
 * is what says "loading" to a screen reader, in words, in a live region. A
 * shimmering rectangle is not an announcement.
 */
function Bar({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`hatched rounded-sm border border-glass-line ${className}`}
    />
  );
}

export function CardSkeleton() {
  return (
    <div
      className="surface rounded-lg border border-glass-line bg-glass p-6"
      aria-hidden="true"
    >
      <Bar className="h-4 w-40" />
      <Bar className="mt-3 h-5 w-28" />
      {/* The band that has not been drawn: full width, and no median tick,
          because the median is exactly the number that is not known yet. */}
      <Bar className="mt-4 h-16 w-full" />
      <div className="mt-4 space-y-2">
        <Bar className="h-3 w-full" />
        <Bar className="h-3 w-5/6" />
        <Bar className="h-3 w-4/6" />
      </div>
    </div>
  );
}
