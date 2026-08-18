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

from collections.abc import Callable
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

    # Pancake's protocol fee, as a numerator out of 10,000, read from
    # `slot0.feeProtocol`. Unlike Uniswap it is ON by default — 3400 on our
    # target pool, so LPs keep 66% of every swap fee. Defaulting to 0 here would
    # quietly reinstate the 1.52x overstatement this field exists to prevent, so
    # it has no default and must be read from chain.
    fee_protocol: int

    @property
    def fee_bps(self) -> float:
        """The fee tier in basis points, the unit the toxicity rule compares in."""
        return self.fee_pips / 100.0

    @property
    def lp_fee_bps(self) -> float:
        """What an LP actually earns, after the protocol takes its share."""
        return self.fee_bps * (1.0 - self.fee_protocol / 10_000.0)


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

    # PancakeSwap's Swap event carries two fields Uniswap's does not: how much
    # of this swap's fee the protocol took before liquidity providers saw any of
    # it. That makes the 34% cut a chain-sourced number per swap rather than a
    # governance parameter we model. Zero on mints and burns.
    protocol_fee0: int = 0
    protocol_fee1: int = 0

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

        # The imbalance z-score is bounded by sqrt(M) — its extreme is every
        # swap in the window the same size and the same direction. A z_pull at
        # or above that ceiling is a threshold nothing can ever cross: the rule
        # would read as configured, report a sensible-looking number on every
        # card, and never once fire.
        #
        # This project has now shipped two gates wired to nothing, both found by
        # accident rather than by a test. Making the unreachable case refuse to
        # construct is cheaper than finding the third the same way.
        import math

        ceiling = math.sqrt(self.imbalance_window)
        if self.z_pull >= ceiling:
            raise ValueError(
                f"z_pull={self.z_pull} is unreachable with M={self.imbalance_window}: "
                f"the z-score cannot exceed sqrt(M)={ceiling:.2f}, so the imbalance "
                "arm of section 3.4 could never fire"
            )


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


# What one recentre costs in gas — burn, collect, mint — in token1.
#
# It lives in core because it existed in two places and they disagreed.
# `replay.driver.CostModel` and `chain.source.TapeChainSource` each carried
# their own default, so correcting one and not the other changed what the two
# drivers charged for the same move — and **test L1 failed on the next run**,
# which is exactly what L1 is for. Both read this now.
#
# 600,000 gas units at BSC's prevailing 0.05 gwei is 3.0e-5 BNB, about two
# cents. `chain/live_source.py` derives the same figure from the chain at
# runtime (`REBALANCE_GAS_UNITS * eth_gasPrice / 1e18`); this is the constant
# the replay uses when there is no chain to ask.
#
# **What is still not implemented:** A4 promises "gas at the gas price
# prevailing in the historical block". The swap tape carries no gas price — the
# schema has no column for one — so a replay charges today's gas for a move made
# three weeks ago. Recording that rather than quietly meeting a weaker standard.
DEFAULT_GAS_QUOTE = 3.0e-5


# The largest position assumption A1's 1% ceiling permits on the target pool,
# measured 18 Aug 2026 against its real liquidity:
#
#     range +/-  20 ticks ->  1.03 WBNB  (~$631)
#     range +/-  60 ticks ->  3.09 WBNB  (~$1,892)
#     range +/-1000 ticks -> 50.26 WBNB  (~$30,810)
#
# The default was **1000**, which in quote currency is ~$613,000 and breaches A1
# in every range this pool supports. Nothing said so: the driver clamped to 1% and
# published the quote anyway, so a position deploying 3 WBNB had its earnings
# divided by the 1,000 it never held. A1 says such a quote is refused rather than
# rendered, and it now is — so a default that always breaches would refuse every
# quote. 1.0 fits the narrowest range with margin. See P-14.
DEFAULT_CAPITAL_QUOTE = 1.0


# What an agent *is*, to this system: a pure function from everything it may
# observe to what it intends to do. Nothing else — no pool handle, no clock, no
# I/O. An agent wanting any of those would have to ask through `Observation`,
# which is scalars only, which is why look-ahead here is structurally impossible
# rather than merely forbidden.
#
# It lives in core rather than in the replay engine because it is the contract
# between an agent and the marketplace, not a detail of one runner. Putting it
# next to the engine would mean every agent had to import the engine to state its
# own type.
Policy = Callable[[Observation, Params, PoolMeta], Decision]
