"""What this marketplace is, as a citizen of the standards it claims to use.

    uv run python scripts/registry_report.py                  # offline only
    uv run python scripts/registry_report.py --sample 40      # + survey the registry

`registry/erc8004.py` and `registry/erc8183.py` are ~800 lines that model agent
identity and the hire flow, and neither has ever had a surface. The README
promises a Hire button; the hire flow's own analysis says a client signs **four
transactions** to complete a job, and that number is the most interesting thing
this project can say about every competitor's one-click Hire.

## Degrading without lying

The ERC-8183 half is pure computation and always renders. The ERC-8004 half
needs an RPC, and when there isn't one this emits `surveyed: false` with the
reason — never a zero, never a count carried over from a previous run. A survey
that silently reports stale numbers is worse than one that says it did not run,
because only the second is visibly missing.

`escrow_address()` raises `NoVerifiedDeployment` by design, and that refusal is
published verbatim rather than rendered as an empty field.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from misquote.chain import addresses as chain_addresses
from misquote.registry import erc8004, erc8183, hire
from misquote.registry.erc8004 import IDENTITY_REGISTRY
from misquote.tearsheet import provenance

REPO = Path(__file__).resolve().parents[1]
BSC_MAINNET = 56


#: Keys a third-party listing may carry. Nothing performance-shaped is on it,
#: and the omission is the design rather than an oversight — see `_listing`.
LISTING_KEYS = frozenset(
    {
        "agent_id",
        "name",
        "description",
        "endpoints",
        "declares_active",
        "declares_schema",
        "resolvable",
        "describes_a_service",
        "looks_like_a_placeholder",
        "substantive",
        "on_chain",
        "notes",
    }
)


def _listing(card, verdict) -> dict[str, Any]:
    """One third-party agent, as much as can honestly be said about it.

    ## Why this is not the same shape as our own agent cards

    Our four agents' cards are live mini-tearsheets: a P25-P75 range replayed
    from thirty days of real history, with the assumption sheet one click away.
    A third-party agent gets no such number and cannot — we do not have its
    policy, so there is nothing to replay. Inventing one, or borrowing a rating
    from somewhere, is exactly the misquote this project is named after.

    So a listing carries what the registration claims and what our own reading
    of it found, and **no performance figure of any kind**. `LISTING_KEYS` is
    the whitelist and a test asserts nothing outside it appears, so the absence
    survives someone later adding a field in a hurry.

    Trimmed, too: the raw card blob and its base64 `data:` URI are dropped. They
    are recoverable from chain by anyone who wants them, and carrying 40 of them
    made this artifact 39KB of encoded JSON nobody reads.
    """
    return {
        "agent_id": card.agent_id,
        "name": card.name,
        "description": card.description,
        "endpoints": card.endpoints,
        "declares_active": verdict.declares_active,
        "declares_schema": verdict.declares_schema,
        "resolvable": verdict.resolvable,
        "describes_a_service": verdict.describes_a_service,
        "looks_like_a_placeholder": verdict.looks_like_a_placeholder,
        "substantive": verdict.substantive,
        "on_chain": card.on_chain,
        "notes": list(verdict.notes),
    }


def _connect():
    """An endpoint that answers for BSC mainnet, keyed or not.

    This function used to be one line — `os.environ.get("BSC_RPC_URL")` — and a
    missing key meant `surveyed: false` forever. The refusal was right in shape
    and wrong in precondition: the survey reads `tokenURI` and `ownerOf`, which
    are `eth_call`, and every free BSC endpoint serves those. It is `eth_getLogs`
    the free endpoints ration, and this makes none.

    So the registry went unsurveyed for the life of the project over a key it did
    not need, and `/registry` rendered the honest refusal every time.

    Prefers `BSC_RPC_URL` when set — it is faster and will not disappear — and
    otherwise walks the same candidates the indexer and the address verifier
    already use. Raises rather than returning None so the caller reports one
    reason rather than inventing a second.
    """
    from web3 import HTTPProvider, Web3

    from misquote.indexer.reader import PUBLIC_RPCS

    keyed = os.environ.get("BSC_RPC_URL")
    candidates = [keyed] if keyed else list(PUBLIC_RPCS.get(BSC_MAINNET, ()))

    for url in candidates:
        try:
            w3 = Web3(HTTPProvider(url, request_kwargs={"timeout": 15}))
            if w3.eth.chain_id == BSC_MAINNET:
                return w3
        except Exception:  # noqa: BLE001 — try the next one
            continue

    raise RuntimeError(
        f"no endpoint answered for chain {BSC_MAINNET} "
        f"({len(candidates)} tried) — no registry read was attempted"
    )


def hire_flow_contracts() -> dict[str, Any]:
    """Which contract each step of the hire flow goes to, per chain.

    Published because the flow spans **three** contracts — the kernel creates
    and funds, the EvaluatorRouter binds and settles, the policy holds the
    dispute window — and a reader told "seven transactions" without being told
    they land on three addresses would build one that reverts on the third.
    """
    out: dict[str, Any] = {}
    for chain_id in (BSC_MAINNET, 97):
        try:
            out[str(chain_id)] = erc8183.contracts_for(chain_id)
        except erc8183.NoVerifiedDeployment as error:
            out[str(chain_id)] = {"available": False, "reason": str(error)}
    return out


def hire_flow() -> dict[str, Any]:
    """ERC-8183, entirely offline: the steps, and what they cost the client."""
    steps = erc8183.steps()

    try:
        escrow: dict[str, Any] = {
            "available": True,
            "address": erc8183.escrow_address(BSC_MAINNET),
            # The findings, not a boolean summarising them.
            #
            # This emitted `{available, address}` and the web page rendered a
            # green "Verified" pill beside the words "a chain check confirmed
            # it" — while the same artifact said `"source": "offline"` and "no
            # registry read was attempted". `available` is a dict lookup, not a
            # read, so the page was asserting a verdict from prose that the
            # artifact deliberately did not carry.
            #
            # `JOB_ESCROW_EVIDENCE` is what a real check recorded, and its own
            # comment says why it is a list rather than a flag: the gap between
            # "a live escrow that settles in the token we already use" and "we
            # have exercised ERC-8183's job interface here" is the slippage this
            # project exists to catch. Two of the seven entries are a NOT VERIFIED
            # clause and a SECURITY note about the escrow being upgradeable —
            # the strongest caveats in the codebase, and neither had a surface.
            "evidence": list(erc8183.JOB_ESCROW_EVIDENCE.get(BSC_MAINNET, ())),
        }
    except erc8183.NoVerifiedDeployment as exc:
        # Published as the refusal it is. A field reading "—" would look like a
        # rendering bug; this is a finding.
        escrow = {"available": False, "reason": str(exc)}

    return {
        "steps": [
            {
                "call": step.call,
                "sender": step.sender,
                "contract": step.contract,
                "why": step.why,
                "is_erc8183": step.is_erc8183,
            }
            for step in steps
        ],
        "transaction_count": erc8183.transaction_count(),
        "client_transaction_count": erc8183.client_transaction_count(),
        "states": list(erc8183.STATES),
        "terminal_states": list(erc8183.TERMINAL),
        "escrow": escrow,
        # The client's way out when nobody settles. `recourse()` is deliberately
        # not part of `steps()` — it is an alternative terminal branch, and
        # folding it in would make `transaction_count()` report a hire as costing
        # eight when no hire ever does.
        "recourse": [
            {"call": step.call, "sender": step.sender, "contract": step.contract, "why": step.why}
            for step in erc8183.recourse()
        ],
        # What reverts, and what each revert means. None of these is in any ABI:
        # `createJob` fails with bare four-byte selectors and no reason string, so
        # each was isolated by varying one argument at a time and three were then
        # matched to a name by preimage search. The four that were not are
        # recorded as unresolved rather than named, which is the rule
        # `aacp.ESCROW_SELECTORS_RESOLVED` set.
        "errors": {**hire.CREATE_JOB_ERRORS, **hire.FLOW_ERRORS},
        "proof": _hire_proof(),
        "fork_proof": _hire_fork_proof(),
        "mainnet_proof": _hire_mainnet_proof(),
        "submit_proof": _submit_proof(),
        "refund_proof": _refund_proof(),
        # The four addresses a browser needs to send any of this itself.
        #
        # They are emitted rather than typed into the web app because
        # `erc8183.py` is where a deployment is admitted after being read, and a
        # second copy in TypeScript is a second thing to be wrong. The console
        # picks the entry for the wallet's chain and refuses when there is none,
        # the same rule `sessionKeys.DEPLOYMENTS` follows.
        "deployments": _deployments(),
    }


#: Cosmetic, and the only part of a deployment entry that is not read from
#: somewhere. The addresses come from `erc8183.py` and the explorer from
#: `chain/addresses.py`; a chain's display name is not a fact about a chain.
CHAIN_NAMES = {56: "BNB Smart Chain", 97: "BNB Smart Chain Testnet"}


#: Where `verify_erc8183.py` leaves the readings it took off chain.
ERC8183_RECORD = REPO / "vetting" / "addresses"


def _payment_token_decimals(chain: int) -> int | None:
    """The token's own `decimals()`, as the verifier read it. `None` if unread.

    Not a constant, and the difference is the whole argument `chain/addresses.py`
    makes about this exact quantity: BSC's USDT is 18 where Ethereum's is 6, and
    assuming wrong misprices by twelve orders of magnitude. The site now renders
    an opening escrow on an agent card, so the scale that formats it is a money
    figure on a storefront.

    Absent rather than 18 when no record exists — `HirePrice` renders no amount
    without it, which is the same rule `money()` follows for a figure whose unit
    is unknown.
    """
    path = ERC8183_RECORD / f"erc8183-{chain}.json"
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    value = (record.get("readings") or {}).get("payment_token_decimals")
    return int(value) if isinstance(value, int) else None


def _deployments() -> dict[str, Any]:
    """Every chain with a verified ERC-8183 deployment, as the UI needs it."""
    out: dict[str, Any] = {}
    for chain in sorted(erc8183.JOB_ESCROW):
        if chain not in chain_addresses.DEPLOYMENTS:
            continue
        entry: dict[str, Any] = {
            "chain_id": chain,
            "name": CHAIN_NAMES.get(chain, f"chain {chain}"),
            "explorer": chain_addresses.DEPLOYMENTS[chain].explorer,
            **erc8183.contracts_for(chain),
        }
        decimals = _payment_token_decimals(chain)
        if decimals is not None:
            entry["decimals"] = decimals
        out[str(chain)] = entry
    return out


#: The chapel run, published beside the flow it exercised.
#:
#: `hire_flow()` describes a sequence; this is what happened when it was sent.
#: The two are kept apart because one is a claim about a standard and the other
#: is a claim about three transaction hashes, and a reader should be able to tell
#: which they are looking at.
HIRE_PROOF_PATH = REPO / "vetting" / "identity" / "hire-97.json"


#: The fork run, which is a different claim from the chapel one and lives in a
#: different file for that reason.
#:
#: `hire-97.json` is chapel, mined, and does not escrow — the payment token is
#: owner-minted and the signer holds none. `hire-fork-56.json` is the mainnet
#: deployment's own bytecode at a forked block, where the owner can be
#: impersonated and the flow runs to settlement. Publishing the second as though
#: it were the first is the misquote this project is named after, so the two are
#: never merged and the fork record carries `network: "fork"` in every consumer's
#: reach.
HIRE_FORK_PATH = REPO / "vetting" / "identity" / "hire-fork-56.json"

#: The mainnet run. A third record, and the one that cost money.
#:
#: `proof` is chapel and stops at `fund` for want of a balance. `fork_proof`
#: settles, on a fork, by moving the clock past a seven-day window. This one
#: escrows on BSC mainnet and then cannot release, which is precisely the
#: difference between the two: the fork skipped the wait and the chain will not.
#: Three records, three claims, never merged.
HIRE_MAINNET_PATH = REPO / "vetting" / "identity" / "hire-mainnet-56.json"


#: The refund. A fourth record, and the only one about getting money back.
#:
#: `mainnet_proof` ends with the budget escrowed and both release calls
#: refusing. That is not the end of the story — `claimRefund` opens at
#: `expiredAt` — but the difference between "recoverable" and "recovered" is
#: exactly the kind of claim this repository does not make on prose alone.
#: `make claim-refund-fork` rehearses it against the real job at the current
#: block, and `MISQUOTE_DRY_RUN=0 make claim-refund` does it for real once the
#: clock allows. Whichever exists is published; the fork one says `network:
#: "fork"` in every consumer's reach, and its transaction hash is deliberately
#: not linkable — it was never on a chain anyone can look it up on.
REFUND_MAINNET_PATH = REPO / "vetting" / "identity" / "refund-56.json"
REFUND_FORK_PATH = REPO / "vetting" / "identity" / "refund-fork-56.json"


def _published_record(
    paths: tuple[Path, ...], skeleton: dict[str, Any], absent: str
) -> dict[str, Any]:
    """One record from disk, or an absence in the same shape as a presence.

    ## The bug this exists to make impossible

    Each of these four used to answer a missing file with
    `{"ran": False, "reason": ...}` — two keys, where the contract in
    `tests/web/test_artifact_contract.py` declares between seventeen and
    twenty-four. It reads well and it cannot be published: on any machine
    without the record files, `make registry` emitted a payload that failed
    `test_the_registry_emitter_writes_exactly_the_contracted_fields` in both
    directions at once, fifteen fields undelivered and `reason` undeclared.
    Four fallbacks written to be honest, none of which could actually run.

    So an absence now carries **every key a presence carries**, nulled. The
    skeleton is also a floor under a present record: `hire-97.json` has no `ran`
    of its own, and `_hire_proof` used to patch that in while its three siblings
    trusted their writers to have done it. Merging over the skeleton makes that
    asymmetry go away rather than documenting it.

    The two-way equality in the contract test now polices the skeletons too — a
    record that grows a field fails until the skeleton grows it as well, which
    is the flaw checking itself instead of waiting to be found.
    """
    for path in paths:
        if not path.is_file():
            continue
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            return {
                **skeleton,
                "reason": f"{path.name} could not be read: {error}",
            }
        return _keep_sub_skeletons(
            skeleton,
            {
                **skeleton,
                **record,
                "ran": True,
                "reason": None,
                "record": str(path.relative_to(REPO)),
            },
        )
    return {**skeleton, "reason": absent}


def _keep_sub_skeletons(skeleton: dict[str, Any], merged: dict[str, Any]) -> dict[str, Any]:
    """A null in the record must not collapse a sub-object the contract declares.

    The merge above is shallow, which is right for scalars and wrong for the
    keys whose skeleton value is itself a shape. `hire_mainnet.py` writes
    `"deliverable": null` on every run that commits to no file — and a null
    there is one leaf where the contract declares four, so a run with no
    `--deliverable-file` would fail
    `test_the_registry_emitter_writes_exactly_the_contracted_fields` in both
    directions at once.

    Nulling the *fields* rather than the object says the same thing and keeps
    the shape a renderer can rely on. `addresses` has the same exposure and has
    simply never been written null yet.
    """
    for key, shape in skeleton.items():
        if isinstance(shape, dict) and not isinstance(merged.get(key), dict):
            merged[key] = dict(shape)
    return merged


#: What a record looks like when there is not one. Derived from the records
#: themselves rather than hand-listed, and held to that by the contract test.
ABSENT_REFUND = {
    "balance_after": None,
    "balance_before": None,
    "budget": None,
    "client": None,
    "expires_at": None,
    "expires_at_utc": None,
    "gas_spent_wei": None,
    "job_id": None,
    "network": None,
    "ran": False,
    "reason": None,
    "record": None,
    "recovered": None,
    "refunded": None,
    "status_after": None,
    "status_before": None,
    "transactions": [],
}

ABSENT_MAINNET = {
    "addresses": {"erc20": None, "kernel": None, "policy": None, "router": None},
    "budget": None,
    "chain_id": None,
    "client": None,
    #: What `submit`'s 32 bytes commit to, when a run committed to anything.
    #:
    #: `hire.py` is blunt that the argument is opaque — "nothing on chain
    #: interprets it, so this does not pretend to" — which makes the commitment
    #: worth exactly as much as the record tying it to a fetchable file. Both
    #: mainnet runs so far sent `keccak256("job-<id>")`, a hash of the job's own
    #: id, so these are null and the page says which.
    "deliverable": {"bytes": None, "file": None, "keccak256": None, "url": None},
    "escrowed": None,
    "escrowed_on_mainnet": None,
    "evaluator": None,
    "gas_spent_wei": None,
    "job_exists": None,
    "job_id": None,
    "job_words": [],
    "network": None,
    "provider": None,
    "ran": False,
    "reason": None,
    "record": None,
    "settled": None,
    "success_criterion": None,
    "transactions": [],
    #: `hire_mainnet.py`'s own label. Emitted so the contract knows the field
    #: exists; the page judges distinctness from `client` and `provider`
    #: directly, for the reason `_two_parties` gives — keying off a label makes
    #: a record that predates the label read as a self-hire.
    "two_party": None,
}

ABSENT_FORK = {
    "addresses": {"erc20": None, "kernel": None, "policy": None, "router": None},
    "budget": None,
    "chain_id": None,
    "client": None,
    "dispute_window_s": None,
    "escrowed": None,
    "escrowed_on_mainnet": None,
    "evaluator": None,
    "forked_at_block": None,
    "forked_from": None,
    "gas_spent_wei": None,
    "job_id": None,
    "job_words": [],
    "minted_to_client": None,
    "network": None,
    "provider": None,
    "ran": False,
    "reason": None,
    "record": None,
    "settled": None,
    "success_criterion": None,
    "token_owner": None,
    "transactions": [],
    "why_not_on_mainnet": None,
    "why_not_on_mainnet_was": None,
}

ABSENT_PROOF = {
    "addresses": {"erc20": None, "kernel": None, "policy": None, "router": None},
    "budget": None,
    "chain_id": None,
    "client": None,
    "escrowed": None,
    "gas_spent_wei": None,
    "job_exists": None,
    "job_id": None,
    "job_words": [],
    "mined": [],
    "not_escrowed_because": None,
    "not_escrowed_because_was": None,
    "ran": False,
    "reason": None,
    "record": None,
    "reverted": [],
    "success_criterion": None,
    "transactions": [],
}


#: The run where `submit` mined. A fourth record, and the one that moves the
#: release half from "never reached" to "waiting on a clock".
#:
#: `hire-mainnet-56.json` is job 56681: funded, then reclaimed, with `submit`
#: refused. This is job 56718 with a 192-hour expiry instead of twelve, which is
#: the whole difference — `SubmissionTooLate()` is a comparison against the
#: policy's dispute window, and one argument was on the wrong side of it.
SUBMIT_PATH = REPO / "vetting" / "identity" / "hire-mainnet-56-submitted.json"

ABSENT_SUBMIT: dict[str, Any] = {
    "addresses": {"erc20": None, "kernel": None, "policy": None, "router": None},
    "budget": None,
    "chain_id": None,
    "client": None,
    #: What `submit`'s 32 bytes commit to, when a run committed to anything.
    #:
    #: `hire.py` is blunt that the argument is opaque — "nothing on chain
    #: interprets it, so this does not pretend to" — which makes the commitment
    #: worth exactly as much as the record tying it to a fetchable file. Both
    #: mainnet runs so far sent `keccak256("job-<id>")`, a hash of the job's own
    #: id, so these are null and the page says which.
    "deliverable": {"bytes": None, "file": None, "keccak256": None, "url": None},
    "dispute_window_s": None,
    "escrowed": None,
    "escrowed_on_mainnet": None,
    "evaluator": None,
    "expires_at": None,
    "expires_at_utc": None,
    "gas_spent_wei": None,
    "job_exists": None,
    "job_id": None,
    "job_words": [],
    "network": None,
    "provider": None,
    "ran": False,
    "reason": None,
    "record": None,
    "settle_earliest_utc": None,
    "settled": None,
    "submitted": None,
    "success_criterion": None,
    "transactions": [],
    #: `hire_mainnet.py`'s own label. Emitted so the contract knows the field
    #: exists; the page judges distinctness from `client` and `provider`
    #: directly, for the reason `_two_parties` gives — keying off a label makes
    #: a record that predates the label read as a self-hire.
    "two_party": None,
    "what_this_run_changes": None,
    "why_settle_reverted": None,
}


def _submit_proof() -> dict[str, Any]:
    """The run that got `submit` mined, or an honest absence."""
    return _published_record(
        (SUBMIT_PATH,),
        ABSENT_SUBMIT,
        "no submitted mainnet hire — `hire_mainnet.py --hours 192` writes this",
    )


def _refund_proof() -> dict[str, Any]:
    """The recovery, mainnet if it has happened and the rehearsal if not."""
    return _published_record(
        (REFUND_MAINNET_PATH, REFUND_FORK_PATH),
        ABSENT_REFUND,
        "no refund has been claimed — `make claim-refund-fork` rehearses it",
    )


def _hire_mainnet_proof() -> dict[str, Any]:
    """The recorded mainnet run, or an honest absence."""
    return _published_record(
        (HIRE_MAINNET_PATH,),
        ABSENT_MAINNET,
        "no mainnet hire has been run — `make hire-mainnet` writes this",
    )


def _hire_fork_proof() -> dict[str, Any]:
    """The recorded fork run, or an honest absence."""
    return _published_record(
        (HIRE_FORK_PATH,),
        ABSENT_FORK,
        "no fork proof has been run — `make prove-escrow` writes this",
    )


def _hire_proof() -> dict[str, Any]:
    """The recorded chapel run, or an honest absence."""
    return _published_record(
        (HIRE_PROOF_PATH,),
        ABSENT_PROOF,
        "no hire has been run — `MISQUOTE_DRY_RUN=0 make hire` writes this",
    )


#: Where a survey lives between the chain read that produced it and the artifact
#: build that publishes it. The badges under `vetting/badges/` play the same role
#: for the same reason — see `read_survey`.
SURVEY_PATH = REPO / "data" / "registry_survey.json"

#: How many sampled agents are published as cards.
#:
#: Applied when the artifact is written, not when the chain is read: the survey
#: on disk keeps every agent it sampled, so changing this number costs nothing
#: and re-reading 400 ids is never the price of a rendering decision.
#:
#: The shares come from the whole sample regardless. This bounds only what the
#: page renders — 400 cards is 226KB for an artifact fetched client-side, and
#: enough DOM to time out a jsdom render — and the artifact carries `sampled`
#: beside `listings_shown` so the card count cannot be read as the sample size.
LISTING_LIMIT = 24


def _base() -> dict[str, Any]:
    return {
        "identity_registry": erc8004.IDENTITY_REGISTRY,
        "reputation_registry": erc8004.REPUTATION_REGISTRY,
        "reputation_note": erc8004.REPUTATION_IS_NOT_DISPLAYED,
        # The level the published intervals are at.
        #
        # Here rather than in `survey_chain`, and the difference matters: this
        # is a property of `wilson_interval`, not of any particular draw. A
        # survey recorded before this field existed would otherwise republish
        # without it forever, because `make registry` reads the recorded file
        # and only `--sample` re-reads the chain — so putting it on the survey
        # would have meant fifteen minutes of chain reads to publish a constant.
        #
        # Published at all because a pair of bounds without its level is not an
        # interval, it is two numbers. `/registry` and `ShareIntervals` both
        # said "95%" in typed prose beside intervals this repository computes,
        # which made the one figure that gives the bounds a meaning the one
        # figure not read from anything — on the block whose entire argument is
        # that a share without an interval is false precision.
        "confidence_level": erc8004.CONFIDENCE_LEVEL,
    }


def read_survey(path: Path = SURVEY_PATH) -> dict[str, Any]:
    """Republish the survey on disk. **This reads no chain.**

    The split `make vet` / `make vetting` already uses, and for the reason that
    file gives: the reading is expensive and occasional, the publishing is cheap
    and happens on every build, and putting the read inside the build makes the
    build need an RPC.

    Here it fixed something worse than slowness. `make registry` ran with no
    `--sample`, the flag defaults to 0, and 0 means *"survey not requested"* —
    so `make artifacts` did not merely skip the survey, it **overwrote a real
    one with a refusal**, taking the third-party listings with it. A build that
    deletes a measurement is worse than one that never takes it.

    An absent file is still `surveyed: false` with a reason. That branch is
    correct and `/registry` renders it properly; it was the precondition that
    was wrong.
    """
    if not path.exists():
        return {
            **_base(),
            "surveyed": False,
            "reason": (
                "no survey has been recorded — run `make registry-survey`, which "
                "reads the chain and writes data/registry_survey.json"
            ),
        }
    try:
        recorded = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return {**_base(), "surveyed": False, "reason": f"{path.name} is unreadable: {error}"}

    identity = {**_base(), **recorded}

    # Every `step`-th, not the first N: taking the head would cluster the cards
    # at low agent ids, which is the same bias the sampler itself was fixed for
    # reintroduced one layer later, where it would be harder to see.
    listings = identity.get("agents") or []
    if len(listings) > LISTING_LIMIT:
        step = max(1, len(listings) // LISTING_LIMIT)
        identity["agents"] = listings[::step][:LISTING_LIMIT]
    identity["listings_shown"] = len(identity.get("agents") or [])
    return identity


def survey_chain(sample: int, seed: int) -> dict[str, Any]:
    """ERC-8004, which needs a chain. Says so plainly when it does not have one."""
    base: dict[str, Any] = _base()

    if sample <= 0:
        return {**base, "surveyed": False, "reason": "survey not requested (pass --sample N)"}

    try:
        w3 = _connect()
    except RuntimeError as error:
        return {**base, "surveyed": False, "reason": str(error)}

    try:
        chain_id = w3.eth.chain_id
        if chain_id != BSC_MAINNET:
            return {
                **base,
                "surveyed": False,
                "reason": f"the endpoint points at chain {chain_id}, not {BSC_MAINNET}",
            }

        registry = erc8004.IdentityRegistry(w3, chain_id)

        # Sample across the registry, not across its first few hundred ids.
        #
        # This drew `rng.sample(range(1, sample * 20), sample)` — at the
        # documented `--sample 40`, ids **1 to 800**. The registry holds ~270,765
        # agents, so that describes its oldest 0.3% while reporting a share as
        # though it were about the whole thing. Early registrations are exactly
        # the population most likely to differ: the deployer's own tests, and the
        # earliest adopters.
        #
        # The bound is measured rather than assumed, because it grows with every
        # registration and a constant would go stale silently.
        population = erc8004.highest_agent_id(registry)
        if population < 1:
            return {**base, "surveyed": False, "reason": "the registry resolved no agent ids"}

        rng = random.Random(seed)
        ids = sorted(rng.sample(range(1, population + 1), min(sample, population)))
        result = erc8004.survey(registry, ids)

        payload = asdict(result) if is_dataclass(result) else dict(result)
        payload = {k: v for k, v in payload.items() if not k.startswith("_")}
        # `asdict` turns the (card, verdict) pairs into nested two-element lists
        # carrying every raw field, including a base64 `data:` URI per agent.
        # Replace them with the trimmed listing the site actually renders.
        # Every sampled agent feeds the shares; a spread of them is published as
        # cards. 400 listings is 226KB of artifact for a page that fetches it
        # client-side, and the statistic is what needs n=400 — the cards are
        # illustrative.
        #
        # Every `step`-th rather than the first N, so the published set spans the
        # registry the way the sample does instead of clustering at low ids —
        # the same bias the sampler itself was fixed for. Deterministic, so the
        # artifact does not churn between runs.
        payload["agents"] = [_listing(card, verdict) for card, verdict in result.agents]
        return {
            **base,
            "surveyed": True,
            # Recorded so the survey is reproducible rather than merely reported.
            "sampled_ids": ids,
            "sampled_at_block": w3.eth.block_number,
            "seed": seed,
            # The population the sample was drawn from. Without it a share is a
            # number about an unnamed thing, and D1's "< ~15 agents" rule cannot
            # be evaluated at all.
            "population": population,
            "substantive_share": result.substantive_share,
            # Every published share, with the interval it is worth to that many
            # observations. A share without one is the false precision this
            # project is named against — and at n=40 "30% substantive" spans
            # 18-46%, which is a different statement from "30%".
            "intervals": {
                name: dict(
                    zip(
                        ("low", "high"),
                        erc8004.wilson_interval(getattr(result, name), result.sampled),
                        strict=True,
                    )
                )
                for name in (
                    "resolvable",
                    "with_endpoint",
                    "placeholders",
                    "declared_active",
                    "on_chain_cards",
                    "substantive",
                )
            },
            **payload,
        }
    except Exception as exc:  # noqa: BLE001 — any failure means "we did not survey"
        return {
            **base,
            "surveyed": False,
            "reason": f"{type(exc).__name__}: {exc}",
        }


def _explorer_agents(aacp) -> dict[str, Any]:
    """Their explorer's agent count, and ours **read at the same moment**.

    The gap between the two is the only interesting thing here, and it is only
    interesting if both numbers were taken together. The first version of this
    compared their live total against `identity.population` — a figure from
    whenever the last survey ran — and produced a gap of **-39,954**, i.e. their
    index appearing to hold forty thousand agents the registry does not have.

    That is not a finding, it is two clocks. The registry grows by roughly a
    thousand registrations an hour, so any comparison across two read times
    measures the delay and calls it a discrepancy — which is the shape of P-8 and
    of every stale-artifact defect in this repository.

    So the chain read happens here, beside the HTTP read, and the gap is computed
    once from the pair rather than by a renderer subtracting two fields it found
    lying near each other.
    """
    try:
        explorer = aacp.fetch_explorer_agents(aacp.BSC_MAINNET)
    except Exception as exc:  # noqa: BLE001 — their outage is not our failure
        return {
            "read": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "note": (
                "Not read this build. The figure is theirs and lives on their "
                "service; publishing the last one we saw would be the stale "
                "number this field exists to retire."
            ),
        }

    # Ours, now. `highest_agent_id` binary-searches `ownerOf` because
    # `totalSupply()` reverts on this proxy — see erc8004.py.
    try:
        w3 = _connect()
        registry = erc8004.IdentityRegistry(w3, aacp.BSC_MAINNET)
        ours = erc8004.highest_agent_id(registry)
        block = int(w3.eth.block_number)
    except Exception as exc:  # noqa: BLE001
        return {
            "read": True,
            **explorer,
            "ours": None,
            "gap": None,
            "gap_note": (
                f"the registry high-water id was not read this build "
                f"({type(exc).__name__}), so there is no same-moment pair and no "
                f"gap. Comparing their live total against a stored figure would "
                f"measure the delay between two reads and call it a discrepancy."
            ),
        }

    return {
        "read": True,
        **explorer,
        "ours": ours,
        "ours_at_block": block,
        "gap": ours - explorer["total"],
        "gap_note": (
            "Both read in the same build. A positive gap is their indexing lag "
            "behind the registry; the registry grows by roughly a thousand "
            "registrations an hour, so a gap measured across two read times "
            "would be that delay rather than a property of their index."
        ),
    }


def aacp_overlap() -> dict[str, Any]:
    """What we already share with TermiX's protocol, if the module exists.

    Optional because it arrived separately: importing it unconditionally would
    make this emitter fail on a checkout that does not have it yet.
    """
    try:
        from misquote.registry import aacp
    except ImportError:
        return {"available": False}

    try:
        contracts = aacp.contracts(aacp.BSC_MAINNET)
        return {
            "available": True,
            "chain_id": aacp.BSC_MAINNET,
            "shares_our_identity_registry": aacp.shares_our_identity_registry(aacp.BSC_MAINNET),
            # The interface the escrow actually has, recovered from its deployed
            # bytecode. Published because the absence in `hire_flow.escrow` is
            # only half the finding: a refusal that does not say what was found
            # instead reads as "we did not look".
            "escrow_interface": dict(aacp.ESCROW_INTERFACE),
            "escrow_selectors": {
                "total": aacp.ESCROW_SELECTORS_TOTAL,
                "resolved": aacp.ESCROW_SELECTORS_RESOLVED,
                "note": (
                    "The unresolved ones are counted, not guessed. Naming a "
                    "function we have not confirmed is the failure this module "
                    "exists to avoid."
                ),
            },
            "not_erc8183": (
                "TermixEscrow implements none of the seven ERC-8183 calls. Jobs "
                "are keyed by a bytes32 order id, not the EIP's uint256 jobId."
            ),
            "order_decode": (
                "orders(bytes32) returns 13 words. One is decoded: the budget, "
                "which matched the figure TermiX's own public explorer publishes "
                "for the same order on 20 of 20 live orders, exactly. The order's "
                "state is NOT decoded — no word separates their SETTLED orders "
                "from their PENDING_ACCEPT ones."
            ),
            "contracts": contracts,
            # How many agents their explorer indexes, read rather than recited.
            #
            # `FOR_JUDGES.md` published this figure as prose — 304,790 — with no
            # constant, no function and no way to re-derive it. By the time
            # anyone looked again it was 320,230. A load-bearing number that
            # cannot be regenerated is a claim, which is the whole subject of
            # this repository.
            #
            # Fails soft: this is one HTTP call to somebody else's service inside
            # an emitter that otherwise touches no network, and `make registry`
            # should not fail because their explorer is briefly down.
            "explorer_agents": _explorer_agents(aacp),
            "note": (
                "A snapshot of TermiX's published table, recorded to be checked "
                "against — never a source of truth for signing. Their own docs say "
                "to fetch live addresses before signing."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


#: Where the third-party reading lives between the API call and the artifact.
#: Same split as `SURVEY_PATH`: the read is separate from the publish, so
#: `make registry` republishes without needing the network.
SCAN_PATH = REPO / "data" / "scan8004.json"


def _reconciliation(ours: int, theirs: int, their_contract: str | None) -> dict[str, Any]:
    """Two counts of one registry, by two methods, with the gap stated not resolved.

    Recomputed rather than carried, and that is the fix rather than a tidying.
    It used to be built once inside `fetch_scan` and then frozen into
    `data/scan8004.json`, so `make registry` — which republishes that file
    verbatim and touches no network — could not correct it. Both inputs are
    already on disk: ours from `data/registry_survey.json`, theirs from the
    recorded population block. A comparison of two recorded numbers belongs
    wherever those numbers are read.
    """
    return {
        "ours": ours,
        "ours_method": "binary search on ownerOf — totalSupply() reverts on this proxy",
        "theirs": theirs,
        "theirs_method": "8004scan's indexer",
        # Signed, because the direction is real information: it says which of
        # the two is larger, and that has changed at least once — ours led when
        # this was written and 8004scan's leads now.
        "difference": ours - theirs,
        # A share **of the larger**, and positive, which is what the page has
        # always called it.
        #
        # This was `100 * (ours - theirs) / ours`, and both halves went wrong on
        # the day the counts crossed over. The sign flipped, so `/registry`
        # rendered "-5,312 apart — -1.90% of the larger": a negative distance,
        # in the aria label as well as on screen. And the denominator became the
        # *smaller* count while the caption went on calling it the larger, which
        # put the figure a few hundredths out on top of being negative.
        #
        # Every part of that was correct when written. Nothing on either side of
        # the artifact boundary noticed when it stopped being, which is the
        # argument for a bound that does not depend on which way the comparison
        # happens to fall.
        "difference_pct": round(100 * abs(ours - theirs) / max(ours, theirs), 3),
        "same_contract": (their_contract or "").lower()
        == IDENTITY_REGISTRY.get(BSC_MAINNET, "").lower(),
        "note": (
            "Two counts of the same registry by different methods, published "
            "together with the gap unresolved. Both are checked to be counting "
            "the same contract."
        ),
    }


def read_scan(path: Path = SCAN_PATH) -> dict[str, Any]:
    """Republish the 8004scan reading on disk. **This calls no API.**

    The reconciliation is the one block rebuilt rather than republished: it
    compares a number from this file against one from `registry_survey.json`,
    and freezing a comparison means it cannot be corrected without a network
    call it does not need. See `_reconciliation`.
    """
    if not path.exists():
        return {
            "available": False,
            "reason": (
                "no 8004scan reading has been recorded — run `make registry-scan`, "
                "which calls the API and writes data/scan8004.json"
            ),
        }
    try:
        recorded = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return {"available": False, "reason": f"{path.name} is unreadable: {error}"}

    population = recorded.get("population") or {}
    ours = read_survey().get("population")
    theirs = population.get("population") if population.get("available") else None
    if ours and theirs:
        recorded["reconciliation"] = _reconciliation(
            int(ours), int(theirs), population.get("contract_address")
        )
    return recorded


def _feedback_cross_check(census: dict[str, Any], reach: dict[str, Any]) -> dict[str, Any]:
    """The same quantity from two of 8004scan's own tables.

    `census` sums `total_feedbacks` across every agent row; `feedback_reach`
    asks the feedback collection for its own total. One index, two tables, and
    no reason for them to differ — so a difference is the index disagreeing with
    itself, which is worth publishing precisely because it is not our finding to
    explain. Same rule as the population gap: stated, not resolved.
    """
    if not (census.get("available") and reach.get("available")):
        return {
            "available": False,
            "reason": "both a census and a feedback count are needed to compare them",
        }
    summed = int(census.get("feedbacks_claimed") or 0)
    counted = int(reach.get("feedbacks") or 0)
    return {
        "available": True,
        "summed_over_agents": summed,
        "counted_in_feedback_table": counted,
        "difference": summed - counted,
        "agree": summed == counted,
        "note": (
            "Two of 8004scan's own tables answering the same question, published "
            "whether or not they agree."
        ),
    }


#: Every key a `census` block carries, whichever way it was arrived at.
#:
#: The census has three states — walked on this run, carried forward from a
#: previous one, or not taken at all — and until this existed each state emitted
#: a different set of keys. That is invisible in Python and loud in TypeScript:
#: `tests/web/test_artifact_contract.py` contracts an artifact's fields in both
#: directions, and a block whose shape depends on which branch produced it
#: cannot be contracted at all. It also means every view reading it needs
#: narrowing for a field that is simply absent rather than false.
#:
#: So the shape is fixed and the *values* carry the state. `available` says
#: whether it ran, `reason` says why not when it did not, `carried_forward` says
#: it was not taken on this run, and `read_at` says when it really was — None on
#: a reading recorded before that field existed, which is a different claim from
#: "just now" and must not be rendered as one.
CENSUS_KEYS = (
    "available",
    "reason",
    "carried_forward",
    "read_at",
    "tier",
    "chain_id",
    "counted",
    "complete",
    "described",
    "verified",
    "starred",
    "with_score",
    "with_feedback",
    "x402_supported",
    "feedbacks_claimed",
    "distinct_owners",
    "distinct_descriptions",
    "protocols",
    "pages_failed",
    "agents_missed",
    "failed_offsets",
    "failure_reasons",
    "population_at_start",
    "population_at_end",
    "minted_during_the_walk",
    "ordering",
    "note",
)


def _census_block(block: dict[str, Any] | None, *, carried_forward: bool = False) -> dict[str, Any]:
    """One census, in the one shape a census has. See `CENSUS_KEYS`."""
    block = dict(block or {})
    block.setdefault("available", False)
    block["carried_forward"] = carried_forward
    return {key: block.get(key) for key in CENSUS_KEYS}


def _counts_cross_check(census: dict[str, Any], counts: dict[str, Any]) -> dict[str, Any]:
    """The same shares, walked and asked. Published whichever way they fall.

    `census` derives `x402_supported` and `with_feedback` by reading 2,848 pages
    and counting rows. `counts` asks 8004scan for the same two quantities and is
    answered in one request each. One index, two routes to one number, and no
    reason for them to differ — so a difference is the index disagreeing with
    itself, which is worth publishing precisely because it is not ours to
    explain. Same rule as the population gap: stated, not resolved.

    **Both denominators travel with both numerators.** The walk counted 278,500
    agents and the ask was answered against 284,996, because the registry grew
    between the two readings. A share computed across them would be a third
    number nobody measured, and the hours between the readings is the fact that
    decides whether a gap is a finding or is growth — so it is carried too.
    """
    if not (census.get("available") and counts.get("available")):
        return {
            "available": False,
            "reason": (
                "both a census and a filtered count are needed to compare them; "
                f"census {'ran' if census.get('available') else 'did not run'}, "
                f"counts {'ran' if counts.get('available') else 'did not run'}"
            ),
        }

    #: The census key each proven filter answers. Only quantities that exist on
    #: both sides appear — the census's `distinct_owners` and its protocol
    #: histogram have no filter behind them at all, and a row here for a
    #: quantity only one side measured would read as a disagreement.
    pairs = {"x402_supported": "x402_supported", "with_feedback": "with_feedback"}

    walked_of = int(census.get("counted") or 0)
    asked_of = int(counts.get("baseline") or 0)

    rows: list[dict[str, Any]] = []
    for filter_name, census_key in pairs.items():
        proven = (counts.get("filters") or {}).get(filter_name) or {}
        if not proven.get("applied"):
            # A filter that could not be proven is not a disagreement with the
            # census — it is a quantity we declined to read. Recorded as that.
            rows.append(
                {
                    "quantity": filter_name,
                    "walked": census.get(census_key),
                    "walked_of": walked_of,
                    "compared": False,
                    "reason": proven.get("reason") or "no filtered count was published",
                }
            )
            continue

        walked = int(census.get(census_key) or 0)
        asked = int(proven["total"])
        walked_share = walked / walked_of if walked_of else None
        asked_share = asked / asked_of if asked_of else None
        rows.append(
            {
                "quantity": filter_name,
                "compared": True,
                "walked": walked,
                "walked_of": walked_of,
                "walked_share": round(walked_share, 5) if walked_share is not None else None,
                "asked": asked,
                "asked_of": asked_of,
                "asked_share": round(asked_share, 5) if asked_share is not None else None,
                "difference": walked - asked,
                "share_difference_pp": (
                    round(100 * (walked_share - asked_share), 3)
                    if None not in (walked_share, asked_share)
                    else None
                ),
                "agree": walked == asked,
            }
        )

    return {
        "available": True,
        "hours_apart": _hours_between(census.get("read_at"), counts.get("read_at")),
        "rows": rows,
        "note": (
            "One index, asked twice: we counted every row, then let 8004scan "
            "count. Neither is privileged and the gap is not resolved — the "
            "registry grew between the readings, so each is published against "
            "its own population."
        ),
    }


def _reach_three_ways(
    census: dict[str, Any], counts: dict[str, Any], graph: dict[str, Any]
) -> dict[str, Any]:
    """How many agents anyone has ever rated, answered three ways by one index.

    Kept separate from `_feedback_cross_check`, which compares two answers to a
    different question — how many *feedbacks* exist (11,681 summed across agents
    against 11,719 in the table). Merging them would produce one block where a
    reader cannot tell which quantity disagrees, and they disagree by different
    amounts for different reasons.

    The three routes:

    * **walked** — `census` counted agent rows whose `total_feedbacks` was above
      zero. Two hours, and a day stale by the time the others are read.
    * **asked** — `min_feedbacks=1`, answered by 8004scan in one request against
      the population as it stands now.
    * **counted in the feedback table** — distinct `agent.token_id` across every
      row of /feedbacks, which is a different table answering from the other end.

    They do not agree, and the spread is the finding: 510, 436 and 547 are three
    numbers one index holds for one quantity. Nothing here can say which is
    right, and picking one would be the misquote.
    """
    readings: list[dict[str, Any]] = []

    if census.get("available") and census.get("with_feedback") is not None:
        readings.append(
            {
                "route": "walked every agent row",
                "agents": int(census["with_feedback"]),
                "of": census.get("counted"),
                "read_at": census.get("read_at"),
                "carried_forward": bool(census.get("carried_forward")),
            }
        )

    proven = (counts.get("filters") or {}).get("with_feedback") or {}
    if proven.get("applied"):
        readings.append(
            {
                "route": "asked the index to filter",
                "agents": int(proven["total"]),
                "of": counts.get("baseline"),
                "read_at": counts.get("read_at"),
            }
        )

    if graph.get("available"):
        readings.append(
            {
                "route": "counted distinct agents in the feedback table",
                "agents": int(graph.get("distinct_rated_agents") or 0),
                "of": graph.get("rows"),
                "read_at": graph.get("read_at"),
            }
        )

    if len(readings) < 2:
        return {
            "available": False,
            "reason": (
                f"at least two readings are needed to compare them; {len(readings)} answered"
            ),
        }

    values = [r["agents"] for r in readings]
    return {
        "available": True,
        "readings": readings,
        "low": min(values),
        "high": max(values),
        "spread": max(values) - min(values),
        "agree": len(set(values)) == 1,
        "note": (
            "One index, three routes to one quantity, and no reason for them to "
            "differ. Published as a spread because nothing here can say which "
            "route is right."
        ),
    }


def _ours_cross_check(indexed: dict[str, Any], recorded: dict[str, Any]) -> dict[str, Any]:
    """Our four registrations, field by field, against a reading we did not take.

    Everything else in `registry.json`'s `ours` block is self-reported: we ran
    `register_identity.py`, it wrote `vetting/identity/97.json`, and the page
    renders that file. It is honest and it is unfalsifiable in the literal
    sense — nothing in the artifact could contradict it.

    This can. 8004scan indexes BSC testnet, our four agents are in it, and the
    two readings either agree, which is evidence, or they do not, which is a
    finding. Same rule the whole module runs on.

    **The honest negatives are published as loudly as the agreements.** The
    index sees zero feedbacks, zero score and an empty protocol list on all
    four. None of that is an indexing error — it is the index correctly
    reporting fields our cards never filled and evidence nobody ever produced,
    held to exactly the standard the survey holds 285,000 strangers to.
    """
    if not indexed.get("available"):
        return {"available": False, "reason": indexed.get("reason") or "no indexed reading"}
    if not recorded.get("agents"):
        return {
            "available": False,
            "reason": "no registration of ours is recorded — vetting/identity/97.json is absent",
        }

    theirs = {str(a.get("token_id")): a for a in indexed.get("agents") or ()}
    ours = {str(a.get("agent_id")): a for a in recorded.get("agents") or ()}

    agreements: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []

    for token_id in sorted(ours.keys() & theirs.keys(), key=int):
        mine, their = ours[token_id], theirs[token_id]
        for field, mine_value, their_value in (
            ("name", mine.get("name"), their.get("name")),
            (
                "owner_address",
                (recorded.get("owner") or "").lower(),
                (their.get("owner_address") or "").lower(),
            ),
        ):
            row = {
                "token_id": int(token_id),
                "field": field,
                "ours": mine_value,
                "theirs": their_value,
            }
            (agreements if mine_value == their_value else disagreements).append(row)

        for field, note in (
            (
                "scan_total_feedbacks",
                "Nobody has rated ours either. The same standard the survey holds "
                "285,000 strangers to, applied here.",
            ),
            (
                "scan_total_score",
                "Zero on the metric this site refuses to rank by, published rather than omitted.",
            ),
            (
                "supported_protocols",
                "Not an indexing error — our cards declare a service endpoint and "
                "no protocol list, so there is nothing here to rank.",
            ),
        ):
            value = their.get(field)
            if not value:
                negatives.append(
                    {"token_id": int(token_id), "field": field, "theirs": value, "note": note}
                )

    return {
        "available": True,
        "chain_id": indexed.get("chain_id"),
        "owner": indexed.get("owner"),
        "recorded": len(ours),
        "indexed": len(theirs),
        "matched": len(ours.keys() & theirs.keys()),
        # Both directions are findings and neither is an error. `recorded_only`
        # means we say a registration exists that the index has never seen;
        # `indexed_only` means the index holds an agent for this owner that our
        # own record does not mention.
        "recorded_only": sorted(ours.keys() - theirs.keys(), key=int),
        "indexed_only": sorted(theirs.keys() - ours.keys(), key=int),
        "same_contract": (indexed.get("indexed_contract") or "").lower()
        == (erc8004.IDENTITY_REGISTRY.get(97) or "").lower(),
        "agreements": agreements,
        "disagreements": disagreements,
        "honest_negatives": negatives,
        "note": (
            "The same four agents according to somebody else's index. Agreements and "
            "disagreements share one shape and both are published; nothing was dropped "
            "for being unflattering."
        ),
    }


def _hours_between(a: str | None, b: str | None) -> float | None:
    """How far apart two readings were, or None if either did not say.

    None rather than 0.0 when a timestamp is missing: zero hours apart is a
    claim that they were simultaneous, and a reading that did not stamp itself
    has said nothing about when it happened.
    """
    if not (a and b):
        return None
    try:
        first, second = datetime.fromisoformat(a), datetime.fromisoformat(b)
    except ValueError:
        return None
    return round(abs((second - first).total_seconds()) / 3600, 2)


def fetch_scan(census: bool = False, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read 8004scan and reconcile it against our own on-chain count.

    The comparison is the point. Our number comes from binary search on
    `ownerOf`; theirs from an indexer. Neither is privileged here — both are
    published with the method named, and the gap between them is stated rather
    than resolved, because nothing in this repository can say which is right.

    What is read depends on what the environment entitles us to, and the payload
    says which it was rather than leaving the reader to infer it from the key
    names. With `SCAN8004_API_KEY` set, the default reading asks the index for
    the shares directly — one request each, each with its filter proven to have
    applied — rather than deriving them from a two-hour walk. The walk is still
    available behind `--census` and is still the only source for the six figures
    8004scan implements no filter for. Without a key, the anonymous tier affords
    one page of the newest hundred, which is a sample of one platform's latest
    batch and is published under `sample` so it can never be read as the
    population.
    """
    from misquote.registry import scan8004

    tier = scan8004.tier()
    pop = scan8004.population(BSC_MAINNET)
    payload: dict[str, Any] = {
        "source": f"8004scan.io{tier.base.removeprefix('https://8004scan.io')}",
        "tier": tier.name,
        "rate_limit_per_minute": tier.requests_per_minute,
        "rate_limit_per_day": tier.requests_per_day,
        "population": pop,
        "stats": scan8004.stats(),
    }

    if tier.can_census:
        payload["counts"] = scan8004.counts(BSC_MAINNET)
        payload["feedback_reach"] = scan8004.feedback_reach(BSC_MAINNET)
        payload["feedback_graph"] = scan8004.feedback_graph(BSC_MAINNET)
        payload["categories"] = scan8004.categories(BSC_MAINNET)
        payload["leaderboard"] = scan8004.leaderboard(BSC_MAINNET)
        # Testnet, where our own four live. Small — 1,906 agents against
        # mainnet's 285,000 — and carried because `ours_as_indexed` reports our
        # agents' zeros against it, and a zero has no meaning without the
        # population it is a zero out of.
        payload["counts_testnet"] = scan8004.counts(scan8004.BSC_TESTNET_CHAIN_ID)
        payload["name_collisions"] = scan8004.name_collisions(chain_id=BSC_MAINNET)

        # The owner comes off our own record rather than out of a constant, so
        # this checks a file against a chain rather than a literal against a
        # file. See `scan8004.ours_as_indexed`.
        recorded_ours = ours()
        owner = recorded_ours.get("owner")
        if owner:
            payload["ours_as_indexed"] = scan8004.ours_as_indexed(owner)
            payload["ours_cross_check"] = _ours_cross_check(
                payload["ours_as_indexed"], recorded_ours
            )

    # The two readings are mutually exclusive on purpose. Publishing a census
    # and a sample together would invite a reader to compare a share of 278,353
    # against a share of 100 as though the difference were a finding about the
    # registry rather than about which tier answered.
    if census and tier.can_census:
        payload["census"] = _census_block(scan8004.census(BSC_MAINNET))
        payload["feedback_cross_check"] = _feedback_cross_check(
            payload["census"], payload["feedback_reach"]
        )
    elif tier.can_census and (previous or {}).get("census", {}).get("available"):
        # **Carried forward, and stamped.**
        #
        # The census is now opt-in, and the failure mode that creates is exactly
        # the one `read_survey` documents fourteen lines up: a build that runs
        # without `--census` must not replace a real two-hour reading with a
        # refusal. "A build that deletes a measurement is worse than one that
        # never takes it."
        #
        # So the recorded block is carried through verbatim with a flag saying
        # it was not taken on this run. Carried *and* stamped — a census silently
        # republished is a number claiming to be current, which is the same
        # defect wearing better clothes. `read_at` says when it was really taken
        # and the page renders its age.
        payload["census"] = _census_block(previous["census"], carried_forward=True)
        payload["feedback_cross_check"] = _feedback_cross_check(
            payload["census"], payload["feedback_reach"]
        )
    elif tier.can_census:
        # Keyed, no census asked for and none on record. `counts` is the whole
        # reading, and no `sample` is published beside it.
        #
        # That exclusion is the same one the census/sample branches have always
        # observed, for the same reason: a share of 284,996 next to a share of
        # 100 invites a reader to treat the difference as a fact about the
        # registry when it is a fact about which reading answered. `counts` is a
        # whole-population share, so a hundred-row sample beside it would be
        # exactly that trap with a new name.
        payload["census"] = _census_block(
            {
                "available": False,
                "tier": tier.name,
                "reason": (
                    "no census has been recorded and none was requested. The filtered "
                    "counts above answer two of its shares directly and are proven; the "
                    "six it derives that no filter can answer — distinct owners, distinct "
                    "descriptions, the protocol histogram — need `make registry-census`, "
                    "which walks 2,848 pages in 60 to 130 minutes."
                ),
            }
        )
    else:
        payload["sample"] = scan8004.sample(BSC_MAINNET, 100)
        payload["census"] = _census_block(
            {
                "available": False,
                "tier": tier.name,
                "reason": (
                    "no SCAN8004_API_KEY, so no whole-population count was taken. "
                    "The anonymous tier answers 180 requests a minute, which is "
                    "affordable — what it cannot do is support the claim: a "
                    "different chain parameter, a different envelope, and a `total` "
                    "nothing here has checked. See scan8004.Tier.can_census."
                ),
            }
        )

    if payload.get("counts") and payload.get("census"):
        payload["counts_cross_check"] = _counts_cross_check(payload["census"], payload["counts"])

    if payload.get("feedback_graph"):
        payload["agents_with_feedback_three_ways"] = _reach_three_ways(
            payload.get("census") or {},
            payload.get("counts") or {},
            payload["feedback_graph"],
        )

    # Named `ours_population` rather than `ours`, which is the name of a
    # module-level function this body now also calls. The shadowing was silent
    # until it wasn't: `ours()` below the assignment raised UnboundLocalError.
    ours_population = read_survey().get("population")
    theirs = pop.get("population") if pop.get("available") else None
    if ours_population and theirs:
        payload["reconciliation"] = _reconciliation(
            int(ours_population), int(theirs), pop.get("contract_address")
        )
    return payload


