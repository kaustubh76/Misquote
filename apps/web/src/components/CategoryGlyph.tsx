/**
 * One mark per category, all four built from the same primitive.
 *
 * The four categories on this site ask four different questions of the same
 * figure, and the category index rendered all of them as an identical bordered
 * box with a name in it. These are those questions as pictures — the band from
 * `src/components/Band.tsx` arranged four ways:
 *
 *   rebalancing    one interval with a median tick, and two positions it has
 *                  moved between: the shape of recentring
 *   market-making  many short ticks across the whole width: a policy that
 *                  quotes continuously rather than occasionally
 *   health         one interval crossed by a threshold rule: the only category
 *                  whose verdict is a fraction against a floor
 *   yield          two intervals with a gap: an allocation choosing between
 *                  venues rather than sitting in one
 *
 * `aria-hidden`, and every card already names its category in text beside it.
 * The glyph is not carrying the meaning on its own — it is the second channel,
 * which is the rule `src/components/Pill.tsx` sets out for this codebase.
 *
 * Keyed by slug with a neutral fallback, because the category list is read out
 * of `index.json` and a fifth one appearing must render as a plain interval
 * rather than as whichever glyph happened to be first.
 */
const MARK = "absolute rounded-full bg-brand";
const FAINT = "absolute rounded-full bg-brand-line";

function Glyph({ slug }: { slug: string }) {
  switch (slug) {
    case "rebalancing":
      return (
        <>
          <span className={`${FAINT} top-1.5 left-1 h-[3px] w-5`} />
          <span className={`${MARK} top-[16px] left-4 h-[3px] w-8`} />
          <span className={`${MARK} top-3 left-[30px] h-[11px] w-0.5`} />
        </>
      );
    case "market-making":
      return (
        <>
          {[2, 8, 14, 20, 26, 32, 38, 44].map((x) => (
            <span key={x} className={`${FAINT} top-2 h-3 w-0.5`} style={{ left: x }} />
          ))}
          <span className={`${MARK} top-[15px] left-1 h-[3px] w-11`} />
        </>
      );
    case "health":
      return (
        <>
          <span className={`${MARK} top-[15px] left-1 h-[3px] w-11`} />
          <span className={`${FAINT} top-1 left-[34px] h-[18px] w-0.5`} />
          <span className={`${MARK} top-3 left-[18px] h-[11px] w-0.5`} />
        </>
      );
    case "yield":
      return (
        <>
          <span className={`${MARK} top-[15px] left-1 h-[3px] w-4`} />
          <span className={`${FAINT} top-[15px] left-[30px] h-[3px] w-4`} />
          <span className={`${MARK} top-3 left-[7px] h-[11px] w-0.5`} />
        </>
      );
    default:
      return <span className={`${MARK} top-[15px] left-1 h-[3px] w-11`} />;
  }
}

export function CategoryGlyph({ slug, className = "" }: { slug: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`relative inline-block h-5 w-12 shrink-0 align-middle ${className}`}
    >
      <Glyph slug={slug} />
    </span>
  );
}
