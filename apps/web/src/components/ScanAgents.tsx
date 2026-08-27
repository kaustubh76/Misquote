import { Badge } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { Heading } from "@/components/Heading";
import { Refusal } from "@/components/Refusal";
import { count, fixed, shortAddress } from "@/lib/format";

/**
 * One agent as a third-party index describes it, and nothing this site measured.
 *
 * ## The one rule this component exists to keep
 *
 * Our four agents render a P25-P75 band replayed over a real pool's history,
 * with the assumption sheet a click away. **These do not, and cannot.** We do
 * not have a stranger's policy, so there is nothing to replay; borrowing
 * 8004scan's score and calling it a quote is exactly the misquote this project
 * is named after.
 *
 * So every number on these rows is prefixed `scan_` in the artifact, every row
 * carries `attributed_to`, and the component renders the attribution rather
 * than treating it as metadata. A third-party number with no source beside it
 * is a number this site is asserting.
 *
 * `registry_report.LISTING_KEYS` forbids performance fields outright on the
 * on-chain survey listings, for the same reason. That whitelist is untouched;
 * this shape is a second one, because the two carry different claims and one
 * list cannot hold both — see `scan8004.SCAN_LISTING_KEYS`.
 */
export interface ScanRow {
  token_id: string;
  name: string | null;
  description: string | null;
  owner_address: string | null;
  created_at: string | null;
  matched_on: string;
  attributed_to: string;
  x402_supported: boolean;
  supported_protocols: string[];
  scan_total_score: number;
  scan_total_feedbacks: number;
  scan_average_score: number;
  scan_rank: number | null;
  scan_network_rank: number | null;
}

/** One agent's own feedback, joined from the walk by token id. */
export interface ScanFeedback {
  token_id: string;
  name: string | null;
  rows: number;
  distinct_raters: number;
  raters: string[];
  tags: Record<string, number>;
  transaction_hashes: string[];
  declared_methods: unknown[];
  latest_block: number | null;
}

export interface ScanCategory {
  available: boolean;
  reason?: string;
  category: string;
  agents: ScanRow[];
  needles: string[];
  matched: number;
  dropped_not_matching: number;
  crowded_out_by_owner_cap: number;
  distinct_owners_matched: number;
  max_per_owner: number;
  attributed_to: string;
  note: string;
}

export interface ProvenSort {
  sorted: boolean;
  reason: string | null;
  monotone: boolean;
  differs_from_unsorted_head: boolean;
  rows?: ScanRow[];
}

export interface ScanLeaderboard {
  available: boolean;
  reason?: string;
  note: string;
  by: Record<string, ProvenSort>;
}

export interface NameCollisions {
  available: boolean;
  reason?: string;
  note: string;
  names: Record<
    string,
    {
      available: boolean;
      search_returned?: number;
      exactly_this_name?: number;
      owners?: string[];
      agents?: ScanRow[];
    }
  >;
}

/**
 * The evidence line under a third-party agent.
 *
 * Feedback count first and score second, and that order is deliberate: a
 * feedback is anchored to a transaction anybody can check, and a score is a
 * number one index computed by a method it does not publish. Ranking the
 * checkable thing above the opaque one is the whole argument of this site,
 * applied to somebody else's data.
 *
 * Zero is rendered rather than hidden. "No feedback" is the single most useful
 * fact about most agents in this registry — 30 of the 31 surfaced across the
 * four categories have none — and a card that draws only the non-zero cases
 * turns an empty registry into a page of agents that all look equally attested.
 */
function Evidence({ row, feedback }: { row: ScanRow; feedback?: ScanFeedback }) {
  const rows = feedback?.rows ?? row.scan_total_feedbacks;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs text-faint">
      <span className={rows > 0 ? "text-ink" : undefined}>
        {rows > 0
          ? `${count(rows)} feedback${rows === 1 ? "" : "s"}` +
            (feedback ? ` from ${count(feedback.distinct_raters)} address${feedback.distinct_raters === 1 ? "" : "es"}` : "")
          : "no feedback, ever"}
      </span>
      <span>score {fixed(row.scan_total_score, 2)}</span>
      {row.x402_supported && <Badge tone="neutral">x402</Badge>}
      {row.supported_protocols.length > 0 && <span>{row.supported_protocols.join(" · ")}</span>}
      {row.owner_address && <span>owner {shortAddress(row.owner_address)}</span>}
    </div>
  );
}