def _surfaced_token_ids(payload: dict[str, Any]) -> set[str]:
    """Which agents this build actually renders, so the rest are not shipped.

    The join between the feedback walk and the category listings, and it is the
    reason the walk is worth its two minutes: an agent on a category card can
    carry *its own* feedback — how many rows, from how many distinct addresses,
    and the transactions that wrote them — instead of a number aggregated over
    strangers.

    Derived from what was published rather than declared, so a category that
    lists a different agent tomorrow ships that agent's feedback and not
    yesterday's.
    """
    scan = payload.get("third_party") or {}
    categories = scan.get("categories") or {}
    return {
        str(agent.get("token_id"))
        for category in categories.values()
        if isinstance(category, dict)
        for agent in category.get("agents") or ()
        if agent.get("token_id")
    }


def publishable_scan(reading: dict[str, Any], token_ids: set[str] | None = None) -> dict[str, Any]:
    """The reading, minus what the browser has no use for.

    `feedback_graph`'s per-agent index is 547 entries and ~290KB — larger than
    every other artifact this site fetches put together, `assumptions.json`
    excepted. It is also, for a page, mostly dead weight: a category card needs
    the dozen agents it lists, not every agent anyone has ever rated.

    So the split is the one `read_survey` already makes between reading and
    publishing, applied to size rather than to freshness. The whole index is
    recorded to `data/scan8004.json`, which nothing downloads; the artifact
    carries the aggregate, plus the per-agent rows for the token ids actually
    surfaced. `LISTING_LIMIT` records the same lesson from the other emitter —
    400 listings was 226KB of artifact "for a page that fetches it client-side,
    and enough DOM to time out a jsdom render".

    The count of what was dropped travels with it. A projection that silently
    shrinks a reading is indistinguishable from a reading that was smaller.
    """
    graph = reading.get("feedback_graph")
    if not isinstance(graph, dict) or "by_agent" not in graph:
        return reading

    full = graph.get("by_agent") or {}
    kept = {k: v for k, v in full.items() if token_ids and k in token_ids}
    return {
        **reading,
        "feedback_graph": {
            **{k: v for k, v in graph.items() if k != "by_agent"},
            "by_agent": kept,
            "by_agent_held": len(full),
            "by_agent_published": len(kept),
            "by_agent_note": (
                f"{len(full)} agents carry feedback and {len(kept)} are published here — "
                "the ones this site surfaces. The full index is recorded but not "
                "served: it is larger than every other artifact this page fetches."
            ),
        },
    }


