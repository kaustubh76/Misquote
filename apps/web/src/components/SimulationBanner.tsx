"use client";

import { useEffect, useState } from "react";
import { activeScenario, SCENARIO_PARAM, type Scenario } from "@/lib/scenario";

/**
 * A page reading recorded answers says so at the top, not only beside each one.
 *
 * `AnsweredBy` already qualifies every individual answer, and its docstring is
 * right that this is where that belongs: "This qualifies one answer the reader
 * just asked for, not the page." But a scenario is a fact about the *whole
 * visit* — someone arrived at a URL that replays recorded responses, and may
 * have arrived at it from a link rather than by typing it — and a reader who
 * scrolls past the one simulated block would otherwise never learn that.
 *
 * So both, and they say different things. The dot beside a figure says where
 * that figure came from. This says what you are looking at and how to leave.
 *
 * ## Why it renders nothing without a scenario
 *
 * Not a hidden element, not a zero-height container: absent. Nothing on this
 * site is in a simulated state by default, and a banner that is present-but-
 * empty on every page is a banner people stop seeing on the one page it
 * matters.
 *
 * ## Why it needs JavaScript, and why that is a feature
 *
 * The scenario name is read from `location.search` in an effect, so a simulated
 * page cannot prerender. The static export contains no simulated HTML at all —
 * which is one more structural thing stopping a recorded answer from being
 * mistaken for a live one, and the reason `check-pages.mjs`'s no-JavaScript
 * pass needs no scenario branch.
 */
export function SimulationBanner() {
  const [scenario, setScenario] = useState<Scenario | null>(null);

  useEffect(() => {
    let live = true;
    void activeScenario().then((found) => {
      if (!live) return;
      setScenario(found);
      // Stamped on the root element so a browser test can assert the state
      // without reading text — the same mechanism `/quote` uses for `data-tape`.
      if (found) document.documentElement.dataset.scenario = found.name;
      else delete document.documentElement.dataset.scenario;
    });
    return () => {
      live = false;
    };
  }, []);

  if (!scenario) return null;

  // Leaving strips only this parameter. Rebuilding the URL from scratch would
  // drop a `#A6` citation or anything else a reader arrived with.
  const leave = () => {
    const url = new URL(window.location.href);
    url.searchParams.delete(SCENARIO_PARAM);
    window.location.href = url.toString();
  };

  return (
    <div
      role="status"
      className="hatched border-b border-warn-line bg-warn-bg/40 px-5 py-3 [--hatch-tone:var(--hatch-none)]"
    >
      <div className="mx-auto flex max-w-5xl flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="m-0 text-sm text-ink">
          <span className="font-mono text-xs tracking-wide text-warn uppercase">
            Simulated ·{" "}
          </span>
          {scenario.label}
        </p>
        <button
          type="button"
          onClick={leave}
          className="cursor-pointer border-0 bg-transparent p-0 font-mono text-xs text-dim underline"
        >
          leave simulation
        </button>
        <p className="m-0 basis-full text-xs text-faint">
          {scenario.why} Nothing on this page was computed just now — these are
          recorded answers, replayed so this state can be looked at.
        </p>
      </div>
    </div>
  );
}
