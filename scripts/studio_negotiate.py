#!/usr/bin/env python3
"""Ask the Agent Studio seller for a quote, and check its signature ourselves.

The BNB Agent Studio scaffold at `studio/misquoterouter` is deployed and serving
at `misquote-agent.onrender.com`. Its agent card advertises two ERC-8183 skills.
Nothing in this repository had ever called one, so "the interface exists" rested
on reading its source — which is the shape of claim this project exists to
refuse.

This calls it. `negotiate` is the safe half of the pair: it is rule-based rather
than an LLM, it moves no money, it writes nothing to a chain, and it costs the
caller nothing. What comes back is an EIP-191 signature over a negotiation hash,
and a signature is checkable without the signer's cooperation.

## What is checked, and why each one is somebody else's word against ours

The interesting output is not the quote. It is that four fields of the envelope
agree with constants this repository derived independently, months earlier, from
deployed bytecode:

1. **The signer.** `provider_sig` recovers to an address. It must be the wallet
   that owns ERC-8004 identity 2102 — the one `bag erc8004 register` minted and
   `vetting/identity/studio-local-run.json` recorded. The agent proves it holds
   the key rather than asserting it.
2. **The verifying contract.** The signature binds to a chain id and a contract.
   That contract must be `erc8183.JOB_ESCROW[97]`, whose selectors
   `erc8183_abi.py` recovered by searching 21,060 candidate signatures against
   the deployed code. The vendor's SDK and our bytecode archaeology arriving at
   the same address is the corroboration; either alone is a claim.
3. **The currency.** `erc8183.PAYMENT_TOKEN[97]`, read from the kernel itself.
4. **The chain.** 97, matching the identity the CLI registered.

A disagreement in any of them is recorded as a disagreement. This script has no
opinion it can express except by writing down what it read.

## What it refuses to do

Call `notify_funded`. That one verifies a funded job on chain and then delivers,
which spends the agent's gas and its LLM credit, and it needs a funded job to
exist first. It is a different piece of work and it is on the ledger as one.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))

from misquote.registry.erc8183 import JOB_ESCROW, PAYMENT_TOKEN  # noqa: E402

RECORD = REPO / "vetting" / "identity" / "studio-negotiation.json"
LOCAL_RUN = REPO / "vetting" / "identity" / "studio-local-run.json"

AGENT = "https://misquote-agent.onrender.com"
AGENT_CARD = f"{AGENT}/.well-known/agent-card.json"

#: The chain the scaffold is configured for — `studio.toml`'s `[network].default`
#: is `bsc-testnet`, and the identity the CLI registered is on the same one.
STUDIO_CHAIN = 97

#: The task put to the agent. Deliberately this project's own question, so the
#: record reads as a marketplace transaction rather than as a ping.
TASK = (
    "Choose which PancakeSwap v3 WBNB/USDT pool range to provide liquidity to "
    "over the next 24 hours, and say why."
)
TERMS = {
    "deliverables": (
        "A named tick range, the expected fee APR net of realized convexity "
        "cost, and the assumption sheet behind it."
    ),
    "quality_standards": (
        "Every number traces to chain state or a published assumption. A range, "
        "not a point estimate."
    ),
}


def _post(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    """The answer, or the failure as the reading."""
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "misquote-studio"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310 — fixed https
            return {"ok": True, "status": answer.status, "body": json.loads(answer.read())}
    except urllib.error.HTTPError as error:
        return {
            "ok": False,
            "status": error.code,
            "error": error.read()[:400].decode(errors="replace"),
        }
    except Exception as error:  # noqa: BLE001 — the failure is the reading
        return {"ok": False, "status": None, "error": f"{type(error).__name__}: {error}"}


def _get(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "misquote-studio"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310 — fixed https
            return {"ok": True, "status": answer.status, "body": json.loads(answer.read())}
    except Exception as error:  # noqa: BLE001 — the failure is the reading
        return {"ok": False, "status": None, "error": f"{type(error).__name__}: {error}"}


def negotiate(timeout: int) -> dict[str, Any]:
    """One A2A `message/send` carrying the `negotiate` data part."""
    return _post(
        AGENT + "/",
        {
            "jsonrpc": "2.0",
            "id": f"misquote-{uuid.uuid4().hex[:8]}",
            "method": "message/send",
            "params": {
                "message": {
                    "kind": "message",
                    "messageId": str(uuid.uuid4()),
                    "role": "user",
                    "parts": [
                        {
                            "kind": "data",
                            "data": {
                                "skill": "negotiate",
                                "task_description": TASK,
                                "terms": TERMS,
                            },
                        }
                    ],
                }
            },
        },
        timeout,
    )


def envelope_from(body: dict[str, Any]) -> dict[str, Any] | None:
    """The signed quote out of the A2A reply, or None if it is not shaped like one."""
    parts = ((body.get("result") or {}).get("parts")) or []
    for part in parts:
        data = part.get("data")
        if isinstance(data, dict) and "provider_sig" in data:
            return data
    return None


def recover(negotiation_hash: str, signature: str) -> dict[str, Any]:
    """Who signed, and under which of the two encodings.

    The hash is a 32-byte value rendered as a hex *string*, and the agent signs
    the string rather than the bytes. That is not obvious and it is not
    documented, so both encodings are tried and the record says which one
    answered — a reader reproducing this should not have to guess, and a future
    SDK that switches encodings should show up as a change here rather than as a
    recovery that silently returns the wrong address.
    """
    from eth_account import Account
    from eth_account.messages import encode_defunct

    out: dict[str, Any] = {}
    try:
        out["as_text"] = Account.recover_message(
            encode_defunct(text=negotiation_hash), signature=signature
        )
    except Exception as error:  # noqa: BLE001
        out["as_text_error"] = f"{type(error).__name__}: {error}"
    try:
        out["as_bytes"] = Account.recover_message(
            encode_defunct(hexstr=negotiation_hash), signature=signature
        )
    except Exception as error:  # noqa: BLE001
        out["as_bytes_error"] = f"{type(error).__name__}: {error}"
    return out


def _same(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and a.lower() == b.lower()


def _short(address: str | None) -> str:
    """An address as a reader scans it, not as a chain stores it.

    The detail strings here are rendered verbatim by `CheckList`, and the first
    of them named the same 42-character address twice in one sentence — 84
    characters of hex carrying one bit of information, which is that they
    matched. A reader checking this copies from the envelope block above, where
    the full value has a `title` on it; the sentence only has to be legible.
    """
    if not address or len(address) < 12:
        return address or "—"
    return f"{address[:6]}…{address[-4:]}"


def _declared_owner() -> str | None:
    """The wallet `studio-local-run.json` says owns identity 2102."""
    if not LOCAL_RUN.exists():
        return None
    record = json.loads(LOCAL_RUN.read_text())
    return (record.get("erc8004") or {}).get("owner")


def check(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    """Every field of the envelope this repository can contradict."""
    owner = _declared_owner()
    recovered = recover(envelope.get("negotiation_hash", ""), envelope.get("provider_sig", ""))
    signer = recovered.get("as_text")
    terms = (envelope.get("response") or {}).get("terms") or {}

    return [
        {
            "name": "the signer holds the identity's key",
            "status": "PASS" if _same(signer, owner) else "FAIL",
            "detail": (
                f"provider_sig recovers to {_short(signer)}, which is the wallet "
                "that owns the identity this agent publishes"
                if _same(signer, owner)
                else f"recovered {_short(signer)}, expected {_short(owner)}"
            ),
            "provenance": "eth_account.recover_message + vetting/identity/studio-local-run.json",
        },
        {
            "name": "the signature binds to the kernel we verified",
            "status": "PASS"
            if _same(envelope.get("verifying_contract"), JOB_ESCROW.get(STUDIO_CHAIN))
            else "FAIL",
            "detail": (
                f"verifyingContract {_short(envelope.get('verifying_contract'))} is "
                f"erc8183.JOB_ESCROW[{STUDIO_CHAIN}], whose selectors this "
                "repository recovered from deployed bytecode"
            ),
            "provenance": "packages/misquote/registry/erc8183.py::JOB_ESCROW",
        },
        {
            "name": "the quote is denominated in the kernel's own token",
            "status": "PASS"
            if _same(terms.get("currency"), PAYMENT_TOKEN.get(STUDIO_CHAIN))
            else "FAIL",
            "detail": (
                f"currency {_short(terms.get('currency'))} is "
                f"erc8183.PAYMENT_TOKEN[{STUDIO_CHAIN}], read from the kernel"
            ),
            "provenance": "packages/misquote/registry/erc8183.py::PAYMENT_TOKEN",
        },
        {
            "name": "the chain matches the registered identity",
            "status": "PASS" if envelope.get("chain_id") == STUDIO_CHAIN else "FAIL",
            "detail": (
                f"signed for chain {envelope.get('chain_id')}, which is the chain "
                "the CLI registered the identity on"
            ),
            "provenance": "the envelope, and vetting/identity/studio-local-run.json",
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=RECORD)
    parser.add_argument("--timeout", type=int, default=90, help="the host sleeps when idle")
    args = parser.parse_args()

    print(f"agent card  {AGENT_CARD}")
    card = _get(AGENT_CARD, args.timeout)
    print(f"  status={card.get('status')} ok={card['ok']}")

    print("negotiate   POST / (A2A message/send)")
    answer = negotiate(args.timeout)
    print(f"  status={answer.get('status')} ok={answer['ok']}")

    envelope = envelope_from(answer.get("body") or {}) if answer["ok"] else None
    checks = check(envelope) if envelope else []
    for row in checks:
        print(f"  [{row['status']:<4}] {row['name']}")

    record: dict[str, Any] = {
        "read_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "subject": "the Agent Studio seller's ERC-8183 negotiate skill",
        "agent": AGENT,
        "chain_id": STUDIO_CHAIN,
        "answered": bool(envelope),
        "request": {"skill": "negotiate", "task_description": TASK, "terms": TERMS},
        "envelope": envelope,
        "recovered": recover(envelope.get("negotiation_hash", ""), envelope.get("provider_sig", ""))
        if envelope
        else None,
        "checks": checks,
        "verdict": (
            "PASS"
            if checks and all(c["status"] == "PASS" for c in checks)
            else ("FAIL" if checks else "UNKNOWN")
        ),
        "agent_card": card.get("body") if card["ok"] else None,
        "reason": None
        if envelope
        else (answer.get("error") or "the agent answered, but not with a signed envelope"),
        # Said here because the record is what the site republishes, and a reader
        # who sees four green checks should be told immediately which half of the
        # protocol they cover.
        "not_covered": (
            "This is the negotiation half. `notify_funded` — verify a funded job "
            "on chain, deliver, and `submit` — has not been driven through this "
            "agent, and no job has been created against the quote below."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"  -> {args.out}  verdict={record['verdict']}")
    return 0 if record["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
