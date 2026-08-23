import { Badge } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { DataTable } from "@/components/DataTable";
import { count, fraction, hours } from "@/lib/format";
import type { RouterArtifact } from "@/lib/artifacts";

/**
 * Router's page. A sibling of `AgentDetail`, for the reason `RouterArtifact` is
 * a sibling of `AgentArtifact`: this agent has no range, no fees and no LVR, and
 * the LP page's columns would have to be filled with zeros that read as claims.
 *
 * The card's job here is unusual and worth stating: on the tape this repository
 * holds, Router **never moved**. A page that rendered that as an empty activity
 * table would look broken. So the finding is the headline, and the numbers that
 * support it — the best rate the venues actually offered, the hurdle it was
 * measured against, and how long capital would have to be committed before the
 * two crossed — are the body.
 */
export function RouterDetail({ data }: { data: RouterArtifact }) {
  const q = data.quote;
  const r = data.replay;
  const pct = (x: number) => `${(100 * x).toFixed(3)}%`;

  return (
    <>
      <CardHeader title={data.agent} eyebrow={`${data.category} · ${data.venue}`} />

      <Badge>{data.badge}</Badge>

      {data.finding && (
        <Card className="mt-4">
          <p className="mb-0 text-sm leading-relaxed">{data.finding}</p>
        </Card>
      )}

      <Card className="mt-4">
        <CardHeader title="What it would have earned" />
        <p className="mb-2 text-sm text-dim">{q.basis}</p>
        {q.sufficient ? (
          <p className="tabular mb-0 text-lg font-semibold">
            {q.p25.toFixed(2)}% – {q.p75.toFixed(2)}%{" "}
            <span className="text-dim text-sm">(median {q.p50.toFixed(2)}%)</span>
          </p>
        ) : (
          <p className="mb-0 text-sm text-warn">withheld — {q.note}</p>
        )}
        <p className="mt-2 mb-0 text-xs text-faint">
          {count(q.net_positive)} of {count(q.samples)} windows finished in profit ·{" "}
          {count(q.windows)} windows × {count(q.perturbations)} perturbations ·{" "}
          {hours(q.hours_per_window)} each
        </p>
      </Card>

      <Card className="mt-4">
        <CardHeader
          title="Why it did what it did"
          eyebrow="The boundary, and how far the market was from crossing it"
        />
        <DataTable
          caption="Router's switching boundary and the rates it was measured against"
          rows={[
            { label: "Best realized rate seen", value: pct(r.best_apr_seen) },
            { label: "Largest edge between venues", value: pct(r.max_edge_apr) },
            { label: "Round-trip hurdle (median)", value: pct(r.hurdle_apr_p50) },
            {
              label: "Commitment before entry repays a round trip",
              value: `${(r.breakeven_horizon_hours / 24).toFixed(1)} days`,
            },
            { label: "Decisions", value: count(r.samples) },
            {
              label: "Enter / switch / exit",
              value: `${r.entries} / ${r.switches} / ${r.exits}`,
            },
            { label: "Share of samples invested", value: fraction(r.invested_fraction) },
            {
              label: "Share of samples on the best venue",
              value: fraction(r.best_venue_fraction),
            },
          ]}
        />
      </Card>

      {data.advantage && (
        <Card className="mt-4">
          <CardHeader
            title="Against doing it yourself"
            eyebrow={data.advantage.without_agent}
          />
          <DataTable
            caption="The baseline's own figures, from the same driver and the same tape"
            rows={[
              { label: "Verdict", value: data.advantage.verdict },
              {
                label: "Baseline net return P25-P75",
                value: `${data.advantage.baseline.p25.toFixed(2)}% – ${data.advantage.baseline.p75.toFixed(2)}%`,
                note: `median ${data.advantage.baseline.p50.toFixed(2)}%`,
              },
              {
                label: "Baseline moves",
                value: `${data.advantage.baseline.entries} enter · ${data.advantage.baseline.switches} switch`,
              },
              {
                label: "Baseline costs",
                value: data.advantage.baseline.costs_quote.toFixed(4),
              },
            ]}
          />
        </Card>
      )}

      {data.cost_model && (
        <Card className="mt-4">
          <CardHeader
            title="What a move costs"
            eyebrow="Every input is a reading, or says it is not"
          />
          <DataTable
            caption="The cost inputs behind the hurdle, and where each came from"
            rows={[
              {
                label: "Swap fee",
                value: `${data.cost_model.slippage_bps} bps`,
                note: "the verified pool's own fee tier",
              },
              {
                label: "Gas per transaction",
                value: data.cost_model.gas_quote.toFixed(6),
                note: "gas units x gas price x native price",
              },
              {
                label: "Derived from readings",
                value: data.cost_model.derived ? "yes" : "no — a fallback is in use",
              },
            ]}
          />
          <p className="mt-3 mb-0 text-xs text-faint">{data.cost_model.basis}</p>
        </Card>
      )}

      <Card className="mt-4">
        <CardHeader
          title="Venues"
          eyebrow="Verified three ways; sizes are as at the end of the tape"
        />
        <DataTable
          caption="The Venus markets Router is allowed to choose between"
          rows={data.venues.map((v) => ({
            label: v.symbol,
            value: `${Math.round(v.supplied_base_at_tape_end).toLocaleString()} supplied`,
            note: `reserve factor ${v.reserve_factor}${
              v.reserve_factor_recorded ? "" : " (not on tape)"
            }`,
          }))}
        />
      </Card>

      {data.provenance && (
        <Card className="mt-4">
          <CardHeader
            title="Where these numbers came from"
            eyebrow="The journal the agent wrote, published beside the replay that quoted it"
          />
          <DataTable
            caption="The decision journal behind this card"
            rows={[
              { label: "Journal", value: data.provenance.journal },
              {
                label: "Rows",
                value: count(data.provenance.journal_rows),
                note: `${hours(data.provenance.hours_covered)} covered`,
              },
            ]}
          />
        </Card>
      )}

      <Card className="mt-4">
        <CardHeader title="Assumptions this rests on" />
        <ul className="mb-0 space-y-2 text-sm text-dim">
          {data.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </Card>
    </>
  );
}