/**
 * The transactions that wrote an agent's feedback.
 *
 * Rendered as hashes rather than as a count, because the count is the claim and
 * the hash is what makes it checkable. This is the difference between a star
 * rating and a reading: one asks to be believed, the other names the row on
 * chain that a reader can go and open.
 */
function Anchors({ feedback }: { feedback: ScanFeedback }) {
  if (feedback.transaction_hashes.length === 0) return null;
  return (
    <div className="mt-1 font-mono text-xs break-all text-faint">
      anchored:{" "}
      {feedback.transaction_hashes.map((tx, i) => (
        <span key={tx}>
          {i > 0 && " · "}
          <a
            href={`https://bscscan.com/tx/${tx}`}
            className="text-faint hover:text-ink"
            rel="noreferrer"
          >
            {shortAddress(tx, 10, 6)}
          </a>
        </span>
      ))}
    </div>
  );
}

function AgentRow({ row, feedback }: { row: ScanRow; feedback?: ScanFeedback }) {
  return (
    <li className="border-t border-line py-3 first:border-t-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-semibold text-ink">{row.name || `Agent #${row.token_id}`}</span>
        <span className="font-mono text-xs text-faint">#{row.token_id}</span>
      </div>
      {row.description && (
        <p className="mt-1 line-clamp-2 text-sm text-muted">{row.description}</p>
      )}
      <Evidence row={row} feedback={feedback} />
      {feedback && <Anchors feedback={feedback} />}
    </li>
  );
}

/**
 * A category's third-party agents, with what the search cost to assemble.
 *
 * `dropped_not_matching` and `crowded_out_by_owner_cap` are rendered rather
 * than kept in the artifact, and both are corrections that would otherwise be
 * invisible:
 *
 * - 8004scan's `search` matches stems, not substrings. `liquidation` and
 *   `liquidity` return the same 311 agents with the same head, so a category
 *   built by trusting the query lists agents that have nothing to do with it.
 *   The dropped count is how many rows failed that check.
 * - Ranked on the index's evidence alone, one address owned all eight
 *   Rebalancing slots — a batch of rarity-tiered cards with one description
 *   template between them. The owner cap is a rendering rule, and what it
 *   suppressed is counted so a thinned category and a thin one do not look
 *   alike.
 */
export function ScanCategoryAgents({
  category,
  // Named for the artifact field it is, rather than for how it reads in JSX.
  // `tests/web/test_artifact_contract.py` checks that a field's declared
  // renderer actually mentions it, and it matches on the leaf name — so a prop
  // called `feedback` would leave `feedback_graph.by_agent` contracted to a
  // file that never says it. The snake_case is the contract showing through.
  by_agent,
}: {
  category: ScanCategory | undefined;
  by_agent?: Record<string, ScanFeedback>;
}) {
  if (!category) return null;
  if (!category.available) {
    return (
      <Refusal
        title="No third-party agents were read for this category"
        reason={category.reason ?? "8004scan did not answer"}
      />
    );
  }

  return (
    <Card>
      <CardHeader
        title="Also on BNB Chain, in this category"
        eyebrow="Third-party · 8004scan"
        aside={<Badge tone="neutral">{count(category.matched)} matched</Badge>}
      />
      <p className="text-sm text-muted">{category.note}</p>

      {category.agents.length === 0 ? (
        <Refusal
          title="The index holds no agent in this category"
          reason={`Searched ${category.needles.join(", ")} and nothing survived the check that a row contains the word it was returned for.`}
        />
      ) : (
        <ul className="mt-4 list-none p-0">
          {category.agents.map((row) => (
            <AgentRow key={row.token_id} row={row} feedback={by_agent?.[row.token_id]} />
          ))}
        </ul>
      )}

      <p className="mt-4 font-mono text-xs text-faint">
        {count(category.matched)} matched across {count(category.distinct_owners_matched)} owners ·{" "}
        {count(category.dropped_not_matching)} dropped for not containing their own search term ·{" "}
        {count(category.crowded_out_by_owner_cap)} crowded out by the {category.max_per_owner}-per-owner
        cap · attributed to {category.attributed_to}
      </p>
    </Card>
  );
}

