"""Reading and escrowing an ERC-8183 job, against a deployment that exists.

`erc8183.py` prices the sequence and `erc8183_abi.py` names the calls. This is
the part that sends them — and, first, the part that reads a job back, because a
write path built before a read path is one nobody can check.

## The blocker this closes, and the one it does not

The ledger said the hire flow was blocked because "nothing here can sign". That
was **not true when it was written**: `chain/signer.py` signs, and
`registry/identity.py` broadcast six ERC-8004 transactions on chapel whose hashes
are in `vetting/identity/97.json`. What was actually missing was an ABI, and the
reason that distinction matters is that "we cannot sign" invites waiting and "we
have no ABI" invites reading a dispatch table.

What is still true is the part underneath: escrowing a job moves real money
through a **proxy its owner can replace**, and `JOB_ESCROW_EVIDENCE` says so on
both chains. So this defaults to chapel and to `MISQUOTE_DRY_RUN`, exactly as
`register_identity.py` does.

## Why the job struct is published as words

`getJob(uint256)` answers on both contracts and returns a struct this repository
has not decoded. `read_job` returns the **32-byte words** with the two fields
that were confirmed by agreement, and nothing else.

That is `aacp.ORDER_STATE_IS_UNDECODED` applied a second time and it is worth the
awkwardness: TermiX's `orders(bytes32)` returned thirteen well-formed words, and
exactly one of them was ever confirmed against an independent source. The other
twelve looked like plausible integers. A decoder that named all thirteen would
have been believed.
"""

from __future__ import annotations

from dataclasses import dataclass

from web3 import Web3

from misquote.registry.erc8183 import (
    EVALUATOR_ROUTER,
    JOB_ESCROW,
    PAYMENT_TOKEN,
    NoVerifiedDeployment,
    contracts_for,
)
from misquote.registry.erc8183_abi import (
    ERC20_ABI,
    KERNEL_ABI,
    KERNEL_INTERFACE,
    ROUTER_ABI,
    selector_for,
)

#: `createJob`'s custom errors, resolved by **isolating one argument at a time**
#: against the live chapel kernel. None is in any ABI we have; they are four-byte
#: selectors with no revert string, so a client hitting one gets `0x55c45de1` and
#: nothing else.
#:
#: This is the D1 checklist's "no permissioning surprises" item, answered with
#: data. The surprise is the last row.
#: Two independent methods, and they agree — which is what makes these decodes
#: rather than plausible readings. The **isolation** column is what varying one
#: argument at a time produced against the live kernel; the **name** column is a
#: brute-force preimage search over error signatures. Where both answered, they
#: say the same thing, and that agreement is the evidence. `aacp.ORDER_WORD_BUDGET`
#: was established the same way — a decode confirmed by an independent source
#: rather than by looking about right.
#:
#: Four are **unresolved and counted, not guessed**, which is `aacp.py`'s rule
#: when it resolved 21 of 65 selectors and refused to name the other 44. Their
#: behaviour is known; their spelling is not.
CREATE_JOB_ERRORS: dict[str, str] = {
    "0x55c45de1": "HookRequired() — hook is the zero address",
    "0x1a5d3d5f": "hook is not an accepted hook contract (name unresolved)",
    "0xd92e233d": "evaluator is the zero address (name unresolved)",
    "0xf7a0748c": "expiredAt is zero or in the past — it is an absolute timestamp, "
    "not a duration (name unresolved)",
    "0xb40b2a0e": "ExpiryTooLong() — expiredAt is too far in the future",
}

