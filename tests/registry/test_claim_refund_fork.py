"""The way out of a funded job nobody settled.

Job 56681 holds 0.1 of the payment token on BSC mainnet because the flow got
four calls in and stopped: `submit` reverted `0x15e5dd74` and `settle` reverted
`NotDecided()`. Money in the kernel with no delivery and no decision has exactly
one exit, `claimRefund`, and it opens at `expiredAt`.

That expiry is compared against `block.timestamp`, so on mainnet it cannot be
hurried — `evm_increaseTime` is an anvil cheat code and BSC has no equivalent.
What a fork can do is stand in for the clock while keeping everything else real:
the job is the actual job, at the current block, holding the actual money.

So this asserts the two halves that matter, and the first is the one usually
skipped: **the guard is watched refusing**. A recovery path that has only ever
been seen succeeding after a warp has not been distinguished from a contract
that would have paid out at any time.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

pytestmark = pytest.mark.chainfork

JOB = 56681


@pytest.fixture(scope="module")
def record() -> dict:
    if not shutil.which("anvil"):
        pytest.skip("anvil not installed")
    if not (
        os.environ.get("MISQUOTE_OPERATOR_PRIVATE_KEY") or os.environ.get("MISQUOTE_PRIVATE_KEY")
    ):
        pytest.skip("no operator key in the environment")
    from claim_refund import rehearse  # noqa: PLC0415 — needs the path insert above

    rpc = os.environ.get("BSC_ARCHIVE_RPC_URL") or "https://bsc-dataseed.bnbchain.org"
    result = rehearse(rpc, JOB)
    if not result.get("ran"):
        pytest.skip(f"fork did not come up: {result.get('reason')}")
    return result


def test_the_expiry_actually_refuses_an_early_claim(record: dict) -> None:
    """The half that would go unnoticed if only the happy path were run."""
    early = [s for s in record["transactions"] if s["when"] == "before expiry"]
    assert early, "the rehearsal must attempt the claim before warping the clock"
    assert not early[0]["ok"], (
        "claimRefund succeeded before expiredAt — the window is not enforced, "
        "which would mean any funded job is drainable by its client at will"
    )


def test_the_budget_comes_back_after_expiry(record: dict) -> None:
    assert record["refunded"], "claimRefund did not return the budget"
    assert record["recovered"] == record["budget"] == 100_000_000_000_000_000
    assert record["balance_after"] > record["balance_before"]


def test_the_job_leaves_the_funded_status(record: dict) -> None:
    """A refund that pays out without moving the status could be claimed twice."""
    assert record["status_before"] == 1, "job 56681 should be sitting funded"
    assert record["status_after"] != record["status_before"]


def test_the_record_never_claims_mainnet(record: dict) -> None:
    """The distinction this project is named for, asserted rather than trusted."""
    assert record["network"] == "fork"
    assert record["client"] == "0x0c501EE1924bfb91a028DB4BcD68f4861B0Ff6eE"
