import Link from "next/link";
import { Badge } from "@/components/Badge";
import { Band } from "@/components/Band";
import { TapeSource } from "@/components/TapeSource";
import { Card, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { CompareToggle } from "@/components/CompareToggle";
import { CostBars } from "@/components/CostBars";
import { DataTable } from "@/components/DataTable";
import { Pill, verdictTone } from "@/components/Pill";
import { count, fraction, hours, isNum, pct, signed, SIGN_CLASS, signOf } from "@/lib/format";
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
        aside={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone="warn">{data.badge}</Badge>
            {/* Which tape, beside the badge saying the position was never held.
                Both qualify every figure on this card and neither is derivable
                from the other: "counterfactual" says nothing happened,
                `source` says whether the history it did not happen over was
                real. `provenance.build_stamp` calls this one required. */}
            <TapeSource source={data.source} />
          </span>
        }
      />

      {/* Two columns, and the card keeps every row it had.
          Stacked, one of these ran about a screen tall: a range chart, a
          caption, two verdict pills, a threshold line, a delta strip, a cost
          figure and a metrics table, times four agents. The reading order is
          the same either way — the quote and its verdict, then where the money
          went — so at `lg` they sit side by side and the page loses roughly
          two-fifths of its height with nothing shrunk or dropped.

          `lg` and not `sm`, deliberately. At the `sm` breakpoint each column
          would be about 300px, which is the width this file already has two
          recorded overflow incidents at: a `-7012.06% – -6650.81%` label
          pushed a card 39px past a 350px column. `min-w-0` on both columns is
          the other half of that fix — a grid child's default `min-width: auto`
          refuses to shrink below its content, so a long tabular figure widens
          the track instead of scrolling inside it. */}
      <div className="mt-4 grid gap-5 lg:grid-cols-2 lg:gap-6">
        <div className="min-w-0">
          <Band
            sufficient={data.quote_sufficient && !!q}
            floor={{
              label: "Observations",
              observed: data.quote_detail?.samples ?? 0,
              required: data.floors.min_observations,
            }}
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

          {/* The risk, which the card did not have. A P25-P75 band is an
              interquartile range: it says nothing about the quarter below it,
              so a reader could see warden's floor of 20.7% and not know whether
              any window lost money. `distinct_returns` is here for the same
              reason — the denominator behind "of 60" is about twenty, and
              `ranges.py` has counted that since it was written. */}
          {q && (isNum(q.worst_return) || isNum(q.distinct_returns)) && (
            <p className="mt-2 mb-0 text-xs text-faint">
              {isNum(q.worst_return) && (
                <>
                  Worst window <span className="tabular font-mono">{pct(q.worst_return)}</span>
                  {isNum(q.best_return) && (
                    <>
                      , best <span className="tabular font-mono">{pct(q.best_return)}</span>
                    </>
                  )}
                </>
              )}
              {isNum(q.worst_return) && isNum(q.distinct_returns) && " · "}
              {isNum(q.distinct_returns) && (
                <>
                  {count(q.distinct_returns)} of {count(q.samples)} observations are
                  distinct results
                </>
              )}
            </p>
          )}

          <div className="mt-5 flex flex-wrap gap-2">
            <Pill tone={verdictTone(data.verdicts.in_range)}>
              In range: {data.verdicts.in_range.label}
            </Pill>
            <Pill tone={verdictTone(data.verdicts.profitable)}>
              Beats holding: {data.verdicts.profitable.label}
            </Pill>
            {/* The two are different questions and the card carried only the
                easier one. "Beats holding" counts windows that finished above
                zero — in a fee-earning position nearly all of them do, and all
                three LP agents read 100%. This counts windows that finished
                above the baseline, which is what somebody hiring is paying for
                and the number the track means by "win rate". */}
            {adv?.beat_rate?.comparable && (
              <Pill
                tone={
                  adv.beat_rate.wins > adv.beat_rate.losses
                    ? "pass"
                    : adv.beat_rate.wins === 0
                      ? "fail"
                      : "none"
                }
              >
                Beats doing it yourself: {count(adv.beat_rate.wins)} of{" "}
                {count(adv.beat_rate.windows)}
              </Pill>
            )}
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
            <p className="mt-4 mb-0 rounded-sm border border-glass-line bg-panel-2/50 px-3 py-2 text-sm">
              <span className="text-faint">vs doing it yourself: </span>
              <span className={`tabular font-semibold ${SIGN_CLASS[signOf(adv.delta_pp)]}`}>
                {signed(adv.delta_pp, 2, "pp")}
              </span>
              <span className="text-dim"> — {adv.verdict}</span>
            </p>
          )}

        </div>

        <div className="min-w-0">
          {/* The money, drawn. These were four of the seven rows below, which left
              the reader to subtract and to notice that costs are three orders of
              magnitude above fees. */}
          <div>
            <CostBars
              caption={`${data.agent}: where the money went`}
              net={r.net_quote}
              unit={data.quote_symbol}
              rows={[
                { label: "fees earned", value: r.fees_quote, direction: "earned" },
                {
                  label: "adverse selection (upper bound)",
                  value: r.lvr_quote_upper_bound,
                  direction: "spent",
                },
                { label: "costs", value: r.costs_quote, direction: "spent" },
              ]}
            />
          </div>

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
                  value: `${count(r.mints)} mint · ${count(r.rebalances)} recentre · ${count(r.pulls)} pull`,
                },
              ]}
            />
          </div>

        </div>
      </div>

      {/* The two verbs a marketplace card is for, and it had neither.
          
          This card's only outbound affordances were the tearsheet link and the
          compare chip. A reader who had decided — which is what the card exists
          to help them do — had nowhere to act: `/quote` is reachable from the
          top nav and from step 2 of the demo, and the hire link sits about four
          screens down the detail page. So the marketplace asked people to read a
          tearsheet and then find the checkout themselves.
          
          `?agent=` carries the choice through. `HireFlow` takes no agent today
          and grants the same key whichever card you came from, which is honest
          about the keystore and silent about the reader's intent; the parameter
          is what lets the next page say which agent they picked. */}
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Button href={`/activate/?agent=${ref_.slug}`} size="sm">
          Hire {ref_.name}
        </Button>
        <Button href="/quote/" size="sm" tone="secondary">
          Quote my position
        </Button>
        <span className="ml-auto flex items-center gap-3">
          <Link href={`/agent/${ref_.slug}`} className="text-sm">
            Full tearsheet →
          </Link>
          <CompareToggle slug={ref_.slug} name={ref_.name} />
        </span>
      </div>
    </Card>
  );
}
