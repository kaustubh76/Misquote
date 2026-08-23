"""Whether a quote is possible, answered before anyone waits for one.

`replay/ranges.py::quote()` records its own measured cost in its docstring: on
the 30-day WBNB/USDT tape, 60 replays of ~125,700 events each, **4.6 hours** for
the four agents the showcase runs. It is also process-global non-reentrant — it
keeps per-run state in a module-level dict so forked workers inherit it, and
raises rather than letting a second call corrupt the first.

So a quote is never a request. Before anything is queued, this recomputes the
engine's *own* sufficiency predicate from the engine's *own* constants and says
no immediately if the answer is already no. Nobody should wait twenty minutes to
be told the tape covers three hours.

## Imported, never re-derived

`MIN_SAMPLES`, `MIN_WINDOW_HOURS` and `rolling_windows` come from
`replay.ranges`. Restating "a window needs 24 hours" here would put a second
copy of the refusal rule one module from the first, and the two would drift —
which is the failure this project is named after, committed against its own
engine. If the engine's floor moves, this moves with it.
"""

from __future__ import annotations

from typing import Any

from misquote.chain.addresses import PoolRef
from misquote.indexer.store import covered_span, tape_summary
from misquote.replay.ranges import MIN_SAMPLES, MIN_WINDOW_HOURS, rolling_windows

SECONDS_PER_HOUR = 3600.0


def assess(conn: Any, ref: PoolRef, *, windows: int = MIN_SAMPLES) -> dict[str, Any]:
    """Can this pool's tape support a quote, and if not, what is missing?

    Reports the arithmetic rather than only the verdict. "Not quotable" invites
    the reader to guess; "the widest window is 3.1h and the floor is 24h" tells
    them what would have to change.
    """
    address = ref.address.lower()
    summary = tape_summary(conn, address)
    span = covered_span(conn, address)

    first_ts = summary.get("first_ts")
    last_ts = summary.get("last_ts")
    hours = (
        (float(last_ts) - float(first_ts)) / SECONDS_PER_HOUR
        if isinstance(first_ts, int | float) and isinstance(last_ts, int | float)
        else 0.0
    )

    spans = (
        rolling_windows(int(first_ts), int(last_ts), windows)
        if isinstance(first_ts, int | float) and isinstance(last_ts, int | float)
        else []
    )
    widest = max(((b - a) / SECONDS_PER_HOUR for a, b in spans), default=0.0)

    reasons: list[str] = []
    if not summary.get("swaps"):
        reasons.append("the tape holds no swaps for this pool")
    if span is None:
        # Not the same as a short tape: the events may be real and the record of
        # what was fetched absent. `store.coverage` says so in its own docstring.
        reasons.append("no coverage is recorded, so the history cannot be vouched for")
    if widest < MIN_WINDOW_HOURS:
        reasons.append(
            f"the widest sub-window is {widest:.1f}h and the engine's floor is "
            f"{MIN_WINDOW_HOURS:.0f}h — shorter than the policy's own horizon, so a "
            "replay would measure startup rather than strategy"
        )

    return {
        "pool": address,
        "label": ref.label if hasattr(ref, "label") else "",
        "quotable": not reasons,
        "why_not": reasons,
        "tape": {
            "swaps": summary.get("swaps"),
            "hours": round(hours, 1),
            "coverage_recorded": span is not None,
        },
        "plan": {
            "windows": windows,
            "widest_window_hours": round(widest, 1),
            "min_window_hours": MIN_WINDOW_HOURS,
            "min_windows": MIN_SAMPLES,
        },
        "remedy": None if not reasons else f"make indexer POOL={ref.address}",
    }
