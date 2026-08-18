import Link from "next/link";
import { count, fraction, money, pct, SIGN_CLASS, signOf } from "@/lib/format";
import type { AgentArtifact, AgentRef } from "@/lib/artifacts";

/**
 * The three agents on one set of axes, above the cards rather than instead.
 *
 * The landing page was a heading, a paragraph, a link and three stacked cards,
 * so the question it exists to answer — *which of these works* — took three
 * screens of scrolling and a memory for numbers. The cards are the detail; this
 * is the answer.
 *
 * What it compares is chosen from what actually varies. The quote does not:
 * the interquartile range is 0.0062pp on a value of −233, and the three
 * perturbations produce identical returns. These do:
 *
 *     in range     6.1%  vs  100%      (against a 70% floor)
 *     moves         498  vs    13
 *     net       -186.74  vs  -0.68
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
  // "Net loss" was written into the caption. Every agent on the 30-day chain
  // tape loses, so it read correctly for as long as that was the only tape
  // anyone looked at — and on a run where all three profit it captions three
  // green bars "the largest loss". Derived from the signs instead.
  const signs = new Set(agents.map((a) => signOf(a.data.replay.net_quote)));
  const extreme = signs.size === 1 && signs.has("neg") ? "loss" : signs.size === 1 && signs.has("pos") ? "gain" : "amount";

  const units = new Set(agents.map((a) => a.data.quote_symbol));
  const unit = units.size === 1 ? [...units][0] : undefined;
  const commensurable = units.size === 1;

  return (
    <div className="rounded-lg border border-line bg-panel-2 p-5">
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

              <div className="relative mt-1.5 h-2 w-full overflow-hidden rounded-full bg-neutral-bg">
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
