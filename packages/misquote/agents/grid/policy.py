"""Grid: a ladder of fixed rungs, on the same core as Warden.

Its purpose is partly to be a second product and mostly to be evidence. A
marketplace claiming it can replay *any* agent's policy on real history, and
then shipping exactly one agent, has not demonstrated the claim — it has
demonstrated that one program works. Grid is a different strategy with different
economics, and it goes through the identical engine, tape, cost model, LVR
accountant and quote machinery.

Where Warden asks "where should the range be, given inventory and volatility",
Grid asks nothing: it places a fixed ladder around a reference price and only
moves when price leaves the ladder entirely. No Avellaneda-Stoikov, no sigma, no
kappa. That difference is the point — if the engine only worked for the policy
it was designed alongside, it would be a Warden harness with delusions of
generality.

The honest comparison this enables: Grid is cheaper to run and worse at avoiding
adverse selection, because it never widens for volatility and never pulls for
toxicity. A marketplace should be able to say that with numbers rather than
adjectives, and after this it can.
"""

from __future__ import annotations

from dataclasses import dataclass

from misquote.core.policy import _round_to_spacing
from misquote.core.types import Action, Decision, Observation, PoolMeta, Tick


@dataclass(frozen=True, slots=True)
class GridParams:
    """Every number a Grid needs, and nothing else.

    Deliberately small. Warden's parameter table is large because the strategy
    genuinely depends on all of it; Grid's is three numbers because the strategy
    genuinely does not.
    """

    rung_width_ticks: int = 200  # half-width of the ladder around the anchor
    reanchor_at_edge: bool = True  # move only when price leaves the ladder
    cooldown_s: int = 3600

    def __post_init__(self) -> None:
        if self.rung_width_ticks <= 0:
            raise ValueError("a ladder with no width is not a ladder")
        if self.cooldown_s < 0:
            raise ValueError("cooldown cannot be negative")


def decide_grid(obs: Observation, params: GridParams, meta: PoolMeta) -> Decision:
    """Place a ladder, and move it only when price walks off the end.

    Returns the same `Decision` type Warden does, so the driver, the journal, the
    replay engine and the tearsheet need no knowledge of which agent produced it.
    That is the whole demonstration.
    """
    centre = _round_to_spacing(float(obs.tick), meta.tick_spacing)
    width = _round_to_spacing(float(params.rung_width_ticks), meta.tick_spacing)
    width = max(width, meta.tick_spacing)

    position = obs.position
    reasons: list[tuple[str, float]] = [
        ("grid_width_ticks", float(width)),
        ("tick", float(obs.tick)),
    ]

    if not position.in_market:
        reasons.append(("reason_mint", 1.0))
        return _decision(Action.MINT, centre, width, obs, reasons)

    inside = position.contains(obs.tick)
    since_move = obs.t - position.last_rebalance_ts
    cooled = since_move >= params.cooldown_s

    reasons += [
        ("in_range", float(inside)),
        ("seconds_since_move", float(since_move)),
        ("cooldown_met", float(cooled)),
    ]

    # The entire policy: move when price has left the ladder, and not before.
    # No drift threshold, no fee-gain gate, no volatility term. Fewer moves than
    # Warden, and no defence at all against being picked off inside the range —
    # which is exactly what the LVR column will show.
    if params.reanchor_at_edge and not inside and cooled:
        reasons.append(("reason_reanchor", 1.0))
        return _decision(Action.RECENTER, centre, width, obs, reasons)

    reasons.append(("reason_hold", 1.0))
    return _decision(Action.HOLD, centre, width, obs, reasons, hold=True)


def _decision(
    action: Action,
    centre: Tick,
    width: int,
    obs: Observation,
    reasons: list[tuple[str, float]],
    *,
    hold: bool = False,
) -> Decision:
    return Decision(
        action=action,
        target_lower=None if hold else centre - width,
        target_upper=None if hold else centre + width,
        center_tick=centre,
        half_width_ticks=width,
        # Grid has no reservation price and no optimal spread. Reporting the
        # observed log-price and the ladder's own half-width in tick units keeps
        # the journal schema identical without pretending the quantities mean
        # what Warden's do.
        r=obs.y,
        delta_star=float(width),
        reasons=tuple(reasons),
    )
