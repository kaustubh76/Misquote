import Link from "next/link";
import { Badge } from "@/components/Badge";
import { TapeSource } from "@/components/TapeSource";
import { Card, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { CompareToggle } from "@/components/CompareToggle";
import { Band } from "@/components/Band";
import {
  count,
  fraction,
  money,
  pct,
  signed,
  SIGN_CLASS,
  signOf,
} from "@/lib/format";
import type { AgentRef, RouterArtifact } from "@/lib/artifacts";

/**
 * Router's landing card.
 *
 * A sibling of `AgentCard` rather than a branch inside it: that component reads
 * `quote_detail`, `verdicts.in_range`, `verdicts.profitable` and a replay block
 * with fees and an LVR upper bound, none of which an allocation agent has. The
 * choice was to fill four of those with zeros or to write forty lines. A zero in
 * an LVR column reads as "lost nothing to adverse selection", which is a claim,
 * and `view.tsx` already refuses to draw a 404'd card as a zero for the same
 * reason.
 *
 * The card leads with the boundary rather than the return, because on this tape
 * the return is zero and the boundary is the finding.
 */
export function RouterCard({
  ref_,
  data,
}: {
  ref_: AgentRef;
  data: RouterArtifact;
}) {
  const r = data.replay;
  const q = data.quote;
  const adv = data.advantage;
  // `rate`, and it reads `fraction` rather than reimplementing it. This was a
  // local `pct` that did the same arithmetic without `fraction`'s `isNum`
  // guard — so a missing field rendered "NaN%" instead of an em dash — and it
  // shadowed `lib/format`'s own `pct`, which takes an already-percentage value
  // and means something else. `RouterDetail.tsx` hit exactly this collision and
  // renamed its local to `rate`; this file kept it for one more commit.
  const rate = (x: number) => fraction(x, 2);
  const unit = data.quote_symbol;

  return (
    <Card as="article" className="min-w-0">
      <CardHeader
        title={<Link href={`/agent/${ref_.slug}`}>{data.agent}</Link>}
        eyebrow={`${ref_.category} · ${data.venue}`}
      />

      <Badge>{data.badge}</Badge>
      <TapeSource source={data.source} />

      <p className="mt-4 mb-4 text-sm text-dim">{q.basis}</p>

      {/* The range, drawn, on the page that argues ranges should be.
          This card printed `1.89% – 1.93% (median 1.91%)` while its three
          siblings on the same screen — `AgentCard`, all LP agents — drew bands
          from the same shape of artifact. The landing page made the argument in
          its headline and broke it in one of its four cards.

          Every input was already in scope and is byte-for-byte the prop set
          `RouterDetail.tsx` passes: two series, because Router publishes a
          park-policy baseline; the rug, because `quote.returns` is a real
          array here (unlike a live job's, which is a count); and `overlap` and
          `deltaPp` from the engine rather than derived, for the reason `Band`
          states — a second implementation of the comparison one screen-inch
          away could be made to disagree.

          The withheld branch was a plain amber sentence. `Band`'s
          `sufficient={false}` gives it the hatched box every other withheld
          figure on this site gets. */}
      <Band
        sufficient={q.sufficient}
        note={q.note}
        returns={q.returns}
        caption={`${data.agent} net return on supplied capital`}
        overlap={adv?.quotable ? adv.ranges_overlap : undefined}
        deltaPp={adv?.quotable ? adv.delta_pp : undefined}
        series={
          q.sufficient
            ? [
                {
                  label: data.agent,
                  p25: q.p25,
                  p50: q.p50,
                  p75: q.p75,
                  tone: "agent",
                },
                ...(adv?.quotable
                  ? [
                      {
                        label: adv.without_agent,
                        p25: adv.baseline.p25,
                        p50: adv.baseline.p50,
                        p75: adv.baseline.p75,
                        tone: "baseline" as const,
                      },
                    ]
                  : []),
              ]
            : []
        }
      />

      {/* The median in text beside it. `Band` puts it only in an `aria-label`,
          which is not `innerText`, and `/` carries a 2,000-character no-JS
          floor. Draw the range and keep the number. */}
      {q.sufficient && (
        <p className="mt-3 mb-0 text-xs text-faint">
          median <span className="tabular text-dim">{pct(q.p50)}</span> ·{" "}
          {count(q.net_positive)} of {count(q.samples)} windows finished in
          profit
        </p>
      )}

      <dl className="mt-4 mb-0 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-faint">Best rate seen</dt>
        <dd className="tabular mb-0">{rate(r.best_apr_seen)}</dd>
        <dt className="text-faint">Round-trip hurdle</dt>
        <dd className="tabular mb-0">{rate(r.hurdle_apr_p50)}</dd>
        <dt className="text-faint">Moves</dt>
        <dd className="tabular mb-0">
          {r.entries} enter · {r.switches} switch · {r.exits} exit
        </dd>
        <dt className="text-faint">Decisions</dt>
        <dd className="tabular mb-0">{count(r.samples)}</dd>
      </dl>

      {/* The venues, and what each could take.

          This card showed the return, the hurdle and the moves, and never once
          said what Router was choosing between. That was survivable while every
          venue was a Venus market and the eyebrow's `data.venue` string covered
          it. It stopped being survivable when a PancakeSwap range became a
          venue: the answer to "can this agent find me a better yield" is now a
          per-venue ceiling, and it lived only on the detail page.

          A range shows its width and what it can absorb; a market shows what it
          holds. Neither borrows the other's column — the fields genuinely do not
          correspond, which is why the artifact publishes two shapes. */}
      {data.venues.length > 0 && (
        <ul className="mt-4 mb-0 grid list-none gap-1 p-0 text-sm">
          {data.venues.map((v) => (
            <li
              key={v.venue_id}
              className="flex flex-wrap items-baseline justify-between gap-x-3"
            >
              <span className="min-w-0 text-dim">
                {v.symbol}
                {v.kind === "pool" && (
                  <span className="text-faint">
                    {" "}
                    · ±{count(v.reference_width_ticks)} ticks
                  </span>
                )}
              </span>
              <span className="tabular text-xs text-faint">
                {/* The ceiling, not the size. A1 bounds the position at a
                    fraction of the venue, and the fraction is the number that
                    decided whether this venue could be used at all. */}
                {money(v.a1_ceiling_quote, unit)} ceiling
                {v.held_samples > 0
                  ? ` · held ${count(v.held_samples)}`
                  : " · never entered"}
              </span>
            </li>
          ))}
        </ul>
      )}

      {adv && (
        <p className="mt-4 mb-0 rounded-sm border border-glass-line bg-panel-2/50 px-3 py-2 text-sm">
          <span className="text-faint">vs doing it yourself: </span>
          <span
            className={`tabular font-semibold ${
              SIGN_CLASS[signOf(adv.delta_pp)]
            }`}
          >
            {signed(adv.delta_pp, 2, "pp")}
          </span>
          <span className="text-dim"> — {adv.verdict}</span>
        </p>
      )}

      {data.finding && (
        <p className="mt-4 mb-0 rounded-sm border border-glass-line bg-panel-2/50 px-3 py-2 text-sm leading-relaxed">
          {data.finding}
        </p>
      )}

      {/* What became of the ranges, beside what the agent allocated.

          Two findings rather than one, because they answer different questions:
          `finding` is about the venue Router chose, and this is about the ones it
          considered and did not. A card carrying only the first reports that
          Router picked a lending market and leaves a reader to assume PancakeSwap
          was never on the table — when it was measured on every sample and turned
          down on size. */}
      {data.pool_finding && (
        <p className="mt-3 mb-0 rounded-sm border border-glass-line bg-panel-2/50 px-3 py-2 text-sm leading-relaxed text-dim">
          {data.pool_finding}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <Button href={`/activate/?agent=${ref_.slug}`} size="sm">
          Hire {ref_.name}
        </Button>
        <p className="m-0 text-xs text-faint">
          <Link href={`/agent/${ref_.slug}`} className="text-dim">
            How it chose, and what that rests on →
          </Link>
        </p>
        {/* Offered here too, and the tray is what refuses the mixed pair. A
            button missing from this card alone would read as "this agent
            cannot be compared with anything", which is not the claim — it
            cannot be compared with an *LP* agent. */}
        <CompareToggle slug={ref_.slug} name={ref_.name} />
      </div>
    </Card>
  );
}