#: Errors from the rest of the sequence, same two methods.
#: **Two of these were read wrong, and a fork is what found out.**
#:
#: `0x32d53d69` was recorded as *"fund() from a wallet holding none of the
#: payment token"*, inferred from a run where the balance happened to be zero.
#: It is `PolicyNotSet()`. A fork with 10,000 tokens in the client's hand and an
#: allowance above the budget reverts with exactly the same four bytes, which is
#: the observation the old reading could not have survived — and could not have
#: been made without a balance nobody could obtain.
#:
#: `0xc94463e3` was recorded as *"consistent with the hook having registered the
#: job already"*. It is `PolicyNotWhitelisted()` — the opposite: nothing had
#: registered anything, and the policy offered was not on the router's list.
#:
#: The names come from the public signature database, not from this repository's
#: own 21,060-candidate search, and they are recorded as *resolved* rather than
#: *inferred* for that reason. `scripts/prove_escrow_fund.py` then drove the
#: whole flow to settlement on a fork, which is what turns a name into a check.
FLOW_ERRORS: dict[str, str] = {
    "0xff97b861": "ZeroBudget() — fund() refuses a budget of zero, so a job with "
    "no budget cannot be escrowed even as a gesture",
    "0x32d53d69": "PolicyNotSet() — fund() on a job whose policy was never "
    "registered. Nothing to do with the balance: the fork proof holds ten times "
    "the budget and reverts identically until registerJob succeeds",
    "0xc94463e3": "PolicyNotWhitelisted() — registerJob offered a policy the "
    "router does not accept. Observed on chapel; mainnet fails earlier, at "
    "RouterNotEvaluator()",
    "0xec43ea50": "RouterNotEvaluator() — registerJob on a job whose evaluator "
    "is not the EvaluatorRouter. The address that settles and the address named "
    "as evaluator are the same one; see EVALUATOR_MUST_BE_THE_ROUTER",
    "0x8e78f0cb": "WrongStatus() — submit() before fund() succeeded. The status "
    "machine is real and the order in steps() is not decorative",
    "0x17be5b7b": "NotDecided() — settle() before the OptimisticPolicy has a "
    "decision to enforce. Observed on mainnet job 56681 both before and after "
    "its dispute window, so waiting alone does not produce one",
    "0x15e5dd74": "SubmissionTooLate() — submit() on a job whose expiredAt is "
    "not further away than the policy's dispute window. Measured first: eight "
    "fork runs identical but for the expiry put the boundary between 168h and "
    "169h against a 604,800s window. Named later, out of @bnbagent/sdk, which "
    "guards the same inequality before it sends and quotes the revert by name; "
    "keccak confirms it. Recorded as unresolved until then, and before that as "
    "one address being both client and provider, which the 720h self-provider "
    "run falsifies by settling",
}

#: **The evaluator must be the EvaluatorRouter itself.**
#:
#: `create_job` refuses a zero evaluator because only the evaluator may settle,
#: and that was right as far as it went. What no reading had established is
#: which non-zero address the deployment accepts: name a third wallet and
#: `registerJob` reverts `RouterNotEvaluator()`, so the job can never be
#: registered, so `fund` reverts `PolicyNotSet()` — two unnamed errors, one
#: cause, and neither of them about money.
#:
#: A client built from the EIP names a human evaluator here. That client cannot
#: escrow anything on this deployment, and the failure surfaces two transactions
#: later than the mistake.
#: **A job cannot be submitted to unless it outlives its own dispute window.**
#:
#: `submit` reverts `SubmissionTooLate()` (`0x15e5dd74`) whenever
#: `expiredAt - now <= disputeWindow()`,
#: and the deployment's window is 604,800s. Measured rather than reasoned: eight
#: runs on a fork of mainnet, identical but for the expiry, refuse at 168h and
#: accept at 169h — `vetting/identity/submit-expiry-fork-56.json` carries all
#: eight. It makes sense after the fact, since a submission that cannot clear
#: its dispute window before the job expires could never be settled.
#:
#: `@bnbagent/sdk` guards the identical inequality before it sends — an
#: independent implementation agreeing with a measurement taken without it,
#: and the source of the name. Their own CLI then defaults `--deadline-min`
#: to 30, which is 336 times below the threshold their SDK enforces.
#:
#: This is why job 56681 stopped four calls in. `hire_mainnet.py` defaulted to
#: twelve hours, so the release half was never reachable — and the reason
#: recorded at the time, that the policy reaches no decision, was a symptom.
#: `settle` had nothing to decide about because nothing had been submitted.
#:
#: Job 56718 asked for 192 hours and `submit` mined on mainnet
#: (`vetting/identity/hire-mainnet-56-submitted.json`). The default is 192 now:
#: one that cannot reach `submit` spends four transactions of real gas to fail.
SUBMIT_NEEDS_EXPIRY_BEYOND_DISPUTE_WINDOW = True

EVALUATOR_MUST_BE_THE_ROUTER = True

#: **The hook is mandatory, and only one address is accepted.**
#:
#: The EIP describes `hook` as an extension point and `erc8183.steps()` records
#: it as one — "provider, evaluator, expiredAt, description, hook -> jobId". On
#: this deployment `address(0)` — the natural way to say *no hook* — reverts, and
#: so does every other contract tried: the kernel itself, the OptimisticPolicy,
#: an EOA. The EvaluatorRouter is the only address that works.
#:
#: Found by varying one argument at a time, because five arguments and an
#: unnamed error is a search space, not a bug report. A client built from the
#: standard passes zero here and fails on the second transaction of seven with no
#: reason string.
REQUIRED_HOOK_IS_THE_ROUTER = True

