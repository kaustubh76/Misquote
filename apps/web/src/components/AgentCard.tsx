import Link from "next/link";
import { Badge } from "@/components/Badge";
import { Band } from "@/components/Band";
import { Card, CardHeader } from "@/components/Card";
import { DataTable } from "@/components/DataTable";
import { Pill, verdictTone } from "@/components/Pill";
import { amount, count, fraction, hours, signed, SIGN_CLASS, signOf } from "@/lib/format";
import type { AgentArtifact, AgentRef, IndexArtifact } from "@/lib/artifacts";

export function AgentCard({
  ref_,
  data,
  baseline,
}: {
  ref_: AgentRef;
  data: AgentArtifact;
  /**
   * What the DIY series is called, from `index.json`.
   *
   * The emitter has always written `{name: "DIY (passive)", description: …}`
   * and nothing read it, so this card printed the literal "Doing it yourself"
   * while its own detail page printed `advantage.without_agent`. A card and its
   * detail page disagreeing about what the grey band represents is a small
   * misquote, and it was shipped.
   */
  baseline?: IndexArtifact["baseline"];
}) {
  const q = data.quote_detail;
  const r = data.replay;
  const adv = data.advantage;

  // `min-w-0`: a grid item defaults to `min-width: auto` and refuses to
  // shrink below its own min-content width. The quote line carries figures
  // whose width is the artifact's business — at the current tape they read
  // "-7012.06% – -6650.81%" — and one long enough pushed the card 39px past
  // a 350px column, scrolling the whole document sideways at 390px. Caught
  // by `make web-check`; invisible at 1280 and invisible to jsdom.
  return (
    <Card as="article" className="min-w-0">
      <CardHeader
        eyebrow={ref_.category}
        title={data.agent}
        href={`/agent/${ref_.slug}`}
        aside={<Badge tone="warn">{data.badge}</Badge>}
      />

      <Band
        sufficient={data.quote_sufficient && !!q}
        note={q?.note}
        returns={q?.returns}
        caption={`${data.agent} net return`}
        overlap={adv?.quotable ? adv.ranges_overlap : undefined}
        deltaPp={adv?.quotable ? adv.delta_pp : undefined}
        series={
          q && q.sufficient
            ? [
                {
                  label: data.agent,
                  p25: q.p25,
                  p50: q.p50,
                  p75: q.p75,
                  tone: "agent" as const,
                },
                ...(adv?.quotable
                  ? [
                      {
                        label: baseline?.name ?? adv.without_agent,
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

      {q?.sufficient && (
        <p className="mt-3 mb-0 text-xs text-faint">
          {/* `windows`, not `samples`. `samples` is windows × perturbations —
              the observation count, and the denominator on every verdict — so
              this line read "across 60 sub-windows of ~362.9h each", which is
              21,771 hours drawn from a 725.7h tape. Impossible on its face, and
              it contradicted /methods, which the next line links to and which
              breaks the two apart in a table: "windows 20 · perturbations 3 ·
              = observations 60". The value was derived all along; the noun was
              the hardcoded part. */}
          P25–P75 across {count(q.windows)} sub-windows of ~{hours(q.hours_per_window)}{" "}
          each, {q.annualised ? "annualised" : "not annualised"}.{" "}
          {/* How many of those windows finished in profit, next to the range
              rather than a page away. The engine publishes `net_positive` and
              the detail page has always shown it; the card showed a median and
              nothing else. On the current tape that median is -6,851%
              *annualised* — a 726h loss multiplied up into a rate nobody can
              support — and "0 of 60" is both the more useful fact and the one
              that tells a reader the magnitude is not a unit error. Neither
              number is invented or softened: both are read from the artifact,
              and the verdicts below already say FAIL. */}
          <span className={q.net_positive === 0 ? "text-warn" : undefined}>
            {count(q.net_positive)} of {count(q.samples)} observations finished in profit.
          </span>{" "}
          {/* The card used to print the quote's window length beside the tape's
              total length with no explanation, so it appeared to contradict
              itself: "over 31h" directly above "44,802 over 62.2h". */}
          <Link href="/methods" className="text-dim">
            Why that differs from the {hours(r.hours)} of tape →
          </Link>
        </p>
      )}

      <div className="mt-5 flex flex-wrap gap-2">
        <Pill tone={verdictTone(data.verdicts.in_range)}>
          In range: {data.verdicts.in_range.label}
        </Pill>
        <Pill tone={verdictTone(data.verdicts.profitable)}>
          Beats holding: {data.verdicts.profitable.label}
        </Pill>
      </div>

      {/* The threshold and the sample size, visible. These were `title`
          attributes on the pills above — the most interesting half of a
          verdict, parked in a tooltip that no screen reader announces and
          neither keyboard nor touch can reach. The detail page has always
          shown them as text; now both do. */}
      <p className="mt-2 mb-0 text-xs text-faint">
        In range: {data.verdicts.in_range.detail} · beats holding:{" "}
        {data.verdicts.profitable.detail}
      </p>

      {adv && (
        <p className="mt-4 mb-0 rounded-sm border border-line bg-panel-2 px-3 py-2 text-sm">
          <span className="text-faint">vs doing it yourself: </span>
          <span className={`tabular font-semibold ${SIGN_CLASS[signOf(adv.delta_pp)]}`}>
            {signed(adv.delta_pp, 2, "pp")}
          </span>
          <span className="text-dim"> — {adv.verdict}</span>
        </p>
      )}

      <div className="mt-5">
        <DataTable
          caption={`${data.agent} replay metrics`}
          rows={[
            { label: "in range", value: fraction(r.in_range_fraction) },
            {
              label: "decisions",
              value: `${count(r.samples)} over ${hours(r.hours)}`,
            },
            {
              label: "moves",
              value: `${r.mints} mint · ${r.rebalances} recentre · ${r.pulls} pull`,
            },
            { label: "fees earned", value: amount(r.fees_quote) },
            {
              label: "adverse selection (upper bound)",
              value: amount(r.lvr_quote_upper_bound),
            },
            { label: "costs", value: amount(r.costs_quote) },
            {
              label: "net",
              value: amount(r.net_quote),
              tone: SIGN_CLASS[signOf(r.net_quote)],
            },
          ]}
        />
      </div>

      <p className="mt-5 mb-0">
        <Link href={`/agent/${ref_.slug}`} className="text-sm">
          Full tearsheet, gate histogram and provenance →
        </Link>
      </p>
    </Card>
  );
}
