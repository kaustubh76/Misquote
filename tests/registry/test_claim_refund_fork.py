"""The way out of a job that was delivered into and never decided.

Job **56718** holds 0.1 of the payment token on BSC mainnet right now: funded,
`submit` mined, and `settle` reverting `NotDecided()` until the seven-day
dispute window closes on 13 Sep. Money in the kernel with a delivery and no
decision has one exit if that date is missed, `claimRefund`, and it opens at
`expiredAt` — 14 Sep 08:00 UTC.

That expiry is compared against `block.timestamp`, so on mainnet it cannot be
hurried — `evm_increaseTime` is an anvil cheat code and BSC has no equivalent.
What a fork can do is stand in for the clock while keeping everything else real:
the job is the actual job, at the current block, holding the actual money.

So this asserts the two halves that matter, and the first is the one usually
skipped: **the guard is watched refusing**. A recovery path that has only ever
been seen succeeding after a warp has not been distinguished from a contract
that would have paid out at any time.

## It used to be job 56681, and that had stopped being true

56681 was funded and never submitted, and `claimRefund` on it was mined on
mainnet on 4 Sep. So the file's own opening sentence — "holds 0.1 of the payment
token" — described a job that had been empty for two days, and every assertion
here was against `status_before == 1` for a job whose status is 5.

It went unnoticed because the whole module skipped: the fixture wanted an
operator key, and nothing had ever run this suite with `.env` in the
environment. The first `--mainnet` gate did, and two of the four failed at once.
The third passed either way — an early claim on a spent job is refused for the
wrong reason — which is what a guard looks like when it has stopped
discriminating.

56681 stays, as the other half of the claim: a job already refunded on mainnet
must refuse a second refund, at any point on the clock.
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

#: Funded, submitted, undecided. The job the recovery path is actually about.
JOB = 56718

#: Funded, never submitted, and refunded on mainnet on 4 Sep. Kept because a
#: spent job is the only way to check that the exit closes behind itself.
SPENT_JOB = 56681


def _rehearse(job: int) -> dict:
    if not shutil.which("anvil"):
        pytest.skip("anvil not installed")
    if not (
        os.environ.get("MISQUOTE_OPERATOR_PRIVATE_KEY") or os.environ.get("MISQUOTE_PRIVATE_KEY")
    ):
        pytest.skip("no operator key in the environment")
    from claim_refund import rehearse  # noqa: PLC0415 — needs the path insert above

    rpc = os.environ.get("BSC_ARCHIVE_RPC_URL") or "https://bsc-dataseed.bnbchain.org"
    result = rehearse(rpc, job)
    if not result.get("ran"):
        pytest.skip(f"fork did not come up: {result.get('reason')}")
    return result


@pytest.fixture(scope="module")
def record() -> dict:
    return _rehearse(JOB)


@pytest.fixture(scope="module")
def spent() -> dict:
    return _rehearse(SPENT_JOB)


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


def test_the_job_leaves_the_status_it_was_in(record: dict) -> None:
    """A refund that pays out without moving the status could be claimed twice.

    `status_before` is 2 — submitted — and that is the point of running this
    against 56718 rather than a job that only ever reached 1. It says the
    deployment lets a client recover a budget it has already been *delivered
    into*, once nobody decided in time. Asserted as "not spent", so the number
    is read from the chain rather than pinned to whichever state today's job
    happens to be in.
    """
    assert record["status_before"] not in (0, 5), (
        f"job {JOB} is not a live funded job any more (status "
        f"{record['status_before']}); this module needs one that is"
    )
    assert record["status_after"] != record["status_before"]


def test_a_job_already_refunded_on_mainnet_cannot_be_refunded_twice(spent: dict) -> None:
    """The exit closes behind itself, checked against a job that used it.

    56681's `claimRefund` was mined on mainnet. On a fork at today's block it is
    status 5 with nothing in it, and both attempts — before the clock moves and
    after — must fail. The "after" one is the half worth having: a contract that
    paid out twice would pay the second time only once the window was open.
    """
    assert spent["status_before"] == 5, (
        f"job {SPENT_JOB} was refunded on mainnet; a fork should show it spent"
    )
    assert not spent["refunded"]
    assert spent["recovered"] == 0
    assert spent["balance_after"] == spent["balance_before"]
    assert all(not step["ok"] for step in spent["transactions"])


def test_the_record_never_claims_mainnet(record: dict) -> None:
    """The distinction this project is named for, asserted rather than trusted."""
    assert record["network"] == "fork"
    assert record["client"] == "0x0c501EE1924bfb91a028DB4BcD68f4861B0Ff6eE"
