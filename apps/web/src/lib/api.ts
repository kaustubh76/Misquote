/**
 * Reaching the live API, and knowing when not to.
 *
 * `artifacts.ts` fetches files the emitters wrote. This fetches answers a
 * running service computed — a wallet's positions, a registry search, what the
 * tape holds right now — and the two have different failure modes, which is why
 * this is a separate module rather than a fifth branch inside `getJSON`.
 *
 * ## The base URL is data, not a build flag
 *
 * The site is a static export. `NEXT_PUBLIC_*` bakes at build time, so a
 * baked-in origin would mean rebuilding the export to point it at a different
 * backend. Instead `/artifacts/api.json` carries it, which is itself an
 * artifact: served by the same route as every other one, counted by the
 * provenance census, and — because the path is already root-absolute under
 * `/artifacts/` — reachable without carving an exception into
 * `src/test/harness.tsx`.
 *
 * `base: null` is the ordinary state and must not fall back to the site origin.
 * There is no API at the export's root, and requesting one would 404.
 */
import { ArtifactError, load } from "@/lib/artifacts";
import { scenarioResponse } from "@/lib/scenario";

/**
 * A refusal is an answer, and it is not an error.
 *
 * The service returns `{detail: {error, remedy, available, note}}` with a status
 * that means something specific — 409 for evidence that cannot support the
 * question, 501 for a capability that does not exist, 503 for "nothing was
 * asked". Routed through `ArtifactError` those all collapse to `kind: "http"`
 * and the message "returned 409 Conflict", throwing away the remedy the backend
 * went to the trouble of naming.
 *
 * `kind` stays the discriminator so the `Loaded` union is unchanged in shape;
 * `instanceof` narrows to the extra fields.
 */
export class RefusalError extends ArtifactError {
  constructor(
    message: string,
    url: string,
    readonly status: number,
    readonly remedy: string,
    readonly available?: string[],
    readonly note?: string,
  ) {
    super(message, url, "refused");
    this.name = "RefusalError";
  }
}

export interface ApiConfig {
  base: string | null;
  routes: Record<string, string>;
}

let cached: ApiConfig | null | undefined;

/**
 * The configured API origin, or null.
 *
 * Memoised for the page's lifetime rather than per call: every live component
 * would otherwise refetch the same tiny file, and the answer cannot change
 * without a reload. `window.__MISQUOTE_API__` overrides it, which is how a demo
 * repoints a built export without rebuilding or redeploying anything.
 */
/**
 * How long to wait on a sleeping instance before giving up.
 *
 * Long enough to cover a cold start on a free plan — measured around fifty
 * seconds — and short enough that a visitor is told something rather than left
 * watching a spinner with no end.
 */
const WAKE_MS = 70_000;

export async function apiBase(): Promise<string | null> {
  const injected = (globalThis as { __MISQUOTE_API__?: string }).__MISQUOTE_API__;
  if (injected) return injected.replace(/\/+$/, "");

  if (cached !== undefined) return cached?.base ?? null;

  const result = await load<ApiConfig>("api.json");
  cached = result.ok ? result.value : null;
  return cached?.base ?? null;
}

/** Which source answered. Rendered, never inferred — see `loadLive`. */
/**
 * Which of three things answered.
 *
 * `simulated` is derived from *where* the answer came from — a scenario file
 * selected by the URL — and never from what came back, which is what makes it
 * impossible to get wrong. See `lib/scenario.ts`.
 */
export type Source = "live" | "artifact" | "simulated";

export type Live<T> =
  | { ok: true; value: T; source: Source }
  | { ok: false; error: ArtifactError };

function refusalFrom(url: string, status: number, body: unknown): RefusalError | null {
  const detail = (body as { detail?: Record<string, unknown> })?.detail;
  if (!detail || typeof detail.error !== "string") return null;

  return new RefusalError(
    detail.error,
    url,
    status,
    typeof detail.remedy === "string" ? detail.remedy : "",
    Array.isArray(detail.available) ? (detail.available as string[]) : undefined,
    typeof detail.note === "string" ? detail.note : undefined,
  );
}

/**
 * Send something, with the same scenario short-circuit `loadLive` has.
 *
 * ## Why this exists, which is a defect rather than a feature request
 *
 * `scenarioResponse` was reachable from exactly one place — `loadLive` — and the
 * flagship flow does not read, it posts. `app/quote/view.tsx`'s `enqueue` called
 * `apiBase()` and then a raw `fetch`, **below** the short-circuit, so
 * `scenarios/quote-thin-tape.json` could never match: its only key is
 * `"POST /quote"`, and the only code that ever passed that string to `loadLive`
 * was a unit test.
 *
 * The consequence was worse than a dead fixture. Under
 * `?scenario=quote-thin-tape` the page showed the simulation banner and then
 * issued a **real** request to the live API — a page saying "simulated" while
 * talking to production, which is the one thing `scenario.ts`'s four rules exist
 * to prevent.
 *
 * ## Deliberately not a `fallback`
 *
 * `loadLive` can fall back to a recorded artifact because a read has a
 * last-known-good. A submission does not: replaying a stale `202` would hand back
 * a job id that was never queued and a poller that will never resolve. So a
 * failure here is terminal, and the caller renders it.
 */
