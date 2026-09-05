"""Signing and broadcasting, with the guards in the order that matters.

Ported from PolyLambda's `execution/testnet_chain.py::AmoySigner`, with three
changes, each of which is a bug that project could still hit.

**The chain-id guard runs before signing, not after.** A signature over a
wrong-chain transaction is a replayable artefact that exists whether or not it
is broadcast. Checking after signing means the dangerous object has already been
created.

**The kill file is checked immediately before broadcast**, inside this module,
so no caller can route around it. A kill switch that lives in the event loop is
a kill switch that only works while the event loop is healthy.

**A revert is never retried.** `_TRANSIENT` in the reader deliberately omits
reverts, and this module additionally refuses to resend a transaction that
already mined with `status == 0` — that is an answer, not a failure.

And the finding from step 10, which is the reason this file exists in this
shape: **`wait_for_transaction_receipt` does not raise when a transaction
reverts.** It returns an ordinary receipt with `status == 0`. Everything here
funnels through `send()`, which raises on a reverted receipt, because an
unchecked revert leaves the agent believing it holds a position it does not.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_account import Account
from web3 import Web3

from misquote.chain.operator import assert_signs_for_operator
from misquote.indexer.reader import is_transient, rpc_retry

SUPPORTED_CHAINS = (56, 97)  # BSC mainnet, chapel testnet

# Anything else is a configuration error, and signing for it would produce a
# valid signature for a chain we never meant to touch.
NONCE_RACE_MARKERS = ("nonce too low", "already known", "replacement transaction underpriced")

DEFAULT_KILL_FILE = "ops/KILL"

#: The most this will pay for gas, in wei per unit, unless told otherwise.
#:
#: There was no ceiling at all until a run with a 0.005757 BNB wallet went
#: looking for one. `build` takes `w3.eth.gas_price` verbatim and multiplies the
#: estimate by 1.25, so the only thing standing between a price spike and an
#: empty wallet was the balance — which is a limit that reports itself by the
#: transaction failing, after the earlier ones have already been paid for.
#:
#: 1 gwei is twenty times BSC's typical 0.05 and still leaves the whole planned
#: run inside that budget. It is deliberately a refusal rather than a clamp:
#: quietly bidding less than the node asks produces a transaction that sits
#: unmined, which is a worse failure than being told the price moved.
DEFAULT_MAX_GAS_PRICE_WEI = 1_000_000_000


class GasPriceTooHigh(RuntimeError):
    """The node's gas price is above the ceiling. Nothing was signed."""


class KillSwitchEngaged(RuntimeError):
    """The kill file exists. Nothing is broadcast while it does."""


class TransactionReverted(RuntimeError):
    """Mined with status 0. An answer, not a failure — never retried."""

    def __init__(self, tx_hash: str, receipt: dict[str, Any]) -> None:
        self.tx_hash = tx_hash
        self.receipt = receipt
        super().__init__(
            f"transaction {tx_hash} reverted "
            f"(gas used {receipt.get('gasUsed', 0):,}, {len(receipt.get('logs', []))} logs). "
            "Low gas with no logs usually means the selector does not exist on that contract."
        )


class DryRunRefusal(RuntimeError):
    """`MISQUOTE_DRY_RUN` is set. The read path works; the write path does not."""


@dataclass(frozen=True, slots=True)
class SentTransaction:
    tx_hash: str
    block: int
    gas_used: int
    effective_gas_price: int

    @property
    def gas_cost_wei(self) -> int:
        return self.gas_used * self.effective_gas_price


