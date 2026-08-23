"use client";

import { Heading, Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge } from "@/components/Badge";
import { Band } from "@/components/Band";
import { Card } from "@/components/Card";
import { ComparisonTable } from "@/components/ComparisonTable";
import { Pill } from "@/components/Pill";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import { SourceBanner } from "@/components/SourceBanner";
import { load, type AdvantageArtifact, type AdvantageTask, type Loaded } from "@/lib/artifacts";
import { agentSlugFor, type IndexedAgentRef } from "@/lib/counterpart";
import { count, money, signed, SIGN_CLASS, signOf } from "@/lib/format";

export function AdvantageView({
  initialMain,
  initialShort,
  initialAgents,
}: {
  /** Read from disk at build time by `page.tsx`. See `lib/build-artifact`. */
  initialMain?: AdvantageArtifact;
  initialShort?: AdvantageArtifact;
  /**
   * The exported agent routes, for linking each task to the card that answers
   * it from its own run. From `index.json`, because that is the file
   * `generateStaticParams` builds the routes from — a slug guessed here would
   * work in dev and 404 on the static export.
   */
  initialAgents?: IndexedAgentRef[];
}) {
  const [main, setMain] = useState<Loaded<AdvantageArtifact> | null>(
    initialMain ? { ok: true, value: initialMain } : null,
  );
  const [short, setShort] = useState<Loaded<AdvantageArtifact> | null>(
    initialShort ? { ok: true, value: initialShort } : null,
  );
  const [agents, setAgents] = useState<IndexedAgentRef[] | undefined>(initialAgents);

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
    // Refreshed rather than frozen at build time, on the same terms as the
    // reports themselves. Only a successful read replaces it: a missing index
    // means no cards were generated, and the honest surface for that is a task
    // that names its agent without linking, not an error on a page about
    // something else.
    load<{ agents?: IndexedAgentRef[] }>("index.json").then((r) => {
      if (live && r.ok) setAgents(r.value.agents);
    });
    return () => {
      live = false;
    };
  }, []);

  const d = main?.ok ? main.value : null;

  return (
    <Loadable loading={main === null} what="the advantage report">
      <h1 className="text-2xl font-semibold">
        Does hiring an agent beat doing the job yourself?
      </h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        {/* 58 words making one claim twice — "same driver, tape, cost model,
            accountant" and "only `policy=` differs" are the same sentence. The
            task count is read; it was typed in five places against one field. */}
        {d ? `${d.summary.tasks} tasks` : "Each task"}, each done both ways. Only{" "}
        <code className="font-mono text-xs">policy=</code> differs between the columns —
        same driver, same tape, same cost model,{" "}
        <strong className="text-ink">held fixed by construction</strong>.
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
                <Heading className="mt-0 mb-2 text-lg font-semibold">
                  Across all {count(d.summary.tasks)} tasks
                </Heading>
                <p className="m-0 font-mono text-sm text-warn">{d.overall.label}</p>
                <p className="mt-3 mb-0 max-w-[56ch] text-sm text-dim">
                  {/* The refusal is the headline, and it is deliberate.
                      Three things here were typed. "thirty-observation floor"
                      spelled out a number `d.overall.label` already renders one
                      line above ("need 30"). The strawman said "the agent wins
                      3 of 3" while `summary` reports 2 ahead and 1 behind — the
                      report is *rendered beside it* saying so, and inventing a
                      more flattering claim to refuse is its own small misquote.
                      And the sample clause was a fake derivation: a ternary on
                      `d.tasks[0]` emitting a fixed string containing two numbers
                      `advantage.json` does not carry at any level. */}
                  {/* The refusal is the headline and stays. What went: a
                      restatement of `d.overall.label` one line above, and a
                      strawman ("led on 2 of 3") that the `dl` beside it already
                      reports — inventing a flattering claim to refuse is its
                      own small misquote. */}
                  {count(d.summary.tasks)} tapes are not evidence about a strategy. Each
                  task&rsquo;s own quote is, and it is drawn from many windows.
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

          {/* The three task cards had no heading above them at all — three h2s
              in a bare div, introduced by nothing. A reader navigating by
              heading met them with no idea what they were a list of. */}
          <Section
            title={<>The {count(d.summary.tasks)} tasks</>}
            className="mt-8"
            intro="The baseline differs per task — several tasks with one baseline is one task relabelled."
          >
            <div className="grid gap-6">
              {d.tasks.map((task) => (
                <TaskCard
                  key={task.task}
                  task={task}
                  capital={d.capital_quote}
                  unit={d.quote_symbol}
                  slug={agentSlugFor(task, agents)}
                />
              ))}
            </div>
          </Section>

          {/* ------------------------------------------- the refusal, live -- */}
          <Section title="The same report, on too little history" className="mt-12" headingClassName="text-lg font-semibold">
            {/* The opening sentence justified the panel's existence rather
                than saying anything about it — and the panel's own badge and
                its all-withheld output are the demonstration. */}
            <p className="mt-2 mb-5 max-w-[68ch] text-sm text-dim">
              The same code path on a tape too short to reach the policy horizon. It
              produces no numbers at all, which is the correct answer.
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
          </Section>

          <p className="mt-10 text-sm">
            <Link href="/methods">How each of these quotes was constructed →</Link>
          </p>
        </>
      )}
    </Loadable>
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

