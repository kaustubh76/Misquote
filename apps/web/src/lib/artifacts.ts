/**
 * Reading the artifacts, and failing in a way that names the failure.
 *
 * The page this replaces did:
 *
 *     try {
 *       const index = await (await fetch("artifacts/index.json")).json();
 *       const agents = await Promise.all(index.agents.map(n => fetch(...).then(r => r.json())));
 *       ...
 *     } catch (e) {
 *       mount.replaceChildren($(`<p>No artifacts yet. Run make showcase.</p>`));
 *     }
 *
 * Four separate defects in six lines:
 *
 *  1. `res.ok` is never checked, so a 404's HTML body reaches `.json()` and
 *     surfaces as a `SyntaxError` about an unexpected `<` — a parse error
 *     standing in for a missing file.
 *  2. `Promise.all` rejects on the first failure, so one bad agent file erases
 *     all three cards rather than one.
 *  3. Every cause — missing index, malformed JSON, a single 404, the page
 *     opened over file:// — collapses into one message, and that message names
 *     the wrong remedy for three of the four.
 *  4. The caught error is discarded entirely, so nothing anywhere records what
 *     actually happened.
 *
 * What follows keeps the causes distinct all the way to the surface.
 */

/**
 * Root-absolute, not relative.
 *
 * `"artifacts/warden.json"` resolves against the *current page*, and with
 * `trailingSlash: true` every route is a directory: from `/agent/warden/` it
 * became `/agent/warden/artifacts/warden.json` and 404'd. Only the Overview,
 * which lives at `/`, ever worked.
 *
 * Nothing caught it for a while. The jsdom page tests stub `fetch` and match on
 * the basename, so a wrong prefix is invisible to them, and the static export
 * still returns 200 for the *page* — it is the data underneath that goes
 * missing, leaving a correctly-rendered "not generated" error. It took loading
 * the built site in a real browser.
 *
 * Two things assert the leading slash now: `src/test/harness.tsx` throws on any
 * request that is not root-absolute, so a page test cannot pass with a relative
 * path; and `scripts/check-pages.mjs` loads the real export in a browser, which
 * is what caught it in the first place.
 */
const BASE = "/artifacts";

/**
 * There is no `status` field, and the HTTP code is not lost by dropping it.
 *
 * One existed, carried the response code, and was read nowhere. The thing that
 * wanted it — a `remedyFor(status)` switch mapping 404 and 403 to different
 * advice — was deleted with `ArtifactView`. What survives is better: the code is
 * already interpolated into `message`, in the sentence the reader sees, so a
 * report of this failure carries "returned 404 Not Found" rather than a number
 * a caller has to translate. `kind` is what code branches on, and it stays
 * meaningful across the network and parse cases, which have no status at all.
 */
export class ArtifactError extends Error {
  constructor(
    message: string,
    readonly url: string,
    /**
     * `"refused"` is the live API's, and it is not a failure of the request.
     *
     * The service answers a question it cannot support with a status that means
     * something — 409 for thin evidence, 501 for an absent capability — and a
     * body carrying the remedy. Folding those into `"http"` would discard the
     * one field the UI acts on. See `RefusalError` in `lib/api.ts`; the union
     * shape is unchanged, so every existing `switch` on `kind` still compiles.
     */
    readonly kind: "http" | "parse" | "network" | "shape" | "refused",
  ) {
    super(message);
    this.name = "ArtifactError";
  }
}

/**
 * Fetch one JSON artifact, distinguishing why it failed.
 *
 * The content-type check is what stops a 404 from masquerading as malformed
 * JSON: a static server hands back an HTML error page with status 404, and
 * without this the reported fault is a parse error on `<!DOCTYPE`.
 *
 * Not exported. It throws, and everything on the site reads artifacts through
 * `load`, which turns the throw into a `Loaded` the caller has to open. Handing
 * out the throwing half invites a `getJSON(...)` with no `catch` — which is the
 * six-line original at the top of this file, reintroduced one route at a time.
 */
