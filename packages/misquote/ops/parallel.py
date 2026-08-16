"""Running independent replays across processes.

This lives in `ops/` rather than in `replay/` for a reason the test suite
enforces: `replay` is a **pure** layer, and `tests/test_layering.py` bans it from
importing `multiprocessing` along with `time`, `socket`, `random` and everything
else that constitutes a capability. *"A layer that cannot read a clock or a
socket cannot read the future."* That rule is what makes T1 and T3 structural
rather than aspirational, and it caught this code the first time it was written
in the wrong place. `EXEMPTIONS` in that test is empty, and adding the first
entry to it in order to make a batch job faster would be a poor trade.

So `ranges.quote` takes a `map_fn` and defaults to the builtin `map`. The pure
layer decides *what* to run; this decides *where*.

**Why fork, and not spawn.** Nothing here can be pickled. `sentinel_policy` and
`grid_policy` both return closures, and every `tape_factory` in the repository is
a closure over its events list, so a spawn-based pool cannot carry the work and
passing it per task is not available either. Fork hands the child the parent's
memory copy-on-write and only the task index crosses the pipe.

**Why a generator.** The pool must not exist until the caller has finished
populating the module-level state the workers inherit, and it must stay alive
while its results are consumed. Creating it lazily, inside the iteration, gets
both: `with ctx.Pool(...)` is entered on the first `next()` and left when the
last result has been yielded.
"""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable, Iterable, Iterator
from typing import Any


def fork_context():
    """A `fork` multiprocessing context, or None where the platform has none.

    Windows and any spawn-only platform get None and the caller stays serial.
    `fork` is unsafe in a process that already has threads; the two callers are
    single-threaded batch scripts.
    """
    try:
        return multiprocessing.get_context("fork")
    except ValueError:  # pragma: no cover — platform-dependent
        return None


def fork_map(jobs: int) -> Callable[[Callable[..., Any], Iterable[Any]], Iterator[Any]]:
    """A drop-in `map` that runs `fn` across `jobs` forked processes.

    Order is preserved — `imap` yields in submission order — so a caller
    assembling a list gets exactly what the serial `map` would have given it.
    That is not a convenience: `replay/ranges.py` builds its percentile inputs
    from this list, and the whole argument for parallelising rather than making
    the sigma estimator incremental is that no number moves.
    """

    def run(fn: Callable[..., Any], items: Iterable[Any]) -> Iterator[Any]:
        work = list(items)
        ctx = fork_context()
        if ctx is None or jobs <= 1 or len(work) < 2:
            yield from map(fn, work)
            return
        with ctx.Pool(processes=min(jobs, len(work))) as pool:
            yield from pool.imap(fn, work)

    return run
