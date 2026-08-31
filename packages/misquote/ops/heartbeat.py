"""Agent liveness: a timestamp, not a boolean.

`ops/jobs.py` already has a heartbeat — `worker.heartbeat_ts`, for the quote
queue — and this is a different one. That answers *is a worker draining jobs*;
this answers *is the agent still deciding*, which nothing asked. Spec §10's
acceptance list has said "heartbeat green" since the beginning and no code
implemented it.

## Why a timestamp

A boolean written by the agent about itself cannot answer "is it alive": a
process that has hung stops updating a flag exactly as it stops updating a
clock, and only the clock says how long ago that was. So `beat()` records *when*
and `stale_for()` is computed by the reader.

The threshold is the reader's too. How long is too long depends on the poll
cadence — `chain/live_source.py` polls once a minute because a five-second cadence
is refused by every public endpoint (matrix D-9) — and a module that hardcoded
"30 seconds is dead" would be asserting a policy against a cadence it does not
know. `is_stale()` takes the bound.

## It also writes to the journal

Because the journal is what the tearsheet reads, and a heartbeat that only exists
in a Prometheus gauge is invisible to every artifact this project publishes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from misquote.ops import metrics


@dataclass(slots=True)
class Heartbeat:
    """The last time an agent completed a cycle, and who is asking.

    `journal` is optional so the loop can beat without one — the tests construct
    it bare — but when present every beat is a row, because the journal outlives
    the process and a gauge does not.
    """

    agent: str
    journal: object | None = None
    #: Seconds between journalled beats. Every beat updates the gauge; only one
    #: a minute is written down. A row per five-second cycle would be 17,280
    #: rows a day saying nothing, and the journal is evidence rather than a log.
    journal_every_s: float = 60.0
    last_ts: float = 0.0
    beats: int = 0
    _last_written: float = field(default=0.0, repr=False)

    def beat(self, *, at: float | None = None) -> float:
        """Record a completed cycle. Returns the timestamp recorded."""
        now = time.time() if at is None else float(at)
        self.last_ts = now
        self.beats += 1
        metrics.metric("heartbeat").labels(agent=self.agent).set(now)

        if self.journal is not None and now - self._last_written >= self.journal_every_s:
            self._last_written = now
            self.journal.write(
                {"event": "heartbeat", "agent": self.agent, "ts": int(now), "beats": self.beats}
            )
        return now

    def stale_for(self, *, now: float | None = None) -> float:
        """Seconds since the last beat. `inf` when there has never been one.

        Not `0.0`, which is what a naive implementation returns and which reads
        as *perfectly healthy* for an agent that has never run a cycle. That is
        the same confusion `api/sessions.py` refuses for an empty grant list.
        """
        if not self.last_ts:
            return float("inf")
        return (time.time() if now is None else now) - self.last_ts

    def is_stale(self, older_than_s: float, *, now: float | None = None) -> bool:
        """Has it been too long? The bound is the caller's, not this module's."""
        if older_than_s <= 0:
            raise ValueError("a staleness bound of zero or less calls every agent dead")
        return self.stale_for(now=now) > older_than_s


__all__ = ["Heartbeat"]