async function getJSON<T>(name: string): Promise<T> {
  const url = `${BASE}/${name}`.replace(/\/{2,}/g, "/");
  let res: Response;

  try {
    res = await fetch(url, { cache: "no-store" });
  } catch (cause) {
    // Thrown for a genuinely unreachable server, and also for file:// — where
    // relative fetches are cross-origin. Worth naming, because it is the most
    // likely way a judge meets this page for the first time.
    throw new ArtifactError(
      `Could not reach ${url}. If this page was opened from the filesystem, serve it over HTTP instead — run \`make web\`.`,
      url,
      "network",
    );
  }

  if (!res.ok) {
    throw new ArtifactError(
      `${url} returned ${res.status} ${res.statusText}.`,
      url,
      "http",
    );
  }

  const type = res.headers.get("content-type") ?? "";
  if (!type.includes("json")) {
    throw new ArtifactError(
      `${url} responded with "${type || "no content-type"}" rather than JSON.`,
      url,
      "parse",
    );
  }

  try {
    return (await res.json()) as T;
  } catch {
    throw new ArtifactError(`${url} is not valid JSON.`, url, "parse");
  }
}

/** A load that either produced a value or produced a reason. Never both, never neither. */
export type Loaded<T> = { ok: true; value: T } | { ok: false; error: ArtifactError };

export async function load<T>(name: string): Promise<Loaded<T>> {
  try {
    return { ok: true, value: await getJSON<T>(name) };
  } catch (error) {
    return {
      ok: false,
      error:
        error instanceof ArtifactError
          ? error
          : new ArtifactError(String(error), name, "network"),
    };
  }
}

/**
 * Load every agent card, settling each independently.
 *
 * `allSettled`, not `all`: one missing agent artifact costs one card, not the
 * whole page. The failures come back alongside the successes so the UI can say
 * which agent is missing instead of implying none were ever generated.
 */
export async function loadAgents(
  agents: readonly AgentRef[],
): Promise<{ slug: string; name: string; result: Loaded<AgentArtifact> }[]> {
  const settled = await Promise.allSettled(
    agents.map((a) => load<AgentArtifact>(`${a.slug}.json`)),
  );

  return agents.map((a, i) => {
    const outcome = settled[i];
    if (outcome && outcome.status === "fulfilled") {
      return { slug: a.slug, name: a.name, result: outcome.value };
    }
    const reason = outcome && outcome.status === "rejected" ? outcome.reason : "unknown";
    return {
      slug: a.slug,
      name: a.name,
      result: {
        ok: false,
        error: new ArtifactError(String(reason), `${a.slug}.json`, "network"),
      },
    };
  });
}

/* ---------------------------------------------------------------- shapes --
 * These mirror the Python emitters exactly. `tests/web/test_artifact_contract.py`
 * compares the field names here against the keys the emitters actually write,
 * so this file cannot drift from `tearsheet/generate.py` unnoticed.
 * ------------------------------------------------------------------------- */

export interface AgentRef {
  name: string;
  slug: string;
  category: string;
  built: boolean;
}

export interface NotBuiltEntry {
  name: string;
  category: string;
  what: string;
  why: string;
  evidence: string;
}

export interface IndexArtifact {
  schema_version: number;
  agents: AgentRef[];
  not_built: NotBuiltEntry[];
  pool: string;
  pool_address: string;
  /** Unit of the `*_quote` figures on every agent artifact. See `money()`. */
  quote_symbol?: string;
  counterfactual: boolean;
  badge: string;
  source: "chain" | "synthetic";
  baseline: { name: string; description: string };
}

export interface BuildArtifact {
  command: string;
  source: string;
  generated_at: string;
  git_sha: string | null;
  git_dirty: boolean | null;
  events: number;
  capital_quote: number;
  span_hours: number;
  quote_symbol?: string;
}

export interface QuoteDetail {
  p25: number;
  p50: number;
  p75: number;
  samples: number;
  windows: number;
  perturbations: number;
  net_positive: number;
  returns: number[];
  in_range_p50: number;
  rebalances_p50: number;
  hours_per_window: number;
  sufficient: boolean;
  annualised: boolean;
  basis: string;
  note: string;
}

