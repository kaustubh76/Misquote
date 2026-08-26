"""Registering this project's own agents, which is the only thing here that signs.

`erc8004.IdentityRegistry` reads the registry; this writes to it. They are
separate classes rather than one, for the reason `chain/positions.py` is separate
from `chain/nfpm.py`: the reader is constructed from a `Web3` and is used by the
API on every request, and giving it a key would mean every read path in the
service was one typo away from a write path.

## Why this lives in `registry/` and not in `chain/`

`chain/` is the I/O layer, and its own docstring says nothing that computes a
number may also be able to spend money. But the addresses, the ABI and the
schema this needs all live in `erc8004.py`, and `registry/` is a driver layer,
which may import `chain/`. Putting the writer here means one module imports the
signer; putting it in `chain/` would mean `chain/` imports `registry/`, which
inverts the layering for no gain.

`registry/erc8183.py` is AST-guarded against importing web3 at all, and stays
that way — that module models the *hire* flow, which is not what this is.

## What it will not do

There is no `register_all`, no retry loop and no "make sure it exists" helper.
Each call sends one transaction. The sequencing, the receipts and the record
belong to `scripts/register_identity.py`, where a human can read them in order —
a convenience method that registered four agents would also be a method that
registered four agents twice if someone ran it twice, and the registry has no
notion of idempotence to save them.

## Reading the new id from the mint, not from the wallet

`register` returns the agent id off the `Transfer` log of its own receipt. The
obvious alternative — register, then ask the registry what the highest id is, or
what this wallet owns — is wrong in the way that only shows up under load:
between the two calls somebody else registers, and the agent is confidently
recorded under a stranger's id. `ChainExecutor.mint` reads `IncreaseLiquidity`
for exactly this reason and says so.
"""

from __future__ import annotations

import json
from typing import Any

from web3 import Web3

from misquote.chain.signer import BscSigner, SentTransaction
from misquote.registry.erc8004 import IDENTITY_REGISTRY

#: Only what this module calls. Four entries, two of which are writes.
#:
#: Deliberately not merged into `erc8004.IDENTITY_ABI`, which is four `view`
#: functions and is handed to the reader the API uses. An ABI is a capability:
#: adding `register` to the one the read path binds would put a nonpayable call
#: on an object whose whole point is that it cannot make one.
WRITE_ABI = json.loads("""[
 {"name":"register","type":"function","stateMutability":"nonpayable",
  "inputs":[{"name":"tokenURI","type":"string"}],
  "outputs":[{"name":"agentId","type":"uint256"}]},
 {"name":"setAgentURI","type":"function","stateMutability":"nonpayable",
  "inputs":[{"name":"agentId","type":"uint256"},{"name":"tokenURI","type":"string"}],
  "outputs":[]},
 {"name":"safeTransferFrom","type":"function","stateMutability":"nonpayable",
  "inputs":[{"name":"from","type":"address"},{"name":"to","type":"address"},
            {"name":"tokenId","type":"uint256"}],"outputs":[]},
 {"name":"tokenURI","type":"function","stateMutability":"view",
  "inputs":[{"type":"uint256"}],"outputs":[{"type":"string"}]},
 {"name":"ownerOf","type":"function","stateMutability":"view",
  "inputs":[{"type":"uint256"}],"outputs":[{"type":"address"}]}
]""")

#: ERC-721's mint event. A `register` receipt carries one, from the zero address.
TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()

ZERO = "0x0000000000000000000000000000000000000000"


class RegistrationNotObserved(RuntimeError):
    """The transaction succeeded and no mint could be read out of it.

    Distinct from a revert, which `BscSigner.send` already raises for. This is
    the worse case: something was written to chain and this process does not
    know what. It is raised rather than returning `None` so a caller cannot
    record a registration under an id it guessed.
    """