#: Which word carries the job id. **The only field confirmed by agreement**, and
#: the way it was confirmed is the point: ask for job 743 and word 1 comes back
#: `0x2e7`. That is an independent source — the id we chose — rather than a
#: plausible integer that looked about right.
#:
#: `aacp.ORDER_WORD_BUDGET` was established the same way, against TermiX's public
#: explorer, on 20 of 20 orders. Nothing else in this struct has that, so nothing
#: else here is named.
JOB_WORD_ID = 1

#: An unknown job **does not revert and does not return zeros.**
#:
#: This is P-18's trap in a new costume. There it was thirteen zero words for an
#: order in the wrong settlement book. Here `getJob(10**9)` returns thirteen
#: words of which two are non-zero — and those two are `0x20` and `0x160`, the
#: ABI head offsets every dynamic-struct return carries. So the obvious existence
#: test, "any word is non-zero", answers **true for every id that has never
#: existed**, and a caller gets a confident, well-formed, entirely fictional job.
#:
#: A real job returns **15** words and an unknown one **13**, which is another
#: tell — but a length check would break the moment a job's description is short
#: enough to pack differently. The id comparison is the one that cannot.
UNKNOWN_JOB_ANSWERS_WITH_ABI_OFFSETS = True


@dataclass(frozen=True, slots=True)
class Job:
    """A job as the chain returned it: the id asked for, and the raw words.

    No `status`, no `budget`, no `provider`. Those are in there and this
    repository has not confirmed which word is which, so naming them would be a
    labelling nobody checked. `words` is what a reader can disagree with.
    """

    job_id: int
    words: tuple[str, ...]
    exists: bool

    @property
    def word_count(self) -> int:
        return len(self.words)


def read_job(w3, chain_id: int, job_id: int) -> Job:
    """One job, as words. Raises for a chain with no verified deployment."""
    kernel = JOB_ESCROW.get(chain_id)
    if kernel is None:
        raise NoVerifiedDeployment(
            f"no verified ERC-8183 deployment for chain {chain_id}; "
            f"verify one with scripts/verify_erc8183.py first"
        )

    data = bytes.fromhex(selector_for("getJob(uint256)")[2:]) + job_id.to_bytes(32, "big")
    raw = w3.eth.call({"to": Web3.to_checksum_address(kernel), "data": data})
    words = tuple("0x" + raw[i : i + 32].hex() for i in range(0, len(raw), 32))
    # Existence is the id coming back, not the answer being non-empty.
    #
    # `any(int(w, 16) for w in words)` was the first version of this line and it
    # is **wrong for every id that has never existed**: the ABI head offsets are
    # non-zero on every return, so it said `True` for job 10**9. See
    # UNKNOWN_JOB_ANSWERS_WITH_ABI_OFFSETS.
    echoed = int(words[JOB_WORD_ID], 16) if len(words) > JOB_WORD_ID else 0
    return Job(job_id=job_id, words=words, exists=echoed == job_id and job_id > 0)


def job_count(w3, chain_id: int) -> int:
    """How many jobs this deployment has seen. The number that made P-24."""
    kernel = JOB_ESCROW.get(chain_id)
    if kernel is None:
        raise NoVerifiedDeployment(f"no verified ERC-8183 deployment for chain {chain_id}")
    data = bytes.fromhex(selector_for("jobCounter()")[2:])
    raw = w3.eth.call({"to": Web3.to_checksum_address(kernel), "data": data})
    return int.from_bytes(raw[:32], "big")