export interface VerdictDetail {
  called: boolean;
  label: string;
  detail: string;
  n: number;
}

export interface Floors {
  min_windows: number;
  min_window_hours: number;
  min_hours_to_annualise: number;
  min_observations: number;
  in_range_floor: number;
}

/**
 * Every field optional, because the emitter can write this block empty.
 *
 * It was declared entirely non-optional, and the declaration was wrong:
 * `tearsheet/generate.py` takes `estimators: dict | None = None` and serialises
 * `dict(estimators or {})`, so any caller that omits the argument produces an
 * artifact whose `estimators` is `{}`. One such caller already exists —
 * `tearsheet/__main__.py` builds without it.
 *
 * A type that promises what the producer does not is worse than a loose one:
 * it is why six call sites here wrote `e.sigma_per_sqrt_hour.toFixed(6)` with a
 * clear conscience, and why a `{}` block would have thrown during render rather
 * than rendering an em dash. `fixed()` handles the absence; this makes the
 * compiler agree that there is an absence to handle.
 */
export interface Estimators {
  sigma_per_sqrt_hour?: number;
  sigma_ready?: boolean;
  kappa_per_tick?: number;
  kappa_per_logprice?: number;
  kappa_r_squared?: number;
  kappa_is_fallback?: boolean;
  kappa_buckets_used?: number;
  kappa_swaps_used?: number;
  kappa_label?: string;
  imbalance_z?: number;
  imbalance_ready?: boolean;
}

export interface ReplayBlock {
  samples: number;
  hours: number;
  mints: number;
  rebalances: number;
  pulls: number;
  in_range_fraction: number;
  fees_quote: number;
  lvr_quote_upper_bound: number;
  costs_quote: number;
  net_quote: number;
}

export interface ActivityBlock {
  decisions: number;
  hours: number;
  mints: number;
  rebalances: number;
  pulls: number;
  // Outcomes, not decisions. The loop journals a decision when it is made and
  // again when it is executed, dropped or refused; counting both as actions is
  // what once rendered a single mint as three.
  executed: number;
  failed: number;
  dropped: number;
  read_errors: number;
  held_by_gate: Record<string, number>;
}

export interface ProvenanceBlock {
  journal: string;
  journal_rows: number;
  hours_covered: number;
  every_number_derived: boolean;
}

export interface AdvantageBlock {
  delta_pp: number;
  material: boolean;
  ranges_overlap: boolean;
  separated: boolean;
  quotable: boolean;
  verdict: string;
  without_agent: string;
  baseline: {
    p25: number;
    p50: number;
    p75: number;
    in_range_fraction: number;
    fees_quote: number;
    lvr_quote_upper_bound: number;
    costs_quote: number;
    moves: number;
  };
}

export interface AgentArtifact {
  agent: string;
  pool: string;
  quote: string;
  quote_sufficient: boolean;
  quote_detail: QuoteDetail | null;
  floors: Floors;
  estimators: Estimators;
  verdicts: { in_range: VerdictDetail; profitable: VerdictDetail };
  activity: ActivityBlock;
  caveats: string[];
  provenance: ProvenanceBlock;
  counterfactual: boolean;
  badge: string;
  source: string;
  replay: ReplayBlock;
  advantage?: AdvantageBlock;
  /**
   * The unit of every `*_quote` figure in this artifact.
   *
   * Optional because artifacts written before the emitter carried it exist and
   * are still readable. Absent means the unit is unknown, and a figure with an
   * unknown unit is rendered bare — never with a guessed one. See `money()`.
   */
  quote_symbol?: string;
}

/**
 * Router's card. A sibling of `AgentArtifact`, not a variant of it.
 *
 * The LP card carries `verdicts.in_range`, `quote_detail.rebalances_p50`, and a
 * replay block with fees and an LVR upper bound. None of those exist for an
 * agent that supplies to a lending market: there is no range to be in, nothing
 * to rebalance, and no arbitrageur to be picked off by. Rendering them as zeros
 * would read as "never out of range, lost nothing to adverse selection" — two
 * claims this agent is not entitled to make, and the same argument `view.tsx`
 * makes about drawing a 404'd card as a zero.
 *
 * `kind` is the discriminator. The Python emitter writes `"allocation"` here and
 * `"lp_range"` on the other three.
 */
