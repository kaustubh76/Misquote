import { Badge } from "@/components/Badge";

/**
 * Whether these numbers came from chain history or from a stand-in.
 *
 * The distinction is not a caveat, it is what the numbers mean, so it is stated
 * at the top of the page rather than in a footnote at the bottom.
 * `scripts/showcase.py` calls mistaking one for the other "the failure this
 * whole project is named after", and this is the surface that makes it hard to.
 *
 * Both branches are live, which is worth saying because this comment used to
 * claim otherwise. The agent artifacts and the index are replayed over indexed
 * chain history; `advantage.json` and `advantage_short.json` are synthetic, and
 * `/status` reports that as a failing gate rather than a footnote. So the two
 * pages a reader is most likely to compare — `/` and `/advantage`, one linked
 * from the other — carry different banners on purpose.
 */
export function SourceBanner({
  source,
  badge,
  pool,
}: {
  source: string;
  badge?: string;
  pool?: string;
}) {
  const synthetic = source !== "chain";

  return (
    <div
      className={`mb-8 rounded-md border p-4 ${
        synthetic ? "border-warn-line bg-warn-bg/40" : "border-line bg-panel-2"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={synthetic ? "warn" : "neutral"}>
          {synthetic ? "Synthetic tape — not chain data" : "Indexed chain history"}
        </Badge>
        {badge && <Badge tone="warn">{badge}</Badge>}
      </div>
      <p className="mt-3 mb-0 text-sm text-dim">
        {synthetic ? (
          <>
            Every figure below was produced by replaying the policies over a{" "}
            <strong className="text-ink">generated</strong> tape, not over this pool&rsquo;s
            real trade history. The shape of the results is real; the history is not.
            Run <code className="font-mono text-xs">make showcase</code> against an indexed
            tape to replace them.
          </>
        ) : (
          <>
            Replayed over indexed history for{" "}
            <span className="font-mono text-xs">{pool}</span>. No position was held — see
            the counterfactual badge.
          </>
        )}
      </p>
    </div>
  );
}
