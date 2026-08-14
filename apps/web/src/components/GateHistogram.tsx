const GATE_MEANING: Record<string, string> = {
  R1: "inside the no-trade band — moving would cost more than the drift is worth",
  R2: "the move would not pay for its own gas and slippage",
  R3: "cooling down — the daily rebalance budget was already spent",
  R4: "flow looked toxic — recentring into it would have been picking up pennies",
};

/**
 * Why the agent held, rather than merely that it did.
 *
 * `tearsheet.generate.read_journal` says the point of putting all four R-gates
 * on every journal row is precisely this: "a tearsheet that can only say 'it
 * did not rebalance' is much less useful than one that can say which gate held
 * it back and how often". It computed the histogram, put it in the artifact as
 * `activity.held_by_gate`, and the card page dropped the entire `activity`
 * block on the floor — so the most interesting thing the agent does, which is
 * decline to act, was invisible.
 */
export function GateHistogram({ blocks }: { blocks: Record<string, number> }) {
  const entries = Object.entries(blocks).sort(([a], [b]) => a.localeCompare(b));

  if (entries.length === 0) {
    return (
      <p className="text-sm text-faint">
        No gate blocks recorded — this replay wrote no decision journal, so there is
        nothing to attribute holds to.
      </p>
    );
  }

  const max = Math.max(...entries.map(([, n]) => n));

  return (
    <ul className="m-0 list-none space-y-2 p-0">
      {entries.map(([gate, n]) => (
        <li key={gate}>
          <div className="flex items-baseline justify-between gap-3 text-xs">
            <span className="font-mono text-dim">{gate}</span>
            <span className="tabular text-faint">{n.toLocaleString("en-US")}</span>
          </div>
          <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-neutral-bg">
            <div
              className="h-full rounded-full bg-warn"
              style={{ width: `${max > 0 ? (100 * n) / max : 0}%` }}
            />
          </div>
          <p className="mt-1 mb-0 text-xs text-faint">{GATE_MEANING[gate] ?? ""}</p>
        </li>
      ))}
    </ul>
  );
}
