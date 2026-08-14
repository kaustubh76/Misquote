"""ERC-8183 Agentic Commerce: what hiring an agent actually costs, in transactions.

Every competing submission will put a **Hire** button on a card. This module
exists to say what is behind one, precisely, and the answer is not one click.

## The correction that produced this file

Our own verified-facts table said ERC-8183 was "live on both BSC networks". It is
not. BNB Chain's announcement of the BNBAgent SDK says it is live on BNB Chain
**testnet**, "where developers can experiment with the full workflow today", with
"**mainnet coming soon**". The EIP is **Draft**, created February 2026, and lists
**no reference deployment addresses at all**.

So there is no address here. `HireFlow` builds and prices the transaction
sequence from the interface; it cannot send anything, and there is deliberately
no code path that could. A marketplace shipping a mainnet hire button against an
address nobody had seen would be doing the exact thing this project is named
after — and this module was written the day we caught ourselves about to.

## The count, derived rather than asserted

With the provider named at creation — so `setProvider` is unnecessary — the
client's path to escrowed funds is **four transactions**:

    approve(escrow, amount)                              ERC-20, not ERC-8183
    createJob(provider, evaluator, expiredAt, ...)  -> jobId
    setBudget(jobId, amount)
    fund(jobId)                                          Open -> Funded

Settlement adds two more, by two other parties:

    submit(jobId, deliverable)                           provider only
    complete(jobId) | reject(jobId)                      evaluator only

**Six transactions end to end.** `steps()` returns that list and `len()` is the
count, so the number on the card is computed from the sequence it describes. A
hardcoded "6" would be a claim; this is a consequence. Our earlier "3-4
transactions" was a guess in the right neighbourhood, which is how the wrong
number survives — it looks careful.

ERC-2771 meta-transactions are an **optional extension, not core**, so nothing in
the core interface batches these away. If a facilitator implements it, the client
signs off-chain and the count falls — but that is a property of a deployment, not
of the standard, and it is not assumed here.

## Who the evaluator is

`createJob` takes a **mandatory** `evaluator` which cannot be zero, and only that
address may `complete` or `reject`. That makes "who evaluates" a product
question, not a detail, because whoever it is can withhold payment.

There are three honest answers and we take the third:

1. **`evaluator = client`.** The EIP explicitly permits it "when there is no
   third-party attester". It is also the client marking their own homework: a
   client who simply never calls `complete` lets the job expire and reclaims the
   budget, so the provider carries all the risk.
2. **UMA's Optimistic Oracle**, which is what BNB's own SDK does — undisputed
   jobs settle fast, challenges escalate to UMA's Data Verification Mechanism.
   Sound, and it costs a dispute window and a bond.
3. **A chain-checkable criterion**, which is what we already have. Gap item
   **G-3** sets an InRange% floor of 70%, and spec section 4.2 requires that
   floor to be binary and verifiable **without a counterfactual**. That is
   exactly the property an optimistic oracle needs to adjudicate cheaply: a
   challenger and a voter can both recompute it from chain state, and neither has
   to be told what the position "would have" earned.

So the job's success condition is a number anyone can recompute, and the
evaluator role degrades gracefully — client-as-evaluator on testnet, an
optimistic oracle when one is wired, with the same criterion under both.
`success_criterion()` renders it, and it is the same InRange% the tearsheet
already publishes rather than a second metric invented for the escrow.
"""

from __future__ import annotations

from dataclasses import dataclass

# The EIP is Draft and publishes no deployment addresses; BNB's implementation is
# testnet-only with "mainnet coming soon". This is a mapping with nothing in it
# on purpose, so that anything wanting an address has to fail loudly rather than
# reach for a plausible-looking constant.
#
# When an address is verified on chain — name, interface, and a job read back —
# it goes here with the evidence, the way the ERC-8004 registries did.
JOB_ESCROW: dict[int, str] = {}

# Six states, per the EIP. Terminal states are the last three.
STATES = ("Open", "Funded", "Submitted", "Completed", "Rejected", "Expired")
TERMINAL = ("Completed", "Rejected", "Expired")


class NoVerifiedDeployment(RuntimeError):
    """Raised by anything that would need an address we do not have.

    Deliberately an exception rather than a `None` return. A caller that forgets
    to check a `None` builds an unsigned transaction to the zero address; a
    caller that ignores this does not compile a demo.
    """


