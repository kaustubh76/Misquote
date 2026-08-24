import { count, pct } from "@/lib/format";

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
 *
 * ## Why the bars are scaled to the decision count and not to each other
 *
 * They were scaled to `max(n)`, which makes the largest bar full by
 * construction. On the committed run all three gates hold on exactly the same
 * 115 rows, so the card rendered **three identical full-width bars** — the
 * picture of "every gate blocked every decision". The real figure is 115 of
 * 175, and the three gates agreeing that often is itself the interesting fact,
 * which a chart normalised against itself cannot show.
 *
 * Relative scaling is not wrong in general — it is the right choice when there
 * is no meaningful denominator. Here there is one, and it is the number the
 * reader is actually asking about: how often did this gate stop a move? So
 * `total` is used when the caller has it, the count is written as "115 of 175"
 * rather than a bare 115, and the fallback to relative scaling says so in the
 * caption instead of quietly looking the same.
 *
 * The gates are not mutually exclusive — a decision can trip several at once —
 * so the shares do not sum to 100% and the component never presents them as
 * parts of a whole.
 */
export function GateHistogram({
  blocks,
  total,
}: {
  blocks: Record<string, number>;
  /** Decisions the journal recorded. Omit only when it is genuinely unknown. */
  total?: number;
}) {
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
  const scale = total && total > 0 ? total : max;
  const relative = !(total && total > 0);

  return (
    <>
      <ul className="m-0 list-none space-y-2 p-0">
        {entries.map(([gate, n]) => (
          <li key={gate}>
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="font-mono text-dim">{gate}</span>
              <span className="tabular text-faint">
                {relative ? count(n) : `${count(n)} of ${count(total)}`}
              </span>
            </div>
            <div className="hatched mt-1 h-1.5 w-full overflow-hidden rounded-full border border-glass-line">
              <div
                className="h-full rounded-full bg-warn"
                style={{ width: `${scale > 0 ? (100 * n) / scale : 0}%` }}
              />
            </div>
            <p className="mt-1 mb-0 text-xs text-faint">
              {GATE_MEANING[gate] ?? ""}
              {!relative && <> · {pct((100 * n) / scale, 0)} of decisions</>}
            </p>
          </li>
        ))}
      </ul>
      {relative && (
        // Said out loud, because a relative chart and an absolute one look
        // identical and mean different things. Without this line the longest
        // bar reads as "always".
        <p className="mt-3 mb-0 text-xs text-faint">
          Bars are scaled to the largest gate, not to a decision count — the journal
          did not record one. The longest bar is the most common reason, not
          &ldquo;every time&rdquo;.
        </p>
      )}
    </>
  );
}
