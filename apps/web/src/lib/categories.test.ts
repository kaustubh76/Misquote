import { describe, expect, it } from "vitest";
import { categoriesFrom, categoryBySlug, categorySlug, routeIntent } from "@/lib/categories";
import type { AgentRef } from "@/lib/artifacts";

/**
 * The slug rule and the grouping, tested because three call sites depend on
 * them agreeing: `generateStaticParams`, the index's links, and the detail
 * page's lookup. A disagreement there is a link that works in dev and 404s on
 * the export, which is the failure nobody sees until the demo.
 */

const AGENTS: AgentRef[] = [
  { name: "Warden", slug: "warden", category: "Rebalancing", built: true },
  { name: "Grid", slug: "grid", category: "Market making", built: true },
  { name: "Sentinel", slug: "sentinel", category: "Health", built: true },
  { name: "Router", slug: "router", category: "Yield", built: true },
];

describe("categorySlug", () => {
  it("lowercases and hyphenates a two-word name", () => {
    expect(categorySlug("Market making")).toBe("market-making");
  });

  it("leaves a single word alone but for case", () => {
    expect(categorySlug("Rebalancing")).toBe("rebalancing");
  });

  it("does not leave a trailing hyphen on punctuation", () => {
    expect(categorySlug("Health.")).toBe("health");
    expect(categorySlug("  Yield  ")).toBe("yield");
  });
});

describe("categoriesFrom", () => {
  it("derives the categories the index publishes, in order", () => {
    expect(categoriesFrom(AGENTS).map((c) => c.name)).toEqual([
      "Rebalancing",
      "Market making",
      "Health",
      "Yield",
    ]);
  });

  it("groups rather than assuming one agent per category", () => {
    // One-per-category is a fact about today's index, not a rule. A second
    // arrival must appear beside the first rather than replace it.
    const withTwo = [...AGENTS, { name: "Warden II", slug: "warden-2", category: "Rebalancing", built: false }];
    const rebalancing = categoriesFrom(withTwo).find((c) => c.slug === "rebalancing");
    expect(rebalancing?.agents.map((a) => a.slug)).toEqual(["warden", "warden-2"]);
  });

  it("skips an agent with no category rather than inventing one", () => {
    const odd = [{ name: "X", slug: "x", category: "", built: true }] as AgentRef[];
    expect(categoriesFrom(odd)).toEqual([]);
  });

  it("is empty when there is no index", () => {
    expect(categoriesFrom(undefined)).toEqual([]);
  });
});

describe("categoryBySlug", () => {
  it("finds by the same rule that generated the slug", () => {
    expect(categoryBySlug("market-making", AGENTS)?.name).toBe("Market making");
  });

  it("returns undefined for a slug nobody publishes", () => {
    // Which the page renders as a refusal, not an empty category.
    expect(categoryBySlug("arbitrage", AGENTS)).toBeUndefined();
  });
});

describe("routeIntent: the one input, and its refusal to guess", () => {
  const agents: AgentRef[] = [
    { name: "Warden", slug: "warden", category: "Rebalancing", built: true },
    { name: "Grid", slug: "grid", category: "Market making", built: true },
    { name: "Sentinel", slug: "sentinel", category: "Health", built: true },
    { name: "Router", slug: "router", category: "Yield", built: true },
  ];

  it("routes a plain sentence to the category it names", () => {
    expect(routeIntent("keep my liquidity in range", agents)?.slug).toBe("rebalancing");
    expect(routeIntent("where is the best rate for idle stablecoins", agents)?.slug).toBe("yield");
    expect(routeIntent("stop me getting picked off", agents)?.slug).toBe("health");
    expect(routeIntent("a spread with an inventory ladder", agents)?.slug).toBe("market-making");
  });

  it("shows which words decided it", () => {
    // The router is a keyword table, and on a site arguing that every answer
    // traces to something, an input that teleports you somewhere without saying
    // why is the wrong shape even when it is right.
    const intent = routeIntent("my lp position keeps going out of range", agents);
    expect(intent?.matched).toContain("out of range");
  });

  it("returns null for a miss rather than falling through to the first category", () => {
    // `scenario.ts` names this mistake for scenario names — "showing a reader a
    // state they did not select while telling them that they did". It is worse
    // here, because the reader typed the thing being ignored.
    expect(routeIntent("what is the weather in Lisbon", agents)).toBeNull();
    expect(routeIntent("", agents)).toBeNull();
    expect(routeIntent("a", agents)).toBeNull();
  });

  it("derives its categories from the index rather than a literal list", () => {
    // A fifth copy of the taxonomy is what `categoriesFrom` exists to avoid, and
    // the router must not reintroduce one: an index with no Yield agent cannot
    // route to Yield.
    const withoutYield = agents.filter((a) => a.category !== "Yield");
    expect(routeIntent("best lending apr", withoutYield)).toBeNull();
    expect(routeIntent("best lending apr", agents)?.slug).toBe("yield");
  });
});