@dataclass(frozen=True, slots=True)
class Step:
    """One transaction in the hire sequence, and who has to send it."""

    call: str
    sender: str  # "client" | "provider" | "evaluator"
    contract: str  # "escrow" | "erc20"
    why: str

    @property
    def is_erc8183(self) -> bool:
        """The ERC-20 approve is part of hiring but not part of the standard.

        Worth distinguishing, because "ERC-8183 needs four transactions" and
        "hiring needs four transactions" are different claims and only the second
        is true.
        """
        return self.contract == "escrow"


def steps(*, provider_known_at_creation: bool = True) -> tuple[Step, ...]:
    """The full sequence, in order. `len()` is the transaction count.

    `provider_known_at_creation` is the ordinary case for a marketplace: the
    client is hiring a *particular* agent, so the provider goes in at creation
    and `setProvider` is never needed. Passing `False` models an open call for
    bids, which costs one more transaction.
    """
    out = [
        Step(
            "approve",
            "client",
            "erc20",
            "the escrow pulls the budget on fund(); without this it reverts",
        ),
        Step(
            "createJob",
            "client",
            "escrow",
            "provider, evaluator, expiry, description, optional hook -> jobId",
        ),
    ]
    if not provider_known_at_creation:
        out.append(
            Step("setProvider", "client", "escrow", "only when createJob passed address(0)")
        )
    out += [
        Step("setBudget", "client", "escrow", "either party may set it, so a price can be agreed"),
        Step("fund", "client", "escrow", "Open -> Funded; the money is now escrowed"),
        Step("submit", "provider", "escrow", "Funded -> Submitted; the deliverable is a bytes32"),
        Step(
            "complete",
            "evaluator",
            "escrow",
            "Submitted -> Completed, releasing funds. Only the evaluator may. "
            "reject() refunds the client instead",
        ),
    ]
    return tuple(out)


def transaction_count(*, provider_known_at_creation: bool = True) -> int:
    """How many transactions hiring takes, end to end. Derived, never written down."""
    return len(steps(provider_known_at_creation=provider_known_at_creation))


def client_transaction_count(*, provider_known_at_creation: bool = True) -> int:
    """How many the *client* sends before the money is escrowed.

    The number a hire button is really promising, since the provider's submit and
    the evaluator's complete are somebody else's problem and happen later.
    """
    return sum(
        1
        for step in steps(provider_known_at_creation=provider_known_at_creation)
        if step.sender == "client"
    )


def success_criterion(in_range_floor: float) -> str:
    """What the evaluator is asked to decide, in one sentence.

    Deliberately the same InRange% the tearsheet already publishes. Inventing a
    second metric for the escrow would mean the thing the agent is paid on and
    the thing it is measured on could disagree, and a marketplace whose payout
    criterion differs from its published one has re-created the misquote in a new
    place.
    """
    return (
        f"The position was in range for at least {in_range_floor:.0%} of samples "
        "over the job window, recomputed from chain state. Binary, and it needs "
        "no counterfactual — spec section 4.2, gap item G-3."
    )


def escrow_address(chain_id: int) -> str:
    """The job escrow, or a refusal.

    There is no fallback and no default. The whole point of this module is that
    we do not have this address.
    """
    address = JOB_ESCROW.get(chain_id)
    if address is None:
        raise NoVerifiedDeployment(
            f"no verified ERC-8183 job escrow for chain {chain_id}. The EIP is Draft "
            "and publishes no reference deployments; BNB Chain's BNBAgent SDK is "
            "live on testnet only, with mainnet 'coming soon'. Verify an address "
            "on chain and add it to JOB_ESCROW with its evidence."
        )
    return address


def render() -> str:
    """The hire flow as a marketplace should show it: honestly, with the count."""
    sequence = steps()
    lines = [
        f"Hiring an agent through ERC-8183 takes {len(sequence)} transactions "
        f"({client_transaction_count()} from the client before the money is escrowed).",
        "",
    ]
    for i, step in enumerate(sequence, 1):
        tag = "" if step.is_erc8183 else "  [ERC-20, not ERC-8183]"
        lines.append(f"  {i}. {step.call:<11} {step.sender:<9} — {step.why}{tag}")
    lines += [
        "",
        "  ERC-2771 meta-transactions are an optional extension, not core, so",
        "  nothing in the standard batches these away.",
        "",
        "  No deployment address: the EIP is Draft with no reference deployments,",
        "  and BNB's implementation is testnet-only. This flow is unsigned.",
    ]
    return "\n".join(lines)
