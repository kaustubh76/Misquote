"""Activation, and the address it now has.

`sessions/keys.py` owns the reasoning; this exposes it. The only decisions that
belong here are the status codes, and neither is the obvious one.

**200 for the capability read.** Asking "can I activate?" and being told the
answer — with the plan and whatever is still missing — is a successful answer to
that question either way. Returning an error status for a truthful
`available: false` would make an absence look like a fault in the service rather
than a fact about the chain. That held while the answer was no and it holds now
that it is yes.

**The grant read was 501 and is now a read.** For as long as
`SESSION_KEY_MODULE` was empty, 501 was the honest code: the route was real, the
capability was not, and a 404 would have said the wrong thing — that activation
was a feature nobody had thought about. `scripts/verify_session_keys.py` ended
that, so this reads the keystore.

**503, never `[]`, when the chain cannot be reached.** The distinction the whole
surface exists to protect: a wallet holding no grants and a wallet nobody could
ask about are different answers, and only one of them is a fact about the wallet.
`api/rpc.connect` refuses rather than returning `None` for the same reason.

**What is read and what is not.** The keystore answers existence, liveness and
the public key. It does not answer the caps — the allowlist and spend cap live in
`registerKey`'s `validator` and `metadata` and on the per-wallet Altana account,
and nothing in this repository reads either. Every row says so in its own
`caps_note` field rather than omitting the key, because a row with no caps key
reads as a grant with no caps.
"""

from __future__ import annotations

from typing import Any

from misquote.api.errors import refuse
from misquote.sessions.keys import NoVerifiedSessionModule, capability, module_for

DEFAULT_CHAIN_ID = 56


def sessions_capability(chain_id: int = DEFAULT_CHAIN_ID) -> dict[str, Any]:
    """What activation would consist of, and whether it is possible today."""
    return capability(chain_id)


def sessions_for(owner: str, chain_id: int = DEFAULT_CHAIN_ID) -> dict[str, Any]:
    """The grants an address holds, read off the verified keystore."""
    try:
        module = module_for(chain_id)
    except NoVerifiedSessionModule as error:
        raise refuse(
            501,
            error=str(error),
            remedy=(
                "verify an Altana session-key module and record it in "
                "sessions/keys.py::SESSION_KEY_MODULE with its readings"
            ),
            note=(
                "The route is real and the capability is not. Nothing was read, so "
                f"this is not a claim that {owner} holds no grants — it is a claim "
                "that there is no contract to ask."
            ),
        ) from error

    from misquote.api.rpc import connect
    from misquote.sessions.calls import grants_for

    w3 = connect(chain_id)  # refuses 503 rather than returning None
    try:
        grants = grants_for(w3, chain_id, owner)
    except Exception as error:  # noqa: BLE001
        # A failed read is not an empty wallet. This is the one confusion the
        # whole surface exists to avoid, and swallowing the exception into `[]`
        # is how it would happen.
        raise refuse(
            502,
            error=f"the keystore did not answer: {type(error).__name__}: {error}",
            remedy="retry, or set BSC_RPC_URL to an endpoint that serves eth_call",
            note=(
                "No grant list was produced. An empty result would be "
                f"indistinguishable from {owner} holding no grants."
            ),
        ) from error

    return {
        "owner": owner,
        "chain_id": chain_id,
        "module": module,
        "grants": grants,
        "count": len(grants),
        "reads_the_caps": False,
        "note": (
            "Existence, liveness and the public key are read from the keystore. "
            "The allowlist and spend cap are not: they live in registerKey's "
            "validator and metadata arguments and on the per-wallet Altana "
            "account, and nothing in this repository reads either."
        ),
    }