#: Ours, mainnet first. The order is the claim: the mainnet mint is the one
#: TermiX indexes and the one a judge can look up on bscscan.
OURS_MAINNET_PATH = REPO / "vetting" / "identity" / "56.json"
OURS_CHAPEL_PATH = REPO / "vetting" / "identity" / "97.json"

#: Every key a present record carries, nulled — the same floor the four hire
#: records sit on, and here for the same reason. `97.json` has a `funding` block
#: and `56.json` does not, so which file is preferred would otherwise decide
#: whether five contracted leaves exist.
ABSENT_OURS: dict[str, Any] = {
    "agents": [],
    "block": None,
    "chain_id": None,
    "checks": [],
    "explorer": None,
    "funding": {"amount": None, "from": None, "to": None, "tx": None, "url": None},
    "implementation": None,
    "owner": None,
    "read_at": None,
    "reason": None,
    "record": None,
    "registry": None,
    "signer": None,
    "summary": {"checked": None, "failed": None, "registered": None, "unknown": None},
    "surveyed": False,
    "verdict": None,
    "age_hours": None,
}


def ours() -> dict[str, Any]:
    """The four registrations this project made, as recorded on disk.

    Read, never re-derived. `scripts/register_identity.py` is the half that
    touches a chain and `make artifacts` must not — the same split
    `addresses_report.read_record` makes, for the same reason its docstring
    gives: a build that could reach the network is a build that can overwrite a
    real reading with a refusal.

    Freshness comes from the file's mtime rather than from a field inside it,
    again following `addresses_report`: the record says when the chain was read,
    and the file says when we last asked.

    ## Mainnet first

    This read `97.json` and nothing else, so `/registry` showed a reader the
    chapel ids 1927-1930 against a testnet explorer while `/status`'s identity
    gate — which now prefers the mainnet record — reported five agents on BSC
    mainnet. Two pages of one site disagreeing about which registration is ours.

    `56.json` is the same four agents on mainnet with twenty-one read-backs, all
    passing, the same owner, and it is the registration TermiX's explorer
    indexes, because that indexes mainnet mints. Chapel remains the fallback.

    Merged over a skeleton rather than published raw, for the reason
    `_published_record` gives above: `97.json` carries a `funding` block and
    `56.json` does not, and the artifact contract declares
    `ours.funding.*`. Without the skeleton, changing which file is preferred
    would silently drop five contracted leaves.
    """
    path = next(
        (p for p in (OURS_MAINNET_PATH, OURS_CHAPEL_PATH) if p.exists()),
        None,
    )
    if path is None:
        return {
            **ABSENT_OURS,
            "reason": (
                "no agent of ours has been registered. `Readme.md` says all four "
                "do; until this file exists that is a claim rather than a reading."
            ),
        }

    record: dict[str, Any] = json.loads(path.read_text())
    read_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    return {
        **ABSENT_OURS,
        **record,
        "read_at": read_at.isoformat(timespec="seconds"),
        "age_hours": round((datetime.now(UTC) - read_at).total_seconds() / 3600, 1),
        "record": str(path.relative_to(REPO)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="read the chain: survey N registry ids and record them to disk",
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--scan",
        action="store_true",
        help=(
            "call 8004scan and record the reading. Without it, whatever was "
            "recorded last is republished — the same split --sample makes for "
            "the chain survey, so `make artifacts` cannot overwrite a real "
            "reading with a refusal."
        ),
    )
    parser.add_argument(
        "--census",
        action="store_true",
        help=(
            "walk every page of /agents and count the whole chain: 2,848 requests "
            "and 60-130 minutes. Opt-in, because the two shares most readers want "
            "are now asked for directly and proven. What only the walk answers is "
            "distinct owners, distinct descriptions and the protocol histogram, "
            "for which 8004scan implements no filter at all."
        ),
    )
    parser.add_argument(
        "--no-census",
        action="store_true",
        help=(
            "deprecated no-op: the census is now opt-in via --census rather "
            "than opt-out. Accepted so a command copied from an older Makefile "
            "still runs."
        ),
    )
    parser.add_argument("--survey-path", default=str(SURVEY_PATH))
    parser.add_argument(
        "--out", default=str(REPO / "apps" / "web" / "public" / "artifacts" / "registry.json")
    )
    args = parser.parse_args()

    survey_path = Path(args.survey_path)

    # Two modes, and only one of them touches a chain.
    #
    #   --sample N   read the registry and record what was found
    #   (default)    republish whatever was recorded
    #
    # `make artifacts` takes the second, so a build cannot destroy a survey it
    # did not take — which is exactly what it used to do.
    if args.sample:
        identity = survey_chain(args.sample, args.seed)
        if identity.get("surveyed"):
            survey_path.parent.mkdir(parents=True, exist_ok=True)
            recorded = {k: v for k, v in identity.items() if k not in _base()}
            survey_path.write_text(json.dumps(recorded, indent=2, sort_keys=True) + "\n")
            print(f"  survey recorded  -> {survey_path}")
    else:
        identity = read_survey(survey_path)

    payload = {
        "hire_flow": hire_flow(),
        # Ours, before the survey of everybody else's. A marketplace that
        # measures four hundred strangers and cannot point at its own row in the
        # same registry is measuring other people.
        "ours": ours(),
        "hire_flow_contracts": hire_flow_contracts(),
        "identity": identity,
        "aacp": aacp_overlap(),
        # A second, independent reading of the same registry. Alongside ours,
        # never instead of it — see `registry/scan8004.py`.
        "third_party": (
            # `read_scan()` first, and its result handed to `fetch_scan` — that
            # argument is what stops a fast run from deleting a slow reading.
            fetch_scan(census=args.census, previous=read_scan()) if args.scan else read_scan()
        ),
        "build": provenance.build_stamp(
            "python scripts/registry_report.py"
            + (f" --sample {args.sample}" if args.sample else ""),
            source="chain" if args.sample else "recorded survey",
        ),
    }

    if args.scan:
        SCAN_PATH.parent.mkdir(parents=True, exist_ok=True)
        # The *whole* reading, before projection. This file is the record; the
        # artifact is the view. Writing the projection here would make the
        # recorded reading a function of what the site happened to render on the
        # day it was taken.
        SCAN_PATH.write_text(json.dumps(payload["third_party"], indent=2, sort_keys=True) + "\n")
        print(f"8004scan reading -> {SCAN_PATH}")

    payload["third_party"] = publishable_scan(payload["third_party"], _surfaced_token_ids(payload))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    flow = payload["hire_flow"]
    print(f"  hire flow        {flow['transaction_count']} transactions end to end")
    print(f"  client signs     {flow['client_transaction_count']}")
    if not flow["escrow"]["available"]:
        print(f"  escrow           REFUSED — {flow['escrow']['reason'][:80]}")
    identity = payload["identity"]
    print(
        f"  registry survey  {'done' if identity['surveyed'] else 'not run — ' + identity['reason']}"
    )
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
