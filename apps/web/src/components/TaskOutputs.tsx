"use client";

/**
 * The outputs, attached.
 *
 * The track asks for "time, cost and output quality, with the actual outputs
 * attached." The first three now render on `/advantage`; this is the fourth,
 * and it was the one the whole site had no affordance for. A repo-wide search
 * for a download link found exactly one, on the error page, pointing at
 * `index.json`. `advantage.json` sits in `public/artifacts/` and is reachable
 * only by guessing the URL.
 *
 * ## What is attached, and what is not
 *
 * Two things, and both are real measurements rather than a rendering of them:
 *
 *   * **the task's own record** — every field the emitter wrote for it,
 *     including both arms' full `returns` arrays;
 *   * **the paired windows** — the two arms side by side, one row per window,
 *     which is the file the win rate is computed from and the one a reader
 *     would want to recompute it in.
 *
 * What is *not* attached is a per-decision trace of the replay. The engine
 * counts decisions (`ReplayDriver.decisions`) and keeps only the last one; no
 * list is captured, so there is no such file to attach and this does not
 * pretend otherwise. The live loop *does* keep one — `data/journal/<agent>.jsonl`,
 * every decision with the gate reasons behind it, served at `/journal/{agent}`
 * and rendered on each agent's page — and that is linked rather than duplicated.
 *
 * ## Built in the browser, from what the page already holds
 *
 * No new artifact and no new route: the task object is already in memory, so
 * the CSV is assembled from it and handed over as a blob. A file the server
 * would have to generate is a file that can go stale against the page beside it.
 */

import { useMemo } from "react";
import type { AdvantageTask } from "@/lib/artifacts";

/** One row per window, both arms, plus the comparison the win rate counts. */
export function pairedWindowsCsv(task: AdvantageTask): string | null {
  const diy = task.baseline.returns;
  const agent = task.agent.returns;
  // Unequal lengths are not the same windows, and `BeatRate` refuses to pair
  // them for that reason. A CSV that zipped to the shorter one would quietly
  // publish a comparison the report itself declines to make.
  if (!diy || !agent || diy.length !== agent.length || diy.length === 0) return null;

  const header = "window,without_agent_pct,with_agent_pct,delta_pp,agent_won";
  const rows = diy.map((base, i) => {
    const a = agent[i]!;
    return [i + 1, base, a, (a - base).toFixed(6), a > base ? "yes" : a === base ? "tie" : "no"].join(
      ",",
    );
  });
  return [header, ...rows].join("\n");
}

function download(name: string, body: string, type: string) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

/** A filename from the task's own name, so two downloads never collide. */
function slugOf(task: string): string {
  return (
    task
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 40) || "task"
  );
}

export function TaskOutputs({ task, agentSlug }: { task: AdvantageTask; agentSlug?: string }) {
  const csv = useMemo(() => pairedWindowsCsv(task), [task]);
  const slug = slugOf(task.task);

  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-4 text-xs">
      <span className="text-faint">Outputs</span>
      <button
        type="button"
        className="underline"
        onClick={() =>
          download(`${slug}.json`, JSON.stringify(task, null, 2), "application/json")
        }
      >
        this task, every field
      </button>
      {csv ? (
        <button
          type="button"
          className="underline"
          onClick={() => download(`${slug}-windows.csv`, csv, "text/csv")}
        >
          {task.agent.returns!.length} paired windows (CSV)
        </button>
      ) : (
        <span className="text-faint">
          no paired windows — the two arms did not report the same count
        </span>
      )}
      <a className="underline" href="/artifacts/advantage.json">
        the whole report
      </a>
      {/* The page, not the `#journal` section on it.
          `AgentDetail` renders that section and `RouterDetail` does not —
          Router replays a Venus rate tape, and its own journal is 169 rows of
          which no two are consecutive, so the component that draws a decision
          history for the LP agents has nothing to draw. The anchor therefore
          resolved on three of four agent routes and died on the fourth, which
          `check-pages.mjs` found and reported as a dead link from /advantage. */}
      {agentSlug && (
        <a className="underline" href={`/agent/${agentSlug}/`}>
          this agent&rsquo;s own page
        </a>
      )}
    </div>
  );
}
