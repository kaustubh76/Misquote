"""The trailing-only estimator contract.

This is where the product's central claim stops being a promise and becomes a
runtime property. Every estimator inherits an `ingest` that raises if the event
it is handed is newer than the decision it is being computed for, and raises
again if events arrive out of chain order.

Two integer comparisons per event. Always on — no debug flag, no environment
variable, no way to switch it off for speed. It runs identically in the live
agent and in the replay engine, which is what makes assumption A3 checkable
rather than merely asserted, and it is test T3 from the frozen spec implemented
in code rather than in review.

The cost of leaving it on forever is nothing. The cost of turning it off is that
every quote the product has ever produced becomes unverifiable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from misquote.core.errors import LookAheadError, OutOfOrderError
from misquote.core.types import Event


class TrailingEstimator(ABC):
    """An estimator that can only ever have seen the past.

    Subclasses implement `_absorb` and `value`. They never see the decision
    time directly, so they cannot accidentally condition on it.
    """

    __slots__ = ("_t", "_last_key", "_seen")

    def __init__(self) -> None:
        self._t: int = 0
        self._last_key: tuple[int, int] = (-1, -1)
        self._seen: int = 0

    @property
    def decision_time(self) -> int:
        return self._t

    @property
    def events_seen(self) -> int:
        return self._seen

    def set_decision_time(self, t: int) -> None:
        """Advance to the next decision. Time only ever moves forward.

        A backwards step would mean the driver is replaying a moment it has
        already decided, which silently invalidates every trailing window built
        so far.
        """
        if t < self._t:
            raise LookAheadError(
                f"{type(self).__name__}: decision time moved backwards, {self._t} -> {t}"
            )
        self._t = t
        self._on_time_advanced()

    def _on_time_advanced(self) -> None:  # noqa: B027 — optional by design
        """Hook for estimators with a trailing window to retire expired data.

        Deliberately concrete and empty rather than abstract: an estimator with
        a bounded buffer has nothing to evict, and forcing it to write a no-op
        would add noise without adding safety.

        Eviction belongs here rather than inside `value()` because `ready` must
        answer honestly too: an estimator whose entire window has aged out is
        not ready, and finding that out only when someone asks for the number is
        how a stale estimate gets published as a fresh one.
        """

    def ingest(self, event: Event) -> None:
        """Absorb one event, or refuse to.

        The two guards are the whole point of this class, so they come before
        anything else and are never conditional.
        """
        if event.ts > self._t:
            raise LookAheadError(
                f"{type(self).__name__}: event at ts={event.ts} is after the decision "
                f"time t={self._t} — this is exactly the look-ahead T3 forbids"
            )
        if event.key <= self._last_key:
            raise OutOfOrderError(
                f"{type(self).__name__}: event {event.key} is not after {self._last_key}; "
                "replay cannot be deterministic without a total order"
            )
        self._last_key = event.key
        self._seen += 1
        self._absorb(event)

    def ingest_all(self, events: object) -> None:
        for event in events:  # type: ignore[attr-defined]
            self.ingest(event)

    @abstractmethod
    def _absorb(self, event: Event) -> None:
        """Update internal state from one event known to be in the past."""

    @abstractmethod
    def value(self) -> float:
        """The current estimate. Must be a pure read — no side effects."""

    @property
    def ready(self) -> bool:
        """Whether the estimate rests on enough data to be worth publishing.

        An estimator that is not ready still returns a value; the caller decides
        whether to label it as a fallback. Silently substituting a default is
        how an unlabelled guess ends up on a card.
        """
        return True
