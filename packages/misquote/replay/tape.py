"""The tape interface, and a pure in-memory implementation.

A tape yields events in `(frontier, t]` and nothing else. The frontier only ever
moves forward; asking it to rewind raises rather than silently restarting,
because a replay that restarts its clock produces a plausible decision sequence
from a history that never happened.

The SQLite implementation lives in `misquote.indexer.tape_source`, because it
holds a database connection and this layer is not allowed to. That separation is
enforced by the layering test rather than by convention.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from misquote.core.errors import LookAheadError
from misquote.core.types import Event


@runtime_checkable
class Tape(Protocol):
    """What a driver may ask of history. Deliberately almost nothing.

    There is no "next N events", no "events near t", no "last event before t".
    Each of those is a foothold for reading past the decision time, and the
    absence of them is the guarantee.
    """

    @property
    def first_ts(self) -> int | None: ...

    @property
    def last_ts(self) -> int | None: ...

    @property
    def frontier(self) -> int: ...

    def advance_to(self, t: int) -> Sequence[Event]: ...

    def close(self) -> None: ...


class MemoryTape:
    """A tape over a list, for tests that need no database.

    Enforces the *same* frontier discipline as the real one rather than being a
    convenient shortcut — a test double that is easier to misuse than the object
    it stands in for tests the wrong thing.
    """

    __slots__ = ("_events", "_frontier", "_cursor")

    def __init__(self, events: Sequence[Event]) -> None:
        self._events = sorted(events, key=lambda e: e.key)
        self._frontier = -1
        # Events are sorted and the frontier only moves forward, so the read
        # position only moves forward too. Rescanning the list on every call
        # makes a replay quadratic in tape length — 40 million comparisons for a
        # four-thousand-event tape sampled every five seconds, which turns a
        # sixty-replay quote into minutes of nothing happening.
        self._cursor = 0

    @property
    def first_ts(self) -> int | None:
        return self._events[0].ts if self._events else None

    @property
    def last_ts(self) -> int | None:
        return self._events[-1].ts if self._events else None

    @property
    def frontier(self) -> int:
        return self._frontier

    def advance_to(self, t: int) -> Sequence[Event]:
        if t < self._frontier:
            raise LookAheadError(
                f"tape frontier moved backwards: {self._frontier} -> {t}. "
                "A replay that restarts its clock produces a plausible decision "
                "sequence from a history that never happened."
            )
        start = self._cursor
        events = self._events
        end = start
        while end < len(events) and events[end].ts <= t:
            end += 1

        self._cursor = end
        self._frontier = t
        return events[start:end]

    def close(self) -> None:
        return None

    def __enter__(self) -> MemoryTape:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