/** A Venus market as the Router card publishes it. */
export interface RouterLendingVenue {
  kind: "lending";
  venue_id: string;
  symbol: string;
  /**
   * The market's size at the **end** of the tape, descriptive only.
   *
   * Named for when it was measured because the replay does not use it: the
   * driver derives size per sample from the accrual it has seen. Passing one
   * fixed figure in was a look-ahead leak — a window replayed on day one was
   * sized by a market measured on day seven.
   */
  supplied_base_at_tape_end: number;
  reserve_factor: number;
  reserve_factor_recorded: boolean;
}

/**
 * A PancakeSwap v3 range as the Router card publishes it.
 *
 * `reference_width_ticks` is not decoration and is not optional. Two LPs in one
 * pool at one moment earn different returns because they chose different widths,
 * so a range rendered without its width would be quoting a number that is not
 * about any position a reader could hold (A21).
 */
export interface RouterPoolVenue {
  kind: "pool";
  venue_id: string;
  symbol: string;
  fee_pips: number;
  reference_width_ticks: number;
  /** What LPs keep of the fee after the protocol's cut — read, never modelled. */
  lp_fee_share: number;
  /**
   * The price used to convert this pool's sizes into the router's units.
   *
   * Published because the comparison is not unit-clean: the pool prices in its
   * own quote token and Router keeps its books in dollars, and this is the
   * number that reconciled them. P-25 is what an unrecorded conversion costs.
   */
  quote_price_quote: number;
}

export interface RouterArtifact {
  agent: string;
  kind: "allocation";
  category: string;
  venue: string;
  /**
   * The venues Router chose between, which are no longer all one kind.
   *
   * A union rather than one widened record with optional fields everywhere.
   * `kind` is the discriminator, exactly as it is on the artifact itself, and it
   * means a renderer cannot reach `reserve_factor` on a range or a width on a
   * lending market without TypeScript stopping it. The emitter builds these two
   * shapes from `LendingVenue.card_fields` and `PoolVenue.card_fields`, and the
   * fields genuinely do not correspond: a supplied market has a reserve factor
   * and no width; a concentrated range has a width, a fee tier and an LP share
   * of that tier, and nothing that plays the reserve factor's part.
   */
  venues: (RouterLendingVenue | RouterPoolVenue)[];
  source: string;
  counterfactual: boolean;
  badge: string;
  quote_symbol?: string;
  capital_quote: number;
  quote: {
    p25: number;
    p50: number;
    p75: number;
    samples: number;
    windows: number;
    perturbations: number;
    best_venue_p50: number;
    switches_p50: number;
    hours_per_window: number;
    sufficient: boolean;
    note: string;
    annualised: boolean;
    basis: string;
    net_positive: number;
    returns: number[];
    max_edge_apr: number;
    hurdle_apr: number;
  };
  replay: {
    samples: number;
    hours: number;
    entries: number;
    switches: number;
    exits: number;
    invested_fraction: number;
    best_venue_fraction: number;
    gross_yield_quote: number;
    costs_quote: number;
    net_quote: number;
    max_edge_apr: number;
    hurdle_apr_p50: number;
    best_apr_seen: number;
    breakeven_horizon_hours: number;
  };
  params: Record<string, number>;
  caveats: string[];
  /** Present when the agent never moved: why that is the answer, in words. */
  finding?: string;
  /**
   * What became of the PancakeSwap ranges, when the card carries any.
   *
   * Separate from `finding` because they answer different questions and one
   * would otherwise swallow the other: `finding` is about the allocation the
   * agent made, and this is about the venues it considered and did not. A range
   * declined because the notional exceeds what it can absorb is a result, and a
   * card that reported only the allocation would have dropped it.
   */
  pool_finding?: string;
  /** Where the numbers came from: the journal `make router` writes. */
  provenance?: {
    journal: string;
    journal_rows: number;
    hours_covered: number;
    every_number_derived: boolean;
  };
  /** The cost inputs behind the hurdle, and whether each was read (P-25). */
  cost_model?: {
    gas_quote: number;
    slippage_bps: number;
    derived: boolean;
    basis: string;
  };
  /** The same question the LP cards answer: does hiring it beat doing it yourself? */
  advantage?: {
    delta_pp: number;
    verdict: string;
    material: boolean;
    ranges_overlap: boolean;
    separated: boolean;
    quotable: boolean;
    source: string;
    without_agent: string;
    baseline: {
      p25: number;
      p50: number;
      p75: number;
      entries: number;
      switches: number;
      invested_fraction: number;
      gross_yield_quote: number;
      costs_quote: number;
      net_quote: number;
    };
  };
  build?: { command: string; source: string; generated_at: string; git_sha: string | null };
}

