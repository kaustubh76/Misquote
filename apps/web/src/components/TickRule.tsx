/**
 * The band, at glyph scale: a rule whose middle half is brand and whose centre
 * carries a median tick.
 *
 * It is the one mark this product can put anywhere and have mean something.
 * `src/components/Band.tsx` draws a P25–P75 interval with a median tick, and
 * the nav wordmark in `src/components/Nav.tsx` is the same shape at 24px; this
 * is that shape doing a divider's job. A section rule that is also the logo
 * that is also the figure.
 *
 * `aria-hidden`, and renders no text — it decorates a heading that already says
 * what it is, and `scripts/check-pages.mjs` measures `innerText` on every route
 * with JavaScript off.
 *
 * Two sizes. `lead` is inline and sits before a section title; the default is a
 * block rule that fills its container and is used at page width under the hero.
 */
export function TickRule({
  lead = false,
  className = "",
}: {
  lead?: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={`tick-rule ${lead ? "tick-rule--lead" : "tick-rule--full"} ${className}`}
    />
  );
}
