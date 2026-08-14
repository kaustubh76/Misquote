"""How a decision changes the position. One implementation, both drivers.

This exists because test L1 caught the two drivers disagreeing. Each computed
the next `PositionState` itself, and they differed on whether an initial mint
counts toward the daily rebalance cap — the replay driver said yes, the live
driver said no. Every subsequent decision then saw a different R4 and the two
sequences drifted apart.

The bug was not really the off-by-one. It was that the bookkeeping existed
twice. So it exists once now, here, in the pure layer where both drivers can
reach it, and the executor's job is narrowed to performing the chain action
rather than deciding what the resulting state is.

The counting rule, stated so it cannot drift again: **`rebalances_today` counts
moves of an existing position.** A first mint is not a rebalance — there was
nothing to rebalance — so it starts the counter at zero. Spec section 8's cap of
eight per day is a limit on churn, and refusing to open a position because the
previous position was moved eight times would be a different rule entirely.
"""

from __future__ import annotations

from misquote.core.types import Action, PositionState, Tick

CLOSED = PositionState(
    lower=None,
    upper=None,
    liquidity=0,
    token_id=None,
    minted_ts=0,
    last_rebalance_ts=0,
    rebalances_today=0,
)


def apply_decision(
    current: PositionState,
    action: Action,
    ts: int,
    *,
    lower: Tick | None = None,
    upper: Tick | None = None,
    liquidity: int = 0,
    token_id: int | None = None,
) -> PositionState:
    """The position after acting. Pure, so both drivers cannot disagree."""
    if action is Action.HOLD:
        return current

    if action is Action.PULL:
        return PositionState(
            lower=None,
            upper=None,
            liquidity=0,
            token_id=None,
            minted_ts=0,
            last_rebalance_ts=ts,
            # A pull is not a rebalance — the position is gone, not moved — but
            # the count survives it, so an agent cannot reset its own daily
            # limit by pulling and re-minting.
            rebalances_today=current.rebalances_today,
        )

    if lower is None or upper is None:
        raise ValueError(f"{action} needs a target range")

    moving = current.in_market
    return PositionState(
        lower=lower,
        upper=upper,
        liquidity=liquidity,
        token_id=token_id if token_id is not None else current.token_id,
        minted_ts=ts,
        last_rebalance_ts=ts,
        rebalances_today=current.rebalances_today + 1 if moving else 0,
    )
