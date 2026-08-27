/**
 * Counts that add to a whole, drawn as one bar.
 *
 * The same twenty lines were hand-inlined three times — `/status` for the
 * readiness gates, `/advantage` for how the tasks fell out, `/vetting` for the
 * verdicts — with the same geometry, the same `n > 0` guard and the same
 * `role="img"` sentence, differing only in which tones they used.
 *
 * `ComparisonTable.tsx` explains why that is worth fixing rather than tidying:
 * it exists because two hand-written `DataTable` calls drifted and
 * `/agent/[slug]` silently lost the "adverse selection (upper bound)" row — "a
 * comparison made of the numbers that flatter the agent, on the page dedicated
 * to that one agent". Three copies is that failure waiting; two more call sites
 * were about to make it five.
 *
 * ## `total` is required, and it is not `sum(parts)`
 *
 * This is the scaling contract `GateHistogram` was written to establish: scale
 * to the denominator when there is one, and fall back to `max` only when there
 * genuinely is none *and say so*, "because a relative chart and an absolute one
 * look identical and mean different things". A parts-of-a-whole strip always
 * has a denominator — that is what makes it one — so `total` is a required
 * prop rather than an optional override, and it is deliberately not derived
 * from the parts.
 *
 * The difference is the point. `/vetting` scales its verdict tally against
 * `everyCheck.length` rather than against the verdicts it happens to have
 * counted, so a check whose verdict nobody recognised leaves a gap in the bar
 * instead of being quietly redistributed across the ones that were. A strip
 * that always fills is a strip that cannot show you something missing.
 *
 * ## Absence is textured, never tinted
 *
 * `/vetting`'s UNKNOWN segment is `hatched` at `--hatch-none`, and the reason
 * generalises: a reading that did not happen has no finding to colour, and the
 * neutral hatch is this site's mark for "there was never anything here"
 * (`Ledger.tsx`). Callers pass the class, so a part can carry a texture without
 * this component knowing what any particular verdict means.
 *
 * ## The sentence is passed in
 *
 * Not generated. The three existing ones differ materially — `/status` names
 * the exit-code verdict, `/vetting` names the worst verdict *and* that the
 * counts are read off the rendered checks rather than off `summary` — and a
 * sentence assembled from labels would flatten all of that into "3 pass, 0
 * fail". `Band.tsx` records the rule this follows: a description that does not
 * say what the mark says is not a description.
 *
 * The figures always appear in words beside the strip too, at the call site.
 * That is not this component's job and must not become it: `/vetting`'s prose
 * line "stays exactly one text node" because `pages.test.tsx` matches it with a
 * singular `getByText`.
 */
export interface TallyPart {
  /** Spoken and written by the caller; this component renders neither. */
  label: string;
  /** A background class, or a hatch for an absence. */
  tone: string;
  n: number;
}

export function TallyStrip({
  parts,
  total,
  ariaSentence,
  className = "",
}: {
  parts: TallyPart[];
  /**
   * The denominator. Required, and not `sum(parts)` — see the docstring: a
   * strip that always fills cannot show a part nobody counted.
   */
  total: number;
  /** A full sentence naming every figure. Never assembled here. */
  ariaSentence: string;
  className?: string;
}) {
  return (
    <div
      className={`flex h-2 w-full overflow-hidden rounded-full border border-glass-line ${className}`}
      role="img"
      aria-label={ariaSentence}
    >
      {parts.map(({ label, tone, n }) =>
        // Zero renders nothing at all, which all three originals did. A
        // zero-width div is not invisible in a flex row — it still takes its
        // border — and a hairline where a count is zero reads as a count that
        // is small.
        n > 0 ? (
          <div
            key={label}
            className={tone}
            style={{ width: `${(n / Math.max(1, total)) * 100}%` }}
          />
        ) : null
      )}
    </div>
  );
}
