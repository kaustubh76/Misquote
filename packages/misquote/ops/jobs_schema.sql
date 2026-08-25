-- The job store. Separate from the tape, deliberately.
--
-- `indexer/schema.sql` is executed by `store.connect()` on *every* call, so
-- putting job tables there would create them in every test's tmp_path database
-- and in every developer's 256MB tape. The tape is also read-mostly evidence
-- that gets rebuilt; job history is neither, and rebuilding one should not
-- erase the other.
--
-- Two rules carried over from the tape's schema, for the same reasons:
-- timestamps are integer epoch seconds, and anything that could exceed a signed
-- 64-bit integer is TEXT. Nothing here is that large today; the convention is
-- kept so a future field cannot silently overflow the way `sqrtPriceX96` would.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS job (
  id            TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,
  params_json   TEXT NOT NULL,

  -- queued | running | done | refused | failed | cancelled | orphaned
  --
  -- `refused` is a distinct terminal state from `failed` and the distinction is
  -- the point: a replay that completes and reports the evidence cannot support
  -- a quote has succeeded at its job. Collapsing the two would turn every
  -- honest "no" into an error the caller is invited to retry.
  status        TEXT NOT NULL,

  created_ts    INTEGER NOT NULL,
  started_ts    INTEGER,
  finished_ts   INTEGER,

  done          INTEGER NOT NULL DEFAULT 0,
  total         INTEGER NOT NULL DEFAULT 0,
  phase         TEXT,

  result_json   TEXT,
  refusal_json  TEXT,

  worker_pid    INTEGER,
  -- Written by the worker as it progresses. A `running` row whose heartbeat has
  -- stopped is how a killed worker is told apart from a slow one.
  heartbeat_ts  INTEGER
);

CREATE INDEX IF NOT EXISTS job_queue ON job (status, created_ts);

-- Append-only, and what SSE replays from.
--
-- A client that connects late, or reconnects with `Last-Event-ID`, gets the
-- whole history rather than whatever happens to arrive next. Progress on a job
-- that takes an hour is a record, not an ephemeral stream — the same instinct
-- as the agents' JSONL journals.
CREATE TABLE IF NOT EXISTS job_event (
  job_id       TEXT NOT NULL REFERENCES job (id),
  seq          INTEGER NOT NULL,
  ts           INTEGER NOT NULL,
  kind         TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY (job_id, seq)
);

-- A worker that has booted, whether or not it has ever claimed anything.
--
-- `worker_last_seen()` inferred a worker from the jobs it had touched, and said
-- so honestly — "evidence, not proof". The gap that inference leaves is the one
-- that matters on a fresh deploy: a worker running against an empty queue is
-- indistinguishable from no worker at all, because neither has touched a row.
--
-- That is exactly the state a judge meets first. They hire, the job sits
-- `queued`, and the response cannot tell them whether it is unattended or
-- merely next in line. One row per process, written on boot and refreshed while
-- idle, makes the two different answers.
CREATE TABLE IF NOT EXISTS worker (
    pid         INTEGER PRIMARY KEY,
    host        TEXT    NOT NULL,
    started_ts  INTEGER NOT NULL,
    heartbeat_ts INTEGER NOT NULL
);
