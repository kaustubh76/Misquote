import { Badge } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { Heading } from "@/components/Heading";
import { Refusal } from "@/components/Refusal";
import type { ScanRow } from "@/components/ScanAgents";
import { count, shortAddress } from "@/lib/format";

/**
 * Our own four agents, read back from an index nobody here runs.
 *
 * ## Why this block had to exist
 *
 * Everything else in the `ours` section is self-reported. We ran
 * `register_identity.py`, it wrote `vetting/identity/97.json`, and the page
 * renders that file. It is honest, and it is unfalsifiable in the literal
 * sense: nothing else in the artifact could contradict it. A marketplace that
 * measures four hundred strangers and takes its own word for its own row is
 * measuring other people.
 *
 * 8004scan indexes BSC testnet, our four are in it, and now the two readings
 * either agree — which is evidence — or they do not, which is a finding. Same
 * rule the whole `scan8004` module runs on, turned around to point here.
 *
 * ## The zeros are the point, not an omission
 *
 * The index sees zero feedbacks, zero score and an empty protocol list on all
 * four of ours. None of that is an indexing error: it is the index correctly
 * reporting evidence nobody ever produced and fields our cards never filled.
 * They are rendered in the same list as the agreements, in the warm tone this
 * site uses for "evidence exists and fell short", because publishing the
 * corroboration and quietly dropping the empty fields would be the misquote
 * with our own name on it.
 */
export interface OursAsIndexed {
  available: boolean;
  reason?: string;
  owner: string;
  population: number | null;
  indexed_contract: string | null;
  agents: ScanRow[];
  note: string;
}

export interface OursCrossCheck {
  available: boolean;
  reason?: string;
  matched: number;
  recorded: number;
  indexed: number;
  recorded_only: string[];
  indexed_only: string[];
  same_contract: boolean;
  agreements: { token_id: number; field: string; ours: unknown; theirs: unknown }[];
  disagreements: { token_id: number; field: string; ours: unknown; theirs: unknown }[];
  honest_negatives: { token_id: number; field: string; theirs: unknown; note: string }[];
  note: string;
}

/** What a testnet zero is a zero out of. */
export interface TestnetCounts {
  available: boolean;
  baseline?: number;
}

function Field({ children, tone }: { children: React.ReactNode; tone: "ok" | "warn" | "bad" }) {
  const border =
    tone === "bad"
      ? "border-warn-line bg-warn-bg/40"
      : tone === "warn"
        ? "border-line-strong"
        : "border-line";
  return <li className={`border-t py-2 first:border-t-0 ${border}`}>{children}</li>;
}

export function IndexedAgreement({
  indexed,
  cross,
  testnet,
}: {
  indexed: OursAsIndexed | undefined;
  cross: OursCrossCheck | undefined;
  testnet?: TestnetCounts;
}) {
  if (!indexed || !cross) return null;
  if (!indexed.available || !cross.available) {
    return (
      <Refusal
        title="Our own registrations were not read back from any index"
        reason={indexed.reason ?? cross.reason ?? "8004scan did not answer"}
      />
    );
  }

  return (
    <Card className="mt-4">
      <CardHeader
        title="Our four, as a stranger's index sees them"
        eyebrow="Independent · 8004scan"
        aside={
          <Badge tone={cross.same_contract ? "neutral" : "warn"}>
            {cross.same_contract ? "Same registry" : "Different registry"}
          </Badge>
        }
      />
      <p className="text-sm text-muted">{cross.note}</p>

      <ul className="mt-4 list-none p-0">
        {indexed.agents.map((row) => (
          <Field key={row.token_id} tone="ok">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-semibold text-ink">{row.name}</span>
              <span className="font-mono text-xs text-faint">
                #{row.token_id} · owner {shortAddress(row.owner_address ?? indexed.owner)}
              </span>
            </div>
          </Field>
        ))}
      </ul>

      <p className="mt-3 font-mono text-xs text-faint">
        {count(cross.matched)} of {count(cross.recorded)} recorded registrations found in an index of{" "}
        {count(indexed.population)} testnet agents · {count(cross.agreements.length)} fields agree ·{" "}
        {count(cross.disagreements.length)} disagree
        {cross.recorded_only.length > 0 && ` · we claim ${count(cross.recorded_only.length)} the index has never seen`}
        {cross.indexed_only.length > 0 && ` · the index holds ${count(cross.indexed_only.length)} we do not record`}
        {indexed.indexed_contract && ` · registry ${shortAddress(indexed.indexed_contract)}`}
      </p>

      {cross.disagreements.length > 0 && (
        <ul className="mt-4 list-none p-0">
          {cross.disagreements.map((d) => (
            <Field key={`${d.token_id}-${d.field}`} tone="bad">
              <span className="font-mono text-xs">
                #{d.token_id} {d.field}: we say {String(d.ours)}, the index says {String(d.theirs)}
              </span>
            </Field>
          ))}
        </ul>
      )}

      {cross.honest_negatives.length > 0 && (
        <div className="mt-5">
          <Heading className="m-0 font-mono text-xs tracking-wide text-faint uppercase">
            What the index does not find
          </Heading>
          <p className="mt-1 text-sm text-muted">
            Held to the same bar this site holds{" "}
            {testnet?.available ? count(testnet.baseline) : "every other"} agent to.
          </p>
          <ul className="mt-2 list-none p-0">
            {[...new Map(cross.honest_negatives.map((n) => [n.field, n])).values()].map((n) => (
              <Field key={n.field} tone="warn">
                <span className="font-mono text-xs text-ink">{n.field}</span>
                <p className="mt-1 text-sm text-muted">{n.note}</p>
              </Field>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