class IdentityWriter:
    """One registry, one signer, one transaction per call."""

    __slots__ = ("signer", "chain_id", "address", "contract", "sent")

    def __init__(self, signer: BscSigner, chain_id: int | None = None) -> None:
        chain_id = signer.chain_id if chain_id is None else int(chain_id)
        if chain_id != signer.chain_id:
            raise ValueError(
                f"registry is on chain {chain_id} and the signer is on {signer.chain_id}"
            )
        if chain_id not in IDENTITY_REGISTRY:
            raise ValueError(
                f"no ERC-8004 identity registry is recorded for chain {chain_id}; "
                f"known: {sorted(IDENTITY_REGISTRY)}"
            )

        self.signer = signer
        self.chain_id = chain_id
        self.address = Web3.to_checksum_address(IDENTITY_REGISTRY[chain_id])
        self.contract = signer.w3.eth.contract(address=self.address, abi=WRITE_ABI)
        #: Every receipt, in order. `gas_spent_wei` is derived from these rather
        #: than from estimates, following `ChainExecutor.sent`.
        self.sent: list[SentTransaction] = []

    # --- writes ------------------------------------------------------------

    def register(self, token_uri: str) -> tuple[int, SentTransaction]:
        """Mint an identity to the signer, and return the id chain gave it."""
        if not token_uri.strip():
            raise ValueError("refusing to register an empty tokenURI")

        call = self.contract.functions.register(token_uri)
        result = self.signer.send(self.signer.build(call))
        self.sent.append(result)
        return self._minted_id(result), result

    def transfer(self, agent_id: int, to: str) -> SentTransaction:
        """Hand the identity to its owner.

        `safeTransferFrom` rather than `transferFrom`: the destination here is
        the address a human typed into a config file, and the safe variant is
        the one that reverts instead of stranding the token if that address
        turns out to be a contract that cannot hold one.
        """
        destination = Web3.to_checksum_address(to)
        if destination == Web3.to_checksum_address(ZERO):
            raise ValueError("refusing to transfer an identity to the zero address")

        holder = self.owner_of(agent_id)
        if Web3.to_checksum_address(holder) != Web3.to_checksum_address(self.signer.address):
            raise ValueError(
                f"agent {agent_id} is owned by {holder}, not by the signer "
                f"{self.signer.address}; this transfer would revert"
            )

        call = self.contract.functions.safeTransferFrom(self.signer.address, destination, agent_id)
        result = self.signer.send(self.signer.build(call))
        self.sent.append(result)
        return result

    def set_agent_uri(self, agent_id: int, token_uri: str) -> SentTransaction:
        """Rewrite a registered agent's card. Owner only.

        The registry checks the caller against the token's owner and reverts
        `Not authorized` otherwise, so this is only usable by whoever holds the
        identity — which, after `transfer`, is not the wallet that registered it.
        That asymmetry is why the ordering matters: a card completed *before*
        handover needs no operator key, and one completed after needs exactly
        that key.

        The same owner check is made here, before building anything, for the
        reason `transfer` makes it: a reverted receipt says a transaction
        failed, not which agent belongs to whom.
        """
        if not token_uri.strip():
            raise ValueError("refusing to set an empty tokenURI")

        holder = self.owner_of(agent_id)
        if Web3.to_checksum_address(holder) != Web3.to_checksum_address(self.signer.address):
            raise ValueError(
                f"agent {agent_id} is owned by {holder}, not by the signer "
                f"{self.signer.address}; setAgentURI is owner-only and would revert"
            )

        call = self.contract.functions.setAgentURI(agent_id, token_uri)
        result = self.signer.send(self.signer.build(call))
        self.sent.append(result)
        return result

    # --- reads, for checking the writes ------------------------------------

    def owner_of(self, agent_id: int) -> str:
        return str(self.contract.functions.ownerOf(agent_id).call())

    def token_uri(self, agent_id: int) -> str:
        return str(self.contract.functions.tokenURI(agent_id).call())

    @property
    def gas_spent_wei(self) -> int:
        return sum(tx.gas_cost_wei for tx in self.sent)

    # --- internals ---------------------------------------------------------

    def _minted_id(self, result: SentTransaction) -> int:
        """The id, read out of the mint log of this transaction and no other."""
        receipt: Any = self.signer.w3.eth.get_transaction_receipt(result.tx_hash)
        wanted = _topic(TRANSFER_TOPIC)
        signer = Web3.to_checksum_address(self.signer.address)

        for log in receipt["logs"]:
            if Web3.to_checksum_address(log["address"]) != self.address:
                continue
            topics = [_topic(t) for t in log["topics"]]
            # A mint: Transfer(from=0x0, to=signer, tokenId), all three indexed.
            if len(topics) != 4 or topics[0] != wanted:
                continue
            if int(topics[1], 16) != 0:
                continue
            if Web3.to_checksum_address("0x" + topics[2][-40:]) != signer:
                continue
            return int(topics[3], 16)

        raise RegistrationNotObserved(
            f"{result.tx_hash} succeeded but carried no ERC-721 mint from the "
            f"registry to {signer}. Something is registered and this process "
            "cannot say under which id — read the transaction before retrying, "
            "because retrying would register a second one."
        )


def _topic(value: Any) -> str:
    """Topics arrive as `HexBytes` from a node and as `str` from a stub."""
    if isinstance(value, str):
        return value if value.startswith("0x") else "0x" + value
    return "0x" + bytes(value).hex()
