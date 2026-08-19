import { amount, money, SIGN_CLASS, signOf } from "@/lib/format";

/**
 * Where the money went: what the position earned, and what it paid to be there.
 *
 * `net = fees − adverse selection − costs` is an identity the engine enforces,
 * so these bars account for the whole result rather than sampling it. It was
 * ten table rows, which left the reader to do the subtraction and to notice the
 * order of magnitude themselves. On the 30-day chain tape:
 *
 *     warden     fees 0.0099   LVR 0.0027   costs 0.1942   net -0.1869
 *     grid       fees 0.0484   LVR 0.0202   costs 0.0101   net +0.0181
 *     sentinel   fees 0.0017   LVR 0.0005   costs 0.1942   net -0.1929
 *
 * Sentinel pays **112× its fees** in costs, on 249 mints and 249 pulls. Grid
 * pays **0.2×**, on one mint and twelve recentres, and is the only one of the
 * three that finishes ahead. That contrast is the entire argument about
 * rebalancing, and it was legible only by dividing two numbers four rows apart.
 *
 * These figures are the fourth set this comment has carried. Every one of the
 * engine fixes that moved them — the capital basis, a sigma estimator clipping
 * 27.8% of its own sample, equation (3) clamping a price it should not have, a
 * pull priced as a fresh entry — left this docstring describing a run that no
 * longer existed, because nothing checks a comment. Read them as an
 * illustration of the shape, and the artifact for the numbers.
 *
 * ## The scaling contract, inherited from GateHistogram
 *
 * Bars are absolute against a stated denominator — the largest component —
 * never normalised per row. `GateHistogram` learned this the hard way: scaled
 * to their own maximum, three gates that each blocked 115 of 175 decisions drew
 * three full-width bars, "the picture of every gate blocked every decision".
 * The same mistake here would draw fees and costs the same length and destroy
 * the only thing worth seeing.
 *
 * Every figure is written beside its bar, so the numbers survive a reader who
 * cannot judge length — and colour is never the only signal: earned and spent
 * are separated by position and by label as well as by tone.
 *
 * ## The unit
 *
 * Stated twice and nowhere else: on the denominator, because a scale without a
 * unit is not a scale, and on the net, because that is the figure that leaves
 * the chart — in a screenshot, in a sentence, in somebody's memory. The rows
 * inherit it from the denominator they are drawn against and stay bare, which
 * is the ordinary convention and keeps three short numbers readable.
 *
 * `0.1942` is not nineteen cents. It is that many BNB — about $119.
 */
export interface CostRow {
  label: string;
  value: number;
  /** Earned adds to net; spent subtracts from it. Decides side and tone. */
  direction: "earned" | "spent";
}

export function CostBars({
  rows,
  net,
  caption,
  unit,
}: {
  rows: CostRow[];
  /** Optional so an absent value renders as a refusal rather than a profit. */
  net?: number;
  caption: string;
  /** What these figures are denominated in. Omitted when the artifact does not say. */
  unit?: string;
}) {
  // The denominator, stated rather than implied. Guarded against an all-zero
  // set so a fresh artifact renders flat bars instead of dividing by zero.
  const largest = Math.max(...rows.map((r) => Math.abs(r.value)), 0);

  return (
    <figure className="m-0" role="group" aria-label={caption}>
      <ul className="m-0 list-none space-y-2 p-0">
        {rows.map((row) => {
          const share = largest > 0 ? (Math.abs(row.value) / largest) * 100 : 0;
          const earned = row.direction === "earned";
          return (
            <li key={row.label}>
              <div className="flex items-baseline justify-between gap-3 text-xs">
                <span className="text-dim">{row.label}</span>
                <span className={`tabular ${earned ? "text-good" : "text-dim"}`}>
                  {earned ? "+" : "−"}
                  {amount(Math.abs(row.value))}
                </span>
              </div>
              <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-neutral-bg">
                <div
                  className={`h-full rounded-full ${earned ? "bg-good" : "bg-warn"}`}
                  // A component that is a rounding error against the largest
                  // still gets a visible mark: Sentinel's 0.0017 of fees against
                  // 0.1942 of costs is 0.9%, and at the ratios this has carried
                  // before it was 0.011% — which would vanish entirely and read
                  // as "no fees at all".
                  style={{ width: `${row.value === 0 ? 0 : Math.max(share, 0.8)}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>

      <figcaption className="mt-3 flex items-baseline justify-between gap-3 border-t border-line pt-2 text-xs">
        <span className="text-faint">
          net — bars scaled against {money(largest, unit)}, the largest component
        </span>
        {/* `signOf`, not `net < 0`. An absent net compares false and would
            have rendered green — a missing measurement shown as a profit. The
            helper returns "none" for a value that is not a number, which is a
            distinct tone from zero. */}
        <span className={`tabular font-semibold ${SIGN_CLASS[signOf(net)]}`}>
          {money(net, unit)}
        </span>
      </figcaption>
    </figure>
  );
}