class BscSigner:
    """Holds a key, and is the only thing in the system that does.

    Dry run is the default. `MISQUOTE_DRY_RUN` must be explicitly `0` to enable
    broadcasting, so an unset environment variable cannot spend anything — the
    failure mode of a missing config is refusing to trade, never trading
    unintentionally.
    """

    __slots__ = (
        "w3",
        "chain_id",
        "account",
        "kill_file",
        "_dry_run",
        "_receipt_timeout",
        "_peers",
        "_max_gas_price_wei",
    )

    def __init__(
        self,
        w3: Web3,
        private_key: str | None = None,
        *,
        kill_file: str | Path = DEFAULT_KILL_FILE,
        receipt_timeout: float | None = None,
        max_gas_price_wei: int | None = None,
        peer_rpcs: tuple[str, ...] = (),
    ) -> None:
        chain_id = int(w3.eth.chain_id)
        if chain_id not in SUPPORTED_CHAINS:
            raise ValueError(
                f"refusing to sign for chain {chain_id}; this agent only knows {SUPPORTED_CHAINS}"
            )

        key = private_key or os.environ.get("MISQUOTE_PRIVATE_KEY")
        if not key:
            raise ValueError(
                "no private key. Set MISQUOTE_PRIVATE_KEY, and set it to a dedicated "
                "hot wallet holding only the capped capital — never a main wallet."
            )

        self.w3 = w3
        self.chain_id = chain_id
        self.account = Account.from_key(key)
        self.kill_file = Path(kill_file)
        # Configurable because 180s is not enough against a load-balanced
        # endpoint, and the failure mode is the expensive one. Two mainnet runs
        # have now died here *after their transactions mined* — the second was
        # `approve` on the ERC-8183 escrow, which had already set its allowance
        # by the time this gave up. A caller that treats the timeout as failure
        # and resends is the thing the error text warns against, so the knob to
        # wait longer belongs beside it.
        if receipt_timeout is None:
            configured = os.environ.get("MISQUOTE_RECEIPT_TIMEOUT_S")
            receipt_timeout = 180.0 if configured is None else float(configured)
        self._receipt_timeout = receipt_timeout
        # Endpoints to ask for a receipt *besides* the one that took the send.
        #
        # `bsc-dataseed.bnbchain.org` is load-balanced: the node that accepts a
        # transaction and the node asked for its receipt seconds later need not
        # be the same one, and the second can be blocks behind. Three mainnet
        # runs have now stalled here on transactions that were already mined —
        # most recently `approve` on the ERC-8183 escrow, which had set its
        # allowance before this gave up on it.
        #
        # A mined transaction is one *any* endpoint will admit to, so this asks
        # more than one. Empty by default: a single trusted node stays a single
        # trusted node unless a caller says otherwise.
        self._peers = tuple(peer_rpcs)
        self._dry_run = os.environ.get("MISQUOTE_DRY_RUN", "1") != "0"

        # `0` disables the ceiling, and that is a real choice rather than an
        # accident of parsing: somebody paying a genuine spike deliberately
        # needs a way to say so, and it should look different from leaving the
        # variable unset.
        if max_gas_price_wei is None:
            configured = os.environ.get("MISQUOTE_MAX_GAS_PRICE_WEI")
            max_gas_price_wei = DEFAULT_MAX_GAS_PRICE_WEI if configured is None else int(configured)
        self._max_gas_price_wei = max_gas_price_wei if max_gas_price_wei else None

        # Only when this signer can actually broadcast.
        #
        # Under dry run there is nothing to protect and a great deal to break:
        # the offline suite constructs signers with a burner key, and the fork
        # fixtures use anvil's funded accounts, neither of which is the address
        # a deployment declares as its own. Checking here rather than in
        # `send()` means the refusal arrives while the process is starting up
        # instead of after it has built a transaction it was never allowed to
        # send — and `MISQUOTE_DRY_RUN=0` is the moment the declaration starts
        # to mean something.
        if not self._dry_run:
            assert_signs_for_operator(self.account.address)

    @property
    def address(self) -> str:
        return self.account.address

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    # --- signing something that is not a transaction -----------------------

    def sign_message(self, text: str, *, authorising: bool = False) -> str:
        """An EIP-191 signature over a message. Returns `0x`-prefixed hex.

        Here rather than in the module that needs it, because `signer.py`'s whole
        claim is that there is one place that signs. `account` is a public
        attribute, so a caller could reach `signer.account.sign_message(...)`
        today — and then the guards below would apply to transactions only, which
        is how a second signing path comes to exist.

        ## Why the dry-run flag does not gate this, and what does

        `MISQUOTE_DRY_RUN` exists to stop the wallet **spending**. An EIP-191
        signature moves no money, costs no gas and touches no chain, so refusing
        it under dry run would be the flag doing something it was not written to
        do — and the failure mode is worse than it sounds: somebody would set
        `MISQUOTE_DRY_RUN=0` in order to log in, and leave it set.

        It is not free either. A signature over somebody's nonce authenticates as
        this wallet, which is why `authorising` is required and explicit. A
        boolean the caller has to pass is a decision at the call site; a flag
        inherited from the environment is a decision nobody remembers making.

        **The kill switch still applies.** It says stop, and continuing to
        authenticate as the operator while the operator has said stop is not the
        exception it might look like.
        """
        if not authorising:
            raise ValueError(
                "sign_message authenticates as this wallet, so the caller has to "
                "say so: pass authorising=True. It is deliberately not gated on "
                "MISQUOTE_DRY_RUN — a signature spends nothing, and making the "
                "dry-run flag mean two things is how it stops meaning one."
            )
        if not text.strip():
            raise ValueError("refusing to sign an empty message")

        self.check_kill_switch()

        from eth_account.messages import encode_defunct

        signed = self.account.sign_message(encode_defunct(text=text))
        return "0x" + signed.signature.hex().removeprefix("0x")

    # --- the guards --------------------------------------------------------

    def check_kill_switch(self) -> None:
        """Raise if the operator has said stop.

        Checked here rather than only in the loop, so every path to a broadcast
        passes through it — including a path someone adds later without reading
        this docstring.
        """
        if self.kill_file.exists():
            raise KillSwitchEngaged(
                f"{self.kill_file} exists; refusing to broadcast. Remove it to resume."
            )

    def _assert_chain(self, transaction: dict[str, Any]) -> None:
        """Before signing. A signature over the wrong chain is already a liability."""
        declared = transaction.get("chainId")
        if declared is None:
            raise ValueError("transaction has no chainId; refusing to sign an ambiguous payload")
        if int(declared) != self.chain_id:
            raise ValueError(
                f"transaction declares chain {declared} but the node is {self.chain_id}"
            )

    def assert_gas_price(self, price_wei: int) -> None:
        """Refuse a price above the ceiling, before anything is estimated.

        In `build` rather than `send`, and that placement is the point: the gas
        estimate immediately below costs an RPC round trip and the caller may
        have several transactions queued behind this one. Failing here stops the
        run at the first sign of an expensive block instead of part-way through
        a sequence, which for a small wallet is the difference between "nothing
        happened" and "half the agents are registered".
        """
        if self._max_gas_price_wei is None:
            return
        if price_wei > self._max_gas_price_wei:
            raise GasPriceTooHigh(
                f"the node quotes {price_wei / 1e9:.3f} gwei and the ceiling is "
                f"{self._max_gas_price_wei / 1e9:.3f} gwei. Nothing was signed. "
                f"Raise MISQUOTE_MAX_GAS_PRICE_WEI if this price is one you meant "
                f"to pay, or wait — on BSC this is usually a passing spike."
            )

    # --- building and sending ---------------------------------------------

    def build(self, function_call, *, gas: int | None = None, value: int = 0) -> dict[str, Any]:
        """A transaction dict with the nonce, gas and chain id filled in."""
        transaction: dict[str, Any] = {
            "from": self.address,
            "chainId": self.chain_id,
            "nonce": self.w3.eth.get_transaction_count(self.address, "pending"),
            "value": value,
        }
        transaction["gasPrice"] = rpc_retry(lambda: self.w3.eth.gas_price)
        self.assert_gas_price(int(transaction["gasPrice"]))

        if gas is not None:
            transaction["gas"] = gas
        else:
            # Estimating catches a revert *before* anything is signed, which is
            # both cheaper and much more informative than a status-0 receipt.
            estimate = function_call.estimate_gas(dict(transaction))
            transaction["gas"] = int(estimate * 1.25)

        return function_call.build_transaction(transaction)

    def send(self, transaction: dict[str, Any]) -> SentTransaction:
        """Sign, broadcast, wait, and insist the receipt says it worked.

        Order is deliberate: kill switch, then chain id, then signature, then
        broadcast. Each guard runs while backing out is still free.
        """
        self.check_kill_switch()
        self._assert_chain(transaction)

        if self._dry_run:
            raise DryRunRefusal(
                "MISQUOTE_DRY_RUN is set; this build is read-only. "
                "Set MISQUOTE_DRY_RUN=0 to broadcast."
            )

        signed = self.account.sign_transaction(transaction)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction

        try:
            tx_hash = self.w3.eth.send_raw_transaction(raw)
        except Exception as error:  # noqa: BLE001 — classified immediately
            if any(marker in str(error).lower() for marker in NONCE_RACE_MARKERS):
                # Refetch once and retry once. More than once means something
                # other than a race, and retrying it would be a loop.
                transaction["nonce"] = self.w3.eth.get_transaction_count(self.address, "pending")
                self._assert_chain(transaction)
                signed = self.account.sign_transaction(transaction)
                raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
                tx_hash = self.w3.eth.send_raw_transaction(raw)
            else:
                raise

        receipt = self.wait_for_receipt(tx_hash)
        if receipt["status"] != 1:
            raise TransactionReverted(tx_hash.hex(), dict(receipt))

        return SentTransaction(
            tx_hash=tx_hash.hex(),
            block=int(receipt["blockNumber"]),
            gas_used=int(receipt["gasUsed"]),
            effective_gas_price=int(
                receipt.get("effectiveGasPrice", transaction.get("gasPrice", 0))
            ),
        )

    def wait_for_receipt(self, tx_hash) -> dict[str, Any]:
        """Poll for a receipt, tolerating a rate-limited node.

        `w3.eth.wait_for_transaction_receipt` gives up on a 429 rather than
        waiting it out, which loses track of a transaction that is already in
        flight — the worst possible outcome, because the agent then does not
        know whether it holds a position.
        """
        sources = [self.w3]
        for url in self._peers:
            try:
                sources.append(Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20})))
            except Exception:  # noqa: BLE001 — an endpoint that will not build is not fatal
                continue

        deadline = time.monotonic() + self._receipt_timeout
        while time.monotonic() < deadline:
            for source in sources:
                try:
                    receipt = source.eth.get_transaction_receipt(tx_hash)
                    if receipt is not None:
                        return receipt
                except Exception as error:  # noqa: BLE001
                    # Only the node that took the send gets to raise a real
                    # error; a peer that has not caught up is the ordinary case
                    # this exists for.
                    if (
                        source is self.w3
                        and not is_transient(error)
                        and "not found" not in str(error).lower()
                    ):
                        raise
            time.sleep(2)

        raise TimeoutError(
            f"no receipt for {tx_hash.hex()} within {self._receipt_timeout:.0f}s. "
            "The transaction may still be in flight — check before resending, because "
            "resending a live transaction is how you end up with two positions."
        )
