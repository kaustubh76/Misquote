import type { AdvantageArtifact, AdvantageTask } from "@/lib/artifacts";

/**
 * Two artifacts, one question, and the join between them.
 *
 * `advantage.json` and the agent cards answer the same thing — did the
 * agent beat doing it yourself — from different runs, and for a while they
 * disagreed in public with nothing between them saying so:
 *
 *     /advantage        Protect — Sentinel   −38.17pp   source: chain
 *     /agent/sentinel   Sentinel             +0.72pp    source: synthetic
 *
 * A sign flip, one click apart, both pages confident. Neither is wrong; they
 * are 30 days of indexed history against 62 hours of generated tape. What was
 * wrong is that the site never said which was which at the point where the
 * number is read, and `scripts/showcase.py` calls mistaking one for the other
 * "the failure this whole project is named after".
 *
 * Nothing here decides which answer is right. It only finds the other one, so
 * both pages can carry it.
 */

/** An agent as the generated index lists it. */
export interface IndexedAgentRef {
  slug?: string;
  name?: string;
}

/** The other run's answer, with the source resolved. */
export interface Counterpart {
  task: AdvantageTask;
  /**
   * The tape behind this task.
   *
   * Per-task first, then the report's. `advantage.json` records a `source` on
   * every task because its three tasks can be replayed separately and two of
   * them were; `advantage_short.json` predates that field and carries only the
   * report-level one. Falling back rather than showing nothing, because "which
   * tape" is the whole point of the cross-reference — an unlabelled second
   * opinion is worse than none.
   */
  source: string;
}

/**
 * The emitter's own shape for an agent column: a name, then a dash, then what
 * the agent does. `"Warden — Avellaneda–Stoikov recentring"`.
 *
 * Any of the three dashes, because prose in this repository uses all of them
 * and the join should not be the thing that notices.
 */
const AFTER_NAME = /^\s*[—–-]\s/;

/**
 * Does this task's agent column name this agent?
 *
 * There is no id to join on. `advantage.json` records the agent as a sentence
 * and the card records a bare `"Warden"`, so the join is the name against the
 * start of the sentence — and the question is where the name is allowed to end.
 *
 * **Not at any non-word character.** That was the first rule here and it is
 * wrong in the one way that matters. The report's third row hires nobody: its
 * agent column is `"pick the pool whose flow is not one-way — PancakeSwap v3
 * WBNB/USDT 0.05%, where §3.4's imbalance arm fires on…"`, a whole paragraph.
 * A future agent called "Pick" clears a "must not be followed by a letter"
 * check on the space in "pick the", inherits that paragraph as its second
 * opinion, and the card quotes a pool-selection result as an answer about
 * itself. The test that says so is in `counterpart.test.ts`; it caught this
 * rule failing before the rule shipped.
 *
 * So the name must run out where the emitter says it does — at the end of the
 * string, or at the dash that separates the agent from its description.
 */
function namesAgent(withAgent: string, agent: string): boolean {
  const name = agent.trim().toLowerCase();
  const column = withAgent.trim().toLowerCase();
  if (!name || !column.startsWith(name)) return false;

  const rest = column.slice(name.length);
  return rest === "" || AFTER_NAME.test(rest);
}

/**
 * The advantage report's answer for one agent, if it has one.
 *
 * `undefined` is a real and common result, not a failure: the report has three
 * tasks and the site has four agents, and they do not line up. Grid appears in
 * neither of the two agent-shaped tasks, and the third task is a choice between
 * pools rather than a policy anybody hired. So two of the pairings resolve to
 * nothing, and the caller must render nothing rather than an empty box — which
 * is the case worth testing, because it is the one that only shows up on the
 * page a judge is least likely to open.
 */
export function counterpartTask(
  agent: string,
  report: AdvantageArtifact | undefined,
): Counterpart | undefined {
  const task = report?.tasks?.find((t) => namesAgent(t.with_agent ?? "", agent));
  if (!task || !report) return undefined;

  const source = task.source ?? report.source;
  return typeof source === "string" && source.length > 0 ? { task, source } : undefined;
}

/**
 * The route for the agent a task names, if the index knows one.
 *
 * The inverse join, and deliberately the same predicate: a task that links to
 * `/agent/warden` from the report and a card that quotes that task back are one
 * relation, and two spellings of it would eventually disagree.
 *
 * The slug comes from `index.json` rather than from lowercasing the name.
 * `generateStaticParams` exports exactly the slugs that file lists, so a name
 * this cannot find is a route that was never exported — and guessing at it
 * would produce a link that 404s on the static site while working in dev.
 */
export function agentSlugFor(
  task: AdvantageTask,
  agents: IndexedAgentRef[] | undefined,
): string | undefined {
  const match = agents?.find(
    (a) => typeof a.name === "string" && namesAgent(task.with_agent ?? "", a.name),
  );
  return typeof match?.slug === "string" && match.slug.length > 0 ? match.slug : undefined;
}
