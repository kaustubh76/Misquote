import { amount, SIGN_CLASS, signOf } from "@/lib/format";

/**
 * Where the money went: what the position earned, and what it paid to be there.
 *
 * `net = fees − adverse selection − costs` is an identity the engine enforces,
 * so these bars account for the whole result rather than sampling it. It was
 * ten table rows, which left the reader to do the subtraction and to notice the
 * order of magnitude themselves. On the committed tape:
 *
 *     warden     fees 0.02   LVR 0.01   costs 186.76   net -186.74
 *     grid       fees 0.16   LVR 0.06   costs   0.78   net   -0.68
 *     sentinel   fees 0.01   LVR 0.00   costs 186.76   net -186.75
 *
 * Warden's costs are **8,960× its fees** — 249 mints and 249 pulls with zero
 * rebalances. That is the entire story of the agent and it was legible only by
 * dividing two numbers four rows apart.
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
}: {
  rows: CostRow[];
  /** Optional so an absent value renders as a refusal rather than a profit. */
  net?: number;
  caption: string;
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
                  // still gets a visible mark: 0.02 against 186.76 is 0.011%,
                  // which would otherwise vanish and read as "no fees at all".
                  style={{ width: `${row.value === 0 ? 0 : Math.max(share, 0.8)}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>

      <figcaption className="mt-3 flex items-baseline justify-between gap-3 border-t border-line pt-2 text-xs">
        <span className="text-faint">
          net — bars scaled against {amount(largest)}, the largest component
        </span>
        {/* `signOf`, not `net < 0`. An absent net compares false and would
            have rendered green — a missing measurement shown as a profit. The
            helper returns "none" for a value that is not a number, which is a
            distinct tone from zero. */}
        <span className={`tabular font-semibold ${SIGN_CLASS[signOf(net)]}`}>
          {amount(net)}
        </span>
      </figcaption>
    </figure>
  );
}
