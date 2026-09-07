import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { TaskOutputs, pairedWindowsCsv } from "@/components/TaskOutputs";
import { readArtifact } from "@/test/harness";
import type { AdvantageArtifact, AdvantageTask } from "@/lib/artifacts";

/**
 * The rubric's fourth clause — "with the actual outputs attached".
 *
 * The site had no download affordance at all before this: one link to a raw
 * artifact anywhere, on the error page.
 */

const report = readArtifact<AdvantageArtifact>("advantage.json");

afterEach(cleanup);

describe("the paired-window CSV", () => {
  it("gives one row per window with the comparison the win rate counts", () => {
    const task = report.tasks.find((t) => (t.agent.returns?.length ?? 0) > 0)!;
    const csv = pairedWindowsCsv(task)!;
    const lines = csv.trim().split("\n");

    expect(lines[0]).toBe("window,without_agent_pct,with_agent_pct,delta_pp,agent_won");
    expect(lines).toHaveLength(task.agent.returns!.length + 1);

    // The verdict column has to agree with the arithmetic in the same row,
    // because a reader recomputing the win rate from this file is exactly the
    // point of attaching it.
    for (const line of lines.slice(1)) {
      const [, diy, agent, , won] = line.split(",");
      const expected = Number(agent) > Number(diy) ? "yes" : Number(agent) === Number(diy) ? "tie" : "no";
      expect(won).toBe(expected);
    }
  });

  it("agrees with the win rate the report published", () => {
    // Counted, because a loop that compares nothing passes while proving
    // nothing — the shape this repository keeps rediscovering. If any task
    // carries a `beat_rate`, at least one comparison has to have happened.
    let compared = 0;
    for (const task of report.tasks) {
      const csv = pairedWindowsCsv(task);
      if (!csv || !task.beat_rate) continue;
      const wins = csv.split("\n").slice(1).filter((r) => r.endsWith(",yes")).length;
      expect(wins).toBe(task.beat_rate.wins);
      compared += 1;
    }
    if (report.tasks.some((t) => t.beat_rate)) {
      expect(compared).toBeGreaterThan(0);
    }
  });

  // Unequal arms are not the same windows. `BeatRate` refuses to pair them and
  // so must this — zipping to the shorter one would publish a comparison the
  // report itself declines to make.
  it("refuses rather than zipping two arms of different lengths", () => {
    const base = report.tasks.find((t) => (t.agent.returns?.length ?? 0) > 1)!;
    const lopsided = {
      ...base,
      agent: { ...base.agent, returns: base.agent.returns!.slice(0, -1) },
    } as AdvantageTask;
    expect(pairedWindowsCsv(lopsided)).toBeNull();
  });

  it("refuses when a task carries no observations", () => {
    const none = { ...report.tasks[0]!, baseline: { ...report.tasks[0]!.baseline, returns: [] } };
    expect(pairedWindowsCsv(none as AdvantageTask)).toBeNull();
  });
});

describe("what the page offers", () => {
  it("attaches the task and the windows, and points at the whole report", async () => {
    const task = report.tasks.find((t) => (t.agent.returns?.length ?? 0) > 0)!;
    render(<TaskOutputs task={task} agentSlug="warden" />);

    expect(await screen.findByRole("button", { name: /this task, every field/ })).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /paired windows \(CSV\)/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /the whole report/ })).toHaveAttribute(
      "href",
      "/artifacts/advantage.json",
    );
  });

  // The replay keeps no per-decision list; the live loop does. Linking the page
  // that carries it beats inventing the one that does not.
  //
  // The page, not its `#journal` section: `RouterDetail` renders no such
  // section, so the anchor resolved on three agent routes and died on the
  // fourth. `check-pages.mjs` caught it as a dead link from /advantage.
  it("points at the agent's page, with no anchor that only some routes have", async () => {
    const task = report.tasks[0]!;
    render(<TaskOutputs task={task} agentSlug="router" />);
    const link = await screen.findByRole("link", { name: /own page/ });
    expect(link).toHaveAttribute("href", "/agent/router/");
    expect(link.getAttribute("href")).not.toContain("#");
  });

  it("says so rather than offering a CSV it cannot build", async () => {
    const none = { ...report.tasks[0]!, agent: { ...report.tasks[0]!.agent, returns: [] } };
    render(<TaskOutputs task={none as AdvantageTask} />);
    expect(await screen.findByText(/did not report the same count/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /paired windows/ })).not.toBeInTheDocument();
  });
});
