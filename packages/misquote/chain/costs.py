"""What a venue switch actually costs, assembled from readings.

`replay/allocation.SwitchCost` knows how to combine a fee, a gas-unit count, a
gas price and a native-token price. It deliberately cannot fetch any of them —
it lives in a pure layer. This is the IO half that goes and gets them.

Two inputs, two sources, both already in this repository:

- **Gas price** comes from the chain, the way `chain/live_source.py` gets it for
  the LP agents (`eth_gasPrice`).
- **The native token's price** comes from the swap tape's own last observation
  of the verified WBNB/USDT pool. Gas is denominated in BNB and Router keeps its
  books in dollars; something has to bridge them, and the honest bridge is the
  pool this project already indexes rather than a number typed in.

Either may be unavailable — no network, or no swap tape. Then `SwitchCost` falls
back and **records that it did**, because a cost that quietly defaults is how
`gas_quote = 0.30` survived long enough to decide a published finding.
"""

from __future__ import annotations

import sqlite3

from ..replay.allocation import SwitchCost
from .addresses import TARGET_POOL
from .venus import STABLE_SWAP_VENUE, VENUS_SWITCH_GAS_UNITS

#: BSC's prevailing gas price when nothing can be asked. The same 0.05 gwei
#: `core/types.py`'s `DEFAULT_GAS_QUOTE` comment records as measured.
FALLBACK_GAS_PRICE_WEI = 50_000_000


def native_price_from_tape(conn: sqlite3.Connection) -> float | None:
    """Dollars per BNB, from the last swap on the verified WBNB/USDT pool.

    The pool's `token0` is the stablecoin and `token1` is WBNB — address-sorted,
    which is not the order the pair is named in, and `PoolRef`'s docstring warns
    that getting it backwards inverts every price in the system. So
    `sqrtPriceX96` gives **BNB per dollar**, a number below one, and dollars per
    BNB is its reciprocal.
    """
    row = conn.execute(
        "SELECT sqrt_price_x96 FROM swap WHERE pool = ? ORDER BY block DESC, log_index DESC LIMIT 1",
        (TARGET_POOL.address.lower(),),
    ).fetchone()
    if not row or not row[0]:
        return None
    sqrt_price = int(row[0])
    if sqrt_price <= 0:
        return None
    # Both tokens are 18 decimals on this pool, so no decimal adjustment.
    bnb_per_dollar = (sqrt_price / (1 << 96)) ** 2
    if bnb_per_dollar <= 0:
        return None
    return 1.0 / bnb_per_dollar


def observed_gas_price_wei(chain_id: int = 56) -> int | None:
    """`eth_gasPrice`, or None when no endpoint answers."""
    try:
        # The indexer's endpoint list and rotation, reused rather than a second
        # copy of "which BSC RPCs answer" — a list that has already been wrong
        # once here (P-11).
        from ..indexer.reader import BscReader, connect_all  # noqa: PLC0415

        endpoints = connect_all(chain_id, on_reject=lambda *_: None)
        if not endpoints:
            return None
        reader = BscReader(endpoints, pace_seconds=0.0)
        return int(reader._call(lambda w3: w3.eth.gas_price))
    except Exception:  # noqa: BLE001 — absence is a state, not an error
        return None


def switch_cost(conn: sqlite3.Connection | None, *, allow_network: bool = True) -> SwitchCost:
    """The cost of one switch, derived as far as the inputs allow."""
    gas_price = observed_gas_price_wei() if allow_network else None
    native = native_price_from_tape(conn) if conn is not None else None
    if gas_price is None and native is not None:
        # The tape can price BNB but no endpoint answered for gas. That is a
        # better position than no inputs at all: use the measured prevailing
        # rate and let `derived` stay true only when both were read.
        gas_price = FALLBACK_GAS_PRICE_WEI
        return SwitchCost.from_venue(
            STABLE_SWAP_VENUE,
            gas_units=VENUS_SWITCH_GAS_UNITS,
            gas_price_wei=gas_price,
            native_price_quote=native,
        ).with_basis_note("gas price is the stated 0.05 gwei fallback, not a reading")
    return SwitchCost.from_venue(
        STABLE_SWAP_VENUE,
        gas_units=VENUS_SWITCH_GAS_UNITS,
        gas_price_wei=gas_price,
        native_price_quote=native,
    )
