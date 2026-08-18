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
    readonly kind: "http" | "parse" | "network" | "shape",
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
    in_range: number;
    fees: number;
    lvr_upper_bound: number;
    costs: number;
    moves: number;
  };
  agent: {
    p25: number;
    p50: number;
    p75: number;
    in_range: number;
    fees: number;
    lvr_upper_bound: number;
    costs: number;
    moves: number;
  };
  delta_pp: number;
  ranges_overlap: boolean;
  material: boolean;
  separated: boolean;
  verdict: string;
}

export interface AdvantageArtifact {
  report: string;
  question: string;
  counterfactual: boolean;
  badge: string;
  source: string;
  capital_quote: number;
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
