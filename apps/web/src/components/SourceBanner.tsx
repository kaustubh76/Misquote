import { Badge } from "@/components/Badge";

/**
 * Whether these numbers came from chain history or from a stand-in.
 *
 * The distinction is not a caveat, it is what the numbers mean, so it is stated
 * at the top of the page rather than in a footnote at the bottom.
 * `scripts/showcase.py` calls mistaking one for the other "the failure this
 * whole project is named after", and this is the surface that makes it hard to.
 *
 * ## Why this no longer says which artifact is on which side
 *
 * It used to, twice, and it was wrong both times — most recently asserting that
 * "the agent artifacts and the index are replayed over indexed chain history;
 * `advantage.json` and `advantage_short.json` are synthetic" on a tree where
 * `index.json` reads `"source": "synthetic"` and `advantage.json` reads
 * `"source": "chain"`. Exactly reversed.
 *
 * Which run produced which file is data, and it changes whenever somebody runs
 * an emitter. A comment cannot track it and a reader who trusts one is worse
 * off than a reader who has none. The rule is what belongs here, and the rule
 * is: **a page says which tape it read before it says what the tape showed.**
 *
 * ## `note`
 *
 * When two artifacts answer the same question from different runs, each side
 * carries the other's answer here — see `lib/counterpart`. It sits in the
 * banner rather than beside the figure because it is the same claim the banner
 * already makes, in its sharpest form: not "this tape is generated" but "the
 * other tape said something else".
 */
export function SourceBanner({
  source,
  badge,
  pool,
  span,
  note,
}: {
  source: string;
  badge?: string;
  pool?: string;
  /** How much tape, already formatted. Omitted where the artifact records none. */
  span?: string;
  /** The other run's answer to the same question, if there is one. */
  note?: React.ReactNode;
}) {
  const synthetic = source !== "chain";

  return (
    <div
      className={`mb-8 rounded-md border p-4 ${
        synthetic
          ? "hatched border-warn-line bg-warn-bg/40 [--hatch-tone:var(--hatch-warn)]"
          : "border-glass-line bg-glass"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={synthetic ? "warn" : "neutral"}>
          {synthetic ? "Synthetic tape — not chain data" : "Indexed chain history"}
        </Badge>
        {badge && <Badge tone="warn">{badge}</Badge>}
      </div>
      <p className="mt-3 mb-0 text-sm text-dim">
        {/* 41 words carrying one claim worth keeping: the shape is real, the
            history is not. The remedy belongs with the empty state that needs
            it, not on a banner every page shows. */}
        {synthetic ? (
          <>
            A <strong className="text-ink">generated</strong> tape — the shape of these
            results is real, the history is not.
          </>
        ) : pool ? (
          <>
            Replayed over indexed history for{" "}
            <span className="font-mono text-xs">{pool}</span>. No position was held.
          </>
        ) : (
          /* `pool` is optional and this branch used to render it regardless, so
             a caller that had no single pool to name produced "Replayed over
             indexed history for . No position was held." — a dangling
             preposition and an empty mono span, on the chain branch, which is
             the reassuring one.

             `/advantage` is that caller and it is right not to pass one: its
             four tasks run across two PancakeSwap pools and a Venus lending
             market, and naming any of them would be naming a third of the
             page. Every other call site has exactly one pool and passes it. */
          <>Replayed over indexed history. No position was held.</>
        )}
        {/* The span goes in the same sentence as the source, because "synthetic"
            and "62.2 hours" are one qualification and a reader who takes only
            the first half has the smaller of the two problems. */}
        {span && <> {span} of it.</>}
      </p>
      {note && (
        <p className="mt-2 mb-0 border-t border-line pt-2 text-sm text-dim">{note}</p>
      )}
    </div>
  );
}