class JobWriter:
    """One deployment, one signer, one transaction per call.

    `registry/identity.py::IdentityWriter` is the shape — same `BscSigner`, same
    receipt list, same gas accounting derived from receipts rather than
    estimates. Three contracts rather than one, because the deployment splits
    creation and funding (the kernel) from binding and settlement (the router),
    and the budget is pulled through an ERC-20 that is neither.
    """

    __slots__ = ("signer", "chain_id", "kernel", "router", "token", "addresses", "sent")

    def __init__(self, signer, chain_id: int | None = None) -> None:
        chain_id = signer.chain_id if chain_id is None else int(chain_id)
        if chain_id != signer.chain_id:
            raise ValueError(
                f"the kernel is on chain {chain_id} and the signer is on {signer.chain_id}"
            )
        self.addresses = contracts_for(chain_id)  # raises for an unverified chain

        self.signer = signer
        self.chain_id = chain_id
        self.kernel = signer.w3.eth.contract(
            address=Web3.to_checksum_address(self.addresses["kernel"]), abi=KERNEL_ABI
        )
        self.router = signer.w3.eth.contract(
            address=Web3.to_checksum_address(self.addresses["router"]), abi=ROUTER_ABI
        )
        self.token = signer.w3.eth.contract(
            address=Web3.to_checksum_address(self.addresses["erc20"]), abi=ERC20_ABI
        )
        self.sent: list = []

    # --- reads, taken before every write -----------------------------------

    def balance(self) -> int:
        return int(self.token.functions.balanceOf(self.signer.address).call())

    def allowance(self) -> int:
        return int(
            self.token.functions.allowance(
                self.signer.address, Web3.to_checksum_address(self.addresses["kernel"])
            ).call()
        )

    def counter(self) -> int:
        return job_count(self.signer.w3, self.chain_id)

    # --- writes -------------------------------------------------------------

    def approve(self, amount: int):
        """Let the kernel pull the budget. ERC-20, not ERC-8183.

        `Step.is_erc8183` draws that line for a reason: "ERC-8183 needs four
        transactions" and "hiring needs four transactions" are different claims
        and only the second is true.
        """
        call = self.token.functions.approve(
            Web3.to_checksum_address(self.addresses["kernel"]), int(amount)
        )
        result = self.signer.send(self.signer.build(call))
        self.sent.append(result)
        return result

    def create_job(
        self,
        *,
        provider: str,
        evaluator: str,
        expired_at: int,
        description: str,
        hook: str | None = None,
    ):
        """`createJob`. Returns `(job_id, receipt)`.

        The provider is an argument here and there is no `setProvider` — the
        correction P-24 made to `steps()`, enforced by the ABI rather than
        remembered.

        The evaluator is **mandatory and may not be zero**: only it can complete
        or reject, so a zero evaluator is a job nobody can settle. Refused before
        anything is built, because a reverted receipt says a transaction failed
        rather than which argument was wrong.
        """
        if int(evaluator, 16) == 0:
            raise ValueError(
                "the evaluator is mandatory and cannot be zero — only it may "
                "complete or reject, so a zero evaluator escrows money nobody "
                "can release. The chain agrees: createJob reverts 0xd92e233d"
            )
        if not description.strip():
            raise ValueError("refusing to create a job with an empty description")

        # Defaulting to the router rather than to zero, which is the opposite of
        # what the EIP's optional-extension wording suggests and what the chain
        # requires. Zero reverts `0xd92e233d`'s neighbour, `0x55c45de1`, with no
        # reason string — see CREATE_JOB_ERRORS.
        hook = hook or self.addresses["router"]
        if int(hook, 16) == 0:
            raise ValueError(
                "the hook cannot be zero on this deployment: createJob reverts "
                "0x55c45de1. Only the EvaluatorRouter has been observed to be "
                "accepted — see REQUIRED_HOOK_IS_THE_ROUTER"
            )
        if int(expired_at) <= 0:
            raise ValueError(
                f"expiredAt {expired_at} is an absolute unix timestamp, not a "
                f"duration; the chain reverts 0xf7a0748c for a past or zero value"
            )

        before = self.counter()
        call = self.kernel.functions.createJob(
            Web3.to_checksum_address(provider),
            Web3.to_checksum_address(evaluator),
            int(expired_at),
            description,
            Web3.to_checksum_address(hook),
        )
        result = self.signer.send(self.signer.build(call))
        self.sent.append(result)
        # Read the counter rather than decode the return value: `getJob`'s struct
        # is undecoded, and a job id inferred from a counter that moved by one is
        # a reading this code can defend.
        after = self.counter()
        if after != before + 1:
            raise RuntimeError(
                f"jobCounter went {before} -> {after}; expected exactly one new "
                f"job, so the id cannot be inferred safely"
            )
        return after, result

    def register_job(self, job_id: int, policy: str | None = None):
        """`registerJob` — on the **router**, not the kernel.

        The third transaction, and the one a client sending everything to one
        address reverts on. P-24 found it; this is where that finding stops being
        a paragraph.
        """
        target = policy or self.addresses["policy"]
        call = self.router.functions.registerJob(int(job_id), Web3.to_checksum_address(target))
        result = self.signer.send(self.signer.build(call))
        self.sent.append(result)
        return result

    def set_budget(self, job_id: int, amount: int, opt_params: bytes = b""):
        call = self.kernel.functions.setBudget(int(job_id), int(amount), opt_params)
        result = self.signer.send(self.signer.build(call))
        self.sent.append(result)
        return result

    def fund(self, job_id: int, expected_budget: int, opt_params: bytes = b""):
        """`fund`. Open -> Funded; the money is escrowed after this and not before.

        Checks the allowance first. Without it the kernel's pull reverts, and a
        failed `fund` after a successful `setBudget` leaves a job that looks
        created and holds nothing.
        """
        if self.allowance() < int(expected_budget):
            raise ValueError(
                f"allowance {self.allowance()} is below the budget "
                f"{expected_budget}; the kernel's pull would revert. Send "
                f"approve() first — it is step one of seven for this reason"
            )
        call = self.kernel.functions.fund(int(job_id), int(expected_budget), opt_params)
        result = self.signer.send(self.signer.build(call))
        self.sent.append(result)
        return result

    def submit(self, job_id: int, deliverable: bytes, opt_params: bytes = b""):
        """`submit`. Funded -> Submitted, sent by the **provider**.

        Three arguments, not the EIP's two — the signature is
        `submit(uint256,bytes32,bytes)` and a client encoding the standard's
        shape hits a selector that does not exist. That is the finding
        `erc8183_abi.py` recovered from bytecode, and this is the call site that
        depends on it.

        `deliverable` is a 32-byte commitment to whatever was produced. Nothing
        on chain interprets it, so this does not pretend to: it is passed
        through and recorded, never decoded.
        """
        if len(deliverable) != 32:
            raise ValueError(
                f"deliverable is {len(deliverable)} bytes; the ABI takes a "
                f"bytes32 and web3 will not pad it for you"
            )
        call = self.kernel.functions.submit(int(job_id), deliverable, opt_params)
        result = self.signer.send(self.signer.build(call))
        self.sent.append(result)
        return result

    def settle(self, job_id: int, opt_params: bytes = b""):
        """`settle` — on the **router**, sent by the evaluator.

        The last of the three contracts. `createJob` refuses a zero evaluator
        because only the evaluator reaches here, and a job nobody can settle is
        money that only `claimRefund` can retrieve.
        """
        call = self.router.functions.settle(int(job_id), opt_params)
        result = self.signer.send(self.signer.build(call))
        self.sent.append(result)
        return result

    def claim_refund(self, job_id: int):
        """The recourse, after `expiredAt`, when nobody settled."""
        call = self.kernel.functions.claimRefund(int(job_id))
        result = self.signer.send(self.signer.build(call))
        self.sent.append(result)
        return result

    @property
    def gas_spent_wei(self) -> int:
        return sum(tx.gas_cost_wei for tx in self.sent)


