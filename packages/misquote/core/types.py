"""The shapes the whole system passes around.

`Observation` is the important one. It is the complete and exhaustive list of
what the policy is allowed to see, and it contains nothing but scalars — no
event, no list, no cursor, no database handle. That is not a stylistic
preference: it is the primary reason look-ahead is structurally impossible here
rather than merely tested for. You cannot read the future through a float.

Everything is a frozen slotted dataclass, so a decision cannot be mutated after
the fact and two runs over the same inputs produce values that compare equal
bit for bit — which is what makes test T1's "bitwise" requirement cheap to
express.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

Tick = int


@dataclass(frozen=True, slots=True)
class PoolMeta:
    """Static facts about the pool. Read from chain once, then carried around."""

    address: str
    chain_id: int
    token0: str
    token1: str
    dec0: int
    dec1: int
    fee_pips: int  # 100 | 500 | 2500 | 10000 on Pancake v3
    tick_spacing: int  # 1   | 10  | 50   | 200

    @property
    def fee_bps(self) -> float:
        """The fee tier in basis points, the unit the toxicity rule compares in."""
        return self.fee_pips / 100.0


@dataclass(frozen=True, slots=True)
class Event:
    """One chain event, in the single shape the whole system uses.

    Amounts are signed from the *pool's* perspective, matching the Swap event as
    emitted: positive means the pool received that token. `sqrt_price_x96`,
    `liquidity`, and `tick` are the post-event state, again as emitted.

    `(block, log_index)` is the total order everything relies on for
    determinism.
    """

    block: int
    log_index: int
    ts: int
    kind: str  # "swap" | "mint" | "burn" | "collect"
    tx: str
    amount0: int
    amount1: int
    sqrt_price_x96: int
    liquidity: int
    tick: int
    tick_lower: Tick | None = None  # mint and burn only
    tick_upper: Tick | None = None

    @property
    def key(self) -> tuple[int, int]:
        return (self.block, self.log_index)


@dataclass(frozen=True, slots=True)
class PositionState:
    """Where the position is right now.

    `lower is None` means out of market — either not yet minted, or withdrawn by
    the toxicity pull. Those are the same state as far as the policy is
    concerned, and distinguishing them is the driver's job.
    """

    lower: Tick | None
    upper: Tick | None
    liquidity: int
    token_id: int | None  # NFPM tokenId; None for a hypothetical replay position
    minted_ts: int
    last_rebalance_ts: int
    rebalances_today: int

    @property
    def in_market(self) -> bool:
        return self.lower is not None and self.upper is not None

    @property
    def center(self) -> Tick | None:
        if self.lower is None or self.upper is None:
            return None
        return (self.lower + self.upper) // 2

    def contains(self, tick: Tick) -> bool:
        if self.lower is None or self.upper is None:
            return False
        return self.lower <= tick < self.upper


@dataclass(frozen=True, slots=True)
class Observation:
    """Everything the policy may see. Scalars only.

    If you find yourself wanting to add a list or an object here, that is the
    firewall working: whatever you were about to do wants information the policy
    is not supposed to have, and the estimator that computes the scalar belongs
    upstream instead.
    """

    t: int  # decision time — the head block's timestamp, never a wall clock
    tick: Tick
    y: float  # ln(price), decimal-adjusted
    sqrt_price_x96: int
    pool_liquidity: int

    q: float  # inventory imbalance, spec section 2, in [-1, 1]
    sigma: float  # per sqrt-hour, spec section 5.1
    kappa: float  # fee-capture intensity decay, spec section 5.2
    kappa_r2: float
    kappa_is_fallback: bool  # if true, the card must say so
    T_t: float  # hours remaining in the rolling window W

    gas_cost_quote: float  # trailing median gas x current price, in token1
    slippage_quote: float
    # Two fee rates, because R2 asks for a *gain*: what the target range would
    # earn against what staying put would earn. One rate alone cannot express a
    # difference.
    fee_rate_per_liquidity_target: float  # trailing fee per unit L per hour, target range
    fee_rate_per_liquidity_current: float  # ... and the range we are in now
    target_liquidity: int  # what the same capital buys at the target width
    position_value_quote: float
    rebalance_notional_quote: float  # what a recentre would actually swap (A4's base)

    cex_gap: float | None  # None means the feed is down; the fallback rule applies
    swap_imbalance_z: float
    lvr_rate: float  # trailing realized LVR per hour
    fee_rate: float  # trailing realized fees per hour

    # Consecutive *prior* samples on which the currently-active gap rule held —
    # the CEX-gap rule when the feed is up, the LVR-vs-fees rule when it is not.
    # The current sample is not included, which is why the policy tests
    # `toxic_streak + 1 >= m`.
    #
    # The driver's contract, and it is easy to get wrong: this counts the *gap
    # arm only*. Section 3.4 requires the gap rule to persist for `m` samples
    # while the imbalance rule fires instantly, so incrementing this on the
    # overall toxic verdict would let a single imbalance spike satisfy the gap
    # arm's persistence requirement. It must also reset when the feed goes down
    # or comes back, since a streak accumulated under one rule says nothing
    # about the other.
    toxic_streak: int
    clear_streak: int  # consecutive samples with no toxicity at all

    position: PositionState

    def __post_init__(self) -> None:
        """Refuse states that would invert the strategy rather than fail.

        A negative horizon flips the sign of the inventory skew: excess token0
        would push the range *up*, making the position a keener buyer of what it
        already holds too much of — the exact inverse of the intended economics,
        and it produces a perfectly plausible range on the wrong side of the
        market. No exception, no NaN, nothing to notice. Given that everything
        else here fails loudly on a broken invariant, this should too.
        """
        if self.T_t < 0.0:
            raise ValueError(f"T_t must not be negative, got {self.T_t}: the skew would invert")
        if self.sigma < 0.0:
            raise ValueError(f"sigma must not be negative, got {self.sigma}")
        if self.kappa <= 0.0:
            raise ValueError(
                f"kappa must be positive, got {self.kappa}: equation (2) divides by it"
            )
        if not -1.0 <= self.q <= 1.0:
            raise ValueError(f"q must lie in [-1, 1] per spec section 2, got {self.q}")
        if self.toxic_streak < 0 or self.clear_streak < 0:
            raise ValueError("streak counters cannot be negative")


@dataclass(frozen=True, slots=True)
class Params:
    """Policy parameters. Every default is published in docs/ASSUMPTIONS.md.

    Values marked with their matrix ID were unspecified in the frozen spec and
    are proposed here; the rest are the spec's own section 8 defaults.
    """

    gamma: float = 0.8
    theta: float = 0.5
    tau_cool_s: int = 7200
    w_min_mult: int = 4
    mev_haircut_bps: float = 10.0
    z_pull: float = 2.5
    m_toxic: int = 3
    m_clear: int = 10
    window_hours: float = 24.0
    max_rebalances_per_day: int = 8

    # Spec section 8's Δs. Published in the assumption sheet but previously
    # absent from the code, which made that row trace to nothing — and made `m`
    # dimensionless: "3 consecutive samples" only means 15 seconds if the
    # sampler actually runs every 5.
    sample_interval_s: int = 5

    # Spec assumption A5's K: the number of rolling sub-windows a P25-P75 range
    # is computed over.
    replay_windows: int = 20

    kappa_r2_floor: float = 0.5

    arb_cost_bps: float = 5.0  # G-2
    imbalance_window: int = 50  # G-1
    inrange_floor: float = 0.70  # G-3
    eps_liquidity_share: float = 0.01  # A1

    def __post_init__(self) -> None:
        if self.gamma <= 0:
            raise ValueError("gamma must be positive: it divides in equation (2)")
        if not 0 < self.theta:
            raise ValueError("theta must be positive")
        if self.m_toxic < 1 or self.m_clear < 1:
            raise ValueError("toxicity sample counts must be at least 1")
        if self.sample_interval_s < 1:
            raise ValueError("sample interval must be at least a second")
        if self.replay_windows < 20:
            raise ValueError("assumption A5 requires at least 20 sub-windows for a P25-P75 range")


class Action(StrEnum):
    HOLD = "hold"
    MINT = "mint"
    RECENTER = "recenter"
    PULL = "pull"
    REENTER = "reenter"


@dataclass(frozen=True, slots=True)
class Decision:
    """What to do, and every number that argued for or against it.

    `reasons` is a tuple of pairs rather than a dict so the whole decision stays
    hashable and compares by exact value. It carries *all* of R1 through R4 and
    the toxicity terms on every decision, including the ones that did nothing,
    because a tearsheet that can only say "it did not rebalance" is much less
    useful than one that can say which gate held it back and by how much.
    """

    action: Action
    target_lower: Tick | None
    target_upper: Tick | None
    center_tick: Tick
    half_width_ticks: int
    r: float  # equation (1)
    delta_star: float  # equation (2), already halved
    reasons: tuple[tuple[str, float], ...]

    def reason(self, name: str) -> float:
        for key, value in self.reasons:
            if key == name:
                return value
        raise KeyError(f"{name!r} not among {[k for k, _ in self.reasons]}")

    @property
    def moves(self) -> bool:
        return self.action is not Action.HOLD
