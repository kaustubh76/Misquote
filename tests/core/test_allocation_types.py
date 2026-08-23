"""The allocation types' refusals, which are the whole reason they exist.

Named `test_allocation_types` and not `test_allocation`, which is the obvious
name and belongs to `tests/replay/test_allocation.py`. `tests/` is not a
package, so pytest derives a module name from the basename alone: two files
called `test_allocation.py` produce one module name, and collection fails —
**taking the whole suite with it**, not just those two files. Both this file and
`tests/vetting/test_venus_checks.py` carry this note because the trap was hit
twice in one session, the second time immediately after writing the warning.

`core/allocation.py` is a sibling of `types.py` rather than an extension of it,
and the argument for that is in its docstring. What this file checks is the part
that argument rests on: that the types refuse rather than degrade.

The pattern is `Params.__post_init__`'s. This repository has shipped two gates
wired to nothing and found both by accident, so a configuration that could never
work fails at construction rather than rendering as configured and never firing.
"""

from __future__ import annotations

import pytest

from misquote.core.allocation import (
    AllocationAction,
    AllocationDecision,
    AllocationObservation,
    VenueQuote,
)

A = "0xfd5840cd36d94d7229439859c0112a4185bc0255"
B = "0xeca88125a5adbe82614ffc12d0db554e2e2867c8"


def venue(vid: str = A, apr: float = 0.02, **kw) -> VenueQuote:
    return VenueQuote(
        venue_id=vid,
        apr=apr,
        apr_samples=kw.pop("apr_samples", 100),
        apr_is_stale=kw.pop("apr_is_stale", False),
        cash_quote=kw.pop("cash_quote", 1e7),
        supplied_base_quote=kw.pop("supplied_base_quote", 1e8),
    )


def observation(**kw) -> AllocationObservation:
    return AllocationObservation(
        t=kw.pop("t", 1_000_000),
        venues=kw.pop("venues", (venue(),)),
        held=kw.pop("held", None),
        notional_quote=kw.pop("notional_quote", 10_000.0),
        gas_quote=kw.pop("gas_quote", 0.3),
        switch_slippage_bps=kw.pop("switch_slippage_bps", 5.0),
        seconds_since_switch=kw.pop("seconds_since_switch", 0),
        switches_today=kw.pop("switches_today", 0),
        edge_streak=kw.pop("edge_streak", 0),
    )


# --- the shape the replay engine depends on ---------------------------------


def test_every_type_is_frozen_and_hashable() -> None:
    """Hashable because `Decision` is, and for the same reason.

    A decision that can be put in a set is a decision that cannot be mutated
    after the journal recorded it.
    """
    q, o = venue(), observation()
    d = AllocationDecision(
        action=AllocationAction.HOLD,
        target_venue=None,
        held_venue=None,
        edge_apr=0.0,
        hurdle_apr=0.01,
        reasons=(("a", 1.0),),
    )
    for obj in (q, o, d):
        assert hash(obj) is not None
        with pytest.raises((AttributeError, TypeError)):
            obj.apr = 1.0  # type: ignore[misc]


def test_two_identical_constructions_are_equal() -> None:
    assert venue() == venue()
    assert observation() == observation()


# --- VenueQuote refuses -----------------------------------------------------


def test_a_rate_below_minus_one_hundred_percent_is_refused() -> None:
    """A supplied position cannot lose more than it supplied."""
    with pytest.raises(ValueError, match="below -100%"):
        venue(apr=-1.5)


def test_exactly_minus_one_hundred_percent_is_allowed() -> None:
    """The boundary is a real rate — total loss — not an error."""
    assert venue(apr=-1.0).apr == -1.0


def test_a_venue_with_no_id_is_refused() -> None:
    with pytest.raises(ValueError, match="no id"):
        venue(vid="")


def test_negative_sample_counts_and_liquidity_are_refused() -> None:
    with pytest.raises(ValueError, match="apr_samples"):
        venue(apr_samples=-1)
    with pytest.raises(ValueError, match="negative liquidity"):
        venue(cash_quote=-1.0)
    with pytest.raises(ValueError, match="negative liquidity"):
        venue(supplied_base_quote=-1.0)


# --- AllocationObservation refuses ------------------------------------------


def test_no_venues_is_refused() -> None:
    with pytest.raises(ValueError, match="nothing to choose between"):
        observation(venues=())


def test_a_held_venue_absent_from_the_observation_is_refused() -> None:
    """The refusal that stops a position being silently re-entered on top of.

    A policy handed a `held` it cannot see would read the position as flat and
    mint a second one over the first.
    """
    with pytest.raises(ValueError, match="not among the observed venues"):
        observation(venues=(venue(A),), held=B)


def test_a_non_positive_notional_is_refused() -> None:
    with pytest.raises(ValueError, match="no yield to optimise"):
        observation(notional_quote=0.0)
    with pytest.raises(ValueError, match="no yield to optimise"):
        observation(notional_quote=-1.0)


def test_negative_costs_are_refused() -> None:
    with pytest.raises(ValueError, match="costs cannot be negative"):
        observation(gas_quote=-0.1)
    with pytest.raises(ValueError, match="costs cannot be negative"):
        observation(switch_slippage_bps=-1.0)


@pytest.mark.parametrize("field", ["edge_streak", "switches_today", "seconds_since_switch"])
def test_negative_counters_are_refused(field: str) -> None:
    with pytest.raises(ValueError, match="counters cannot be negative"):
        observation(**{field: -1})


# --- and the refusals are not vacuous ---------------------------------------


def test_a_valid_observation_still_constructs() -> None:
    """Without this every test above would pass on a type that refuses everything."""
    o = observation(venues=(venue(A), venue(B, 0.05)), held=A)
    assert o.held == A
    assert len(o.venues) == 2


# --- the lookups the driver and the policy both use -------------------------


def test_venue_lookup_finds_and_misses_honestly() -> None:
    o = observation(venues=(venue(A), venue(B, 0.05)), held=A)
    assert o.venue(B) is not None and o.venue(B).apr == 0.05
    assert o.venue("0xdead") is None


def test_held_quote_is_none_when_flat_rather_than_raising() -> None:
    """Flat is a real state, not a missing one."""
    assert observation(held=None).held_quote is None
    assert observation(venues=(venue(A),), held=A).held_quote is not None


# --- the decision's own accessors -------------------------------------------


def test_moves_is_true_for_every_action_that_costs_money() -> None:
    def decision(action):
        return AllocationDecision(
            action=action,
            target_venue=None,
            held_venue=None,
            edge_apr=0.0,
            hurdle_apr=0.0,
            reasons=(),
        )

    assert not decision(AllocationAction.HOLD).moves
    for action in (AllocationAction.ENTER, AllocationAction.SWITCH, AllocationAction.EXIT):
        assert decision(action).moves, f"{action} spends gas and must count as a move"


def test_reason_lookup_returns_none_for_a_gate_that_was_not_consulted() -> None:
    """None, not 0.0 — a gate that did not run and a gate that returned false
    must not read the same, which is the whole point of the histogram."""
    d = AllocationDecision(
        action=AllocationAction.HOLD,
        target_venue=None,
        held_venue=None,
        edge_apr=0.0,
        hurdle_apr=0.0,
        reasons=(("cooldown_met", 0.0),),
    )
    assert d.reason("cooldown_met") == 0.0
    assert d.reason("never_consulted") is None