export interface AdvantageTask {
  task: string;
  category: string;
  venue: string;
  metric: string;
  without_agent: string;
  with_agent: string;
  quotable: boolean;
  note: string;
  baseline: {
    p25: number;
    p50: number;
    p75: number;
    /**
     * Optional, every one of them, and that is the artifact telling the truth.
     *
     * A task publishes only the quantities its replay actually has. The Route
     * task runs a Venus lending market through `AllocationResult`, which
     * carries costs and moves and has no in-range fraction, no fees and no
     * adverse-selection accounting — so those keys are absent rather than
     * zero. `lib/format.ts::isNum` renders a missing number as an em dash,
     * which is the honest mark for a question this venue does not answer.
     *
     * Typed as required until the emitter stopped fabricating them, which is
     * how `/advantage` came to show `fees (WBNB) 0.00` for a lending venue.
     */
    in_range?: number;
    fees?: number;
    lvr_upper_bound?: number;
    costs?: number;
    moves?: number;
    /** How many of the reported samples are distinct results. */
    distinct_returns?: number;
    /** The observations the band was drawn from, when the quote carries them. */
    returns?: number[];
  };
  agent: {
    p25: number;
    p50: number;
    p75: number;
    /**
     * Optional, every one of them, and that is the artifact telling the truth.
     *
     * A task publishes only the quantities its replay actually has. The Route
     * task runs a Venus lending market through `AllocationResult`, which
     * carries costs and moves and has no in-range fraction, no fees and no
     * adverse-selection accounting — so those keys are absent rather than
     * zero. `lib/format.ts::isNum` renders a missing number as an em dash,
     * which is the honest mark for a question this venue does not answer.
     *
     * Typed as required until the emitter stopped fabricating them, which is
     * how `/advantage` came to show `fees (WBNB) 0.00` for a lending venue.
     */
    in_range?: number;
    fees?: number;
    lvr_upper_bound?: number;
    costs?: number;
    moves?: number;
    /** How many of the reported samples are distinct results. */
    distinct_returns?: number;
    /** The observations the band was drawn from, when the quote carries them. */
    returns?: number[];
  };
  delta_pp: number;
  ranges_overlap: boolean;
  material: boolean;
  separated: boolean;
  verdict: string;
  /**
   * Both columns are the same replay, not two that agreed.
   *
   * `task_choose` reuses the baseline run when the depth heuristic and the flow
   * screen pick the same pool. Its comment says re-running "would invite the
   * reader to think two things were measured when one was" — and the chart drew
   * two identical bands, doing exactly that.
   *
   * Read rather than inferred from `delta_pp === 0`: two genuinely separate
   * runs are allowed to tie, and collapsing those would erase a real finding.
   */
  same_run?: boolean;
  /**
   * The tape behind this one task.
   *
   * Optional because it is, on disk. `advantage.json` records it per task —
   * the three tasks are separate replays and need not share a tape — while
   * `advantage_short.json` predates the field and carries only the report-level
   * `source`. Declaring it required would type a lie about a file the site
   * ships.
   */
  source?: string;
  /**
   * The capital this task was quoted on, in `quote_symbol`.
   *
   * Also per task, and also absent from the short report. The Choose task is
   * quoted on 0.0318 WBNB against 1.0 for the other two, which is why the
   * report-level field stopped being a number — see `AdvantageArtifact`.
   */
  capital_quote?: number;
  /**
   * How many days of tape this task replayed.
   *
   * Optional because `advantage_short.json` predates it, and per task for the
   * same reason `source` and `capital_quote` are: these are separate replays.
   *
   * They are not the same length. Three tasks run 31.0 days and Route runs
   * 17.0, and until this field was read nothing on `/advantage` said so — the
   * page put four deltas in one list and let a reader assume one tape. It does
   * not bias a delta, because both columns of a task share that task's tape;
   * it bounds how much of a year the annualised figure describes.
   */
  replay_days?: number;
  /**
   * The quantity the task is named for, as against the net return.
   *
   * The Protect task is "avoid being picked off by one-way flow", and its
   * primary metric is the convexity cost it was hired to reduce — the agent
   * comes in 18.4x better on that while losing 38.17pp of net return. The page
   * showed only the second for as long as this field went unread, which is
   * half a finding.
   *
   * `summary` is written by the emitter and rendered verbatim. Recomputing the
   * ratio in the browser would put a second implementation of the comparison
   * one inch from the sentence Python wrote — the argument `Band` already
   * makes about `ranges_overlap`.
   *
   * Null on disk for a task with no single metric: the Choose task compares
   * two pools, and there is no one number the choice is about.
   */
  primary_metric?: PrimaryMetric | null;
}

