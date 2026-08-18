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
from pathlib import Path
from typing import Any

from misquote.registry import erc8004, erc8183
from misquote.tearsheet import provenance

REPO = Path(__file__).resolve().parents[1]
BSC_MAINNET = 56


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


def identity_survey(sample: int, seed: int) -> dict[str, Any]:
    """ERC-8004, which needs a chain. Says so plainly when it does not have one."""
    base: dict[str, Any] = {
        "identity_registry": erc8004.IDENTITY_REGISTRY,
        "reputation_registry": erc8004.REPUTATION_REGISTRY,
        "reputation_note": erc8004.REPUTATION_IS_NOT_DISPLAYED,
    }

    rpc = os.environ.get("BSC_RPC_URL")
    if not rpc or sample <= 0:
        return {
            **base,
            "surveyed": False,
            "reason": (
                "no BSC_RPC_URL configured — no registry read was attempted"
                if not rpc
                else "survey not requested (pass --sample N)"
            ),
        }

    try:
        from web3 import HTTPProvider, Web3

        w3 = Web3(HTTPProvider(rpc, request_kwargs={"timeout": 15}))
        chain_id = w3.eth.chain_id
        if chain_id != BSC_MAINNET:
            return {
                **base,
                "surveyed": False,
                "reason": f"BSC_RPC_URL points at chain {chain_id}, not {BSC_MAINNET}",
            }

        registry = erc8004.IdentityRegistry(w3, chain_id)
        rng = random.Random(seed)
        ids = sorted(rng.sample(range(1, sample * 20), sample))
        result = erc8004.survey(registry, ids)

        payload = asdict(result) if is_dataclass(result) else dict(result)
        payload = {k: v for k, v in payload.items() if not k.startswith("_")}
        return {
            **base,
            "surveyed": True,
            # Recorded so the survey is reproducible rather than merely reported.
            "sampled_ids": ids,
            "sampled_at_block": w3.eth.block_number,
            "seed": seed,
            "substantive_share": result.substantive_share,
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
            "contracts": contracts,
            "note": (
                "A snapshot of TermiX's published table, recorded to be checked "
                "against — never a source of truth for signing. Their own docs say "
                "to fetch live addresses before signing."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=0, help="survey N registry ids (needs RPC)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--out", default=str(REPO / "apps" / "web" / "public" / "artifacts" / "registry.json")
    )
    args = parser.parse_args()

    payload = {
        "hire_flow": hire_flow(),
        "identity": identity_survey(args.sample, args.seed),
        "aacp": aacp_overlap(),
        "build": provenance.build_stamp(
            "python scripts/registry_report.py"
            + (f" --sample {args.sample}" if args.sample else ""),
            source="chain" if args.sample else "offline",
        ),
    }

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
