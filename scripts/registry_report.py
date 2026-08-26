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

from misquote.registry import erc8004, erc8183
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
    }


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
                "TermixEscrow implements none of the seven calls erc8183.steps() "
                "models, across 5,894 candidate signatures. Jobs are keyed by a "
                "bytes32 order id, not the EIP's uint256 jobId, which is why "
                "jobs(uint256), nextJobId() and jobCount() all revert. Verified "
                "against the live contract in tests/registry/test_termix_escrow_fork.py."
            ),
            "order_decode": (
                "orders(bytes32) returns 13 words. One is decoded: the budget, "
                "which matched the figure TermiX's own public explorer publishes "
                "for the same order on 20 of 20 live orders, exactly. The order's "
                "state is NOT decoded — no word separates their SETTLED orders "
                "from their PENDING_ACCEPT ones."
            ),
            "contracts": contracts,
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


def read_scan(path: Path = SCAN_PATH) -> dict[str, Any]:
    """Republish the 8004scan reading on disk. **This calls no API.**"""
    if not path.exists():
        return {
            "available": False,
            "reason": (
                "no 8004scan reading has been recorded — run `make registry-scan`, "
                "which calls the API and writes data/scan8004.json"
            ),
        }
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return {"available": False, "reason": f"{path.name} is unreadable: {error}"}


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
            "Two of 8004scan's own tables answering the same question. Published "
            "whether or not they agree — a third-party index disagreeing with "
            "itself is a fact about the source, and resolving it here would mean "
            "choosing a number we have no way to check."
        ),
    }


def fetch_scan(census: bool = True) -> dict[str, Any]:
    """Read 8004scan and reconcile it against our own on-chain count.

    The comparison is the point. Our number comes from binary search on
    `ownerOf`; theirs from an indexer. Neither is privileged here — both are
    published with the method named, and the gap between them is stated rather
    than resolved, because nothing in this repository can say which is right.

    What is read depends on what the environment entitles us to, and the payload
    says which it was rather than leaving the reader to infer it from the key
    names. With `SCAN8004_API_KEY` set this counts every agent the index holds
    for BSC, an hour or so for 278,000 — and the shares carry no interval
    because nothing was inferred. Without it, the anonymous tier affords one
    page of the newest hundred, which is a sample of one platform's latest batch
    and is published under `sample` so it can never be read as the population.
    """
    from misquote.registry import scan8004

    tier = scan8004.tier()
    pop = scan8004.population(BSC_MAINNET)
    payload: dict[str, Any] = {
        "source": f"8004scan.io{tier.base.removeprefix('https://8004scan.io')}",
        "tier": tier.name,
        "rate_limit_per_minute": tier.requests_per_minute,
        "population": pop,
        "stats": scan8004.stats(),
    }

    # The two readings are mutually exclusive on purpose. Publishing a census
    # and a sample together would invite a reader to compare a share of 278,353
    # against a share of 100 as though the difference were a finding about the
    # registry rather than about which tier answered.
    if census and tier.can_census:
        payload["census"] = scan8004.census(BSC_MAINNET)
        payload["feedback_reach"] = scan8004.feedback_reach(BSC_MAINNET)
        payload["feedback_cross_check"] = _feedback_cross_check(
            payload["census"], payload["feedback_reach"]
        )
    else:
        payload["sample"] = scan8004.sample(BSC_MAINNET, 100)
        if census:
            payload["census"] = {
                "available": False,
                "tier": tier.name,
                "reason": (
                    "no SCAN8004_API_KEY, so the whole-population count was not "
                    "affordable — 10 requests a minute is about 4.6 hours for BSC"
                ),
            }

    ours = read_survey().get("population")
    theirs = pop.get("population") if pop.get("available") else None
    if ours and theirs:
        payload["reconciliation"] = {
            "ours": ours,
            "ours_method": "binary search on ownerOf — totalSupply() reverts on this proxy",
            "theirs": theirs,
            "theirs_method": "8004scan's indexer",
            "difference": ours - theirs,
            "difference_pct": round(100 * (ours - theirs) / ours, 3),
            "same_contract": (
                (pop.get("contract_address") or "").lower()
                == IDENTITY_REGISTRY.get(BSC_MAINNET, "").lower()
            ),
            "note": (
                "Two counts of the same registry by different methods. They are "
                "published together and the gap is not resolved: nothing here can "
                "say which is right, and picking the larger would be the misquote "
                "this project is named after. What is checked is that both are "
                "counting the same contract — if they were not, the comparison "
                "would be meaningless rather than merely unresolved."
            ),
        }
    return payload


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
    """
    path = REPO / "vetting" / "identity" / "97.json"
    if not path.exists():
        return {
            "surveyed": False,
            "reason": (
                "no agent of ours has been registered. `Readme.md` says all four "
                "do; until this file exists that is a claim rather than a reading."
            ),
            "chain_id": 97,
            "agents": [],
            "checks": [],
        }

    record: dict[str, Any] = json.loads(path.read_text())
    read_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    record["read_at"] = read_at.isoformat(timespec="seconds")
    record["age_hours"] = round((datetime.now(UTC) - read_at).total_seconds() / 3600, 1)
    record["record"] = str(path.relative_to(REPO))
    return record


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
        "--no-census",
        action="store_true",
        help=(
            "with a key, --scan counts every BSC agent the index holds, which "
            "took 68 minutes the first time it ran. This takes the one-page "
            "reading instead — "
            "faster, and honestly labelled a sample rather than a population."
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
        "third_party": fetch_scan(census=not args.no_census) if args.scan else read_scan(),
        "build": provenance.build_stamp(
            "python scripts/registry_report.py"
            + (f" --sample {args.sample}" if args.sample else ""),
            source="chain" if args.sample else "recorded survey",
        ),
    }

    if args.scan:
        SCAN_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCAN_PATH.write_text(json.dumps(payload["third_party"], indent=2, sort_keys=True) + "\n")
        print(f"8004scan reading -> {SCAN_PATH}")

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