/**
 * A separated band is a *finding*, not a win.
 *
 * The tone was `task.separated ? "pass" : "none"` — green whenever the two
 * bands cleared each other, in either direction. So "Protect — avoid being
 * picked off by one-way flow", where the agent loses to the baseline by
 * 1.77pp, rendered as **✓ −1.77pp** in green: the glyph said pass, the number
 * said loss, and the glyph is what a reader takes in first.
 *
 * `Pill` deliberately carries meaning three ways — shape, glyph, colour — so
 * that removing the colour still leaves the verdict readable. That only helps
 * if all three agree. Here the two non-colour channels were both wrong, which
 * makes it worse for a colourblind reader than a colour-only design would have
 * been.
 *
 * Separation and direction are separate facts and the artifact publishes both:
 *
 *   separated + ahead  → pass   the win survives the spread
 *   separated + behind → fail   so does the loss
 *   overlapping        → none   the sample cannot tell them apart
 *
 * A losing task is not a broken page. `/advantage` exists to publish the
 * comparison honestly, and a task going the other way is the most
 * credible thing on it.
 */
function taskTone(task: AdvantageTask) {
  if (!task.separated) return "none" as const;
  return task.delta_pp > 0 ? ("pass" as const) : ("fail" as const);
}

function TaskCard({
  task,
  capital,
  unit,
  slug,
}: {
  task: AdvantageTask;
  /**
   * The report-level basis, used only when the task carries none of its own.
   *
   * It is `number | string` because the emitter writes the sentence "per task —
   * see tasks[].capital_quote" whenever the tasks disagree, which they now do.
   * `money()` returns a dash for anything non-numeric, so passing that string
   * through rendered "on — of capital" on all three cards.
   */
  capital: number | string;
  unit?: string;
  /** The route for the agent this task hired, when the index exports one. */
  slug?: string;
}) {
  const sign = signOf(task.delta_pp);
  // Per task first. The Choose task is quoted on 0.0318 WBNB and the other two
  // on 1.0 — one basis for all three has not been true since the report started
  // comparing venues.
  const basis = task.capital_quote ?? capital;

  return (
    // `min-w-0`: this card is a grid item, and a grid item defaults to
    // `min-width: auto` — it refuses to shrink below its own min-content width.
    // The regenerated report puts a 42-character pool address in `task.venue`,
    // which has no break opportunity, so the card grew to 465px inside a 350px
    // column and pushed the page 95px sideways at 390px.
    //
    // `AgentCard.tsx` carries this same fix and the same reasoning; this card
    // never needed it while the committed artifact had no addresses in those
    // strings. Caught by `make web-check`, invisible at 1280 and to jsdom.
    <Card as="article" className="min-w-0">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {/* `break-words`: the venue string carries a pool address, and a
              42-character unbroken token cannot wrap. At 390px it pushed the
              page 95px sideways — caught by `make web-check`, invisible at
              1280 and invisible to jsdom. The stale artifact had been hiding
              it: the addresses only entered these strings when the report was
              regenerated from chain. */}
          <div className="mb-1 font-mono text-xs tracking-wide break-all text-faint uppercase">
            {task.category} · {task.venue}
          </div>
          <Heading className="m-0 text-md font-semibold">{task.task}</Heading>
        </div>
        {task.quotable ? (
          <Pill tone={taskTone(task)}>{signed(task.delta_pp, 2, "pp")}</Pill>
        ) : (
          <Pill tone="none">Withheld</Pill>
        )}
      </div>

      <dl className="mb-5 grid gap-3 text-sm sm:grid-cols-2">
        <div className="min-w-0 rounded-sm border border-line bg-panel-2 p-3">
          <dt className="text-xs tracking-wide text-faint uppercase">Without an agent</dt>
          <dd className="m-0 mt-1 break-all text-dim">{task.without_agent}</dd>
        </div>
        <div className="min-w-0 rounded-sm border border-line bg-panel-2 p-3">
          <dt className="text-xs tracking-wide text-faint uppercase">With an agent</dt>
          {/* The agent's own card answers this same task from its own run, and
              the two have disagreed by as much as a sign. This sentence named
              the agent as inert text, so a reader had no way to reach the other
              answer or to know there was one.

              Only when the index exports a route for it. The third task hires
              nobody — its agent column is a paragraph about which pool to
              provide to — and it must stay unlinked rather than acquire a link
              to a page that was never built. */}
          {/* `overflow-wrap: anywhere`, because this carries a pool address.
              A 42-character hex string is one unbreakable word, and `break-words`
              only breaks at opportunities the text offers — of which an address
              offers none. At the old 13px it happened to fit the column; at 16px
              it pushed the grid 75px past the viewport at 390px. The value is
              prose *plus* an address, so `break-all` is wrong: it would hyphenate
              the sentence too. `anywhere` breaks only where nothing else works. */}
          <dd className="m-0 mt-1 text-dim [overflow-wrap:anywhere]">
            {slug ? <Link href={`/agent/${slug}`}>{task.with_agent}</Link> : task.with_agent}
          </dd>
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
            {/* The strategies, not "With agent" / "Without". The same table on
                /agent/[slug] passes the two names, so one component labelled
                its columns two ways depending on the page — and the names are
                the more useful half anyway, since the baseline differs per
                task. */}
            <ComparisonTable
              caption={`${task.task}: agent against baseline`}
              unit={unit}
              agentLabel={task.with_agent}
              baselineLabel={task.without_agent}
              agent={{
                p25: task.agent.p25,
                p50: task.agent.p50,
                p75: task.agent.p75,
                inRange: task.agent.in_range,
                fees: task.agent.fees,
                lvrUpperBound: task.agent.lvr_upper_bound,
                costs: task.agent.costs,
                moves: task.agent.moves,
              }}
              baseline={{
                p25: task.baseline.p25,
                p50: task.baseline.p50,
                p75: task.baseline.p75,
                inRange: task.baseline.in_range,
                fees: task.baseline.fees,
                lvrUpperBound: task.baseline.lvr_upper_bound,
                costs: task.baseline.costs,
                moves: task.baseline.moves,
              }}
            />
            <p className="mt-3 mb-0 text-xs break-all text-faint">
              {task.metric} · on {money(basis, unit)} of capital · {task.note}
            </p>
          </div>
        </details>
      )}
    </Card>
  );
}
