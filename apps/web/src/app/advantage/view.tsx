"use client";

import { Heading, Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge } from "@/components/Badge";
import { Band } from "@/components/Band";
import { TallyStrip } from "@/components/TallyStrip";
import { EngineStamp } from "@/components/EngineStamp";
import { TapeSource } from "@/components/TapeSource";
import { Card } from "@/components/Card";
import { ComparisonTable } from "@/components/ComparisonTable";
import { Pill } from "@/components/Pill";
import { ErrorNotice, Refusal } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import {
  load,
  type AdvantageArtifact,
  type AdvantageTask,
  type Loaded,
} from "@/lib/artifacts";
import { agentSlugFor, type IndexedAgentRef } from "@/lib/counterpart";
import {
  EMPTY,
  SIGN_CLASS,
  count,
  fixed,
  isNum,
  money,
  signOf,
  signed,
} from "@/lib/format";

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
    initialMain ? { ok: true, value: initialMain } : null
  );
  const [short, setShort] = useState<Loaded<AdvantageArtifact> | null>(
    initialShort ? { ok: true, value: initialShort } : null
  );
  const [agents, setAgents] = useState<IndexedAgentRef[] | undefined>(
    initialAgents
  );

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

  // The distinct replay windows, longest first, and how many tasks ran on each.
  // Derived rather than read, because the report publishes no such field — and
  // that absence is exactly why the page never disclosed that its four tasks
  // are not all on the same length of tape.
  const windows = [
    ...new Set((d?.tasks ?? []).map((t) => t.replay_days).filter(isNum)),
  ].sort((a, b) => b - a);
  const tasksOn = (n: number) =>
    (d?.tasks ?? []).filter((t) => t.replay_days === n).length;

  return (
    <Loadable loading={main === null} what="the advantage report">
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">
        Does hiring an agent beat doing the job yourself?
      </h1>
      <p className="mt-3 max-w-[68ch] text-dim">
        {/* 58 words making one claim twice — "same driver, tape, cost model,
            accountant" and "only `policy=` differs" are the same sentence. The
            task count is read; it was typed in five places against one field. */}
        {d ? `${d.summary.tasks} tasks` : "Each task"}, each done both ways.
        Only <code className="font-mono text-xs">policy=</code> differs between
        the columns — same driver, same tape, same cost model,{" "}
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
                Run{" "}
                <code className="font-mono text-xs">make advantage-demo</code>{" "}
                for a labelled synthetic tape, or{" "}
                <code className="font-mono text-xs">make advantage</code>{" "}
                against an indexed one.
              </>
            }
          />
        </div>
      )}

      {d && (
        <>
          {/* ------------------------------------------------- the headline -- */}
          <Card className="mt-8 mb-8">
            <div className="grid gap-6 sm:grid-cols-[1fr_auto] sm:items-center">
              <div>
                {/* The badge, read from the report, above the verdict it
                    qualifies.

                    `advantage.json` has carried `badge` since the emitter was
                    written and no view rendered it — the whole report is a
                    replay, neither position was ever held, and the page saying
                    so had been lost. `check-pages.mjs` keeps a no-JavaScript
                    needle on the word for exactly that reason, and that needle
                    had been failing.

                    Not a `Badge` component: this qualifies the entire report
                    rather than one figure on it, and `Badge`'s own docstring
                    reserves itself for "a badge qualifies a number". */}
                {d.badge && (
                  <p className="mt-0 mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs tracking-wide text-warn">
                    {d.badge}
                    {/* Which tape this report ran over. `test_source_disclosure.py`
                        exists because `/advantage` once said `source: chain` for
                        a task while `/agent/sentinel` said `source: synthetic`
                        for the same agent, a sign flip one click apart, with
                        neither page mentioning the other. That test was narrowed
                        to guard the artifact when the component carrying this
                        was deleted — and the artifact half was never the half
                        that broke. */}
                    <TapeSource source={d.source} />
                  </p>
                )}
                {/* And which engine scored them. This report and the agent
                    cards it scores are written by different make targets, so
                    they can be — and were — generated nine engine commits
                    apart: this page said Warden loses to DIY by 64.29pp while
                    /agent/warden said it beats DIY by 17.21pp. The commit was
                    in both artifacts and on neither page. */}
                <EngineStamp
                  className="mb-3"
                  sha={d.build?.git_sha}
                  generatedAt={d.build?.generated_at}
                  dirty={d.build?.git_dirty}
                />
                <Heading className="mt-0 mb-2 text-lg font-semibold">
                  Across all {count(d.summary.tasks)} tasks
                </Heading>
                {/* Toned from the verdict, not from a guess about it. This
                    was `text-warn` unconditionally, so an `overall` that ever
                    resolved to a pass would have been painted as a warning —
                    the page's own headline verdict, mis-toned by a constant.
                    `/status` does this correctly through `OUTCOME_STYLE`, and
                    this now follows it: `called` is the emitter's word for
                    "a verdict was reached", so an uncalled overall is neutral
                    rather than amber, and colour is never the only signal —
                    the label itself is the claim and it renders either way. */}
                <p
                  className={`m-0 font-mono text-sm ${
                    d.overall.called ? "text-ink" : "text-warn"
                  }`}
                >
                  {d.overall.label}
                </p>

                {/* How the tasks fell out, as a shape.

                    The `dl` beside this carries the same four counts in words,
                    and four numbers in a column is work a reader does that a
                    strip does for free — the same argument `/status` makes
                    about its own gate counts. It is not a verdict:
                    `overall.label` above says there is none, and this says
                    nothing the list does not.

                    Writing it is what found that `indistinguishable` had never
                    rendered anywhere, so the list reported 0 ahead and 2 behind
                    of 4 tasks and left the other two unaccounted for. It has a
                    row now, next to its slice. */}
                <TallyStrip
                  className="mt-3"
                  total={d.summary.tasks}
                  parts={[
                    { label: "agent ahead", tone: "bg-good", n: d.summary.agent_ahead },
                    { label: "doing it yourself ahead", tone: "bg-bad", n: d.summary.diy_ahead },
                    {
                      label: "too close to call",
                      tone: "bg-neutral",
                      n: d.summary.indistinguishable,
                    },
                    { label: "withheld", tone: "bg-warn", n: d.summary.withheld },
                  ]}
                  ariaSentence={
                    `Of ${count(d.summary.tasks)} tasks: ${count(d.summary.agent_ahead)} ` +
                    `with the agent ahead, ${count(d.summary.diy_ahead)} with doing it ` +
                    `yourself ahead, ${count(d.summary.indistinguishable)} too close to ` +
                    `call, ${count(d.summary.withheld)} withheld.`
                  }
                />
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
                  {count(d.summary.tasks)} tapes are not evidence about a
                  strategy. Each task&rsquo;s own quote is, and it is drawn from
                  many windows.
                </p>
              </div>

              <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-1">
                <Summary label="tasks" value={count(d.summary.tasks)} />
                <Summary label="quotable" value={count(d.summary.quotable)} />
                <Summary
                  label="withheld"
                  value={count(d.summary.withheld)}
                  tone="text-warn"
                />
                <Summary
                  label="agent ahead"
                  value={count(d.summary.agent_ahead)}
                  tone="text-good"
                />
                <Summary
                  label="DIY ahead"
                  value={count(d.summary.diy_ahead)}
                  tone="text-bad"
                />
                {/* On the interface since the report was written and rendered
                    nowhere, so the list said 0 ahead and 2 behind of 4 and left
                    the other two unaccounted for. They are the calls this
                    report declines to make, which is the most characteristic
                    number on the page. */}
                <Summary
                  label="too close to call"
                  value={count(d.summary.indistinguishable)}
                />
                <Summary
                  label="bands separated"
                  value={count(d.summary.separated)}
                />
              </dl>
            </div>
          </Card>

          {/* The three task cards had no heading above them at all — three h2s
              in a bare div, introduced by nothing. A reader navigating by
              heading met them with no idea what they were a list of. */}
          <Section
            title={<>The {count(d.summary.tasks)} tasks</>}
            className="mt-8"
            intro={
              <>
                The baseline differs per task — several tasks with one baseline
                is one task relabelled — and so does the tape.
                {/* Derived, never typed, and that is the point: the report
                    publishes no "the windows differ" flag, which is precisely
                    why nothing on this page ever said they do. No cause is
                    invented either — the artifact does not record why Route's
                    window is shorter, so this does not guess. */}
                {windows.length > 1 && (
                  <>
                    {" "}
                    {windows
                      .map((n) => `${count(tasksOn(n))} on ${fixed(n, 1)} days`)
                      .join(", ")}
                    . Each column is compared against the other on that
                    task&rsquo;s own tape, so the window bounds how much of a
                    year the annualised figure describes — not which of the two
                    is ahead.
                  </>
                )}
              </>
            }
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
          <Section
            title="The same report, on too little history"
            className="mt-12"
            headingClassName="text-lg font-semibold"
          >
            {/* The opening sentence justified the panel's existence rather
                than saying anything about it — and the panel's own badge and
                its all-withheld output are the demonstration. */}
            <p className="mt-2 mb-5 max-w-[68ch] text-sm text-dim">
              The same code path on a tape too short to reach the policy
              horizon. It produces no numbers at all, which is the correct
              answer.
            </p>

            {short?.ok ? (
              <Card>
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">Deliberately short tape</Badge>
                  {/* Short and synthetic are different claims, and this panel
                      only made the first. A short *chain* tape is real history
                      that ran out; a short *synthetic* one is a random walk
                      truncated on purpose. This report is the second, has been
                      since it was added, and the page said so nowhere. */}
                  <TapeSource source={short.value.source} />
                  <EngineStamp
                    sha={short.value.build?.git_sha}
                    generatedAt={short.value.build?.generated_at}
                    dirty={short.value.build?.git_dirty}
                  />
                  <span className="font-mono text-xs text-faint">
                    {short.value.summary.withheld} of{" "}
                    {short.value.summary.tasks} withheld
                  </span>
                </div>
                <ul className="m-0 list-none space-y-3 p-0">
                  {short.value.tasks.map((t) => (
                    <li key={t.task}>
                      <p className="m-0 text-sm font-medium">{t.task}</p>
                      <p className="mt-1 mb-0 font-mono text-xs text-warn">
                        {t.verdict}
                      </p>
                    </li>
                  ))}
                </ul>
                <p className="mt-4 mb-0 text-sm text-dim">
                  Overall:{" "}
                  <span className="font-mono text-warn">
                    {short.value.overall.label}
                  </span>
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
            <Link href="/methods">
              How each of these quotes was constructed →
            </Link>
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
        <div className="min-w-0 rounded-sm border border-glass-line bg-panel-2/50 p-3">
          <dt className="text-xs tracking-wide text-faint uppercase">
            Without an agent
          </dt>
          <dd className="m-0 mt-1 break-all text-dim">{task.without_agent}</dd>
        </div>
        <div className="min-w-0 rounded-sm border border-glass-line bg-panel-2/50 p-3">
          <dt className="text-xs tracking-wide text-faint uppercase">
            With an agent
          </dt>
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
            {slug ? (
              <Link href={`/agent/${slug}`}>{task.with_agent}</Link>
            ) : (
              task.with_agent
            )}
          </dd>
        </div>
      </dl>

      {/* One series when one thing was measured.

          `task_choose` reuses the baseline replay when the depth heuristic and
          the flow screen land on the same pool, and says why: re-running "would
          invite the reader to think two things were measured when one was". The
          chart then drew two bands, two dots and two legend rows, identical —
          the exact impression the emitter went out of its way not to give. The
          eyebrow carried the fact and the figure contradicted it.

          `task.same_run`, not `delta_pp === 0`: two separate runs are allowed
          to tie, and collapsing those would erase the finding that two
          different choices came out the same. */}
      <Band
        sufficient={task.quotable}
        note={task.note}
        caption={task.task}
        overlap={task.ranges_overlap}
        deltaPp={task.delta_pp}
        // The observations behind the band, the same rug the agent cards draw.
        // `Band` keys it to the agent series, so the agent's are the ones that
        // belong here; on a `same_run` task the two lists are the same anyway.
        returns={task.agent.returns}
        series={
          task.quotable
            ? task.same_run
              ? [
                  {
                    label: task.with_agent,
                    p25: task.agent.p25,
                    p50: task.agent.p50,
                    p75: task.agent.p75,
                    tone: "agent",
                  },
                ]
              : [
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

      {task.quotable && task.same_run && (
        <p className="mt-3 mb-0 max-w-[62ch] text-sm text-dim">
          <strong className="text-ink">
            One band, because one thing was measured.
          </strong>{" "}
          Both rules chose the same venue, so the two columns are the same
          replay — same tape, same policy, same capital — and the difference
          between them is exactly zero by construction rather than by
          measurement.
        </p>
      )}

      <p className="mt-4 mb-0 text-sm">
        <span className={`tabular font-semibold ${SIGN_CLASS[sign]}`}>
          {task.quotable ? signed(task.delta_pp, 2, "pp") : "—"}
        </span>{" "}
        <span className="text-dim">{task.verdict}</span>
      </p>

      {/* The quantity the task is named for, as against the net return.

          "Protect — avoid being picked off by one-way flow" rendered as
          "loses to DIY by 38.17pp" and nothing else, while the artifact
          recorded that on the convexity cost the task exists to reduce the
          agent came in 18.4x better. Showing the first without the second is
          half a finding, and the half that flatters the baseline.

          `summary` is the emitter's own sentence, rendered verbatim. The ratio
          is not recomputed here: a second implementation of the comparison one
          inch from the one Python wrote is the defect `Band` avoids by taking
          `ranges_overlap` as a prop rather than deriving it. It renders on all
          four tasks, including the two where it reads "worse".

          `null` on disk for the Choose task, which compares two pools and has
          no single number the choice is about. Absent, not zero. */}
      {task.primary_metric && (
        <p className="mt-3 mb-0 rounded-sm border border-glass-line bg-panel-2/50 px-3 py-2 text-sm">
          <span className="text-faint">{task.primary_metric.name}: </span>
          <span
            className={`tabular ${
              task.primary_metric.improved ? "text-good" : "text-dim"
            }`}
          >
            {task.primary_metric.summary.replace(
              `${task.primary_metric.name}: `,
              ""
            )}
          </span>
        </p>
      )}

      {/* The three fields behind the sentence above, on every card in the same
          place.

          `material` and `separated` are the two conditions a call needs and
          only one of them reached the page — `separated` through the pill's
          tone, `material` nowhere. And `replay_days` reached it nowhere at all:
          three tasks replay 31.0 days and Route replays 17.0.

          Stated on all four rather than flagged on the short one. A window
          noted only where it is unusual is an apology; a window on every card
          is a field, and the comparison between them belongs to the reader. */}
      <p className="mt-2 mb-0 font-mono text-xs text-faint">
        {task.material ? "material" : "immaterial"} · bands{" "}
        {task.separated ? "separated" : "overlapping"}
        {isNum(task.replay_days) && (
          <> · {fixed(task.replay_days, 1)} days of tape</>
        )}
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
            {/* An em dash in this table is a question the venue does not
                answer, not a measurement of nothing — and a dash without that
                sentence is indistinguishable from a number that failed to
                load. The Route task replays a lending market, which has no
                in-range fraction, no fees and no adverse-selection cost.

                Derived from the artifact rather than from the task's name: a
                second lending task would inherit this without anyone
                remembering to add it, and an LP task that somehow lost a field
                would say so rather than showing a bare dash. */}
            {(task.agent.fees === undefined ||
              task.agent.in_range === undefined) && (
              <p className="mt-3 mb-0 text-xs text-dim">
                Rows reading {EMPTY} are quantities this venue does not have —
                not measurements of zero. A lending market has no range to be in
                and pays no swap fee to a provider.{" "}
                {/* The scope of this task, said here rather than left to be
                    reconciled. Router's own card names two PancakeSwap ranges
                    among its venues; this task deliberately asks the narrower
                    question its name states, and a reader meeting both surfaces
                    should not have to work out which is out of date. Neither
                    is. */}
                This task asks only about lending venues, which is what its name
                says; <Link href="/agent/router">Router&rsquo;s own card</Link>{" "}
                asks the wider question and puts PancakeSwap ranges beside them.
              </p>
            )}
            <p className="mt-3 mb-0 text-xs break-all text-faint">
              {task.metric} · on {money(basis, unit)} of capital · {task.note}
            </p>
          </div>
        </details>
      )}
    </Card>
  );
}
