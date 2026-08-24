import Link from "next/link";
import { count, fraction, money, pct, SIGN_CLASS, signOf } from "@/lib/format";
import type { AgentArtifact, AgentRef } from "@/lib/artifacts";

/**
 * The LP agents on one set of axes, above the cards rather than instead.
 *
 * Router is deliberately absent: it supplies to a lending market, so it has no
 * in-range fraction and no adverse-selection cost, and a zero in either column
 * would read as a claim. `view.tsx` renders the exclusion and its reason.
 *
 * The landing page was a heading, a paragraph, a link and three stacked cards,
 * so the question it exists to answer — *which of these works* — took three
 * screens of scrolling and a memory for numbers. The cards are the detail; this
 * is the answer.
 *
 * What it compares is chosen from what actually varies. On the 30-day chain
 * tape:
 *
 *                in range   moves      net
 *     warden         6.1%     498   -0.1869
 *     grid         100.0%      13   +0.0181
 *     sentinel       9.5%     498   -0.1929
 *
 * One agent clears its costs and two do not, and the difference is thirteen
 * moves against four hundred and ninety-eight. That is the comparison; the
 * quote is not, because its interquartile range is a fraction of a point.
 *
 * `net` is shared across all three rows by design — one scale, so a bar twice
 * as long means twice the loss. Scaling each row to itself would make three
 * very different results look identical, which is the mistake `GateHistogram`
 * documents at length.
 *
 * A shared scale is only meaningful if the figures share a unit, so the unit is
 * taken from the agents rather than assumed, and only when they agree. They do
 * agree today — one run, one pool — but the pool is a constant somebody can
 * change, and `EQUITY_POOL` quotes in tokenized Tesla shares. Drawing WBNB and
 * TSLAx on one axis would be a category error rendered as a ranking.
 */
export interface ComparedAgent {
  ref: AgentRef;
  data: AgentArtifact;
}

export function AgentComparison({
  agents,
  inRangeFloor,
}: {
  agents: ComparedAgent[];
  /** The threshold the in-range verdict is called against, from `floors`. */
  inRangeFloor?: number;
}) {
  if (agents.length === 0) return null;

  // One scale across every agent. `Math.abs` because a profitable agent and a
  // loss-making one belong on the same axis; the sign is carried by the figure.
  const worst = Math.max(...agents.map((a) => Math.abs(a.data.replay.net_quote)), 0);

  // Unanimous or nothing. `undefined` covers both "no artifact said" and "they
  // disagreed"; the second also suppresses the shared-scale claim below, since
  // in that case the bars are comparing quantities that are not comparable.
  // "Net loss" was written into the caption, and it read correctly for as long
  // as every agent on the chain tape lost. Derived from the signs instead —
  // and the hypothetical arrived: Grid now finishes ahead while Warden and
  // Sentinel do not, so the signs disagree, this reads "largest amount", and
  // the bars are mixed red and green. The branch that had only a synthetic
  // test is the one the site now takes.
  const signs = new Set(agents.map((a) => signOf(a.data.replay.net_quote)));
  const extreme = signs.size === 1 && signs.has("neg") ? "loss" : signs.size === 1 && signs.has("pos") ? "gain" : "amount";

  const units = new Set(agents.map((a) => a.data.quote_symbol));
  const unit = units.size === 1 ? [...units][0] : undefined;
  const commensurable = units.size === 1;

  return (
    <div className="surface rounded-lg border border-glass-line bg-glass p-5">
      <ul className="m-0 list-none space-y-4 p-0">
        {agents.map(({ ref, data }) => {
          const r = data.replay;
          const moves = r.mints + r.rebalances + r.pulls;
          const share = worst > 0 ? (Math.abs(r.net_quote) / worst) * 100 : 0;
          const held = r.in_range_fraction;
          const clears = inRangeFloor !== undefined && held >= inRangeFloor;

          return (
            <li key={ref.slug} className="min-w-0">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <Link href={`/agent/${ref.slug}`} className="text-sm font-semibold text-ink">
                  {ref.name}
                </Link>
                <span className="tabular text-xs text-dim">
                  {/* Every figure is written out. The bar is the comparison;
                      the numbers are the record, and a reader who cannot judge
                      length loses nothing. */}
                  in range{" "}
                  <span className={clears ? "text-good" : "text-bad"}>{fraction(held)}</span>
                  {" · "}
                  {count(moves)} moves{" · "}
                  {/* The net itself, not its share of the worst. "−100% of the
                      worst" reads as a percentage loss rather than a ranking,
                      and "−0% of the worst" for a real $0.68 loss is worse than
                      opaque. The bar carries the ratio; the figure carries the
                      amount, which is what a reader came for. */}
                  <span className={SIGN_CLASS[signOf(r.net_quote)]}>{money(r.net_quote, unit)}</span>
                </span>
              </div>

              {/* `aria-hidden`, and the comment above is why: every figure in
                  this row is written out beside it, so the bar is the ranking
                  and not the record. It was neither hidden nor labelled — the
                  only bar family on the site that announced as "image" and then
                  said nothing, on the landing page.

                  Hiding rather than labelling is the honest call here. `CostBars`
                  and `ShareIntervals` name themselves because they carry a
                  figure the prose does not; this one carries `Math.abs(net) /
                  worst`, a ratio no sentence on the page states and none needs
                  to, because the amounts are right there.

                  The track is hatched like every other empty track — `CostBars`,
                  `GateHistogram` and both `/quote` bars. It was the last
                  `bg-neutral-bg` left, which made it the one place an empty
                  track meant nothing in particular. */}
              <div
                aria-hidden="true"
                className="hatched relative mt-1.5 h-2 w-full overflow-hidden rounded-full border border-glass-line"
              >
                <div
                  className={`h-full rounded-full ${r.net_quote < 0 ? "bg-bad" : "bg-good"}`}
                  style={{ width: `${Math.max(share, 0.8)}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>

      <p className="mt-4 mb-0 border-t border-line pt-3 text-xs text-faint">
        {commensurable ? (
          <>
            {agents.length} agents over one tape, on one scale — longest bar is the
            largest {extreme}.
          </>
        ) : (
          <>
            These agents report in different units, so the bars rank nothing — read the
            figures.
          </>
        )}
        {inRangeFloor !== undefined && ` In range is called against a ${pct(100 * inRangeFloor, 0)} floor.`}
      </p>
    </div>
  );
}