export async function postLive<T>(path: string, body: unknown): Promise<Live<T>> {
  // Same ordering as `loadLive`, and for the same reason: above `apiBase()`, so
  // under a scenario no request is issued at all.
  const recorded = await scenarioResponse(path);
  if (recorded) {
    const refusal = refusalFrom(path, recorded.status, recorded.body);
    if (refusal) return { ok: false, error: refusal };
    return { ok: true, value: recorded.body as T, source: "simulated" };
  }

  const base = await apiBase();
  if (!base) {
    return {
      ok: false,
      error: new ArtifactError(
        "No live API is configured, and a submission has no precomputed fallback.",
        path,
        "network",
      ),
    };
  }

  const url = `${base}${path.replace(/^POST /, "")}`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await res.json().catch(() => null);

    if (res.ok || res.status === 202) {
      return { ok: true, value: payload as T, source: "live" };
    }
    const refusal = refusalFrom(url, res.status, payload);
    if (refusal) return { ok: false, error: refusal };
    return {
      ok: false,
      error: new ArtifactError(`${url} answered ${res.status}.`, url, "network"),
    };
  } catch {
    return {
      ok: false,
      error: new ArtifactError(`${url} could not be reached.`, url, "network"),
    };
  }
}

/**
 * Ask the API, and fall back to the artifact — but not for every failure.
 *
 * **The rule: fall back on `network` and on 5xx. Never on `refused`.**
 *
 * A refusal is the service answering. Quietly substituting a precomputed
 * snapshot for "the tape cannot support this quote" would replace a considered
 * no with a stale yes, at the same URL, with nothing saying which happened —
 * which is the failure this repository is named after. A 5xx or an unreachable
 * host is different: nothing was answered, so the snapshot is the best available
 * truth and is labelled as such.
 *
 * `source` is returned rather than inferred so the UI can say which it got.
 */
export async function loadLive<T>(
  path: string,
  options: {
    fallback?: string;
    /**
     * Pick this call's answer out of a fallback artifact that holds several.
     *
     * Returning `undefined` means the artifact has nothing recorded for this
     * subject, which is a miss rather than an empty result — see the call site
     * below for why those must not be the same thing.
     */
    select?: (artifact: unknown) => unknown;
  } = {},
): Promise<Live<T>> {
  // Before `apiBase()`, and that ordering is the guarantee rather than an
  // optimisation: under a scenario **no request is issued at all**, so a
  // simulated answer cannot arrive by the route a live one arrives by. See
  // `lib/scenario.ts` for the other three things that stop it masquerading.
  const recorded = await scenarioResponse(path);
  if (recorded) {
    // A scenario may refuse, and its refusal is terminal exactly as a live
    // one is — no fallback, no snapshot. The refusal states are the ones most
    // worth being able to show; a scenario that could only succeed would be a
    // demo of the happy path.
    const refusal = refusalFrom(path, recorded.status, recorded.body);
    if (refusal) return { ok: false, error: refusal };
    return { ok: true, value: recorded.body as T, source: "simulated" };
  }

  const base = await apiBase();

  if (base) {
    const url = `${base}${path}`;
    try {
      // The API sleeps. It is on a free plan that spins down when idle, and the
      // next request pays the boot — measured around fifty seconds. With no
      // timeout a visitor watched "Reading…" for a minute with nothing to say
      // whether it was working, and `AbortSignal.timeout` is not available in
      // every runtime this file is parsed in, so it is fetched defensively.
      const res = await fetch(url, {
        cache: "no-store",
        ...(typeof AbortSignal !== "undefined" && "timeout" in AbortSignal
          ? { signal: AbortSignal.timeout(WAKE_MS) }
          : {}),
      });

      if (res.ok) {
        return { ok: true, value: (await res.json()) as T, source: "live" };
      }

      // A refusal is terminal. Read the body before deciding, because that is
      // where the remedy is.
      //
      // `Math.floor(status / 100) === 5` rather than `status >= 500`, and the
      // reason is a guard rather than taste: `500` is a real artifact value —
      // it is the `fee_pips` of the target pool — so
      // `test_no_artifact_number_is_hardcoded_in_the_ui` flags the literal, and
      // it is right to. Adding 500 to that test's undistinctive list to quiet
      // this would blind it to a genuinely hardcoded fee tier. The class check
      // says "5xx", which is what is meant anyway.
      const body = await res.json().catch(() => null);
      const refusal = refusalFrom(url, res.status, body);
      const serverError = Math.floor(res.status / 100) === 5;
      if (refusal && !serverError) return { ok: false, error: refusal };
    } catch {
      // Unreachable. Falls through to the artifact below.
    }
  }

  if (!options.fallback) {
    return {
      ok: false,
      error: new ArtifactError(
        base
          ? `The API at ${base} did not answer ${path}, and this view has no precomputed fallback.`
          : `No live API is configured, and this view has no precomputed fallback.`,
        `${base ?? ""}${path}`,
        "network",
      ),
    };
  }

  const snapshot = await load<unknown>(options.fallback);
  if (!snapshot.ok) return { ok: false, error: snapshot.error };

  // `select` exists because one artifact can answer for several subjects.
  //
  // `journal.json` holds every agent that has ever run, keyed by name, while
  // `/journal/{agent}` answers about one. Without this the choice was to emit
  // one artifact per agent — more files, each needing its own contract entry,
  // all to avoid a property lookup — or to have the caller reimplement the
  // fallback branch. Neither is better than a selector.
  //
  // A `select` that finds nothing is a **miss**, not an empty answer. The
  // artifact holding no entry for this agent is the same fact the API states
  // when it refuses: "Either this agent has never run, or the name is not one
  // of ours. Both are absences and neither is an empty journal."
  const picked = options.select ? options.select(snapshot.value) : snapshot.value;
  if (picked === undefined || picked === null) {
    return {
      ok: false,
      error: new ArtifactError(
        `${options.fallback} holds no recorded answer for ${path}.`,
        `/artifacts/${options.fallback}`,
        "shape",
      ),
    };
  }
  return { ok: true, value: picked as T, source: "artifact" };
}
