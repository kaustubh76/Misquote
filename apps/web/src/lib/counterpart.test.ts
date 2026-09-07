import { describe, expect, it } from "vitest";
import { readArtifact } from "@/test/harness";
import { agentSlugFor, counterpartTask } from "@/lib/counterpart";
import type { AdvantageArtifact, AdvantageTask, IndexArtifact } from "@/lib/artifacts";

/** A task with only the fields the join looks at. */
function task(withAgent: string, extra: Partial<AdvantageTask> = {}): AdvantageTask {
  return { with_agent: withAgent, delta_pp: 0, task: "t", ...extra } as AdvantageTask;
}

function report(tasks: AdvantageTask[], source = "chain"): AdvantageArtifact {
  return { source, tasks } as AdvantageArtifact;
}

describe("counterpartTask", () => {
  it("matches the card's bare name against the report's sentence", () => {
    const r = report([task("Warden — Avellaneda–Stoikov recentring")]);
    expect(counterpartTask("Warden", r)?.task.with_agent).toMatch(/^Warden/);
  });

  it("will not claim a task whose agent column merely starts with the name", () => {
    // The report's third row hires nobody: its agent column is "pick the pool
    // whose flow is not one-way — PancakeSwap v3 WBNB/USDT 0.05%, where §3.4's
    // imbalance arm fires on 41.9% of samples…", a whole paragraph. A plain
    // `startsWith` gives that paragraph to any future agent called "Pick", and
    // the card would then quote a pool-selection result as its own second
    // opinion — the exact substitution this file exists to prevent.
    const r = report([task("pick the pool whose flow is not one-way — PancakeSwap v3")]);
    expect(counterpartTask("Pick", r)).toBeUndefined();
  });

  it("matches on the whole name only", () => {
    const r = report([task("Sentinel — withdraw on §3.4 toxicity")]);
    expect(counterpartTask("Sentine", r)).toBeUndefined();
    expect(counterpartTask("Sentinel", r)).toBeTruthy();
  });

  it("is undefined when the report judges no such agent", () => {
    expect(counterpartTask("Grid", report([task("Warden — recentring")]))).toBeUndefined();
  });

  it("survives a missing report rather than throwing on the page", () => {
    expect(counterpartTask("Warden", undefined)).toBeUndefined();
  });

  it("takes the task's own source, and falls back to the report's", () => {
    // `advantage.json` records a source per task; `advantage_short.json`
    // predates the field. An unlabelled second opinion is worse than none, so
    // the fallback is what keeps the older report usable rather than silent.
    const r = report([task("Warden — x", { source: "synthetic" })], "chain");
    expect(counterpartTask("Warden", r)?.source).toBe("synthetic");

    const older = report([task("Warden — x")], "chain");
    expect(counterpartTask("Warden", older)?.source).toBe("chain");
  });

  it("declines to cross-reference a run that names no tape at all", () => {
    const r = report([task("Warden — x")], "");
    expect(counterpartTask("Warden", r)).toBeUndefined();
  });
});

describe("when one agent is named by more than one task", () => {
  // The equities task runs the same Warden against the same baseline on the
  // tokenized-equity venue, and it is withheld: 85 swaps over 4.1 days cannot
  // support the twenty windows A5 asks for. Two tasks, one agent column.
  const withheld = task("Warden — Avellaneda–Stoikov recentring", {
    task: "Equities — provide liquidity to a tokenized stock",
    quotable: false,
  });
  const measured = task("Warden — Avellaneda–Stoikov recentring", {
    task: "Earn — fees on a liquidity position",
    quotable: true,
  });

  it("prefers the task that measured something, whatever the order", () => {
    // The array order is what made this correct before it was a rule, so the
    // withheld one goes first here on purpose.
    expect(counterpartTask("Warden", report([withheld, measured]))?.task.task).toBe(
      "Earn — fees on a liquidity position",
    );
    expect(counterpartTask("Warden", report([measured, withheld]))?.task.task).toBe(
      "Earn — fees on a liquidity position",
    );
  });

  it("still shows a refusal when the refusal is the only reading there is", () => {
    // Not `undefined`. "The only run we have withheld itself" is a second
    // opinion worth carrying; silence is not.
    expect(counterpartTask("Warden", report([withheld]))?.task.quotable).toBe(false);
  });
});

describe("agentSlugFor", () => {
  it("uses the index's slug rather than lowercasing the name", () => {
    const agents = [{ slug: "warden-v2", name: "Warden" }];
    expect(agentSlugFor(task("Warden — recentring"), agents)).toBe("warden-v2");
  });

  it("is undefined for a task that hires nobody the index exports", () => {
    expect(agentSlugFor(task("pick the pool whose flow…"), [{ slug: "grid", name: "Grid" }])).toBeUndefined();
    expect(agentSlugFor(task("Warden — x"), undefined)).toBeUndefined();
    expect(agentSlugFor(task("Warden — x"), [{ name: "Warden" }])).toBeUndefined();
  });
});

describe("against the artifacts on disk", () => {
  // The two joins are one relation, and this is the pairing that made the
  // relation worth having: on the tree this was written against, `/advantage`
  // said Sentinel loses by 38.17pp and `/agent/sentinel` said it wins by
  // 0.72pp. Both pages carry the other's answer now.
  const advantage = readArtifact<AdvantageArtifact>("advantage.json");
  const index = readArtifact<IndexArtifact>("index.json");

  it("agrees with itself in both directions", () => {
    for (const agent of index.agents) {
      const found = counterpartTask(agent.name, advantage);
      if (!found) continue;
      expect(agentSlugFor(found.task, index.agents)).toBe(agent.slug);
    }
  });

  it("resolves some of the report and not all of it", () => {
    // Both halves matter. Nothing resolving would mean the join is broken and
    // every cross-reference silently absent; everything resolving would mean
    // the boundary check has stopped doing anything, since the report carries
    // a row that hires no agent.
    const linked = advantage.tasks.filter((t) => agentSlugFor(t, index.agents));
    expect(linked.length).toBeGreaterThan(0);
    expect(linked.length).toBeLessThan(advantage.tasks.length);
  });
});
