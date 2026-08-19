"""What TermiX's escrow actually is, exercised against the real contract.

`registry/erc8183.py` carried this address as a verified ERC-8183 job escrow and
its own evidence named the hole: nobody had read a job back out of it. This file
is the reading, and it is the reason `JOB_ESCROW` is empty again.

Three things are checked here, in the order that matters:

1. **It is not ERC-8183.** `jobs(uint256)`, `nextJobId()` and `jobCount()` all
   revert on the live contract. Asserted against the chain rather than quoted
   from the evidence string, so the claim cannot outlive the fact.
2. **The interface it does have answers.** `orders(bytes32)` returns a 13-word
   struct for a real order id taken from TermiX's own public explorer.
3. **The decode agrees with an independent source.** The budget word matches the
   figure TermiX publishes for the same order — the check that separates a
   decode from a plausible reading of arbitrary bytes.

Read-only. Nothing here signs, and the fork exists so that the reads happen at a
pinned height against real deployed code rather than against a mock of it. The
plan for this file was originally the six-transaction ERC-8183 hire lifecycle;
that sequence cannot be driven against this contract because none of its calls
exist here, and discovering that is the result.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time

import pytest
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from misquote.registry import aacp
from misquote.registry.aacp import BSC_MAINNET, CONTRACTS

# The escrow holding the live orders. TermiX runs one per settlement currency,
# and their live config makes the USDC one the default — the USDT escrow we had
# recorded returns all-zero words for a USDC order, which is a correct answer to
# a question about a different book.
USDC_ESCROW = CONTRACTS[BSC_MAINNET]["TermixEscrow_USDC"]
USDT_ESCROW = CONTRACTS[BSC_MAINNET]["TermixEscrow_USDT"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def forked():
    """A forked BSC at the current head. Reads only, so nothing is funded."""
    if not shutil.which("anvil"):
        pytest.skip("anvil not installed")

    rpc = os.environ.get("BSC_ARCHIVE_RPC_URL") or "https://bsc-dataseed.bnbchain.org"
    port = _free_port()
    proc = subprocess.Popen(
        ["anvil", "--fork-url", rpc, "--port", str(port), "--no-rate-limit"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    w3 = Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}", request_kwargs={"timeout": 180}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    for _ in range(45):
        if proc.poll() is not None:
            pytest.skip("anvil exited (free endpoints prune; set BSC_ARCHIVE_RPC_URL)")
        try:
            if w3.is_connected() and w3.eth.block_number > 0:
                break
        except Exception:  # noqa: BLE001 — still booting
            pass
        time.sleep(1)
    else:
        proc.terminate()
        pytest.skip("anvil did not come up")

    try:
        yield w3
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def live_orders():
    """Real order ids from TermiX's public explorer. No credentials."""
    try:
        items = aacp.fetch_public_jobs(BSC_MAINNET)
    except Exception as error:  # noqa: BLE001 — their API being down is not our failure
        pytest.skip(f"TermiX explorer unreachable: {error}")
    if not items:
        pytest.skip("explorer returned no orders")
    return items


@pytest.mark.chainfork
def test_the_escrow_does_not_implement_erc8183(forked) -> None:
    """The finding, asserted against the contract instead of quoted from a string.

    This is the check that should have run before the address was ever recorded
    as an ERC-8183 escrow. It costs three reverting `eth_call`s.
    """
    assert not aacp.implements_erc8183(forked, USDC_ESCROW)
    assert not aacp.implements_erc8183(forked, USDT_ESCROW)


@pytest.mark.chainfork
def test_the_order_accessor_answers_for_a_real_order(forked, live_orders) -> None:
    """`orders(bytes32)` returns a struct where the EIP's accessors reverted."""
    words = aacp.read_order(forked, USDC_ESCROW, live_orders[0]["chainOrderId"])

    assert len(words) == aacp.ORDER_WORDS
    assert any(words), "a real order id returned an all-zero struct"


@pytest.mark.chainfork
def test_the_budget_word_agrees_with_what_termix_publishes(forked, live_orders) -> None:
    """The check that makes this a decode rather than a guess.

    One matching word could be coincidence. Every order on the explorer agreeing,
    exactly, in 18-decimal units, is not — and it is the only field this codebase
    claims to have decoded.
    """
    checked = 0
    for order in live_orders:
        words = aacp.read_order(forked, USDC_ESCROW, order["chainOrderId"])
        assert aacp.order_budget(words) == pytest.approx(float(order["budget"]), abs=1e-9), (
            f"order {order['chainOrderId'][:14]} reads "
            f"{aacp.order_budget(words)} on chain, {order['budget']} on their explorer"
        )
        checked += 1

    assert checked >= 5, f"only {checked} orders checked; one agreement is a coincidence"


@pytest.mark.chainfork
def test_the_usdt_escrow_is_a_different_book(forked, live_orders) -> None:
    """A USDC order is not on the USDT escrow, and the contract says so cleanly.

    Worth asserting because it is the trap in reading this contract: an unknown
    order id returns thirteen zero words rather than reverting, so a caller
    pointed at the wrong escrow gets a confident, well-formed, entirely fictional
    order with a budget of zero.
    """
    words = aacp.read_order(forked, USDT_ESCROW, live_orders[0]["chainOrderId"])

    assert not any(words), "expected an empty struct from the other settlement book"
    assert aacp.order_budget(words) == 0.0
