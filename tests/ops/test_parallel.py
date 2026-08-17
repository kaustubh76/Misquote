"""The fan-out, tested for the properties `ranges.quote` relies on.

`tests/replay/test_ranges.py` proves the end-to-end claim — a parallel quote is
bit-identical to a serial one — but it proves it for one shape of input, and it
is slow enough that it cannot cover the edges. These cover the contract itself,
which is narrow and load-bearing:

**Order.** `quote` builds its percentile inputs from the list this returns. If
results came back in completion order rather than submission order, `returns`
would be a permutation and `p25`/`p75` would still agree — the sorted
percentiles are permutation-invariant — while the published per-window
distribution silently reordered. That is the kind of difference that passes the
headline assertion and corrupts the artifact underneath it.

**Fallback.** A platform without `fork` must run serially rather than fail, and
`jobs <= 1` must not pay for a pool it will not use.
"""

from __future__ import annotations

import pytest

from misquote.ops.parallel import fork_context, fork_map


def double(x: int) -> int:
    return x * 2


def slow_for_the_first(x: int) -> int:
    """Finishes in reverse order of submission, given enough workers.

    Task 0 sleeps longest, so completion order is the reverse of submission
    order and anything yielding as-completed will be visibly wrong.
    """
    import time

    time.sleep(0.20 - 0.02 * x)
    return x


# --- order ------------------------------------------------------------------


def test_results_come_back_in_submission_order() -> None:
    assert list(fork_map(4)(double, range(12))) == [x * 2 for x in range(12)]


def test_order_holds_when_completion_order_is_the_reverse() -> None:
    """The assertion above would pass on a lucky schedule. This one will not."""
    if fork_context() is None:  # pragma: no cover — platform-dependent
        pytest.skip("no fork on this platform")

    assert list(fork_map(8)(slow_for_the_first, range(8))) == list(range(8))


# --- falling back rather than failing ---------------------------------------


def test_one_job_stays_in_this_process() -> None:
    """`jobs=1` must not pay to create a pool it will not use."""
    assert list(fork_map(1)(double, range(5))) == [0, 2, 4, 6, 8]


def test_a_single_item_stays_in_this_process() -> None:
    """A pool for one task is pure overhead."""
    assert list(fork_map(8)(double, [7])) == [14]


def test_no_fork_context_falls_back_to_serial(monkeypatch) -> None:
    """Windows and any spawn-only platform. The work still has to happen."""
    monkeypatch.setattr("misquote.ops.parallel.fork_context", lambda: None)

    assert list(fork_map(8)(double, range(6))) == [0, 2, 4, 6, 8, 10]


def test_an_empty_plan_is_not_an_error() -> None:
    assert list(fork_map(4)(double, [])) == []


# --- failure ----------------------------------------------------------------


def boom(x: int) -> int:
    if x == 3:
        raise ValueError("worker failed on 3")
    return x


def test_a_failing_task_raises_rather_than_returning_short() -> None:
    """A quote built from 59 of 60 replays would be quietly wrong — it would
    still clear `MIN_SAMPLES` and read as a complete run."""
    if fork_context() is None:  # pragma: no cover — platform-dependent
        pytest.skip("no fork on this platform")

    with pytest.raises(ValueError, match="worker failed on 3"):
        list(fork_map(4)(boom, range(8)))


def test_the_same_failure_surfaces_on_the_serial_path(monkeypatch) -> None:
    """Both paths must fail the same way, or a fallback turns an error into a
    short result on exactly the platforms nobody tests on."""
    monkeypatch.setattr("misquote.ops.parallel.fork_context", lambda: None)

    with pytest.raises(ValueError, match="worker failed on 3"):
        list(fork_map(8)(boom, range(8)))


# --- the pool exists only while it is being consumed ------------------------


def test_the_pool_is_created_lazily(monkeypatch) -> None:
    """`ranges.quote` populates the state workers inherit *after* calling this
    and *before* pulling the first result. A pool created eagerly would fork
    children that inherit nothing.
    """
    created: list[int] = []
    real = fork_context()
    if real is None:  # pragma: no cover — platform-dependent
        pytest.skip("no fork on this platform")

    class Watcher:
        def Pool(self, processes):  # noqa: N802 — mirrors the ctx API
            created.append(processes)
            return real.Pool(processes=processes)

    monkeypatch.setattr("misquote.ops.parallel.fork_context", Watcher)

    iterator = fork_map(4)(double, range(8))
    assert created == [], "the pool was created before a result was asked for"

    assert next(iterator) == 0
    assert created == [4]
    list(iterator)  # drain, so the pool closes
