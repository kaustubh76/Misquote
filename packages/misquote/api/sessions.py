"""Activation, and the address it does not have.

`sessions/keys.py` owns the reasoning; this exposes it. The only decision that
belongs here is the status code, and it is not the obvious one.

**501, not 404.** A 404 says the route does not exist, which is the wrong claim:
the grant path is enumerated, the revoke is one transaction, and both are
described in the response body. What is absent is a verified deployment to send
them to. 501 — *not implemented* — is the honest reading, and it keeps a client
from concluding that activation is a feature nobody thought about.

**200 for the capability read.** Asking "can I activate?" and being told "no, and
here is the plan and what is missing" is a successful answer to that question.
Returning an error status for a truthful `available: false` would make the
absence look like a fault in the service rather than a fact about the chain.
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
    """The grants an address holds — refused while there is nowhere to read them from."""
    try:
        module_for(chain_id)
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

    # Unreachable while SESSION_KEY_MODULE is empty, and deliberately left as a
    # refusal rather than a stub returning `[]`. An empty list here would be
    # indistinguishable from a genuine read of a wallet with no grants, which is
    # the one confusion this whole surface exists to avoid.
    raise refuse(  # pragma: no cover — no verified deployment exists
        501,
        error="a session-key module is recorded but reading grants is not implemented",
        remedy="implement the allowlist/cap/expiry read in sessions/keys.py",
        note="An empty result would be indistinguishable from a wallet holding no grants.",
    )
