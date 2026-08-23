"""Altana session keys: the caps subset, and the address it does not have.

`Readme.md` §1 puts activation on the never-cut list — grant with visible caps,
inspect, one-transaction revoke — and this package has been a docstring since it
was created. What follows is the honest half: the shape of the grant, priced and
enumerated, and a refusal where a verified deployment would go.

## Why there is no address here

`SESSION_KEY_MODULE` is empty, and it is empty on purpose rather than pending.
`vetting/addresses/` holds `56.json`, `venus-56.json`, `erc8183-56.json` and
`erc8183-97.json` — nothing session-key shaped — because nobody has run the
three-way check against an Altana session-key module the way
`scripts/verify_erc8183.py` did for `JOB_ESCROW`. Writing a plausible address
here would make every function below return something, and the demo would work
right up until a judge sent a transaction to it.

The precedent is `registry/erc8183.py::NoVerifiedDeployment`, and its reasoning
carries over exactly: an exception rather than a `None`, because a caller that
forgets to check a `None` builds an unsigned transaction to the zero address,
and a caller that ignores an exception does not compile a demo.

## What is real without an address

The *plan* is. `grant_plan` and `revoke_plan` enumerate the transactions a
grant consists of and who sends each, which is a fact about the caps subset and
not about any particular deployment — the same thing `erc8183.steps()` publishes
for the hire flow. A reader can see that revoking is one transaction, sent by
the owner, before anyone has deployed anything. That is worth publishing; a
fabricated address is not.

`tests/web/test_ledger.py` verifies the ledger's claim by importing
`SESSION_KEY_MODULE` and asserting it is falsy. The day someone records a
verified address, that test goes red and the ledger entry has to be rewritten —
which is a stronger guarantee than the "docstring only" claim it replaces,
because that one would have gone quiet the moment this file was created.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

#: Verified Altana session-key modules, by chain id. Deliberately empty.
#:
#: An entry belongs here only after the same three-way check `JOB_ESCROW`
#: passed: the address is a contract, it answers the calls this module makes,
#: and its behaviour was observed on a live network rather than inferred from
#: an SDK's constants.
SESSION_KEY_MODULE: dict[int, str] = {}

#: What was read to justify each entry above, by chain id. Empty for the same
#: reason, and kept beside it so an address can never arrive without evidence.
SESSION_KEY_EVIDENCE: dict[int, tuple[str, ...]] = {}

#: Where a verifier would look. Named so the refusal can say what was searched
#: rather than only that nothing was found.
SEARCHED = (
    "vetting/addresses/56.json",
    "vetting/addresses/erc8183-56.json",
    "vetting/addresses/erc8183-97.json",
)


class NoVerifiedSessionModule(RuntimeError):
    """Raised by anything that would need an address we do not have.

    An exception rather than a `None` return, for the reason
    `registry/erc8183.py::NoVerifiedDeployment` gives: a caller that forgets to
    check a `None` builds an unsigned transaction to the zero address; a caller
    that ignores this does not compile a demo.
    """


@dataclass(frozen=True, slots=True)
class Cap:
    """The caps subset, and nothing beyond it.

    Four fields because four is what `Readme.md` §1 commits to — allowlist,
    spend cap, expiry, revoke — and a session key that could do a fifth thing
    would not be the bounded grant the page promises. `targets` is an allowlist
    and never a wildcard: a grant that can call anything is not a cap.
    """

    targets: tuple[str, ...]
    token: str
    amount: int
    expiry_ts: int

    def __post_init__(self) -> None:
        if not self.targets:
            raise ValueError("a grant with no allowlist is not a bounded grant")


@dataclass(frozen=True, slots=True)
class Step:
    """One transaction in the activation sequence, and who has to send it."""

    name: str
    sender: str
    what: str


def module_for(chain_id: int) -> str:
    """The verified session-key module for a chain, or a refusal naming the search."""
    try:
        return SESSION_KEY_MODULE[chain_id]
    except KeyError:
        raise NoVerifiedSessionModule(
            f"no verified Altana session-key module for chain {chain_id}. "
            f"Searched {', '.join(SEARCHED)}. Verify one the way "
            f"scripts/verify_erc8183.py verified JOB_ESCROW, and record it in "
            f"sessions/keys.py::SESSION_KEY_MODULE with its readings."
        ) from None


def grant_plan() -> tuple[Step, ...]:
    """The transactions a grant consists of, independent of any deployment.

    Two, and the first is the one people forget. A session key that may spend a
    token needs that token approved to the module first, and a demo that shows
    only the grant looks like a one-transaction flow until it is run.
    """
    return (
        Step(
            name="approve",
            sender="owner",
            what="approve the spend cap's token to the session-key module",
        ),
        Step(
            name="grant",
            sender="owner",
            what="register the session key with its allowlist, cap and expiry",
        ),
    )


def revoke_plan() -> tuple[Step, ...]:
    """One transaction, sent by the owner. The claim the product makes."""
    return (
        Step(
            name="revoke",
            sender="owner",
            what="revoke the session key; the agent's next transaction reverts",
        ),
    )


def capability(chain_id: int = 56) -> dict[str, Any]:
    """The whole honest answer: what is readable, what needs a signer, what is absent."""
    try:
        module = module_for(chain_id)
        available = True
        reason = ""
    except NoVerifiedSessionModule as error:
        module = ""
        available = False
        reason = str(error)

    return {
        "chain_id": chain_id,
        "available": available,
        "module": module or None,
        "reason": reason,
        "searched": list(SEARCHED),
        "evidence": list(SESSION_KEY_EVIDENCE.get(chain_id, ())),
        # `asdict`, not `__dict__`: `Step` uses slots, so it has no instance
        # dict and the attribute access raises. Safe here where it was not in
        # `api/journal.py` — every field is a string, so there is no container
        # for `asdict` to rebuild wrongly.
        "grant_plan": [asdict(step) for step in grant_plan()],
        "revoke_plan": [asdict(step) for step in revoke_plan()],
        "readable_without_a_signer": [
            "the allowlist a key was granted",
            "its spend cap and how much is left",
            "its expiry",
            "whether it has been revoked",
        ],
        "needs_a_signer": ["grant", "revoke"],
        "note": (
            "The plans above are facts about the caps subset, not about a deployment: "
            "revoking is one transaction whether or not anyone has deployed the module. "
            "Everything under readable_without_a_signer is readable only once an "
            "address is verified, and none of it is readable today."
        ),
    }
