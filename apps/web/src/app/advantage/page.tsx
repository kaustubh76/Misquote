"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge } from "@/components/Badge";
import { Band } from "@/components/Band";
import { Card } from "@/components/Card";
import { DataTable } from "@/components/DataTable";
import { Pill } from "@/components/Pill";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { SourceBanner } from "@/components/SourceBanner";
import { load, type AdvantageArtifact, type AdvantageTask, type Loaded } from "@/lib/artifacts";
import { amount, count, fraction, pct, signed, SIGN_CLASS, signOf } from "@/lib/format";

export default function AdvantagePage() {
  const [main, setMain] = useState<Loaded<AdvantageArtifact> | null>(null);
  const [short, setShort] = useState<Loaded<AdvantageArtifact> | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([
      load<AdvantageArtifact>("advantage.json"),
      load<AdvantageArtifact>("advantage_short.json"),
    ]).then(([m, s]) => {
      if (!live) return;
      setMain(m);
      setShort(s);
    });
    return () => {
      live = false;
    };
  }, []);

  const d = main?.ok ? main.value : null;

  return (
    <div aria-busy={main === null}>
      <h1 className="text-2xl font-semibold">
        Does hiring an agent beat doing the job yourself?
      </h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        Three tasks, each done both ways. The baseline is{" "}
        <strong className="text-ink">not a different program</strong>: it runs through the
        same replay driver, the same tape, the same cost model and the same
        adverse-selection accountant. The only thing that differs between the two columns
        is the function that returns a decision. Swap <code className="font-mono text-xs">policy=</code>{" "}
        and everything else is held fixed by construction.
      </p>

      {main === null && (
        <div className="mt-10 grid gap-5">
          <CardSkeleton />
          <CardSkeleton />
        </div>
      )}

      {main && !main.ok && (
        <div className="mt-10">
          <ErrorNotice
            title="The advantage report has not been generated"
            detail={main.error.message}
            remedy={
              <>
                Run <code className="font-mono text-xs">make advantage-demo</code> for a
                labelled synthetic tape, or{" "}
                <code className="font-mono text-xs">make advantage</code> against an
                indexed one.
              </>
            }
          />
        </div>
      )}

      {d && (
        <>
          <div className="mt-8">
            <SourceBanner source={d.source} badge={d.badge} />
          </div>

          {/* ------------------------------------------------- the headline -- */}
          <Card className="mb-8">
            <div className="grid gap-6 sm:grid-cols-[1fr_auto] sm:items-center">
              <div>
                <h2 className="mt-0 mb-2 text-lg font-semibold">Across all three tasks</h2>
                <p className="m-0 font-mono text-sm text-warn">{d.overall.label}</p>
                <p className="mt-3 mb-0 max-w-[56ch] text-sm text-dim">
                  {/* The refusal is the headline, and it is deliberate. */}
                  The overall verdict uses the same thirty-observation floor the cards use,
                  so with three tasks it <strong className="text-ink">refuses to call it</strong>.
                  Three tapes are not evidence about a strategy, and a report claiming
                  &ldquo;the agent wins 3 of 3&rdquo; from three tapes would be doing the
                  thing this project argues against. What carries the argument is each
                  task&rsquo;s own quote, where the sample is {" "}
                  {d.tasks[0] ? "twenty sub-windows times three perturbations" : "many windows"},
                  not one.
                </p>
              </div>

              <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-1">
                <Summary label="tasks" value={count(d.summary.tasks)} />
                <Summary label="quotable" value={count(d.summary.quotable)} />
                <Summary label="withheld" value={count(d.summary.withheld)} tone="text-warn" />
                <Summary
                  label="agent ahead"
                  value={count(d.summary.agent_ahead)}
                  tone="text-good"
                />
                <Summary label="DIY ahead" value={count(d.summary.diy_ahead)} tone="text-bad" />
                <Summary label="bands separated" value={count(d.summary.separated)} />
              </dl>
            </div>
          </Card>

          {/* ----------------------------------------------------- the tasks -- */}
          <div className="grid gap-6">
            {d.tasks.map((task) => (
              <TaskCard key={task.task} task={task} capital={d.capital_quote} />
            ))}
          </div>

          {/* ------------------------------------------- the refusal, live -- */}
          <section className="mt-12">
            <h2 className="text-lg font-semibold">The same report, on too little history</h2>
            <p className="mt-2 mb-5 max-w-[68ch] text-sm text-dim">
              A floor nobody has seen bite is indistinguishable from a floor that is not
              wired up. Below is the identical report — same three tasks, same machinery,
              same code path — run against a tape too short for a single sub-window to
              reach the 24-hour policy horizon. It produces no numbers at all, which is
              the correct answer and the point.
            </p>

            {short?.ok ? (
              <Card>
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">Deliberately short tape</Badge>
                  <span className="font-mono text-xs text-faint">
                    {short.value.summary.withheld} of {short.value.summary.tasks} withheld
                  </span>
                </div>
                <ul className="m-0 list-none space-y-3 p-0">
                  {short.value.tasks.map((t) => (
                    <li key={t.task}>
                      <p className="m-0 text-sm font-medium">{t.task}</p>
                      <p className="mt-1 mb-0 font-mono text-xs text-warn">{t.verdict}</p>
                    </li>
                  ))}
                </ul>
                <p className="mt-4 mb-0 text-sm text-dim">
                  Overall:{" "}
                  <span className="font-mono text-warn">{short.value.overall.label}</span>
                </p>
              </Card>
            ) : (
              <Refusal
                title="The short-tape demonstration has not been generated"
                reason="This panel shows the refusal machinery running against history too thin to quote."
                floor="make advantage-short"
                cite="A5"
              />
            )}
          </section>

          <p className="mt-10 text-sm">
            <Link href="/methods">How each of these quotes was constructed →</Link>
          </p>
        </>
      )}
    </div>
  );
}

