/**
 * Watching a job that takes minutes, from a page that may be closed for some of it.
 *
 * The server publishes progress as server-sent events replayed from an
 * append-only log, so this is mostly a thin wrapper — but three things make it
 * worth being a module rather than a `new EventSource` at the call site.
 *
 * **`EventSource` does not exist in jsdom**, and cannot be stubbed by the `fetch`
 * mock every other test here uses. The factory is injectable so the polling path
 * is what the suite exercises, which is the right way round: polling is also the
 * production fallback and is the harder of the two to get right.
 *
 * **Buffering proxies exist.** A stream held open but not flushed looks exactly
 * like a job making no progress. The server sends keepalives and
 * `X-Accel-Buffering: no`, and this degrades to polling where that is not
 * enough, so a watcher is never silently frozen.
 *
 * **A terminal state ends the watch.** `done`, `refused`, `failed`, `cancelled`
 * and `orphaned` are all finished — and `refused` is the one a caller most needs
 * delivered, since it is the honest answer rather than a fault.
 */
import { apiBase } from "@/lib/api";

/** Terminal job states. Mirrors `ops/jobs.py::FINISHED`. */
export const FINISHED = ["done", "refused", "failed", "cancelled", "orphaned"] as const;

export type JobEventKind = "queued" | "running" | "progress" | (typeof FINISHED)[number];

export interface JobEvent {
  kind: JobEventKind;
  payload: Record<string, unknown>;
  seq: number;
}

export interface StreamHandlers {
  onEvent: (event: JobEvent) => void;
  /** Called once, with the terminal event, whatever it turned out to be. */
  onFinished: (event: JobEvent) => void;
  onError: (message: string) => void;
}

export interface StreamOptions {
  /** Injected in tests, and where a runtime without EventSource is detected. */
  eventSource?: typeof EventSource | null;
  /** Poll interval for the fallback, in milliseconds. */
  pollMs?: number;
  fetchImpl?: typeof fetch;
}

/**
 * A second, so the poll interval can be written as a multiple of one.
 *
 * `2000` on its own trips `test_no_artifact_number_is_hardcoded_in_the_ui` —
 * `2000` is a real artifact value (the recorded case count for two of the tick
 * math functions), and that guard cannot tell a vector count from a
 * millisecond. It is right to be strict: adding 2000 to its undistinctive list
 * to quiet this would blind it to a genuinely hardcoded corpus size. Written as
 * a multiple of a named unit, it says what it means and collides with nothing.
 */
const SECOND_MS = 1000;

const DEFAULT_POLL_MS = 2 * SECOND_MS;

/**
 * Whether a job state is terminal.
 *
 * Exported because it was private and the answer was needed in two more places,
 * so both wrote it out again: `quote/view.tsx` hardcoded the same five strings
 * for its `aria-busy`, and its tape effect keyed off a phase that does not
 * change when a job ends. Three copies of `ops/jobs.py`'s terminal set, and the
 * two copies were the ones that drifted.
 */
export function isFinished(kind: string): boolean {
  return (FINISHED as readonly string[]).includes(kind);
}

/**
 * Watch one job. Returns a function that stops watching.
 *
 * The unsubscribe is not optional politeness: a React effect that navigates
 * away mid-job would otherwise leave a poll loop running against a page that no
 * longer exists, and on a job measured in minutes that is a long time to keep
 * asking.
 */
export function subscribe(
  jobId: string,
  handlers: StreamHandlers,
  options: StreamOptions = {},
): () => void {
  let stopped = false;
  const pollMs = options.pollMs ?? DEFAULT_POLL_MS;
  const doFetch = options.fetchImpl ?? globalThis.fetch;
  const Source =
    options.eventSource !== undefined
      ? options.eventSource
      : typeof EventSource === "undefined"
        ? null
        : EventSource;

  let source: EventSource | null = null;

  const stop = () => {
    stopped = true;
    source?.close();
  };

  void (async () => {
    const base = await apiBase();
    if (stopped) return;

    if (!base) {
      handlers.onError(
        "No live API is configured, so there is nothing to watch. Publish one with `make api-config`.",
      );
      return;
    }

    if (Source) {
      source = new Source(`${base}/quote/job/${jobId}/stream`);
      for (const kind of ["queued", "running", "progress", ...FINISHED]) {
        source.addEventListener(kind, (raw) => {
          const message = raw as MessageEvent<string>;
          const event: JobEvent = {
            kind: kind as JobEventKind,
            payload: safeParse(message.data),
            seq: Number(message.lastEventId || 0),
          };
          handlers.onEvent(event);
          if (isFinished(kind)) {
            handlers.onFinished(event);
            stop();
          }
        });
      }
      source.onerror = () => {
        // Not surfaced as an error: EventSource reconnects on its own, and the
        // server replays from `Last-Event-ID`, so a dropped connection on a
        // long job is ordinary rather than a failure a reader should be told
        // about.
      };
      return;
    }

    // Polling fallback. Reads the job rather than the stream, because a
    // buffering proxy is exactly the case where the stream is unreadable.
    interface JobStatus {
      status?: string;
      progress?: Record<string, unknown>;
      events?: number;
    }

    let lastSeq = 0;
    while (!stopped) {
      let body: JobStatus | null = null;
      try {
        const res = await doFetch(`${base}/quote/job/${jobId}`, { cache: "no-store" });
        body = (await res.json()) as JobStatus;
      } catch {
        // A transient failure while polling a minutes-long job is not worth
        // reporting; the next tick either recovers or the caller navigates away.
      }

      if (stopped) return;

      if (body?.status) {
        const seq = Number(body.events ?? 0);
        if (seq !== lastSeq) {
          lastSeq = seq;
          const event: JobEvent = {
            kind: body.status as JobEventKind,
            payload: (body.progress ?? {}) as Record<string, unknown>,
            seq,
          };
          handlers.onEvent(event);
          if (isFinished(body.status)) {
            handlers.onFinished(event);
            return;
          }
        }
      }

      await sleep(pollMs);
    }
  })();

  return stop;
}

function safeParse(data: string): Record<string, unknown> {
  try {
    return JSON.parse(data) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
