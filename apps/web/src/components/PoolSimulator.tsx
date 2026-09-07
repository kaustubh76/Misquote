"use client";

import { useMemo, useState } from "react";
import { Band } from "@/components/Band";
import { CostBars } from "@/components/CostBars";
import { Card } from "@/components/Card";
import { Refusal } from "@/components/Refusal";
import { amount, count, fixed, fraction, money } from "@/lib/format";

/** One rolling window at one width, as `simulation.json` records it. */
export interface SimCell {
  width_ticks: number;
  window: number;
  /** The size this cell was replayed at. The ladder shares a (width, window). */
  capital_quote: number;
  /** A1's ceiling for this cell: 1% of the depth the position sat in. */
  a1_ceiling_quote: number;
  start_ts: number;
  end_ts: number;
  hours: number;
  swaps: number;
  fee_apr: number;
  convexity_cost_apr: number;
  net_apr: number;
  /** At this cell's own `capital_quote`. Never scaled from another cell's. */
  fees_quote: number;
  convexity_cost_quote: number;
  depth_quote: number;
  /** The range the accountant actually used, published by the estimator. */
  tick_lower: number;
  tick_upper: number;
}

export interface SimBand {
  width_ticks: number;
  p25: number;
  p50: number;
  p75: number;
  observations: number;
  sufficient: boolean;
  note: string;
}

export interface SimPool {
  address: string;
  label: string;
  quote_symbol: string;
  fee_pips: number;
  tick_spacing: number;
  lp_fee_share: number;
  badged: boolean;
  tape: { swaps: number; first_ts: number; last_ts: number };
  price_path: { ts: number; tick: number; price: number }[];
  cells: SimCell[];
  bands: SimBand[];
  best_width_ticks: number | null;
  verdict: string;
}

export interface SimulationArtifact {
  chain_id: number;
  /** The size the published bands were measured at. */
  capital_quote: number;
  width_ladder: number[];
  /** Every size swept. The page offers these and nothing between them. */
  capital_ladder: number[];
  /** A1's share of a venue a position may occupy, as the emitter read it. */
  a1_share: number;
  path_points: number;
  summary: {
    pools: number;
    badged: number;
    simulable: number;
    refused: number;
    cells: number;
  };
  pools: SimPool[];
}

