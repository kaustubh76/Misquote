"""Sentinel: the agent whose job is knowing when to leave.

Third agent, and the one that found something. Warden recentres for profit and
consults toxicity as one gate among four; Grid ignores health entirely and only
moves when price walks off its ladder. Both spend nearly all their time *in* the
market, so between them they exercised one of the engine's five actions barely at
all and one of them never.

Sentinel inverts that. It holds a deliberately wide, cheap band and never
recentres for profit — it has no view on where the range should be. Its entire
active behaviour is withdrawal and re-entry: `PULL` when the pool looks unsafe,
`REENTER` when it has looked safe for long enough. Readme section on agents calls
this "threshold de-risk", and constrains it usefully: Hawkes intensity is an
early-warning dashboard only, never in the backtest path. So this is thresholds,
and nothing here is fitted.

**Building it is what exposed the dead gate.** Sentinel's primary signal is spec
section 3.4's swap-imbalance z-score, and the engine passed a hardcoded `0.0` for
it. Warden could not tell — the imbalance arm is one of two ways it reaches the
same pull, and the other arm was live — and Grid never reads it. An agent that
consults a signal as one input among many cannot distinguish a quiet signal from
a broken one. An agent that consults it *first* discovers immediately that it
never fires.

That is the argument for a third agent stated concretely: each new policy is a
different set of load-bearing assumptions about the engine, and the engine only
learns which of its parts are actually wired when something leans on them.

## What it is honestly good and bad at

It cannot beat a fee-maximising strategy on fee capture, because it is out of the
market during exactly the volatile periods when fees are highest. What it can do
is not be there when flow turns informed. Whether that trade pays is a property
of the tape, not of the agent, and the whole point of the replay engine is that
nobody has to take either side of that argument on faith.

Two failure modes worth naming before the numbers do it:

- **It withdraws late.** The on-chain arm compares *realized* LVR against
  realized fees, so it reacts after the damage rather than before it. Only the
  CEX-gap arm leads, and that needs a feed we do not have in replay.
- **Its band is wide, so its fee rate is low.** A wide range earns a small share
  of each swap. Sentinel trades fee density for not needing to move.
"""

from __future__ import annotations

from dataclasses import dataclass

from misquote.core.policy import _round_to_spacing, toxicity
from misquote.core.types import (
    Action,
    Decision,
    Observation,
    Params,
    Policy,
    PoolMeta,
    Tick,
)


@dataclass(frozen=True, slots=True)
class SentinelParams:
    """Thresholds, and nothing fitted.

    Every one of these is a number an operator sets and can defend, not a
    parameter estimated from data. That is the difference between this and
    Warden, and it is deliberate: an agent that exists to be trusted during a
    crisis should not have its behaviour depend on a regression that was last
    refit at some point before the crisis.
    """

    # Wide by design. Sentinel is not trying to sit where the fees are; it is
    # trying not to have to move. Roughly +/-5% at this tick scale.
    band_ticks: int = 500

    # Re-anchor only if price leaves the band entirely — the same rule Grid uses,
    # for the same reason. Sentinel has no opinion about the centre.
    reanchor_at_edge: bool = True

    # Consecutive clear samples before re-entering after a pull. Defaults to the
    # spec's own `m_clear` so the two agree unless deliberately overridden.
    clear_samples: int | None = None

    # Minimum seconds in market before a pull is allowed. Without it, a position
    # minted into an already-imbalanced window pulls on its first sample, having
    # paid to open and earned nothing — a cost with no exposure to show for it.
    min_hold_s: int = 600

    def __post_init__(self) -> None:
        if self.band_ticks <= 0:
            raise ValueError("a band with no width is not a band")
        if self.clear_samples is not None and self.clear_samples < 1:
            raise ValueError("re-entry must require at least one clear sample")
        if self.min_hold_s < 0:
            raise ValueError("minimum hold cannot be negative")


def unsafe(obs: Observation, params: Params, meta: PoolMeta) -> tuple[bool, str, dict]:
    """Is the pool unsafe right now, and which arm of section 3.4 says so?

    Calls the shared `toxicity()` rather than restating the rule. Section 3.4 is
    the *spec's* definition of toxic flow, not Warden's — the agents differ in
    what they do about the verdict, not in how it is measured. An earlier draft
    of this function reimplemented the on-chain arm as `lvr_rate > fee_rate`,
    which is the same duplication that let the policy and the engine drift into
    applying two different imbalance rules (matrix V-12). Once is enough.

    Reusing it also means Sentinel inherits both persistence rules for free: the
    gap arm must hold for `m` samples, the imbalance arm fires instantly, exactly
    as section 3.4 specifies.

    Naming which arm fired is not decoration. The two have completely different
    lead times — the CEX gap leads the damage, realized LVR trails it — so a card
    that says "withdrew" without saying "after the fact" overstates what the agent
    knew at the time.
    """
    is_toxic, terms = toxicity(obs, params, meta)
    if not is_toxic:
        return False, "", terms
    if terms.get("imbalance_toxic"):
        return True, "imbalance", terms
    if terms.get("using_onchain_fallback"):
        return True, "realized_lvr", terms
    return True, "cex_gap", terms


