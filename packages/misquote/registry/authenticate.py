"""TermiX's authenticated API: the exchange, and what it does not buy.

## The blocker this closes, and it is the fourth of its kind

The ledger said this was *"blocked on a wallet-signed nonce exchanged for a
session JWT, **which is the same signing path the 24h burn-in needs and which
does not exist yet**"*. Both halves were false.

- **Message signing was a wrapper gap, not a capability gap.** `BscSigner` had no
  `sign_message`, and `encode_defunct` appeared nowhere in the repository — but
  `signer.account` is a public `LocalAccount` and has signed messages all along.
- **It is not the burn-in's path.** `check_burn_in` reads journal timestamps and
  never touches a signer, a key or a signature.

And the endpoints were never private. A GET on any unmatched `/api/v1/*` path
returns `401 UNAUTHORIZED`, so GET probes say nothing — but POST separates them,
because the public ones validate: `/auth/nonce` and `/auth/wallet` both answer
`400 walletAddress: Required`. That is **P-29**, and it is the same shape as P-24
(no verified deployment exists), P-27 (no session-key module has been verified)
and P-28 (nothing here can sign): a blocker recorded one level too high, which
stops the work that would clear it.

## It is SIWE, and the message is theirs

`/auth/nonce` returns EIP-4361: a `nonce`, a `domain`, a `chainId`, an
`expiresAt` ten minutes out, and the **exact `message` to sign**. This module
signs *that string, verbatim*. Reconstructing a SIWE message from its parts is
the standard way to produce a signature that recovers to the right address and
still fails verification — one character of whitespace, one field order, one
`Issued At` rounded differently. The server told us what it wants signed; there
is no reason to guess.

## What authenticating buys, and what it did not

Their backend is chain 56 only — `aacp.API_BASE` has no chain 97 key, by
construction, because there is no testnet deployment.

This paragraph used to end "a token authenticates us and **still cannot list
them**", which was true while the four agents existed only on chapel. They were
then minted on 56 and the authenticated read went from zero items to three. What
it buys is the read; what lists an agent is a mainnet mint **by the wallet that
authenticates** — TermiX attributes an agent to its minter, not its owner, so
warden is registered, owned, and still absent. `vetting/identity/termix-listing-56.json`
carries the experiment and the falsified lag hypothesis.

## The token is a secret

Nothing here writes it to `vetting/`, to an artifact, or to the journal. The
evidence file records *that* the exchange succeeded, for which wallet, against
which endpoint, at what time — the same shape as every other evidence record in
this repository, minus the credential. A repository whose argument is that
everything is checkable still does not publish bearer tokens.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from misquote.registry.aacp import BSC_MAINNET, api_base
from misquote.registry.erc8004 import _assert_fetchable

NONCE_PATH = "/api/v1/auth/nonce"
WALLET_PATH = "/api/v1/auth/wallet"
REFRESH_PATH = "/api/v1/auth/refresh"

#: Fields `/auth/nonce` returns. Recorded so a shape change is visible rather
#: than arriving as a `KeyError` three lines later.
NONCE_FIELDS = ("walletAddress", "nonce", "domain", "chainId", "message", "expiresAt")

#: What `/auth/wallet` requires, discovered one 400 at a time — each response
#: names exactly one missing field, so the set is read rather than guessed.
WALLET_FIELDS = ("walletAddress", "nonce", "signature")

#: Keys that may hold the credential in their response. More than one because
#: their shape is not documented and a wrong guess here silently produces a
#: client that authenticated and then sends no header.
TOKEN_KEYS = ("accessToken", "token", "access_token", "jwt")
REFRESH_KEYS = ("refreshToken", "refresh_token")


class AuthFailed(RuntimeError):
    """The exchange did not complete, with what the server said.

    An exception rather than a `None` token, for the reason `NoVerifiedDeployment`
    gives: a caller that forgets to check a `None` sends `Authorization: Bearer
    None` and reads the 401 as "the endpoint needs different credentials".
    """


@dataclass(frozen=True, slots=True)
class Challenge:
    """What the server asked us to sign. Its `message` is signed verbatim."""

    wallet: str
    nonce: str
    message: str
    domain: str
    chain_id: int
    expires_at: str

    @property
    def is_siwe(self) -> bool:
        """Does the message look like EIP-4361 rather than a bare nonce?

        Worth asking, because the two are signed the same way and mean different
        things: a bare nonce carries no domain binding, so a signature over it is
        replayable at any site that asked for the same string.
        """
        return "wants you to sign in with your Ethereum account" in self.message


@dataclass(slots=True)
class Session:
    """An authenticated session. **`token` never leaves this process.**

    `evidence()` is what may be written down: it deliberately has no field that
    could hold the credential, so a future caller cannot serialise one by
    reaching for the obvious attribute.
    """

    wallet: str
    chain_id: int
    token: str = field(repr=False)
    refresh_token: str = field(default="", repr=False)
    obtained_at: float = field(default_factory=time.time)
    challenge: Challenge | None = field(default=None, repr=False)

    @property
    def header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def evidence(self) -> dict[str, Any]:
        """What happened, with nothing that could be replayed.

        No token, no refresh token, and not the signature either — a signature
        over a live SIWE message is a credential for as long as the nonce is
        valid, which is ten minutes and long enough.
        """
        return {
            "authenticated": True,
            "wallet": self.wallet,
            "chain_id": self.chain_id,
            "endpoint": WALLET_PATH,
            "obtained_at": int(self.obtained_at),
            "siwe": bool(self.challenge and self.challenge.is_siwe),
            "domain": self.challenge.domain if self.challenge else "",
            "token_recorded": False,
            "note": (
                "The access token is a bearer credential and is not written to "
                "disk, to an artifact, or to the journal. This record says the "
                "exchange completed and for whom; it is not a way to repeat it."
            ),
        }


class TermixSession:
    """One wallet, one platform, one token at a time.

    Takes a `BscSigner` rather than a key, so the kill switch and the operator
    declaration apply to authenticating exactly as they apply to spending.
    """

    __slots__ = ("signer", "chain_id", "_session", "_timeout")

    def __init__(self, signer, chain_id: int = BSC_MAINNET, *, timeout: float = 20.0) -> None:
        # No chain-id equality check against the signer, and the asymmetry is the
        # point: TermiX's platform is chain 56 only, while the wallet that owns
        # our agents signs on chapel. The *same key* authenticates here and
        # broadcasts there, which is legitimate — an EIP-191 signature is not
        # bound to a network the way a transaction is. `chain_id` below selects
        # whose API to talk to, not what the signature is valid for.
        self.signer = signer
        self.chain_id = chain_id
        self._timeout = timeout
        self._session: Session | None = None

    @property
    def session(self) -> Session:
        if self._session is None:
            raise AuthFailed("not authenticated; call authenticate() first")
        return self._session

    @property
    def authenticated(self) -> bool:
        return self._session is not None

    # --- the exchange -------------------------------------------------------

    def challenge(self) -> Challenge:
        """Ask for a nonce. Public, no credentials."""
        payload = self._post(NONCE_PATH, {"walletAddress": self.signer.address})
        missing = [f for f in ("nonce", "message") if not payload.get(f)]
        if missing:
            raise AuthFailed(
                f"{NONCE_PATH} returned no {', '.join(missing)} — their shape "
                f"changed. Got keys: {sorted(payload)}"
            )
        return Challenge(
            wallet=str(payload.get("walletAddress", self.signer.address)),
            nonce=str(payload["nonce"]),
            message=str(payload["message"]),
            domain=str(payload.get("domain", "")),
            chain_id=int(payload.get("chainId", self.chain_id)),
            expires_at=str(payload.get("expiresAt", "")),
        )

    def authenticate(self) -> Session:
        """nonce → sign → token. Returns the session; the token stays inside it."""
        challenge = self.challenge()

        # Verbatim. See the module docstring: a reconstructed SIWE message
        # produces a signature that recovers correctly and verifies wrongly.
        signature = self.signer.sign_message(challenge.message, authorising=True)

        payload = self._post(
            WALLET_PATH,
            {
                "walletAddress": self.signer.address,
                "nonce": challenge.nonce,
                "signature": signature,
            },
        )
        token = _first(payload, TOKEN_KEYS)
        if not token:
            raise AuthFailed(
                f"{WALLET_PATH} accepted the signature and returned no token "
                f"under any of {TOKEN_KEYS}. Keys: {sorted(payload)}"
            )
        self._session = Session(
            wallet=self.signer.address,
            chain_id=self.chain_id,
            token=token,
            refresh_token=_first(payload, REFRESH_KEYS) or "",
            challenge=challenge,
        )
        return self._session

    def refresh(self) -> Session:
        """Trade the refresh token for a new access token."""
        current = self.session
        if not current.refresh_token:
            raise AuthFailed("no refresh token was issued; re-authenticate instead")
        payload = self._post(REFRESH_PATH, {"refreshToken": current.refresh_token})
        token = _first(payload, TOKEN_KEYS)
        if not token:
            raise AuthFailed(f"{REFRESH_PATH} returned no token. Keys: {sorted(payload)}")
        current.token = token
        current.refresh_token = _first(payload, REFRESH_KEYS) or current.refresh_token
        current.obtained_at = time.time()
        return current

    # --- authenticated reads ------------------------------------------------

    def get(self, path: str) -> Any:
        """One authenticated GET. Raises rather than returning a 401's body.

        A caller handed a parsed error object treats it as data — which is how a
        page comes to render `{"error": ...}` as a result.
        """
        import httpx

        url = api_base(self.chain_id) + path
        _assert_fetchable(url)
        response = httpx.get(
            url, headers=self.session.header, timeout=self._timeout, follow_redirects=False
        )
        if response.status_code == 401:
            raise AuthFailed(f"{path} refused the token; it may have expired")
        response.raise_for_status()
        return response.json()

    # --- internals ----------------------------------------------------------

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        import httpx

        url = api_base(self.chain_id) + path
        _assert_fetchable(url)
        response = httpx.post(url, json=body, timeout=self._timeout, follow_redirects=False)
        try:
            payload = response.json()
        except ValueError:
            raise AuthFailed(f"{path} returned {response.status_code} and no JSON") from None
        if response.status_code >= 400:
            error = (payload or {}).get("error") or {}
            raise AuthFailed(
                f"{path} -> {response.status_code} "
                f"{error.get('code', '')}: {error.get('message', payload)}"
            )
        if not isinstance(payload, dict):
            raise AuthFailed(f"{path} returned {type(payload).__name__}, not an object")
        return payload


def _first(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


__all__ = [
    "NONCE_FIELDS",
    "NONCE_PATH",
    "REFRESH_PATH",
    "TOKEN_KEYS",
    "WALLET_FIELDS",
    "WALLET_PATH",
    "AuthFailed",
    "Challenge",
    "Session",
    "TermixSession",
]
