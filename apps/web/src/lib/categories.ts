import type { AgentRef } from "@/lib/artifacts";

/**
 * The four marketplace categories, and the one rule that turns a name into a URL.
 *
 * ## Why the slug rule lives here and nowhere else
 *
 * Three places need it: `generateStaticParams`, the index page's links, and the
 * detail page's lookup. `output: "export"` ships exactly the params
 * `generateStaticParams` returns and nothing else — so two spellings of this
 * rule do not produce a mismatch that typechecks and then fails loudly. They
 * produce a link that works in `next dev` and 404s on the built site, which is
 * the failure mode nobody sees until the demo.
 *
 * `lib/counterpart.ts::agentSlugFor` makes the same argument for agent slugs
 * and resolves them from `index.json` rather than by lowercasing a name. The
 * difference here is that a category has no slug in any artifact — the emitter
 * publishes `"Market making"` and nothing else — so the rule has to exist
 * somewhere. It exists once.
 *
 * ## Three category vocabularies, and only one of them is this one
 *
 * `index.json`'s agents carry *Rebalancing · Market making · Health · Yield*.
 * `advantage.json`'s tasks carry *trading · security* — the TermiX judging
 * criteria, a different axis entirely. `index.json`'s `not_built[]` carries
 * *Yield · Activation · Due diligence · Operations · Registry*, which overlaps
 * the first only on `Yield`.
 *
 * So a category page cannot join to the advantage report by category. It joins
 * by agent, through `counterpartTask`, whose predicate already handles the fact
 * that the report names an agent in a sentence rather than by id.
 */

/** `"Market making"` -> `"market-making"`. Lowercase, spaces to hyphens. */
export function categorySlug(category: string): string {
  return category
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export interface Category {
  /** As the emitter writes it: `"Market making"`. */
  name: string;
  slug: string;
  agents: AgentRef[];
}

/**
 * The categories the index actually publishes, in the order it publishes them.
 *
 * Derived rather than declared. A literal list here would be a fifth copy of a
 * taxonomy that already exists in `index.json`, and the day a category is added
 * or renamed the site would show one and route to the other.
 *
 * `agents` is a list even though every category currently holds exactly one —
 * because "one agent per category" is a fact about today's index, not a rule,
 * and a page that assumed it would break silently when a second arrives.
 */
export function categoriesFrom(agents: readonly AgentRef[] | undefined): Category[] {
  const byName = new Map<string, Category>();

  for (const agent of agents ?? []) {
    const name = agent.category?.trim();
    if (!name) continue;

    const existing = byName.get(name);
    if (existing) existing.agents.push(agent);
    else byName.set(name, { name, slug: categorySlug(name), agents: [agent] });
  }

  return [...byName.values()];
}

/** One category by slug, or undefined — which is a 404, not an empty page. */
export function categoryBySlug(
  slug: string,
  agents: readonly AgentRef[] | undefined,
): Category | undefined {
  return categoriesFrom(agents).find((c) => c.slug === slug);
}

/**
 * What the category is judged on, in the words the artifacts already use.
 *
 * Two fields, from two different places, and the asymmetry is real rather than
 * an oversight.
 *
 * **The baseline** is `advantage.without_agent` on the agent's own artifact —
 * `"mint once at the same width, never touch it (passive_policy)"` for the
 * three LP agents, `"supply to the highest-rate venue once and never move
 * (park_policy)"` for Router. It is identical across the three LP agents
 * because it describes the *tape*, not the policy, which is exactly what makes
 * it a category-level fact rather than an agent-level one.
 *
 * **The metric sentence is not on the agent artifact at all.** There is no
 * `advantage.metric` there — that field lives on `advantage.json`'s tasks, so
 * it arrives through `counterpartTask` and is therefore absent for any agent
 * the report does not cover. Grid is one: the report has four tasks and Grid
 * appears in none of them. Router is the exception that carries its own, in
 * `quote.basis` (`"net return on supplied capital (realized yield − switch
 * costs)"`), because its quote is an object where the LP agents' is a string.
 *
 * So `metric` is optional and a page must render its absence rather than an
 * empty label. Inventing a sentence to fill the gap would be describing a
 * measurement nobody made.
 */
export interface CategoryBasis {
  metric?: string;
  baseline?: string;
}