def decide_sentinel(
    obs: Observation,
    params: Params,
    meta: PoolMeta,
    config: SentinelParams | None = None,
) -> Decision:
    """Hold wide, leave when unsafe, come back when it has been safe for a while.

    Returns the same `Decision` every other agent does, so the engine, driver,
    journal, LVR accountant and tearsheet need no idea which agent produced it.

    Sentinel's own parameters are a fourth argument rather than a field on
    `Observation`. That is the firewall: `Observation` carries what the *pool*
    looks like, and letting agent config in would open it in the one direction it
    exists to close. `sentinel_policy()` binds this argument and hands the engine
    the three-argument `Policy` it expects.
    """
    config = config or SentinelParams()
    spacing = meta.tick_spacing
    centre = _round_to_spacing(float(obs.tick), spacing)
    width = max(_round_to_spacing(float(config.band_ticks), spacing), spacing)

    position = obs.position
    is_unsafe, rule, terms = unsafe(obs, params, meta)
    clear_needed = config.clear_samples or params.m_clear

    reasons: list[tuple[str, float]] = [
        ("band_ticks", float(width)),
        ("lvr_rate", obs.lvr_rate),
        ("fee_rate", obs.fee_rate),
        ("unsafe", float(is_unsafe)),
        ("unsafe_rule_imbalance", float(rule == "imbalance")),
        ("unsafe_rule_realized_lvr", float(rule == "realized_lvr")),
        ("unsafe_rule_cex_gap", float(rule == "cex_gap")),
        ("clear_samples_required", float(clear_needed)),
        # Every term section 3.4 weighed, carried on every decision including the
        # ones that did nothing. A tearsheet that can only say "it held" is much
        # less useful than one that can say which arm nearly fired and by how
        # much.
        #
        # The two rate terms are listed above unconditionally rather than taken
        # from here, because `toxicity` only reports them on the feed-down path.
        # A journal whose columns depend on whether a CEX feed was up is a
        # journal that cannot be read as a table.
        *sorted((k, v) for k, v in terms.items() if k not in ("lvr_rate", "fee_rate")),
    ]

    if not position.in_market:
        # Out of market, for either reason: never opened, or pulled. Sentinel
        # treats them the same and waits for the same evidence, because "we have
        # not seen trouble yet" and "trouble has passed" are the same claim about
        # the present, differing only in what came before.
        if is_unsafe:
            reasons.append(("reason_wait_unsafe", 1.0))
            return _decision(Action.HOLD, centre, width, obs, reasons, hold=True)
        if obs.clear_streak < clear_needed:
            reasons.append(("reason_wait_clear_streak", 1.0))
            return _decision(Action.HOLD, centre, width, obs, reasons, hold=True)
        reasons.append(("reason_enter", 1.0))
        # MINT the first time, REENTER after a pull. Section 3.4's action is
        # "re-enter when the signal clears", and recording it as a distinct
        # action is what lets a tearsheet count round trips rather than report a
        # suspiciously mint-happy agent.
        action = Action.REENTER if position.last_rebalance_ts > 0 else Action.MINT
        return _decision(action, centre, width, obs, reasons)

    held_for = obs.t - position.minted_ts
    reasons.append(("seconds_held", float(held_for)))

    if is_unsafe and held_for >= config.min_hold_s:
        reasons.append(("reason_pull", 1.0))
        return _decision(Action.PULL, centre, width, obs, reasons, hold=True)

    if config.reanchor_at_edge and not position.contains(obs.tick) and not is_unsafe:
        reasons.append(("reason_reanchor", 1.0))
        return _decision(Action.RECENTER, centre, width, obs, reasons)

    reasons.append(("reason_hold", 1.0))
    return _decision(Action.HOLD, centre, width, obs, reasons, hold=True)


def sentinel_policy(config: SentinelParams | None = None) -> Policy:
    """Bind Sentinel's parameters and return the `Policy` the engine runs."""
    bound = config or SentinelParams()

    def policy(obs: Observation, params: Params, meta: PoolMeta) -> Decision:
        return decide_sentinel(obs, params, meta, bound)

    return policy


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
        # Sentinel has no reservation price and no optimal spread — it does not
        # solve for where the range should be. Reporting the observed log-price
        # and the band's own half-width keeps the journal schema identical
        # without pretending these quantities mean what Warden's do.
        r=obs.y,
        delta_star=float(width),
        reasons=tuple(reasons),
    )
