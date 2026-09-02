"""The ERC-8183 flow, driven to settlement against the real mainnet kernel.

`test_termix_escrow_fork.py` is the negative of this: a contract that could not
be driven because its calls do not exist. This one can be, and the reason it had
not been is the interesting part.

## The blocker was money, and the reading of it was wrong twice

The ledger recorded the escrow as not built because *"the payment token is
owner-minted with no faucet"*. True — and a statement about acquiring a token,
not about the code. `registry/hire.py` has implemented `fund` since it was
written and nothing had ever called it holding a balance.

Two published readings did not survive the first call that did:

- `0x32d53d69` was recorded as *"fund() from a wallet holding none of the payment
  token"*. It is `PolicyNotSet()`. This test holds ten times the budget and
  reverts identically until `registerJob` succeeds.
- `0xc94463e3` was recorded as *"consistent with the hook having registered the
  job already"*. It is `PolicyNotWhitelisted()` — nothing had registered
  anything.

And the cause underneath both: **the evaluator must be the EvaluatorRouter**.
Name a third wallet and `registerJob` reverts `RouterNotEvaluator()`, so no
policy is ever set, so `fund` reverts — two unnamed errors, one cause, neither
about money. A client written from the EIP names a human evaluator and fails two
transactions after the mistake.

## What this does not prove

That real money can be escrowed. The owner is impersonated here and holds none
to sell on a live chain. `escrowed_on_mainnet` stays false in the record, and
the artifact publishes this beside the chapel run rather than merged into it.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

pytestmark = pytest.mark.chainfork


@pytest.fixture(scope="module")
def record() -> dict:
    if not shutil.which("anvil"):
        pytest.skip("anvil not installed")
    import os

    from prove_escrow_fund import run  # noqa: PLC0415 — needs the path insert above

    rpc = os.environ.get("BSC_ARCHIVE_RPC_URL") or "https://bsc-dataseed.bnbchain.org"
    result = run(rpc, None)
    if not result.get("ran"):
        pytest.skip(f"fork did not come up: {result.get('reason')}")
    return result


def test_the_owner_can_be_impersonated_into_minting(record: dict) -> None:
    """The blocker, and its whole cost on a fork."""
    assert record["minted_to_client"] > record["budget"], (
        "the client must hold more than the budget, or a fund() revert cannot "
        "be distinguished from an empty wallet — which is the mistake this "
        "whole file exists to correct"
    )


def test_every_step_of_the_flow_succeeds(record: dict) -> None:
    failed = [s for s in record["transactions"] if not s.get("ok")]
    assert not failed, f"steps reverted: {[(s['call'], s.get('error')) for s in failed]}"


def test_the_money_moves_and_the_provider_is_paid(record: dict) -> None:
    """`escrowed` is the budget leaving the client; `settled` is it arriving."""
    assert record["escrowed"], "fund() did not move the budget out of the client"
    assert record["settled"], "settle() did not pay the provider"


def test_the_record_never_claims_mainnet(record: dict) -> None:
    """The distinction this project is named for, asserted rather than trusted."""
    assert record["network"] == "fork"
    assert record["escrowed_on_mainnet"] is False
    assert record["why_not_on_mainnet"].strip()