function Summary({
  label,
  value,
  tone = "text-ink",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs tracking-wide text-faint uppercase">{label}</dt>
      <dd className={`tabular m-0 font-semibold ${tone}`}>{value}</dd>
    </div>
  );
}

function TaskCard({ task, capital }: { task: AdvantageTask; capital: number }) {
  const sign = signOf(task.delta_pp);

  return (
    <Card as="article">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1 font-mono text-xs tracking-wide text-faint uppercase">
            {task.category} · {task.venue}
          </div>
          <h2 className="m-0 text-md font-semibold">{task.task}</h2>
        </div>
        {task.quotable ? (
          <Pill tone={task.separated ? "pass" : "none"}>
            {signed(task.delta_pp, 2, "pp")}
          </Pill>
        ) : (
          <Pill tone="none">Withheld</Pill>
        )}
      </div>

      <dl className="mb-5 grid gap-3 text-sm sm:grid-cols-2">
        <div className="rounded-sm border border-line bg-panel-2 p-3">
          <dt className="text-xs tracking-wide text-faint uppercase">Without an agent</dt>
          <dd className="m-0 mt-1 text-dim">{task.without_agent}</dd>
        </div>
        <div className="rounded-sm border border-line bg-panel-2 p-3">
          <dt className="text-xs tracking-wide text-faint uppercase">With an agent</dt>
          <dd className="m-0 mt-1 text-dim">{task.with_agent}</dd>
        </div>
      </dl>

      <Band
        sufficient={task.quotable}
        note={task.note}
        caption={task.task}
        overlap={task.ranges_overlap}
        deltaPp={task.delta_pp}
        series={
          task.quotable
            ? [
                {
                  label: task.with_agent,
                  p25: task.agent.p25,
                  p50: task.agent.p50,
                  p75: task.agent.p75,
                  tone: "agent",
                },
                {
                  label: task.without_agent,
                  p25: task.baseline.p25,
                  p50: task.baseline.p50,
                  p75: task.baseline.p75,
                  tone: "baseline",
                },
              ]
            : []
        }
      />

      <p className="mt-4 mb-0 text-sm">
        <span className={`tabular font-semibold ${SIGN_CLASS[sign]}`}>
          {task.quotable ? signed(task.delta_pp, 2, "pp") : "—"}
        </span>{" "}
        <span className="text-dim">{task.verdict}</span>
      </p>

      {task.quotable && (
        <details className="mt-5 border-t border-line pt-4">
          <summary className="cursor-pointer text-sm font-semibold text-warn">
            The supporting numbers
          </summary>
          <div className="mt-4">
            <DataTable
              caption={`${task.task}: agent against baseline`}
              hideCaption={false}
              columns={["Metric", "With agent", "Without"]}
              rows={[
                {
                  label: "median return",
                  value: pct(task.agent.p50),
                  note: pct(task.baseline.p50),
                },
                {
                  label: "P25 – P75",
                  value: `${pct(task.agent.p25)} – ${pct(task.agent.p75)}`,
                  note: `${pct(task.baseline.p25)} – ${pct(task.baseline.p75)}`,
                },
                {
                  label: "in range",
                  value: fraction(task.agent.in_range),
                  note: fraction(task.baseline.in_range),
                },
                {
                  label: "fees",
                  value: amount(task.agent.fees),
                  note: amount(task.baseline.fees),
                },
                {
                  label: "adverse selection (upper bound)",
                  value: amount(task.agent.lvr_upper_bound),
                  note: amount(task.baseline.lvr_upper_bound),
                },
                { label: "costs", value: amount(task.agent.costs), note: amount(task.baseline.costs) },
                { label: "moves", value: count(task.agent.moves), note: count(task.baseline.moves) },
              ]}
            />
            <p className="mt-3 mb-0 text-xs text-faint">
              {task.metric} · on {amount(capital)} of capital · {task.note}
            </p>
          </div>
        </details>
      )}
    </Card>
  );
}
