"""Errors that mean a guarantee was broken, not that an input was odd.

These are deliberately loud. Every one of them signals that something the
product *claims* — no look-ahead, ordered ingestion, a policy that only sees
scalars — has stopped being true. There is no sensible fallback behaviour for
that, so nothing here is ever caught and logged; it stops the run.
"""

from __future__ import annotations


class MisquoteError(Exception):
    """Base for every invariant this codebase enforces."""


class LookAheadError(MisquoteError):
    """A decision was about to use information from after the decision time.

    Raised on the ingest path, unconditionally, in both the live and the replay
    driver. This is test T3 from the frozen spec, implemented in code rather
    than checked in review, which is the only form of it worth having.
    """


class OutOfOrderError(MisquoteError):
    """Events arrived out of chain order.

    Replay must be deterministic to be reproducible, and determinism requires a
    total order. `(block, log_index)` is that order; a regression in it means the
    tape or the indexer is wrong, and any number computed afterwards is
    unreliable in a way that would not otherwise be visible.
    """


class AssumptionViolated(MisquoteError):
    """A published assumption stopped holding, so the quote must not render.

    The assumption sheet is a promise about how every displayed number was
    produced. When an input breaches one — a replayed position larger than the
    A1 liquidity cap, say — the honest response is to refuse the quote rather
    than to show it with a caveat nobody reads.
    """
