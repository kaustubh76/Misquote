import { amount, count, fraction, pct } from "@/lib/format";
import { DataTable } from "@/components/DataTable";

/**
 * The agent against the baseline, defined once.
 *
 * ## Why this is a component and not two nice-looking tables
 *
 * `/advantage` and `/agent/[slug]` both answer "what does hiring this thing get
 * you", from the same replay, against the same baseline. They were built as two
 * hand-written `DataTable` calls with the same seven rows in the same order —
 * and they drifted. `/advantage` carried an **adverse selection (upper bound)**
 * row that the agent page did not.
 *
 * Which half went missing matters. Adverse selection is the cost side: the value
 * the pool bleeds to arbitrage when the price moves against a position that has
 * not been recentred. Dropping it leaves fees, costs and return — a comparison
 * made of the numbers that flatter the agent, on the page dedicated to that one
 * agent. Nobody chose that. One table was edited and the other was not, which is
 * how every divergence of this kind happens.
 *
 * The value was already on the agent page, thirty lines below in the replay
 * table, so the two tables on a single screen disagreed about what counted as a
 * cost. That is the failure this project is named for, and the fix is not to
 * remember harder.
 *
 * ## The seam
 *
 * The two call sites read different artifacts — `warden.json` spells it
 * `lvr_quote_upper_bound` and `in_range_fraction`, `advantage.json` spells the
 * same quantities `lvr_upper_bound` and `in_range` — so each adapts its own
 * shape into `Side` and the row list lives here. Adding a row now adds it to
 * both pages, and removing one removes it from both. There is no third state.
 *
 * Every field is optional and every formatter is null-safe: a withheld quote has
 * no percentiles, and it must render as an em dash rather than as a zero. `pct`,
 * `amount`, `fraction` and `count` all return "—" for a missing value, which is
 * the same rule the rest of the app follows — a number that was never measured
 * never renders as one that was measured to be zero.
 */
export interface Side {
  p25?: number;
  p50?: number;
  p75?: number;
  inRange?: number;
  fees?: number;
  /** Named "upper bound" everywhere it is shown: realised LVR is bounded, not point-estimated. */
  lvrUpperBound?: number;
  costs?: number;
  moves?: number;
}

export function ComparisonTable({
  caption,
  agentLabel,
  baselineLabel,
  agent,
  baseline,
  unit,
}: {
  caption: string;
  /** Column headers. Shown, not visually-hidden: a bare second figure is unattributed. */
  agentLabel: string;
  baselineLabel: string;
  agent: Side;
  baseline: Side;
  /** Unit of the three money rows. Omitted when the artifact does not say. */
  unit?: string;
}) {
  // On the row label rather than on six figures: a two-column table of amounts
  // reads worse with the unit repeated in every cell, and the label is where a
  // reader looks to find out what a column of numbers means. `median return`,
  // `in range` and `moves` are not money and are left alone.
  const inUnit = unit ? ` (${unit})` : "";

  return (
    <DataTable
      caption={caption}
      hideCaption={false}
      columns={["Metric", agentLabel, baselineLabel]}
      rows={[
        { label: "median return", value: pct(agent.p50), note: pct(baseline.p50) },
        {
          label: "P25 – P75",
          value: `${pct(agent.p25)} – ${pct(agent.p75)}`,
          note: `${pct(baseline.p25)} – ${pct(baseline.p75)}`,
        },
        { label: "in range", value: fraction(agent.inRange), note: fraction(baseline.inRange) },
        { label: `fees${inUnit}`, value: amount(agent.fees), note: amount(baseline.fees) },
        {
          label: `adverse selection (upper bound)${inUnit}`,
          value: amount(agent.lvrUpperBound),
          note: amount(baseline.lvrUpperBound),
        },
        { label: `costs${inUnit}`, value: amount(agent.costs), note: amount(baseline.costs) },
        { label: "moves", value: count(agent.moves), note: count(baseline.moves) },
      ]}
    />
  );
}

/**
 * The row labels, in order, exported for the test that pins them.
 *
 * Not read by the component — it renders the literals above, because a table
 * whose labels come from an array one indirection away is harder to read than
 * the table it replaced. This is the assertion's copy, and the test that the two
 * agree is what makes it worth having: `ComparisonTable.test.tsx` renders the
 * component and checks the row headers against this list, so deleting a row
 * without deciding to fails rather than silently narrowing the comparison.
 *
 * These are the labels with no unit supplied. When one is, the three money rows
 * gain a ` (WBNB)` suffix — asserted separately, so this list stays a statement
 * about which rows exist rather than about how they are spelled.
 */
export const COMPARISON_ROWS = [
  "median return",
  "P25 – P75",
  "in range",
  "fees",
  "adverse selection (upper bound)",
  "costs",
  "moves",
] as const;
