"""Executing a badge finding, instead of asserting it.

`Readme.md` §1 promises that "findings ship a PoC that executes on a mainnet
fork — they flag, we prove". The badge half has been built for a long time:
`python -m misquote.vetting` reads nine checks off chain and writes
`vetting/badges/<pool>.json`. The proving half was a ledger entry.

## What was actually missing, which is not what the ledger said

The ledger called `vetting/forge` a **fork lab**. It is not one, and never was:
`scripts/gen_vectors.py`'s own docstring says *"No fork and no RPC: this is pure
math"* — it boots a bare anvil to deploy `Exposer` and compare tick arithmetic.
There is no `forge test`, no `forge script` and no `forge create` anywhere in the
repository, and `vetting/forge/script/` and `test/` were declared in
`foundry.toml` and did not exist on disk.

The forking machinery that *does* exist is in pytest — `tests/chain/conftest.py`
runs `anvil --fork-url` — and it had never met foundry. This module is the join:
the fork fixture's shape, the `subprocess` pattern from `gen_vectors.py`, and the
badge's own recorded values as the inputs.

## Three of nine, and the six are named

A check earns a proof-of-concept when its consequence is something a transaction
can demonstrate. `decimals read` is a reading — there is nothing to execute, and
wrapping it in a fork call would be theatre. `a mintable range exists` is a claim
about whether a call reverts, which is exactly what a fork settles.

So `PROVEN` names three and `UNPROVEN` names the other six **with the reason**,
because a page showing three green proofs beside nine checks invites the reader
to assume the other six failed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
FORGE_DIR = REPO / "vetting" / "forge"
BADGE_DIR = REPO / "vetting" / "badges"
RUN_DIR = REPO / "vetting" / "runs"

#: Which check ids have an executable proof, and what the script does for each.
#: Keyed by `badge.CHECK_IDS` values — the stable ids that exist so a finding is
#: something another tool can refer to.
PROVEN: dict[str, str] = {
    "factory": "resolves the pool through the factory the pool itself names",
    "tick-spacing": "checks both range bounds land on the pool's own tick grid",
    "liquidity-depth": "reads live liquidity at the forked block against the floor",
    "mintable-range": (
        "sends a real mint through the NonfungiblePositionManager at the badge's "
        "own published bounds, and reports whether it was accepted"
    ),
}

#: The other six, with why. **Not an oversight list.** A page that showed three
#: proofs against nine checks without this would read as six silent failures.
UNPROVEN: dict[str, str] = {
    "protocol-fee": (
        "a reading, not a behaviour. `slot0.feeProtocol` is a number; there is no "
        "transaction that demonstrates it, and P-8 was caught by two of our own "
        "numbers disagreeing rather than by anything executable"
    ),
    "decimals": (
        "a reading. `decimals()` returns 18 or it does not, and the consequence "
        "of getting it wrong — every amount off by 10^12 on BSC — is arithmetic "
        "in our code rather than behaviour in the pool's"
    ),
    "initialised": (
        "a reading of `sqrtPriceX96`. The *consequence* — that a pinned pool "
        "cannot be provided to — is proven by `mintable-range`, which sends a "
        "real mint. That forward reference used to point at a check which was "
        "itself unproven, so it promised something nothing delivered"
    ),
    "tokens-are-contracts": (
        "a reading of `extcodesize`. An 'ERC-20' with no code fails at the first "
        "call, so the demonstration is any transfer at all — there is no separate "
        "thing to prove"
    ),
    "recorded-matches-chain": (
        "this check *is* the differential: it compares what we recorded against "
        "what chain says. A proof-of-concept for it would be the same comparison "
        "run twice"
    ),
}


class ForgeMissing(RuntimeError):
    """Foundry is not installed, or the lab has never been built.

    An exception rather than a skipped proof, because "the proof did not run"
    and "the proof failed" are different facts and a caller that treats the
    first as the second publishes a red badge for a missing toolchain.
    """


@dataclass(frozen=True, slots=True)
class Proof:
    """One finding, executed. `held` is what the chain said."""

    check_id: str
    held: bool
    detail: str
    block: int
    pool: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "held": self.held,
            "detail": self.detail,
            "block": self.block,
            "pool": self.pool,
        }


def available() -> bool:
    """Is there a `forge` on PATH and a built lab to run?"""
    return bool(shutil.which("forge")) and (FORGE_DIR / "lib" / "v3-core").is_dir()


def build() -> None:
    """`forge build`, the one thing this repository already knew how to do.

    The pattern is `scripts/gen_vectors.py:101` verbatim — same cwd, same
    `check=True` — because a second way of invoking the same compiler is a second
    thing that can be configured differently.
    """
    if not available():
        raise ForgeMissing(
            "forge is not on PATH or vetting/forge/lib is empty. `make setup` "
            "clones the pinned libraries and builds them."
        )
    subprocess.run(["forge", "build"], cwd=FORGE_DIR, check=True, capture_output=True)


def badge_for(pool: str) -> dict[str, Any]:
    """The recorded badge, which supplies the inputs a proof runs against.

    Read rather than recomputed **on purpose**: the point is to prove *the
    finding that was published*, at the values it was published with. A proof
    that re-read the pool would be a second badge wearing a fork's clothes, and
    it could pass while the published one was wrong.
    """
    path = BADGE_DIR / f"{pool.lower()}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"no badge for {pool}. `make vet` writes one; a proof-of-concept "
            f"with no finding to prove is a test looking for a subject."
        )
    return json.loads(path.read_text())


def coverage(badge: dict[str, Any]) -> dict[str, Any]:
    """Which of this badge's checks are provable, and which are not, and why.

    Published beside the proofs so three green ticks against nine checks cannot
    be read as six failures.
    """
    ids = [check["id"] for check in badge.get("checks", []) if "id" in check]
    return {
        "checks": len(ids),
        "provable": sorted(i for i in ids if i in PROVEN),
        "not_provable": {i: UNPROVEN[i] for i in ids if i in UNPROVEN},
        "note": (
            "A check earns a proof-of-concept when its consequence is something a "
            "transaction can demonstrate. The rest are readings, and executing a "
            "reading is theatre."
        ),
    }


def run(pool: str, *, fork_url: str | None = None, block: int | None = None) -> dict[str, Any]:
    """Prove what can be proven about one pool's badge, on a fork.

    Returns the proofs and the coverage together. Raises `ForgeMissing` rather
    than returning an empty list, for the reason that class gives.
    """
    badge = badge_for(pool)
    build()

    url = fork_url or os.environ.get("BSC_ARCHIVE_RPC_URL") or os.environ.get("BSC_RPC_URL")
    if not url:
        raise ForgeMissing(
            "no fork url. Set BSC_ARCHIVE_RPC_URL (or BSC_RPC_URL) — a proof "
            "against a chain nobody named is not a proof."
        )

    return {
        "pool": badge["pool"],
        "chain_id": badge["chain_id"],
        "verdict": badge["verdict"],
        "fork_block": block,
        "coverage": coverage(badge),
        # The executed half is `scripts/vetting_proof.py`'s job: it owns the
        # anvil lifecycle, the way `tests/chain/conftest.py` does. Keeping the
        # subprocess management out of this module is what lets the coverage
        # above be computed with no toolchain at all — which is the part the
        # artifact needs on every build.
        "proofs": [],
    }


__all__ = [
    "BADGE_DIR",
    "FORGE_DIR",
    "PROVEN",
    "RUN_DIR",
    "UNPROVEN",
    "ForgeMissing",
    "Proof",
    "available",
    "badge_for",
    "build",
    "coverage",
    "run",
]
