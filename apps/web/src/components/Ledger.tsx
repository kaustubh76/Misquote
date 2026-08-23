import { Badge } from "@/components/Badge";
import { Heading } from "@/components/Heading";
import type { NotBuiltEntry } from "@/lib/artifacts";

/**
 * The things that were promised and do not exist.
 *
 * Rendered with the same weight as the things that do, because a marketplace
 * showing fewer agent cards than it advertises categories and silently omitting the rest
 * advertises is misquoting by omission — which is the specific failure this
 * product is named after. `docs/FOR_JUDGES.md` leads with what is not proven;
 * this is that page's counterpart in the UI.
 */
export function NotBuiltCard({ entry }: { entry: NotBuiltEntry }) {
  return (
    <article className="rounded-lg border border-dashed border-line-strong bg-panel/50 p-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="mb-1 font-mono text-xs tracking-wide text-faint uppercase">
            {entry.category}
          </div>
          <Heading className="m-0 text-md font-semibold text-dim">{entry.name}</Heading>
        </div>
        <Badge tone="neutral">Not built</Badge>
      </div>

      <dl className="m-0 space-y-3 text-sm">
        <div>
          <dt className="text-xs tracking-wide text-faint uppercase">Would have</dt>
          <dd className="m-0 text-dim">{entry.what}</dd>
        </div>
        <div>
          <dt className="text-xs tracking-wide text-faint uppercase">Why it is not here</dt>
          <dd className="m-0 text-dim">{entry.why}</dd>
        </div>
        <div>
          <dt className="text-xs tracking-wide text-faint uppercase">Check it</dt>
          <dd className="m-0 font-mono text-xs break-words text-faint">{entry.evidence}</dd>
        </div>
      </dl>
    </article>
  );
}

export function LedgerTable({ entries }: { entries: NotBuiltEntry[] }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {entries.map((entry) => (
        <NotBuiltCard key={entry.name} entry={entry} />
      ))}
    </div>
  );
}