/**
 * The whole registry's top, and the proof that the ordering was real.
 *
 * `sort_by=star_count` and `sort_by=health_score` are accepted by this API and
 * silently ignored — both answer with the newest-first page, which is a ranking
 * that looks exactly like a ranking. So a leaderboard here is gated on
 * `sorted`, which is true only when the values came back non-increasing *and*
 * the head differs from the head the same query returns unsorted.
 *
 * The result is unflattering and is published anyway: ranked by feedback count,
 * the top of this registry is celebrity-named cards. That is a fact about what
 * a feedback count measures here, and it is the reason this site will not rank
 * its own agents on one.
 */
export function ScanLeaderboardCard({ leaderboard }: { leaderboard: ScanLeaderboard | undefined }) {
  if (!leaderboard) return null;
  if (!leaderboard.available) {
    return (
      <Refusal
        title="No ranking was read"
        reason={leaderboard.reason ?? "8004scan did not answer"}
      />
    );
  }

  return (
    <Card className="mt-4">
      <CardHeader title="The index's own ranking" eyebrow="Proven to have applied" />
      <p className="text-sm text-muted">{leaderboard.note}</p>
      {Object.entries(leaderboard.by).map(([key, proof]) => (
        <div key={key} className="mt-4">
          <Heading className="m-0 font-mono text-xs tracking-wide text-faint uppercase">
            by {key.replace("_", " ")}
          </Heading>
          {!proof.sorted ? (
            <Refusal
              title="This ordering was not published"
              reason={proof.reason ?? "the sort could not be shown to have applied"}
              floor={`monotone: ${proof.monotone} · moved the head: ${proof.differs_from_unsorted_head}`}
            />
          ) : (
            <ul className="mt-2 list-none p-0">
              {(proof.rows ?? []).slice(0, 5).map((row) => (
                <AgentRow key={row.token_id} row={row} />
              ))}
            </ul>
          )}
        </div>
      ))}
    </Card>
  );
}

/**
 * Agents on BSC mainnet carrying our agents' names, owned by strangers.
 *
 * Four requests, and the cheapest strong claim on this page. A registry storing
 * 285,000 free-text names produces collisions by construction — two other
 * Wardens, three other Sentinels — and a marketplace whose users hire by name
 * is quoting the wrong agent. It is also the reason every row this site renders
 * is keyed by token id and owner rather than by the name beside it.
 */
export function NameCollisionsCard({ collisions }: { collisions: NameCollisions | undefined }) {
  if (!collisions?.available) return null;
  const colliding = Object.entries(collisions.names).filter(
    ([, v]) => (v.exactly_this_name ?? 0) > 0,
  );
  if (colliding.length === 0) return null;

  return (
    <Card className="mt-4">
      <CardHeader title="A name is not an identity" eyebrow="Third-party · 8004scan" />
      <p className="text-sm text-muted">{collisions.note}</p>
      <ul className="mt-3 list-none p-0">
        {colliding.map(([name, v]) => (
          <li key={name} className="border-t border-line py-2 first:border-t-0">
            <span className="font-semibold text-ink">{name}</span>
            <span className="ml-2 font-mono text-xs text-faint">
              {count(v.exactly_this_name)} other agent
              {v.exactly_this_name === 1 ? "" : "s"} with exactly this name ·{" "}
              {(v.owners ?? []).map((o) => shortAddress(o)).join(" · ")}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
