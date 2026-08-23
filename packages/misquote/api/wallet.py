"""What a wallet actually holds, which is where a personal quote starts.

The quote engine's question is "what would these agents have done with *your*
positions", and it cannot be asked until the positions are known. This is that
read: token ids from the NFPM, each resolved to its ticks and liquidity, split
by whether the pool is one this repository has verified and indexed.

## The split is the answer, not a filter

A wallet with four positions in pools nobody here has read holds four positions
and zero quotable ones. Reporting only the quotable count would render as an
empty wallet, and the reader would conclude the service could not see their
money. So `held` is everything and `in_known_pools` is the subset, with the
difference named — `unquotable` is a number a reader can act on, because the
action is "we would need to index that pool".

## No key, by construction

`chain/positions.py::PositionReader` has no signer and no method that builds a
transaction, which is why it exists at all rather than this route using
`PositionManager` — that class takes a `BscSigner`, and `BscSigner` refuses to
construct without a private key. A read-only endpoint that required a spending
key to answer would be the wrong shape even if it worked.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from misquote.api import rpc
from misquote.api.errors import refuse
from misquote.chain.addresses import known_pools_on
from misquote.chain.positions import PositionReader

DEFAULT_CHAIN_ID = 56

#: A 20-byte hex address. Checked before an RPC round trip, so a typo comes back
#: as a typo rather than as an empty wallet.
ADDRESS_LENGTH = 42


def _valid(address: str) -> bool:
    if len(address) != ADDRESS_LENGTH or not address.startswith("0x"):
        return False
    try:
        int(address, 16)
    except ValueError:
        return False
    return True


def wallet_positions(address: str, chain_id: int = DEFAULT_CHAIN_ID) -> dict[str, Any]:
    """Every v3 position the address holds, and which of them we could replay."""
    if not _valid(address):
        raise refuse(
            400,
            error=f"{address!r} is not a 20-byte hex address",
            remedy="pass a 0x-prefixed 40-hex-digit address",
            note=(
                "Refused before the chain read rather than after: an unreachable "
                "address and an empty wallet return the same thing from an RPC, and "
                "a typo must not come back as 'you hold nothing'."
            ),
        )

    pools = known_pools_on(chain_id)
    if not pools:
        raise refuse(
            404,
            error=f"no verified pool on chain {chain_id}",
            remedy="see `packages/misquote/chain/addresses.py::KNOWN_POOLS`",
            available=[str(DEFAULT_CHAIN_ID)],
        )

    w3 = rpc.connect(chain_id)
    reader = PositionReader(w3, chain_id)
    found = reader.read(address, pools)

    return {
        "owner": found.owner,
        "chain_id": found.chain_id,
        "read_at_block": found.read_at_block,
        "held": len(found.held),
        "unquotable": found.unknown_pool_count,
        "positions": {
            pool: [dataclasses.asdict(p) for p in positions]
            for pool, positions in found.in_known_pools.items()
        },
        "known_pools": [ref.address.lower() for ref in pools],
        "note": (
            "`held` counts every v3 position this wallet owns on the DEX. "
            "`positions` carries only those in pools this repository has verified "
            "and indexed — the rest cannot be replayed, because a pool's fee tier "
            "and protocol cut decide what its swaps mean."
        ),
    }
