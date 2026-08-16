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

  return (
    <Card as="article">
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
          P25–P75 across {count(q.samples)} sub-windows of ~{hours(q.hours_per_window)}{" "}
          each, {q.annualised ? "annualised" : "not annualised"}.{" "}
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
