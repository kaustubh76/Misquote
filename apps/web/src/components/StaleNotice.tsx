import { count } from "@/lib/format";

/**
 * These figures were produced by an engine that has since changed.
 *
 * `go_no_go.py` has computed this for as long as the checklist has existed and
 * reported it in exactly one place. On the tree this was written against,
 * `advantage.json` was generated eleven hours before `ade7d87` — a commit that
 * touched `replay/ranges.py` and `estimators/base.py` — and `warden.json`,
 * `grid.json` and `sentinel.json` were four days older still. `/status` called
 * that a blocking UNVERIFIED gate. Searching the rendered text of `/advantage`
 * for "engine", "stale", "commit" or "generated" returned nothing.
 *
 * So the page making the argument was silent about the thing that undermines
 * it, and the reader most likely to notice — one who checks the numbers — was
 * the one least likely to look at the checklist first.
 *
 * ## Read, never re-derived
 *
 * The rule is `go_no_go.py`'s: `git log <artifact sha>..HEAD -- ENGINE_PATHS`,
 * where `ENGINE_PATHS` is deliberately narrower than "everything under
 * packages" — the indexer and the vetting layer can change without moving a
 * figure, "and a gate that goes amber on an unrelated commit is a gate people
 * learn to wave through". A browser cannot run git, and reconstructing the rule
 * here would be a second implementation of it. The check now publishes its
 * findings structurally beside its prose, and this renders those.
 *
 * ## Why a page-level strip
 *
 * The same argument `SourceBanner`'s docstring makes for a synthetic tape:
 * staleness qualifies every figure below it rather than any one of them, so it
 * is stated once at the top instead of a dozen times beside the numbers, where
 * it would compete with the verdict pills that are already there.
 *
 * Warn rather than fail, and hatched like every other absence here. An artifact
 * that predates an engine change is not known to be wrong — it is known not to
 * have been re-derived, which is the distinction `vetting/badge.py` draws
 * between unknown and failed.
 */
export interface BehindEntry {
  artifact: string;
  recorded_sha: string;
  commits: number;
}

export function StaleNotice({
  behind,
  artifacts,
  className = "",
}: {
  /** From `status.json`'s engine check. Empty when nothing is behind. */
  behind: BehindEntry[];
  /** Which artifacts this page's figures come from. Others are not its problem. */
  artifacts: string[];
  className?: string;
}) {
  const mine = behind.filter((entry) => artifacts.includes(entry.artifact));
  // Nothing to say. Not an empty strip — a page whose numbers are current
  // should look like a page with nothing wrong, and this is also the assertion
  // that the notice is driven by data rather than hardcoded.
  if (mine.length === 0) return null;

  // The largest gap, because the strip makes one claim and the worst case is
  // the honest one to make it with.
  const worst = Math.max(...mine.map((entry) => entry.commits));

  return (
    <div
      className={`hatched hatched-wide rounded-md border border-warn-line bg-warn-bg/40 p-4 [--hatch-tone:var(--hatch-warn)] ${className}`}
    >
      <p className="m-0 text-sm text-ink">
        <strong>
          {mine.length === 1
            ? "This figure predates a change to the engine that produced it."
            : "These figures predate a change to the engine that produced them."}
        </strong>{" "}
        <span className="text-dim">
          {/* The verb agrees with the commit count, not with the artifact
              count. Those differ — two stale artifacts one commit behind is the
              ordinary case — and the first draft read "These figures … 1 commit
              … have landed", pluralising one clause off each noun. */}
          {count(worst)} commit{worst === 1 ? " has" : "s have"} landed on the replay
          engine since {mine.length === 1 ? "it was" : "they were"} generated. Nothing here is
          known to be wrong — {mine.length === 1 ? "it has" : "they have"} not been
          re-derived, which is a different claim.
        </span>
      </p>
      <ul className="mt-2 mb-0 flex flex-wrap gap-x-4 gap-y-1 list-none p-0 font-mono text-[11px] text-faint">
        {mine.map((entry) => (
          <li key={entry.artifact}>
            {entry.artifact} @ {entry.recorded_sha}
          </li>
        ))}
      </ul>
    </div>
  );
}
