import { timestamp } from "@/lib/format";

/**
 * Where a number came from: the command, when it ran, and against which tree.
 *
 * ## The divergence this closes
 *
 * Three artifacts carry a provenance block — `build.json`, `vetting.json` and
 * `registry.json` — written by the same `tearsheet.provenance.build_stamp()`.
 * Three pages read them, and all three rendered it differently:
 *
 *   - `/` printed command, time, sha, **and `(dirty tree)`**, plus the tape.
 *   - `/vetting` printed command, time and sha, and its local type declared no
 *     `git_dirty` field at all — so the flag was dropped before it could be
 *     forgotten. The artifact said `"git_dirty": true`; the page showed a bare
 *     `344fda7`, which reads as a clean commit anyone can check out.
 *   - `/registry` printed nothing. `registry.json` has carried a full stamp the
 *     whole time.
 *
 * A dirty tree is the qualification that matters most here, because it is the
 * one that makes the sha a lie: `344fda7` is a real commit, and the numbers
 * beside it were produced by code that is not in it. Two pages quoting the same
 * run — one saying "dirty", one not — is the failure this project is named for,
 * arrived at through three separate hand-written footers.
 *
 * ## Why the flag is not styled as an error
 *
 * Regenerating artifacts from a working tree is normal and often unavoidable —
 * `make artifacts` takes half an hour, and it runs while somebody is editing.
 * The requirement is that it be *said*, not that it be prevented. So it renders
 * in the same muted footer as everything else, in words, and the page does not
 * pretend a clean rebuild happened.
 *
 * ## `source`, which this declared and dropped
 *
 * The interface has always carried `source?: string` and the JSX has never
 * rendered it. Five artifacts publish one — `offline`, `chain reads recorded on
 * disk`, `vector files on disk` — and every page showed a command, a timestamp
 * and a sha instead.
 *
 * `/registry` is where that cost something. Its view removed a green "Verified"
 * pill and the comment explaining why cites this exact field: the artifact says
 * `"source": "offline"`, so `available` is a dict lookup rather than a reading.
 * The page made its most careful decision on the strength of a fact it never
 * showed the reader, who was left to take the removal on trust.
 *
 * Rendered first now, before the command, because it is the qualification that
 * changes what everything after it means — the same argument the dirty-tree
 * clause is here for.
 */
export interface Build {
  command: string;
  generated_at: string;
  git_sha: string | null;
  git_dirty?: boolean | null;
  source?: string;
}

export function BuildStamp({
  build,
  extra,
  className = "",
}: {
  build: Build;
  /** Anything the artifact adds — the tape length on the overview, say. */
  extra?: React.ReactNode;
  className?: string;
}) {
  return (
    <p className={`m-0 font-mono text-xs text-faint ${className}`}>
      {build.source ? <>{build.source} · </> : null}
      {build.command} · {timestamp(build.generated_at)} ·{" "}
      {build.git_sha ?? "no commit"}
      {/* Never abbreviated to a symbol. A dirty tree means the sha beside it
          does not contain the code that produced these numbers, and that is a
          sentence, not a marker somebody has to know the legend for. */}
      {build.git_dirty ? " (dirty tree — uncommitted changes)" : ""}
      {extra ? <> · {extra}</> : null}
    </p>
  );
}
