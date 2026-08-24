import Link from "next/link";
import { Badge } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { CompareToggle } from "@/components/CompareToggle";
import { count } from "@/lib/format";
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
export function RouterCard({ ref_, data }: { ref_: AgentRef; data: RouterArtifact }) {
  const r = data.replay;
  const q = data.quote;
  const pct = (x: number) => `${(100 * x).toFixed(2)}%`;

  return (
    <Card as="article" className="min-w-0">
      <CardHeader
        title={<Link href={`/agent/${ref_.slug}`}>{data.agent}</Link>}
        eyebrow={`${ref_.category} · ${data.venue}`}
      />

      <Badge>{data.badge}</Badge>

      <p className="mt-4 mb-0 text-sm text-dim">{q.basis}</p>
      <p className="tabular mt-1 mb-0 text-lg font-semibold">
        {q.sufficient ? (
          <>
            {q.p25.toFixed(2)}% – {q.p75.toFixed(2)}%{" "}
            <span className="text-dim text-sm">(median {q.p50.toFixed(2)}%)</span>
          </>
        ) : (
          <span className="text-warn text-sm">withheld — {q.note}</span>
        )}
      </p>

      <dl className="mt-4 mb-0 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-faint">Best rate seen</dt>
        <dd className="tabular mb-0">{pct(r.best_apr_seen)}</dd>
        <dt className="text-faint">Round-trip hurdle</dt>
        <dd className="tabular mb-0">{pct(r.hurdle_apr_p50)}</dd>
        <dt className="text-faint">Moves</dt>
        <dd className="tabular mb-0">
          {r.entries} enter · {r.switches} switch · {r.exits} exit
        </dd>
        <dt className="text-faint">Decisions</dt>
        <dd className="tabular mb-0">{count(r.samples)}</dd>
      </dl>

      {data.advantage && (
        <p className="mt-4 mb-0 rounded-sm border border-line bg-panel-2 px-3 py-2 text-sm">
          <span className="text-faint">vs doing it yourself: </span>
          <span className="tabular font-semibold">
            {data.advantage.delta_pp >= 0 ? "+" : ""}
            {data.advantage.delta_pp.toFixed(2)}pp
          </span>
          <span className="text-dim"> — {data.advantage.verdict}</span>
        </p>
      )}

      {data.finding && (
        <p className="mt-4 mb-0 rounded-sm border border-line bg-panel-2 px-3 py-2 text-sm leading-relaxed">
          {data.finding}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
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