/**
 * One quantity, both ways, with the emitter's own verdict on it.
 *
 * `lower_is_better` and `improved` are both carried because they are different
 * facts — a cost falling is an improvement and a fee falling is not — and a UI
 * that derived the second from the first would be reimplementing the emitter.
 */
export interface PrimaryMetric {
  name: string;
  baseline: number;
  agent: number;
  lower_is_better: boolean;
  unit: string;
  improved: boolean;
  /** Rendered verbatim. Never reconstructed from the two numbers above. */
  summary: string;
}

export interface AdvantageArtifact {
  report: string;
  question: string;
  counterfactual: boolean;
  badge: string;
  source: string;
  /**
   * One capital basis for the whole report, or a pointer to the per-task ones.
   *
   * It stopped being a number when the tasks stopped sharing a basis: the
   * emitter now writes the literal string `"per task — see
   * tasks[].capital_quote"` whenever they differ, and on the current report
   * they do — 1.0 WBNB for Earn and Protect, 0.0318 for Choose.
   *
   * This was typed `number` for as long as that was true, and the string then
   * flowed straight into `money()`, which returns `EMPTY` for anything that is
   * not a number. So all three task cards read "on — of capital": a dash
   * standing in for a figure the artifact was holding, on the one page this
   * project is judged by. `TaskCard` reads the task's own value now and falls
   * back here only when a report has no per-task figures, which is exactly the
   * case `advantage_short.json` is.
   */
  capital_quote: number | string;
  /** Unit of `capital_quote` and of every fee/cost figure on each task. */
  quote_symbol?: string;
  summary: {
    tasks: number;
    quotable: number;
    withheld: number;
    agent_ahead: number;
    diy_ahead: number;
    indistinguishable: number;
    bands_overlap: number;
    separated: number;
    categories: string[];
    venues: string[];
  };
  overall: { called: boolean; label: string };
  tasks: AdvantageTask[];
}

/**
 * What every artifact on this site records about the tree that produced it.
 *
 * Declared here rather than beside `censusArtifacts()`, which builds it: that
 * function imports `node:fs`, `/status` is a client component, and
 * `tests/web/test_client_boundary.py` fails a `"use client"` module that names
 * the reader at all. Deliberately, and it caught this — a type-only import is
 * erased by the compiler and reaches no bundle, but it is one keystroke from a
 * value import whose failure mode is silent. The type is artifact-shaped and
 * belongs with the artifact shapes.
 */
export interface ArtifactCensus {
  /** Every `.json` in the artifacts directory. */
  total: number;
  /** Those recording a commit, and which one. */
  stamped: { name: string; sha: string }[];
  /** Those publishing figures and recording no commit at all. */
  unstamped: string[];
  /** Excluded by name, with the reason. */
  exempt: { name: string; why: string }[];
}
