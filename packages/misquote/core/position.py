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

**`reentries_today` counts mints that follow a pull**, and answers to its own cap.
Both survive a pull, so neither limit can be reset by withdrawing and re-minting —
the property the single counter was introduced to protect, kept intact while
splitting it.

Why split at all: a recentre is discretionary and a re-entry is not. Warden's
toxicity arm withdrew the position and every return then spent a recentre, so on
the 30-day tape the agent made 249 mints and 249 pulls inside a budget of eight
moves a day, exhausted that budget early, and sat out of the market 94% of the
time (P-20). One counter was pricing two behaviours that do not trade off against
each other.
"""

from __future__ import annotations

from misquote.core.types import Action, PositionState, Tick

SECONDS_PER_DAY = 86_400


def _same_day(position: PositionState, now: int) -> bool:
    """Whether `now` falls in the same UTC day as the position's last move."""
    if position.last_rebalance_ts <= 0:
        return True
    return now // SECONDS_PER_DAY == position.last_rebalance_ts // SECONDS_PER_DAY


def reentries_today(position: PositionState, now: int) -> int:
    """How many re-entries count against today's budget.

    Same rollover rule as `rebalances_today`, and separate from it for the reason
    recorded on `Params.max_reentries_per_day`: coming back after a defensive
    withdrawal is not the churn the recentre cap was written to limit, and
    charging both to one counter is what left Warden out of the market on 94% of
    the 30-day tape.

    Two counters mean two chances to get the rollover wrong, so both go through
    `_same_day` rather than each spelling the arithmetic out.
    """
    if not _same_day(position, now):
        return 0
    return position.reentries_today


def rebalances_today(position: PositionState, now: int) -> int:
    """How many moves count against today's budget.

    Spec section 8 caps rebalances **per day**, which is a rate limit. The stored
    counter only ever increased, so the cap behaved as a limit for the lifetime
    of the position: after eight moves the agent froze and could never recentre
    again however far price drifted.

    A 62-hour replay is what surfaced it — the agent made exactly eight moves and
    then held 14.6% in range for the remainder. Over a few hours the bug is
    invisible, which is why it survived every test until a run was long enough to
    cross a day boundary.

    The day is the UTC calendar day of the last move. Rolling rather than
    calendar windows would be defensible too, but calendar days are what "per
    day" means to the operator reading the parameter.
    """
    if not _same_day(position, now):
        return 0
    return position.rebalances_today


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
            rebalances_today=rebalances_today(current, ts),
            reentries_today=reentries_today(current, ts),
        )

    if lower is None or upper is None:
        raise ValueError(f"{action} needs a target range")

    # Continue today's counts, or start fresh ones if the day has rolled over.
    prior = rebalances_today(current, ts)
    prior_reentries = reentries_today(current, ts)

    # Which budget this move spends. Coming back from a pull is a re-entry: the
    # position was withdrawn, not moved, and `in_market` is the state that tells
    # the two apart at the moment of acting. A recentre of a live position is a
    # rebalance and always was.
    #
    # `last_rebalance_ts` cannot serve here the way it does for `first_ever`
    # below — it is set by a pull too, so it says the position has been acted on
    # without saying whether one currently exists.
    is_reentry = not current.in_market

    # Only a *first ever* entry starts the count at zero. This used to test
    # `current.in_market`, which is false for every re-entry after a pull — so a
    # re-mint reset the counter, and the PULL branch above preserved a number the
    # very next action discarded. Its comment claims an agent "cannot reset its
    # own daily limit by pulling and re-minting"; that is exactly what it could
    # do, and on the 30-day chain tape it did so 2,585 times.
    #
    # `token_id is None` cannot be the discriminator, because PULL nulls it — on
    # chain the NFT really is burned. `last_rebalance_ts` is what survives: it is
    # zero only on a position that has never been acted on at all.
    first_ever = current.last_rebalance_ts <= 0
    if first_ever:
        rebalances = 0
        reentries = 0
    elif is_reentry:
        # The re-entry spends its own budget and leaves the recentre budget
        # alone. The comment above still holds: the counts survive the pull, so
        # this cannot be used to reset either limit.
        rebalances = prior
        reentries = prior_reentries + 1
    else:
        rebalances = prior + 1
        reentries = prior_reentries

    return PositionState(
        lower=lower,
        upper=upper,
        liquidity=liquidity,
        token_id=token_id if token_id is not None else current.token_id,
        minted_ts=ts,
        last_rebalance_ts=ts,
        rebalances_today=rebalances,
        reentries_today=reentries,
    )
