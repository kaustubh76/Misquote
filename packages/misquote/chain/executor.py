"""The `Executor` that actually broadcasts. The only one that can.

`agents/warden/live.py` has defined an `Executor` protocol since Step 13 and had
exactly one implementation, `SimulatedExecutor`, which moves a position that
exists only in memory. That is why `make warden` has no `--live` flag and why the
not-built ledger carries a "chain executor" entry: the decisions were real, the
policy was real, and nothing could act on them.

This is that implementation. It is a thin adapter over `PositionManager`, which
already builds and sends every transaction, and over `BscSigner`, which already
owns the kill switch, the chain-id assertion, the dry-run refusal and the
revert check. Nothing here re-implements any of that — an executor that grew its
own idea of when it was safe to send would be a second opinion on the one
question that must have exactly one.

## The ordering, and what a failure part-way leaves behind

A recentre is a close and an open, and the order is chosen for what a crash in
the middle leaves:

    decreaseLiquidity   principal moves out of the pool, into `tokensOwed`
    collect             `tokensOwed` moves to the wallet
    burn                the empty NFT is destroyed
    mint                the new range is opened

Closing first means a failure between the two leaves the agent **out of the
market holding its own tokens** — flat, solvent, and recoverable by re-running.
Minting first would need the capital twice over, which we do not have, and a
failure would leave two overlapping positions with no record of which is
current.

`PositionManager.close` already orders the exit so that a failure after
`decreaseLiquidity` is recoverable by `collect` alone, and that ordering is
reused rather than restated.

## Sizing

The protocol hands us a *liquidity* figure; the manager wants token *amounts*.
Converting between them needs the current price, so it is done here, at send
time, with the same `get_amounts_for_liquidity` the replay engine uses and the
fork test compares to the real contracts to one wei. Sizing from a price
observed at decision time instead would put a stale number into a slippage
bound.

## One execution path

`WardenLive.perform` calls this executor and *then* applies the decision, so a
transaction that raises leaves the engine's idea of the position equal to the
chain's. That property comes from call order alone.

It used to be only half true. `WardenLoop` kept a **second** execution path — its
own `executor_call`, run after `step()` had already committed the position — so
every decision was acted on twice unless one of the two executors was inert, and
a failure on the queue path was journalled without rolling anything back. That
was matrix **P-9**, and it is now fixed: `decide` observes, `perform` acts, and
`perform` is the only thing that does.

## Reconciliation

`observe()` reads what the wallet actually holds. An agent that restarts with an
empty memory would otherwise mint a *second* position and orphan the first —
capital in the pool with no fee accounting and no kill switch pointed at it,
which is the failure that makes an unattended run unsafe.
"""

from __future__ import annotations

from web3 import Web3

from misquote.chain.nfpm import PositionManager
from misquote.chain.signer import SentTransaction
from misquote.core.errors import AssumptionViolated, PositionClosedNotReopened
from misquote.core.liquidity import get_amounts_for_liquidity
from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import PositionState, Tick

# `IncreaseLiquidity(uint256 indexed tokenId, uint128 liquidity, uint256, uint256)`.
# The NFPM emits it on every mint, with the token id as the first indexed topic —
# which is how a freshly minted position is identified without guessing.
INCREASE_LIQUIDITY_TOPIC = Web3.keccak(
    text="IncreaseLiquidity(uint256,uint128,uint256,uint256)"
).hex()