def drift(chain_id: int) -> list[str]:
    """TermiX's recorded addresses against their live config, before signing.

    `aacp.fetch_live_contracts()` and `aacp.mismatches()` were written for this
    and had **no caller** — `tests/test_no_dead_definitions.py` exempted them as
    "built ahead, and recorded as built-ahead rather than allowed to look wired",
    with the note that "the check belongs on the signing path, and that path does
    not exist".

    It exists now. Returns the mismatches; an empty list is the answer that
    permits a send.
    """
    from misquote.registry.aacp import NoDeployment, fetch_live_contracts, mismatches

    try:
        live = fetch_live_contracts(chain_id)
    except NoDeployment:
        # TermiX documents no testnet, so there is no live config to drift from
        # on chapel. Not a mismatch — an inapplicable check, and saying which is
        # the whole point of returning a list rather than a bool.
        return []
    return mismatches(chain_id, live)


__all__ = [
    "EVALUATOR_ROUTER",
    "KERNEL_INTERFACE",
    "PAYMENT_TOKEN",
    "JOB_WORD_ID",
    "UNKNOWN_JOB_ANSWERS_WITH_ABI_OFFSETS",
    "CREATE_JOB_ERRORS",
    "FLOW_ERRORS",
    "REQUIRED_HOOK_IS_THE_ROUTER",
    "EVALUATOR_MUST_BE_THE_ROUTER",
    "SUBMIT_NEEDS_EXPIRY_BEYOND_DISPUTE_WINDOW",
    "Job",
    "JobWriter",
    "drift",
    "job_count",
    "read_job",
]