function day(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

/**
 * A PancakeSwap v3 position you can actually operate, on history that happened.
 *
 * The track asks for a real benefit to liquidity providers. Everything needed to
 * deliver one has been computed here for weeks and thrown away twenty times per
 * width: `PoolAprEstimator.fit()` returns the fee APR, the realized
 * adverse-selection cost, both of those in the quote token, the depth the
 * position sat in and the tick range it was accounted over — and
 * `band_for_width` kept `net_apr` and dropped the rest.
 *
 * `/venue` publishes what survived: three percentiles per rung. That ranks
 * widths, which is a real answer to a question nobody asks first. The question
 * they ask first is *what would have happened to my money*, and a percentile is
 * not an amount, a rung is not a position, and neither is a window you can point
 * at.
 *
 * ## It signs nothing
 *
 * This is a replay of recorded swaps, so there is no wallet, no approval, no
 * transaction and no way for it to cost anybody anything — which is the honest
 * reading of "without ever putting user funds at risk", rather than a claim
 * about a safety mechanism.
 *
 * ## Every figure is selected, none is computed
 *
 * Each control chooses a cell Python already replayed with the real engine —
 * including the amount, which was very nearly a number box.
 *
 * The reasoning for the number box was that APR is per unit of capital, so
 * money is linear in it and the browser could just multiply. Measured, it is
 * not: ten times the capital earned 9.988 times the fees and a *lower* rate,
 * because `LvrAccountant` prorates each swap's fee by liquidity share,
 * `L / (L_pool + L)`, and a bigger position sits in a bigger denominator. A
 * multiplication would have deleted exactly that, in the direction that
 * flatters the larger position, on the page whose entire purpose is to be the
 * quote that does not flatter. So the sizes are swept and these are them.
 *
 * A width, a window or an amount that is not in `cells` is **absent**, and
 * absent refuses. There is no nearest-neighbour and no averaging of the rungs
 * either side.
 *
 * ## A size above A1's ceiling is refused, not clamped
 *
 * A replayed position may occupy at most `a1_share` of the venue it sits in —
 * 1%, `Params.eps_liquidity_share` — because a position large enough to move
 * the price it is being paid at is not one history can answer for. The ceiling
 * is on every cell, computed where the depth was measured. On the 0.25% pool at
 * its narrowest rung it is 0.026 WBNB, which refuses most of the ladder — and
 * saying so, with the depth it came from, is the most useful thing this page
 * does for that venue. Depth grows with width, so the same amount that is
 * refused narrow is often accepted wide, which is a capacity finding an LP
 * cannot get anywhere else here.
 */
export function PoolSimulator({ data }: { data: SimulationArtifact }) {
  const simulable = data.pools.filter((p) => p.cells.length > 0);
  const [address, setAddress] = useState(
    simulable[0]?.address ?? data.pools[0]?.address ?? ""
  );
  const pool =
    data.pools.find((p) => p.address === address) ?? data.pools[0] ?? null;

  // Widths this pool actually has cells for, not the ladder it was swept at.
  // A rung offered as a control and then refusing is a control that lies about
  // what it does.
  const widths = useMemo(
    () => [...new Set((pool?.cells ?? []).map((c) => c.width_ticks))].sort((a, b) => a - b),
    [pool]
  );
  const [width, setWidth] = useState<number | null>(null);
  const chosenWidth = width !== null && widths.includes(width) ? width : (widths[0] ?? null);

  const cellsAt = useMemo(
    () => (pool?.cells ?? []).filter((c) => c.width_ticks === chosenWidth),
    [pool, chosenWidth]
  );
  // Sizes this pool has cells for at this width, ascending. Derived rather than
  // read off `data.capital_ladder`, for the same reason the widths are: a rung
  // offered and then refusing is a control that lies about what it does.
  const sizes = useMemo(
    () => [...new Set(cellsAt.map((c) => c.capital_quote))].sort((a, b) => a - b),
    [cellsAt]
  );
  const [capital, setCapital] = useState<number | null>(null);
  const chosenCapital =
    capital !== null && sizes.includes(capital)
      ? capital
      : (sizes.find((s) => s === data.capital_quote) ?? sizes[0] ?? null);

  const cells = useMemo(
    () =>
      cellsAt
        .filter((c) => c.capital_quote === chosenCapital)
        .sort((a, b) => a.start_ts - b.start_ts),
    [cellsAt, chosenCapital]
  );
  const [windowIndex, setWindowIndex] = useState(0);
  const at = Math.min(windowIndex, Math.max(0, cells.length - 1));
  const cell = cells[at] ?? null;

  // A1, read off the cell rather than recomputed. The ceiling is a property of
  // the depth this window sat in, so it moves with the window and the width.
  const overCeiling = cell !== null && cell.capital_quote > cell.a1_ceiling_quote;

  // The smallest size replayed in this same window, so the page can say what
  // scaling up actually did to the rate.
  //
  // This is the finding the whole design turns on and until now it was only in
  // the code: the sizes are swept *because* fees are sublinear in capital, and
  // a reader pressing the rungs could see the rate move without being told why
  // — which leaves them to assume it is noise. Both figures are replayed cells
  // at the same width and window, so the comparison is between two
  // measurements and not between a measurement and an extrapolation of it.
  const smallest = useMemo(() => {
    if (!cell) return null;
    const sameWindow = cellsAt.filter((c) => c.window === cell.window);
    return sameWindow.reduce<SimCell | null>(
      (best, c) => (best === null || c.capital_quote < best.capital_quote ? c : best),
      null
    );
  }, [cellsAt, cell]);
  // Percentage points, which is the unit a difference between two rates is in.
  const dilutionPp =
    cell && smallest && smallest.capital_quote < cell.capital_quote
      ? (smallest.net_apr - cell.net_apr) * 100
      : null;

  const band = pool?.bands.find((b) => b.width_ticks === chosenWidth) ?? null;
  const unit = pool?.quote_symbol ?? "";

  if (!pool) return null;

  return (
    <div className="flex flex-col gap-4">
      {/* ------------------------------------------------- the controls -- */}
      <Card>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm">
            <span className="text-dim">Pool</span>
            <select
              value={pool.address}
              onChange={(event) => {
                setAddress(event.target.value);
                setWidth(null);
                setWindowIndex(0);
              }}
              className="mt-1 w-full rounded-sm border border-glass-line bg-glass px-2.5 py-1.5 text-sm text-ink focus:border-brand"
            >
              {data.pools.map((p) => (
                <option key={p.address} value={p.address}>
                  {p.label}
                  {p.cells.length === 0 ? " — not simulable" : ""}
                </option>
              ))}
            </select>
          </label>

          <fieldset className="border-0 p-0 text-sm">
            <legend className="p-0 text-dim">Amount, in {unit}</legend>
            {/* Sizes, not a box. See the note on this component: fees are
                sublinear in capital because a bigger position dilutes its own
                liquidity share, so a number a reader typed could only be
                answered by multiplying — which would delete the dilution in the
                direction that flatters the bigger position. */}
            <div className="mt-2 flex flex-wrap gap-1.5">
              {sizes.map((size) => {
                const on = size === chosenCapital;
                return (
                  <button
                    key={size}
                    type="button"
                    aria-pressed={on}
                    onClick={() => {
                      setCapital(size);
                      setWindowIndex(0);
                    }}
                    className={`tabular rounded-sm border px-2.5 py-1 font-mono text-xs transition-colors ${
                      on
                        ? "border-brand-line bg-brand-bg font-medium text-brand"
                        : "border-glass-line bg-panel-2/50 text-dim hover:text-ink"
                    }`}
                  >
                    {amount(size, 2)}
                  </button>
                );
              })}
            </div>
          </fieldset>
        </div>

        {widths.length > 0 && (
          <fieldset className="mt-4 border-0 p-0">
            <legend className="p-0 text-sm text-dim">
              Range half-width, in ticks
            </legend>
            {/* The same rung idiom as the ladder on `/venue`, and for the same
                reason: a width is a choice from a swept set, not a slider over
                a continuum. Every one of these has cells behind it. */}
            <div className="mt-2 flex flex-wrap gap-1.5">
              {widths.map((w) => {
                const on = w === chosenWidth;
                return (
                  <button
                    key={w}
                    type="button"
                    aria-pressed={on}
                    onClick={() => {
                      setWidth(w);
                      setWindowIndex(0);
                    }}
                    className={`tabular rounded-sm border px-2.5 py-1 font-mono text-xs transition-colors ${
                      on
                        ? "border-brand-line bg-brand-bg font-medium text-brand"
                        : "border-glass-line bg-panel-2/50 text-dim hover:text-ink"
                    }`}
                  >
                    ±{count(w)}
                    {w === pool.best_width_ticks && " · leads"}
                  </button>
                );
              })}
            </div>
          </fieldset>
        )}

        {cells.length > 1 && cell && (
          <label className="mt-4 block text-sm">
            <span className="text-dim">
              Window {count(at + 1)} of {count(cells.length)} —{" "}
              <span className="tabular text-ink">
                {day(cell.start_ts)} to {day(cell.end_ts)}
              </span>
            </span>
            <input
              type="range"
              min={0}
              max={cells.length - 1}
              step={1}
              value={at}
              onChange={(event) => setWindowIndex(event.target.valueAsNumber)}
              className="mt-2 w-full accent-[var(--brand)]"
            />
          </label>
        )}
      </Card>

      {/* --------------------------------------------------- the answer -- */}
      {!cell ? (
        <Refusal
          title="No position can be simulated on this pool"
          reason={pool.verdict}
          floor={`It saw ${count(pool.tape.swaps)} swaps across the whole tape. A width whose windows never cleared the evidence floor has no answer here rather than a small number.`}
        />
      ) : overCeiling ? (
        /* A1, and a refusal rather than a clamp — P-14's rule, in the venue the
           same argument applies to. A position this size would have moved the
           price it is being paid at, so the history it would be quoted from is
           history it would have changed. Clamping and publishing the clamped
           figure would answer a question nobody asked, at the size they did. */
        <Refusal
          title={`${amount(cell.capital_quote, 2)} ${unit} is more than this range can absorb`}
          reason={`Assumption A1 caps a replayed position at ${fraction(
            data.a1_share
          )} of the venue it sits in. Over ticks ${count(cell.tick_lower)} to ${count(
            cell.tick_upper
          )} this pool held ${amount(cell.depth_quote, 2)} ${unit} of depth, so the ceiling is ${amount(
            cell.a1_ceiling_quote,
            4
          )} ${unit}.`}
          floor="Refused rather than clamped: a position large enough to move the price it is paid at cannot be quoted from history it would have changed. Pick a smaller amount, or a wider range — depth grows with width."
        />
      ) : (
        <>
          <Card>
            <p className="mt-0 mb-1 text-sm font-semibold text-ink">
              {money(cell.fees_quote - cell.convexity_cost_quote, unit, 5)}{" "}
              <span className="font-normal text-dim">
                net over {count(Math.round(cell.hours / 24))} days
              </span>
            </p>
            <p className="mt-0 mb-4 max-w-[70ch] text-sm text-dim">
              {money(cell.capital_quote, unit, 2)} in a ±{count(cell.width_ticks)}-tick
              range on {pool.label}, opened {day(cell.start_ts)}, held through{" "}
              {count(cell.swaps)} swaps. That is{" "}
              <span className="tabular text-ink">{fraction(cell.net_apr)}</span>{" "}
              annualised — a rate, not a return anybody realized over{" "}
              {count(Math.round(cell.hours))} hours.
            </p>

            {/* Reused rather than redrawn: this is the same three-part split
                `CostBars` was built for on the agent cards — earned, spent, and
                the identity between them. Every figure is this cell's own; not
                one of them is another cell's scaled. */}
            <CostBars
              caption="What the position earned and gave up"
              unit={unit}
              rows={[
                {
                  label: "fees earned",
                  value: cell.fees_quote,
                  direction: "earned",
                },
                {
                  label: "adverse selection (upper bound)",
                  value: cell.convexity_cost_quote,
                  direction: "spent",
                },
              ]}
              net={cell.fees_quote - cell.convexity_cost_quote}
            />

            {/* What scaling up cost, in the rate, between two replayed sizes.
                Rendered only when it is a real difference: below a hundredth of
                a percentage point the two sizes are the same answer, and a line
                claiming otherwise would be noise dressed as a finding. */}
            {dilutionPp !== null && smallest && Math.abs(dilutionPp) >= 0.01 && (
              <p className="mt-4 mb-0 max-w-[70ch] border-t border-line pt-3 text-sm text-dim">
                The same window at{" "}
                <span className="tabular text-ink">
                  {amount(smallest.capital_quote, 2)} {unit}
                </span>{" "}
                earned{" "}
                <span className="tabular text-ink">{fraction(smallest.net_apr)}</span>.
                This position is{" "}
                <span className="tabular text-ink">
                  {fixed(cell.capital_quote / smallest.capital_quote, 0)}&times;
                </span>{" "}
                the size and earns{" "}
                <span className="tabular text-warn">
                  {fixed(Math.abs(dilutionPp), 2)}pp
                </span>{" "}
                {dilutionPp > 0 ? "less" : "more"} on every unit of it — a bigger
                position takes a smaller share of each swap&rsquo;s fee, because the
                share is <code className="font-mono text-xs">L / (L_pool + L)</code>{" "}
                and it is in the denominator. Both figures are replayed; neither
                is the other one scaled.
              </p>
            )}

            <p className="mt-4 mb-0 border-t border-line pt-3 text-xs text-faint">
              Ticks {count(cell.tick_lower)} to {count(cell.tick_upper)} — the
              range the accountant used, not one redrawn here. The pool&rsquo;s own
              depth over it was worth{" "}
              <span className="tabular">{amount(cell.depth_quote, 2)}</span> {unit}.
              A1&rsquo;s ceiling on it is{" "}
              <span className="tabular">{amount(cell.a1_ceiling_quote, 4)}</span> {unit}.
              LPs keep{" "}
              <span className="tabular">{fraction(pool.lp_fee_share)}</span> of every
              fee on this pool; the rest is the protocol&rsquo;s and this position
              never saw it.
            </p>
          </Card>

          {/* The window in the company of every other window at this width.
              One draw shown alone is the misquote: it is a number with no sense
              of how much it could have been otherwise. */}
          {band && (
            <Card>
              <p className="mt-0 mb-3 max-w-[70ch] text-sm text-dim">
                The window above is one of {count(band.observations)} at this
                width. Here is the range they span, so a good one is visibly a
                draw rather than a promise.
              </p>
              <Band
                sufficient={band.sufficient}
                note={band.note}
                caption={`Net APR at ±${count(chosenWidth ?? 0)} ticks, across every window`}
                series={[
                  {
                    label: `±${count(chosenWidth ?? 0)} ticks`,
                    // `Band` speaks in percentage points and the artifact is in
                    // fractions. Converted here rather than in the emitter,
                    // which publishes one unit for every rate it carries.
                    p25: band.p25 * 100,
                    p50: band.p50 * 100,
                    p75: band.p75 * 100,
                    tone: "agent",
                  },
                ]}
              />
              <p className="mt-3 mb-0 text-xs text-faint">{pool.verdict}</p>
            </Card>
          )}

          <PricePath pool={pool} cell={cell} />
        </>
      )}
    </div>
  );
}

/**
 * The price the position sat through, and where its range was.
 *
 * The figures above say what happened. This says *why*: a range the price left
 * early earns nothing for the rest of the window, and that is visible here and
 * nowhere else on the site. Out-of-range stretches are hatched, which is this
 * codebase's texture for "there is deliberately nothing here" — which is exactly
 * what an out-of-range position earns.
 *
 * Inline positioned elements rather than SVG, the choice `Band.tsx` records:
 * the chart has to be fluid from 320px to a wide desktop, and a stretched SVG
 * distorts its own strokes.
 */
function PricePath({ pool, cell }: { pool: SimPool; cell: SimCell }) {
  const path = pool.price_path.filter(
    (p) => p.ts >= cell.start_ts && p.ts <= cell.end_ts
  );
  if (path.length < 2) return null;

  const ticks = path.map((p) => p.tick);
  const lo = Math.min(...ticks, cell.tick_lower);
  const hi = Math.max(...ticks, cell.tick_upper);
  const pad = hi === lo ? 1 : (hi - lo) * 0.08;
  const [low, high] = [lo - pad, hi + pad];
  const y = (tick: number) => 100 - ((tick - low) / (high - low)) * 100;
  const x = (ts: number) =>
    ((ts - cell.start_ts) / Math.max(1, cell.end_ts - cell.start_ts)) * 100;

  const outside = path.filter(
    (p) => p.tick < cell.tick_lower || p.tick > cell.tick_upper
  ).length;

  return (
    <Card>
      <p className="mt-0 mb-3 max-w-[70ch] text-sm text-dim">
        Where the price went, and where the range was.{" "}
        {outside === 0 ? (
          <>It never left the range — every swap in the window paid this position.</>
        ) : (
          <>
            <span className="tabular text-ink">
              {fraction(outside / path.length)}
            </span>{" "}
            of the sampled path sat outside the range, earning nothing.
          </>
        )}
      </p>

      <div
        className="relative h-40 w-full overflow-hidden rounded-sm border border-glass-line bg-panel-2/50"
        role="img"
        aria-label={`Price over the window, in ticks, from ${count(
          Math.min(...ticks)
        )} to ${count(Math.max(...ticks))}, against a range of ${count(
          cell.tick_lower
        )} to ${count(cell.tick_upper)}. ${
          outside === 0
            ? "The price never left the range."
            : `${outside} of ${path.length} sampled points sat outside it.`
        }`}
      >
        {/* The range, as a band across the whole window. */}
        <div
          className="absolute inset-x-0 border-y border-brand-line bg-brand/12"
          style={{
            top: `${y(cell.tick_upper)}%`,
            height: `${Math.max(0, y(cell.tick_lower) - y(cell.tick_upper))}%`,
          }}
        />
        {/* The path, as segments. Hatched where it is outside the range, which
            is the one thing a line alone cannot say. */}
        {path.slice(1).map((point, index) => {
          const previous = path[index]!;
          const out =
            point.tick < cell.tick_lower || point.tick > cell.tick_upper;
          const left = x(previous.ts);
          const right = x(point.ts);
          const top = Math.min(y(previous.tick), y(point.tick));
          const bottom = Math.max(y(previous.tick), y(point.tick));
          return (
            <div
              key={point.ts}
              className={
                out
                  ? "hatched absolute border-l border-warn-line [--hatch-tone:var(--hatch-warn)]"
                  : "absolute border-l border-ink/60"
              }
              style={{
                left: `${left}%`,
                width: `${Math.max(0.35, right - left)}%`,
                top: `${top}%`,
                height: `${Math.max(0.6, bottom - top)}%`,
              }}
            />
          );
        })}
      </div>

      <p className="mt-2 mb-0 flex flex-wrap justify-between gap-x-4 text-xs text-faint">
        <span className="tabular">{day(cell.start_ts)}</span>
        <span>
          ticks {count(cell.tick_lower)} – {count(cell.tick_upper)}, sampled from{" "}
          {count(pool.price_path.length)} points across the tape
        </span>
        <span className="tabular">{day(cell.end_ts)}</span>
      </p>
    </Card>
  );
}