class ChainExecutor:
    """Performs decisions against a real pool, through the verified manager.

    Holds no key and makes no safety decision of its own: `BscSigner` refuses to
    broadcast when the kill file is present, when the chain is not the one the
    signer was built for, or when `MISQUOTE_DRY_RUN` is not explicitly `"0"`.
    This class would be the wrong place for a second copy of any of that.
    """

    __slots__ = ("manager", "sent", "_last_mint")

    def __init__(self, manager: PositionManager) -> None:
        self.manager = manager
        # Every transaction this executor has sent, in order, so a run can be
        # audited against the chain afterwards rather than against its own logs.
        self.sent: list[SentTransaction] = []
        self._last_mint: int | None = None

    # --- the protocol ------------------------------------------------------

    def mint(self, lower: Tick, upper: Tick, liquidity: int, ts: int) -> int | None:
        """Open a position and return its NFPM token id.

        Approvals first. `ensure_allowance` had three call sites and all of them
        were tests — the fork fixture approved both tokens before any test ran, so
        every mint in the suite met an allowance that production would never have
        set. A first real mint would have failed at `estimate_gas`: loudly, at
        least, but for a reason that looks like a broken contract rather than a
        missing step.

        Idempotent, so this costs a read and nothing else once the allowance is
        already sufficient — which is what the fork fixture's own approvals make
        it, and what proves the call is harmless where it was already handled.
        """
        del ts  # the deadline comes from the chain's clock, not the policy's
        amount0, amount1 = self._amounts_for(lower, upper, liquidity)
        self.manager.ensure_allowance(self.manager.meta.token0, amount0)
        self.manager.ensure_allowance(self.manager.meta.token1, amount1)
        sent = self.manager.mint(lower, upper, amount0, amount1)
        self.sent.append(sent)
        self._last_mint = self._token_id_from(sent)
        return self._last_mint

    def rebalance(
        self, current: PositionState, lower: Tick, upper: Tick, liquidity: int, ts: int
    ) -> int | None:
        """Close the old range and open the new one, in that order.

        Returns the **new** token id. Reusing the old one would be a lie the
        journal then carries: `decreaseLiquidity` plus `burn` destroys the NFT,
        and the position that follows is a different token.

        If the close succeeds and the open does not, that is **not** an ordinary
        failure and must not be reported as one. The wallet is flat and solvent —
        which is what the ordering buys — but the caller still believes it holds
        the old range, and every decision after that would be about a position
        that no longer exists. So it raises `PositionClosedNotReopened`, which
        `WardenLive._execute` catches to put the engine flat before re-raising.
        """
        closed = False
        if current.token_id is not None:
            self._close(current.token_id)
            closed = True
        try:
            return self.mint(lower, upper, liquidity, ts)
        except Exception as error:
            if closed:
                raise PositionClosedNotReopened(current.token_id, error) from error
            raise

    def pull(self, current: PositionState, ts: int) -> None:
        """Withdraw to the wallet. Not just out of the pool — to the wallet.

        `decreaseLiquidity` alone moves principal into `tokensOwed` and leaves it
        in the contract, which reports success and withdraws nothing. `close`
        does all three legs — and the third is `burn`, so **the token id is dead
        afterwards**. Reading `positions(tokenId)` on it reverts with "Invalid
        token ID" rather than returning an empty position, which is the correct
        behaviour and surprising enough to be worth stating.
        """
        del ts
        if current.token_id is not None:
            self._close(current.token_id)

    # --- internals ---------------------------------------------------------

    def _close(self, token_id: int) -> None:
        self.sent.extend(self.manager.close(token_id))

    def _amounts_for(self, lower: Tick, upper: Tick, liquidity: int) -> tuple[int, int]:
        """What `liquidity` costs at the price the pool is at *now*.

        At send time rather than at decision time: the slippage bound the manager
        derives from these is only meaningful against the price the transaction
        will actually meet.
        """
        if liquidity <= 0:
            raise ValueError(f"cannot mint {liquidity} liquidity")
        sqrt_price = self.manager._sqrt_price_now()  # noqa: SLF001 — same package
        amount0, amount1 = get_amounts_for_liquidity(
            sqrt_price, get_sqrt_ratio_at_tick(lower), get_sqrt_ratio_at_tick(upper), liquidity
        )
        # The curve rounds against the provider, so ask for one wei more than the
        # exact figure on each side; the manager's own slippage bound is what
        # protects the downside.
        return amount0 + 1, amount1 + 1

    def _token_id_from(self, sent: SentTransaction) -> int | None:
        """Read the token id out of the mint's own `IncreaseLiquidity` log.

        Not from `balanceOf`/`tokenOfOwnerByIndex`: that reports the newest token
        the *wallet* holds, which is a different thing the moment the wallet holds
        any other position, and it would fail silently rather than loudly.
        """
        w3 = self.manager.w3
        try:
            receipt = w3.eth.get_transaction_receipt(sent.tx_hash)
        except Exception:  # noqa: BLE001 — a lost receipt is not a reason to crash
            return None

        want = INCREASE_LIQUIDITY_TOPIC
        if not want.startswith("0x"):
            want = "0x" + want
        for log in receipt.get("logs", []):
            topics = log.get("topics", [])
            if not topics:
                continue
            first = topics[0]
            first = first.hex() if hasattr(first, "hex") else str(first)
            if not first.startswith("0x"):
                first = "0x" + first
            if first.lower() == want.lower() and len(topics) > 1:
                raw = topics[1]
                return int(raw.hex(), 16) if hasattr(raw, "hex") else int(raw, 16)
        return None

    @property
    def gas_spent_wei(self) -> int:
        """What this run has actually cost, from receipts rather than estimates."""
        return sum(tx.gas_cost_wei for tx in self.sent)

    # --- reconciliation ----------------------------------------------------

    def observe(self) -> PositionState | None:
        """What the wallet **actually** holds in this pool, read from chain.

        An agent that restarts with an empty memory believes it holds nothing,
        mints a *second* position, and orphans the first — capital left in the
        pool with nothing tracking it, no fee accounting, and no kill switch
        pointed at it. That is the failure that makes an unattended 24-hour run
        unsafe, and it is not something a journal can fix: the journal records
        what the agent *did*, and the question here is what is *true*.

        So the chain is the authority. `PancakeV3PositionManager` is
        `ERC721Enumerable` — `supportsInterface(0x780e9d63)` returns true on
        mainnet, verified rather than assumed — so the wallet's tokens can be
        walked directly.

        Returns `None` when the wallet holds no live position in this pool, which
        is the ordinary state and not an error. A closed-but-unburned NFT reads as
        `None` too: `liquidity == 0` is not a position, it is a receipt.

        **Raises when the wallet holds more than one.** A wallet can legitimately
        hold several positions in one pool — someone minted by hand, or a previous
        crash left one behind — and there is then no way to know which one is the
        agent's. Adopting the first is a guess, and a guess here means rebalancing
        one position while the other sits unmanaged. So it refuses and names them
        all, which is a thing an operator can act on.
        """
        found = self._live_positions()
        if not found:
            return None
        if len(found) > 1:
            raise AssumptionViolated(
                f"the wallet holds {len(found)} live positions in {self.manager.meta.address} "
                f"(tokens {sorted(t for t, _ in found)}). Which one is the agent's cannot be "
                "known from chain, and adopting one would leave the other unmanaged. Close "
                "the ones that should not be there, then restart."
            )

        token_id, held = found[0]
        return PositionState(
            lower=held.lower,
            upper=held.upper,
            liquidity=held.liquidity,
            token_id=token_id,
            # Unknown from chain: the NFPM records no mint timestamp, and
            # inventing one would put a fabricated number into the horizon the
            # policy reasons about. Zero is the honest "not known", and
            # `rebalances_today` deliberately restarts at zero rather than being
            # guessed at from a journal that may not describe this position.
            minted_ts=0,
            last_rebalance_ts=0,
            rebalances_today=0,
        )

    def _live_positions(self) -> list[tuple[int, object]]:
        """Every open position the wallet holds *in this pool*."""
        manager = self.manager
        out: list[tuple[int, object]] = []
        for token_id in manager.tokens_of(manager.signer.address):
            try:
                held = manager.position(token_id)
            except Exception:  # noqa: BLE001 — a burned or foreign token is not ours
                continue
            if held.liquidity > 0 and manager.is_for_pool(held):
                out.append((token_id, held))
        return out
