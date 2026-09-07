"""The Agent Studio seller's negotiate skill, reachable from a browser.

The scaffold at `studio/misquoterouter` serves A2A at
`misquote-agent.onrender.com` and sends **no** `Access-Control-Allow-Origin`
header on either its agent card or its JSON-RPC root. A page on the marketplace
origin therefore cannot call it: the request is made, the agent answers, and the
browser discards the answer before any code sees it. That is a property of the
vendor's runtime rather than a bug in either side, and it is why this route
exists at all — without it the honest options were an iframe, a lie, or nothing.

So this is a proxy and it is deliberately a thin one. It does not interpret the
quote, does not cache it, and does not decide whether it is good. It forwards one
A2A `message/send` carrying the `negotiate` data part, and returns the seller's
envelope with one field added: the address `provider_sig` recovers to.

## Why the recovery happens here and not in the browser

It could happen in either. It happens here because the page must not be the only
thing that can check the signature — a marketplace that renders "verified" from
its own frontend has proved nothing — and because `scripts/studio_negotiate.py`
already does exactly this against the same constants. Two callers, one rule.

The client is told which encoding recovered (`signed_over`), because the agent
signs the negotiation hash **as a hex string** rather than as 32 bytes, that is
documented nowhere, and a reader reproducing the check would otherwise recover a
plausible-looking wrong address.

## What it refuses

`notify_funded`. That skill verifies a funded job on chain and then spends the
agent's gas and its LLM credit to deliver. It is not something a visitor should
be able to trigger by pressing a button on a marketing page, and no route here
exposes it.

The statuses follow `errors.py`: **503** when the agent did not answer — the host
scales to zero and a cold start is transient, so retry is correct — and **502**
when it answered with something that is not a signed envelope, which is a
disagreement rather than an outage.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from typing import Any

from misquote.api.errors import refuse
from misquote.registry.erc8183 import JOB_ESCROW, PAYMENT_TOKEN

AGENT = "https://misquote-agent.onrender.com"

#: The chain the scaffold is configured for, and the one its identity is on.
STUDIO_CHAIN = 97

#: How long to wait. The host sleeps when idle and a cold start is most of a
#: minute; `lib/api.ts` already waits 70s for exactly this on the quote service,
#: so the ceiling here is the one that fits inside it.
TIMEOUT = 60

#: The task the page asks about. Fixed rather than taken from the request: a
#: free-text field posted to somebody else's agent through our origin is an open
#: relay, and the interesting fact here is the signature rather than the prompt.
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


def _envelope(body: dict[str, Any]) -> dict[str, Any] | None:
    for part in ((body.get("result") or {}).get("parts")) or []:
        data = part.get("data")
        if isinstance(data, dict) and "provider_sig" in data:
            return data
    return None


def _recover(negotiation_hash: str, signature: str) -> str | None:
    """The signer, or None. A failed recovery is not an error here — it is a no."""
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct

        return Account.recover_message(encode_defunct(text=negotiation_hash), signature=signature)
    except Exception:  # noqa: BLE001 — an unrecoverable signature is an answer
        return None


def studio_negotiate() -> dict[str, Any]:
    """Ask the seller for a signed quote, and say who signed it."""
    payload = {
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
                        "data": {"skill": "negotiate", "task_description": TASK, "terms": TERMS},
                    }
                ],
            }
        },
    }

    request = urllib.request.Request(
        AGENT + "/",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "misquote-api"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:  # noqa: S310 — fixed https
            body = json.loads(answer.read())
    except Exception as error:  # noqa: BLE001 — the failure is the answer
        raise refuse(
            503,
            error=f"the Agent Studio seller did not answer: {type(error).__name__}",
            remedy="try again — the host scales to zero and a cold start takes about a minute",
            note=(
                "Nothing was read. This is not a claim that the agent is down, "
                "only that it did not answer within the timeout."
            ),
        ) from error

    envelope = _envelope(body)
    if not envelope:
        raise refuse(
            502,
            error="the seller answered, but not with a signed envelope",
            remedy="check the agent card at /.well-known/agent-card.json for the negotiate skill",
            note="The reply is not being reshaped to look like one.",
        )

    terms = (envelope.get("response") or {}).get("terms") or {}
    signer = _recover(envelope.get("negotiation_hash", ""), envelope.get("provider_sig", ""))

    return {
        "envelope": envelope,
        "recovered_signer": signer,
        "signed_over": "the negotiation hash as a hex string, EIP-191",
        # What this repository can contradict, resolved here rather than on the
        # page, so the page renders an answer instead of computing one.
        "binds_to_the_verified_kernel": bool(
            envelope.get("verifying_contract")
            and envelope["verifying_contract"].lower() == JOB_ESCROW[STUDIO_CHAIN].lower()
        ),
        "denominated_in_the_kernels_token": bool(
            terms.get("currency")
            and terms["currency"].lower() == PAYMENT_TOKEN[STUDIO_CHAIN].lower()
        ),
        "chain_matches": envelope.get("chain_id") == STUDIO_CHAIN,
        "not_covered": (
            "This is the negotiation half. Nothing has been funded, and "
            "`notify_funded` is not reachable from here."
        ),
    }
