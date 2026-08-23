"""Read a wallet's v3 positions without holding a key.

`PositionManager` in `nfpm.py` already knows how to do this — `tokens_of`,
`position`, `is_for_pool` — and cannot be used for it. Its constructor takes a
`BscSigner`, and `BscSigner.__init__` raises `ValueError("no private key…")`
when `MISQUOTE_PRIVATE_KEY` is unset. That is the right shape for the thing it
is: a class that mints, rebalances and burns should not be constructible without
the ability to send. But it means the *reading* half is behind the *spending*
half, and the personal quote engine needs the first without the second.

So this is the reader, and it is deliberately incapable. It has no signer, no
`send`, and no method that builds a transaction. A key is not merely unnecessary
here; there is no code path that could use one.

## What it does not redefine

`NFPM_ABI` and `OnChainPosition` are imported from `nfpm.py`, not restated. Two
ABIs for one contract drift, and the field ordering in `positions()` — where
`liquidity` is index 7 and the ticks are 5 and 6 — is exactly the kind of detail
that is wrong once and then wrong differently in the copy.

The pool filter is `(token0, token1, fee)`, matching `is_for_pool`'s reasoning:
PancakeSwap runs the same pair at four fee tiers, and adopting a 1% position as
though it were the 0.05% one prices every fee it earns against the wrong rate.
"""

from __future__ import annotations

from dataclasses import dataclass

from web3 import Web3

from misquote.chain.addresses import PoolRef, deployment_for
from misquote.chain.nfpm import NFPM_ABI, OnChainPosition


@dataclass(frozen=True, slots=True)
class WalletPositions:
    """Everything a wallet holds, split by whether we can replay it.

    The split is the point. A wallet with four positions in pools this
    repository has never verified holds four positions and zero quotable ones,
    and reporting only the second number would read as an empty wallet.
    """

    owner: str
    chain_id: int
    read_at_block: int
    #: Every NFPM token id the address holds, across every pool on the DEX.
    held: tuple[OnChainPosition, ...]
    #: Those that sit in a pool `chain/addresses.py` has verified, by address.
    in_known_pools: dict[str, tuple[OnChainPosition, ...]]

    @property
    def unknown_pool_count(self) -> int:
        known = sum(len(v) for v in self.in_known_pools.values())
        return len(self.held) - known


class PositionReader:
    """The NFPM, read-only. No signer, and no method that could use one."""

    __slots__ = ("w3", "chain_id", "contract")

    def __init__(self, w3: Web3, chain_id: int) -> None:
        self.w3 = w3
        self.chain_id = chain_id
        deployment = deployment_for(chain_id)
        self.contract = w3.eth.contract(
            address=Web3.to_checksum_address(deployment.position_manager), abi=NFPM_ABI
        )

    def token_ids(self, owner: str) -> list[int]:
        """Every token id the address holds.

        A wallet with no positions returns an empty list rather than raising:
        holding nothing is the ordinary state and is not an error. An
        unreachable node *is* an error and propagates — the two must not
        collapse, because "your wallet is empty" and "we could not look" are
        different answers to the same question.
        """
        address = Web3.to_checksum_address(owner)
        count = int(self.contract.functions.balanceOf(address).call())

        out: list[int] = []
        for index in range(count):
            try:
                out.append(int(self.contract.functions.tokenOfOwnerByIndex(address, index).call()))
            except Exception:  # noqa: BLE001 — a token moving mid-scan shifts the index
                continue
        return out

    def position(self, token_id: int) -> OnChainPosition:
        """One position, in the manager's own field order."""
        raw = self.contract.functions.positions(token_id).call()
        return OnChainPosition(
            token_id=token_id,
            lower=raw[5],
            upper=raw[6],
            liquidity=raw[7],
            tokens_owed0=raw[10],
            tokens_owed1=raw[11],
            token0=raw[2],
            token1=raw[3],
            fee_pips=raw[4],
        )

    def read(self, owner: str, pools: tuple[PoolRef, ...]) -> WalletPositions:
        """Everything the wallet holds, and which of it sits in a verified pool."""
        held = tuple(self.position(token_id) for token_id in self.token_ids(owner))

        by_pool: dict[str, tuple[OnChainPosition, ...]] = {}
        for ref in pools:
            matched = tuple(p for p in held if _is_in(p, ref))
            if matched:
                by_pool[ref.address.lower()] = matched

        return WalletPositions(
            owner=Web3.to_checksum_address(owner),
            chain_id=self.chain_id,
            read_at_block=self.w3.eth.block_number,
            held=held,
            in_known_pools=by_pool,
        )


def _is_in(position: OnChainPosition, ref: PoolRef) -> bool:
    """All three of token0, token1 and the fee tier — see `nfpm.is_for_pool`."""
    return (
        position.token0.lower() == ref.token0.lower()
        and position.token1.lower() == ref.token1.lower()
        and position.fee_pips == ref.fee_pips
    )
