"""ERC-8183 Agentic Commerce: what hiring an agent actually costs, in transactions.

Every competing submission will put a **Hire** button on a card. This module
exists to say what is behind one, precisely, and the answer is not one click.

## The correction that produced this file

Our own verified-facts table said ERC-8183 was "live on both BSC networks". It is
not. BNB Chain's announcement of the BNBAgent SDK says it is live on BNB Chain
**testnet**, "where developers can experiment with the full workflow today", with
"**mainnet coming soon**". The EIP is **Draft**, created February 2026, and lists
**no reference deployment addresses at all**.

This module was written the day we caught ourselves about to ship a mainnet hire
button against an address nobody had seen. It shipped with `JOB_ESCROW` empty.

**It had one entry, and the entry was wrong.** TermiX's own AACP — the sponsor
of the track this work serves — runs a `TermixEscrow` on BSC mainnet, and it was
added here on the strength of being a real, verified, USDT-settling escrow whose
identity registry is byte-identical to the ERC-8004 one this codebase already
reads. Everything in that sentence is still true. It is also not sufficient,
and the earlier evidence said so in its own words: *nobody has read an ERC-8183
job back out of it*.

Somebody has now, and the answer was no. The implementation's dispatch table was
recovered from the deployed bytecode, and **none of the seven calls `steps()`
models — `createJob`, `setProvider`, `setBudget`, `fund`, `submit`, `complete`,
`reject` — is present**, across 5,894 candidate signatures. What is there is an
order-keyed escrow: `orders(bytes32)` and `acceptOrder(bytes32)`. Jobs are
identified by a `bytes32` order id, not the EIP's `uint256` jobId, which is why
`nextJobId()`, `jobCount()` and `jobs(uint256)` all reverted — they were never
the wrong *call*, they were the wrong *interface*.

So TermiX's escrow left `JOB_ESCROW`, and for a while the mapping was empty and
`escrow_address()` raised. That was the module's own rule applied to itself
rather than around itself: this mapping is for **verified ERC-8183 job
escrows**, a real escrow that does not implement ERC-8183 is not one, and a
mapping whose name overstates its contents is the misquote wearing our own logo.
What that contract *is* is recorded in `registry/aacp.py`, under its real
interface, with the readings.

**It is not empty now, and the reason is not a relaxation of that rule.** The
claim "the EIP publishes no reference deployments" was true and was the wrong
question: Altana ships `ERC8183_ADDRESSES` for both BSC networks, and nobody
here had looked. `scripts/verify_erc8183.py` looked, three ways, and every check
passed on both chains — 56,632 jobs on mainnet against a kernel that answers
`jobCounter()` and `paymentToken()`. The entries carry those readings. See P-24.

The rule is **no entry without evidence**, and a test enforces it.

Nothing here can send. `steps()` builds and prices the sequence; there is no
signer, no web3, and deliberately no code path that could acquire one.

## The count, derived rather than asserted

The provider is an argument to `createJob` and there is no setter for it, so the
client's path to escrowed funds is **five transactions**:

    approve(kernel, amount)                              ERC-20, not ERC-8183
    createJob(provider, evaluator, expiredAt, ...)  -> jobId
    registerJob(jobId, policy)                           EvaluatorRouter, not the kernel
    setBudget(jobId, amount, optParams)
    fund(jobId, expectedBudget, optParams)               Open -> Funded

Settlement adds two more, by two other parties:

    submit(jobId, deliverable)                           provider only
    settle(jobId, evidence)                              EvaluatorRouter, evaluator only

**Seven transactions end to end.** `steps()` returns that list and `len()` is the
count, so the number on the card is computed from the sequence it describes. A
hardcoded "7" would be a claim; this is a consequence. Our earlier "3-4
transactions" was a guess in the right neighbourhood, which is how the wrong
number survives — it looks careful.

The count was **six** until 21 Aug 2026, when the sequence was checked against a
deployed kernel rather than read off the Draft EIP. `registerJob` is the extra
one, and it goes to a second contract — which is the more useful half of the
correction: a client that sent all seven to one address would revert on the
third.

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

# The AgenticCommerce kernel, verified on chain rather than taken from a table.
#
# This was empty, and the reason given was that the EIP is Draft and "lists no
# reference deployment addresses at all". That is still true of the EIP. It was
# never true of the ecosystem: `@altananetwork/sdk@0.8.0` publishes
# `ERC8183_ADDRESSES` for both BSC networks, and nobody here had looked.
#
# `scripts/verify_erc8183.py` looked, the same three ways `verify_venus.py` does,
# and every check passed on both chains — see `JOB_ESCROW_EVIDENCE`. The entry
# exists because of those readings, not because a table said so; that is the
# rule this module set for itself and it is being followed rather than waived.
JOB_ESCROW: dict[int, str] = {
    56: "0xEa4DAa3100A767e86FDed867729ae7446476EBA6",
    97: "0xa206c0517B6371C6638CD9e4a42Cc9f02A33B0DE",
}

#: The rest of the deployment, carried because a kernel alone cannot settle.
#: `registerJob` and `settle` live on the EvaluatorRouter and the dispute window
#: on the OptimisticPolicy — three contracts, which is itself a correction to
#: the single-escrow shape `steps()` originally modelled.
EVALUATOR_ROUTER: dict[int, str] = {
    56: "0x51895229E12F9876011789B04f8698af06cCD6DA",
    97: "0xD7d36D66d2F1B608A0F943f722D27e3744f66F25",
}
OPTIMISTIC_POLICY: dict[int, str] = {
    56: "0x9C01845705b3078Aa2e8cfF7520a6376FD766dE5",
    97: "0x4F4678D4439feC812Ac7674Bb3Efb4C8f5Fb78A6",
}
#: What a job is denominated in. Read from the kernel itself, not from the table.
PAYMENT_TOKEN: dict[int, str] = {
    56: "0xcE24439F2D9C6a2289F741120FE202248B666666",
    97: "0xc70B8741B8B07A6d61E54fd4B20f22Fa648E5565",
}

# What was actually checked, and — more importantly — what was not.
#
# Kept as a record because the readings are the interesting output, and
# deleting them would erase the correction along with the claim. Keyed by
# address rather than by chain: it is evidence about a contract, and that
# contract is not this module's escrow — a different one is.
#
# The last line is the one that moved. It used to say the job interface had not
# been exercised. It has been now, and it is not there.
FORMER_CANDIDATE_EVIDENCE: dict[str, tuple[str, ...]] = {
    "0xCE02f987D8b8AF694E13C8a843Db9c77caBF544c": (
        "TermiX AACP `TermixEscrow` (USDT). Address appears in TermiX's own live "
        "config at /api/v1/config/contracts, and our recorded snapshot matched it "
        "with zero mismatches across 16 addresses.",
        "EIP-1967 proxy: 170 bytes of code whose bytecode contains the 1967 "
        "implementation slot constant; implementation 0xbc8225ee...1e854 holds "
        "17,941 bytes.",
        "`settlementToken()` returns 0x55d3...7955 — read off the escrow itself, "
        "and byte-identical to our USDT_MAINNET and to token0 of the flagship pool.",
        "TermiX's IdentityRegistry is 0x8004A169...a432, byte-identical to the "
        "ERC-8004 registry this codebase already reads, whose `name()` answers "
        "'AgentIdentity'.",
        "NOT ERC-8183. The implementation's dispatch table was recovered from the "
        "deployed bytecode: none of `createJob`, `setProvider`, `setBudget`, "
        "`fund`, `submit`, `complete` or `reject` appears, across 5,894 candidate "
        "signatures. It is an order-keyed escrow — `orders(bytes32)`, "
        "`acceptOrder(bytes32)` — so `jobs(uint256)` reverted because the "
        "interface differs, not because the call was misspelled.",
        "SECURITY: `owner()` returns 0x1095ded9...5e42. The contract holding "
        "escrowed funds is upgradeable by that owner, so the code a job is "
        "escrowed under is not the code it may be settled under. That is a "
        "property of the venue, not a defect, but a marketplace that routes user "
        "funds through it should say so rather than discover it later.",
        "NO TESTNET: TermiX documents chains 56 and 8453 only. Anything that "
        "writes runs on a fork first.",
    ),
}

#: What was read to justify each entry in `JOB_ESCROW`, and — the half that
#: matters more — what those readings do not establish.
#:
#: This header used to say "addresses that were considered and rejected", which
#: belongs to `FORMER_CANDIDATE_EVIDENCE` below. The two dicts had each other's
#: descriptions: the accepted deployment was labelled as a rejection and the
#: rejection as a record of what was checked.
JOB_ESCROW_EVIDENCE: dict[int, tuple[str, ...]] = {
    56: (
        "Bytecode present at all five addresses: kernel 130 bytes (proxy), "
        "EvaluatorRouter 130, OptimisticPolicy 4,413, registry 130, payment "
        "token 2,007. Read 21 Aug 2026 at block 117,226,038.",
        "The interface answers: `jobCounter()` returns **56,632**, "
        "`paymentToken()` returns 0xce24439f...666666, and the policy's "
        "`disputeWindow()` returns 604,800 (seven days).",
        "The answers agree: the kernel's own `paymentToken()` matches the "
        "published table, and the table's registry is byte-identical to the "
        "address we verified independently months earlier.",
        "56,632 jobs is what distinguishes this from the previous candidate, "
        "which implemented none of ERC-8183. This one answers the EIP's own "
        "accessors and has been used at scale.",
        "NOT VERIFIED: the write path. Every reading above is a call, never a "
        "send. A contract that answers `jobCounter()` and one that will accept "
        "*our* job are different claims, and only the first is supported.",
        "SECURITY: three of the five are 130-byte proxies, so the code holding "
        "escrowed funds is upgradeable by its owner. We verified what they "
        "delegate to today, not who may change it.",
    ),
    97: (
        "Same five checks, same shapes, chapel testnet. `jobCounter()` returns "
        "581 and `disputeWindow()` returns 86,400 (one day, shorter than "
        "mainnet's seven).",
        "The table's `registry` equals `erc8004.IDENTITY_REGISTRY[97]`, again byte-identical.",
        "NOT VERIFIED: the write path is unexercised here too — same reason, "
        "same absence of a signer. Chapel would be the honest place to exercise "
        "it, and that has not been done.",
        "SECURITY: proxies again, and a one-day dispute window against "
        "mainnet's seven. A flow rehearsed on chapel is not rehearsing "
        "mainnet's timing.",
    ),
}

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
    contract: str  # "kernel" | "router" | "erc20"
    why: str

    @property
    def is_erc8183(self) -> bool:
        """The ERC-20 approve is part of hiring but not part of the standard.

        Worth distinguishing, because "ERC-8183 needs four transactions" and
        "hiring needs four transactions" are different claims and only the second
        is true.

        Two contracts count, not one. The deployed standard splits creation and
        funding (the AgenticCommerce kernel) from binding and settlement (the
        EvaluatorRouter) — a shape the single-`escrow` version of this property
        could not express, and which is exactly what a caller sending everything
        to one address would discover halfway through.
        """
        return self.contract in ("kernel", "router")


def contracts_for(chain_id: int) -> dict[str, str]:
    """Every address a hire touches on one chain, by the role `steps()` names.

    `steps()` built its sequence with the string literals `"kernel"` and
    `"router"` while `EVALUATOR_ROUTER`, `OPTIMISTIC_POLICY` and `PAYMENT_TOKEN`
    sat verified and unread three screens above. The module checked three
    addresses, wrote them down, and then priced a flow against two words — so
    nothing could have caught the roles pointing at the wrong contracts.

    Raises for a chain with no verified deployment, exactly as `escrow_address`
    does, rather than returning a partial map.
    """
    if chain_id not in JOB_ESCROW:
        raise NoVerifiedDeployment(
            f"no verified ERC-8183 deployment for chain {chain_id}. "
            f"Verify one with scripts/verify_erc8183.py before pricing a flow against it."
        )
    return {
        "kernel": JOB_ESCROW[chain_id],
        "router": EVALUATOR_ROUTER[chain_id],
        "policy": OPTIMISTIC_POLICY[chain_id],
        "erc20": PAYMENT_TOKEN[chain_id],
    }


def steps(*, provider_known_at_creation: bool = True) -> tuple[Step, ...]:
    """The full sequence, in order. `len()` is the transaction count.

    ## Corrected against the deployed kernel, 21 Aug 2026

    This modelled seven calls on a single escrow: `createJob`, `setProvider`,
    `setBudget`, `fund`, `submit`, `complete`, `reject`. That was a reading of
    the EIP, and the EIP is Draft. The deployment differs in three ways, all
    confirmed against the AgenticCommerce kernel's own ABI:

    - **There is no `setProvider`.** The provider is an argument to `createJob`,
      which this module's own docstring had already deduced from TermiX's
      bytecode without following through to the sequence. So
      `provider_known_at_creation=False` no longer costs an extra transaction —
      it is not a supported shape at all, and passing it now says so.
    - **Settlement is on a different contract.** `registerJob` binds a dispute
      policy and `settle` releases, and both live on the **EvaluatorRouter**,
      not the kernel. A sequence that sent everything to one address would
      revert halfway through.
    - **The accessors are `jobCounter()` and `getJob(uint256)`**, not
      `nextJobId()` / `jobs(uint256)`. P-18 probed for the second pair on
      TermiX's escrow and found neither, and recorded that as the wrong
      *interface* — which was right about the contract and, it turns out,
      partly wrong about the names.

    P-18's conclusion stands: `TermixEscrow` implements none of this. What
    changes is that the sequence below now describes a contract that exists.

    ## `setBudget` before `registerJob`, corrected 7 Sep 2026

    This published `registerJob` third and `setBudget` fourth. **No run has ever
    sent them in that order.** All three scripts that drive the flow send
    `setBudget` first — `hire_mainnet.py:207-208`, `hire_agent.py:224-229`,
    `prove_escrow_fund.py:222-227` — and between them they have mined jobs 746 on
    chapel, 56681 and 56718 on mainnet, and every fork rehearsal.

    So `/registry` rendered a lifecycle table in one order while the console
    directly beneath it offered the buttons in the other, and the table was the
    half nobody had executed. The order here is now the order that has run.
    """
    if not provider_known_at_creation:
        raise ValueError(
            "the deployed AgenticCommerce kernel takes the provider as an argument "
            "to createJob and has no setProvider. An open call for bids is not a "
            "shape this deployment supports, so pricing it would be fiction."
        )

    return (
        Step(
            "approve",
            "client",
            "erc20",
            "the kernel pulls the budget on fund(); without this it reverts",
        ),
        Step(
            "createJob",
            "client",
            "kernel",
            "provider, evaluator, expiredAt, description, hook -> jobId",
        ),
        Step(
            "setBudget",
            "client",
            "kernel",
            "either party may set it, so a price can be agreed",
        ),
        Step(
            "registerJob",
            "client",
            "router",
            "binds the dispute policy on the EvaluatorRouter — a second contract",
        ),
        Step("fund", "client", "kernel", "Open -> Funded; the money is now escrowed"),
        Step(
            "submit",
            "provider",
            "kernel",
            "Funded -> Submitted. The deployment takes three arguments, not "
            "the EIP's two, so a client encoding the standard's shape reverts "
            "with no reason string",
        ),
        Step(
            "settle",
            "evaluator",
            "router",
            "releases escrow or opens a dispute, on the EvaluatorRouter. The "
            "OptimisticPolicy's disputeWindow() is 604,800s on mainnet",
        ),
    )


def recourse() -> tuple[Step, ...]:
    """What the client can send when nobody settles. Not part of `steps()`.

    `claimRefund(uint256)` is on the kernel — selector `0x5b7baf64`, present in
    the deployed dispatch table — and it was modelled nowhere, which left the
    published flow with no answer to the obvious question: *what happens to my
    money if the provider never submits?*

    **Deliberately not appended to `steps()`.** It is an alternative terminal
    branch, not an eighth transaction: nobody sends both `settle` and
    `claimRefund`, so folding it in would make `transaction_count()` report a
    hire as costing eight when no hire ever does. The count is derived from the
    sequence precisely so it means something, and quietly widening the sequence
    to include a branch would be the kind of number this project exists to
    refuse.

    What it does change is the answer to "who bears the risk". The EIP's
    evaluator is mandatory and only it may complete or reject, so a client whose
    evaluator goes silent is not stuck — they wait out `expiredAt` and reclaim.
    That is worth publishing beside the flow rather than discovering.
    """
    return (
        Step(
            "claimRefund",
            "client",
            "kernel",
            "after expiredAt, with no settlement: the client reclaims the escrowed "
            "budget. The answer to 'what if nobody ever completes the job'",
        ),
    )


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

    There is no fallback and no default: a chain without a verified deployment
    raises rather than returning a plausible address. Two chains have one now,
    and each carries the readings that put it there — see `JOB_ESCROW_EVIDENCE`,
    including the two things those readings do **not** establish.
    """
    address = JOB_ESCROW.get(chain_id)
    if address is None:
        raise NoVerifiedDeployment(
            f"no verified ERC-8183 job escrow for chain {chain_id}. The EIP is Draft "
            "and publishes no reference deployments; BNB Chain's BNBAgent SDK is "
            "live on testnet only, with mainnet 'coming soon'. "
            "TermiX's TermixEscrow was carried here and removed: its deployed "
            "bytecode implements none of createJob/setProvider/setBudget/fund/"
            "submit/complete/reject, across 5,894 candidate signatures. It is an "
            "order-keyed escrow — orders(bytes32) — so it is a real escrow that is "
            "not this standard. See registry/aacp.py:ESCROW_INTERFACE. "
            "Verify an address on chain and add it to JOB_ESCROW with its evidence."
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
    ]
    lines += [
        "  If nobody settles, the client's recourse after expiredAt is:",
        "",
    ]
    for step in recourse():
        lines.append(f"     {step.call:<11} {step.sender:<9} — {step.why}")
    lines.append("")

    if JOB_ESCROW:
        chains = ", ".join(str(c) for c in sorted(JOB_ESCROW))
        lines += [
            f"  Escrow verified on chain {chains}. What was checked, and what was",
            "  not, is in JOB_ESCROW_EVIDENCE — including that the contract holding",
            "  escrowed funds is upgradeable by its owner.",
            "",
            # This used to end "including that nobody has yet read an ERC-8183 job
            # back out of it". Somebody has: `registry/hire.py` reads jobs off the
            # chapel kernel and this repository created one. Leaving the sentence
            # would have been the under-claiming direction of the same defect the
            # ledger keeps catching in the over-claiming one.
            "  A job has been read back, and one created: see registry/hire.py and",
            "  vetting/identity/hire-97.json. What has *not* happened is an escrow —",
            "  fund() moves the deployment's payment token and that token is",
            "  owner-minted — but it trades on PancakeSwap against USDT and "
            "WBNB, so the escrow is a purchase away rather than out of reach.",
        ]
    else:
        lines += [
            "  No deployment address: the EIP is Draft with no reference",
            "  deployments. Nothing here can be sent anywhere.",
        ]
    lines.append("  This flow is unsigned either way: there is no key in this module.")
    return "\n".join(lines)
