"""The auth exchange, and the one thing it must never do.

Every test here is about a way a credential leaks or a refusal gets read as a
result. The exchange itself is exercised live by `scripts/termix_login.py`; what
is asserted offline is the shape of the thing holding the token.
"""

from __future__ import annotations

import json

import pytest

from misquote.registry import authenticate as auth


def _session(**kwargs) -> auth.Session:
    return auth.Session(
        wallet="0x" + "11" * 20,
        chain_id=56,
        token="SECRET-ACCESS-TOKEN",
        refresh_token="SECRET-REFRESH-TOKEN",
        **kwargs,
    )


def test_the_token_is_not_in_the_repr() -> None:
    """A bearer token in a `repr` reaches every log line that ever prints the
    object, and nobody chooses that — it happens because the dataclass default
    includes every field."""
    text = repr(_session())
    assert "SECRET" not in text, text
    assert "0x1111" in text, "and the useful half must still be there"


def test_the_evidence_record_cannot_carry_a_credential() -> None:
    """Not "does not" — **cannot**.

    `evidence()` has no field that could hold the token, the refresh token, or
    the signature. A future caller who wants to record more has to add a field,
    which is a visible decision; reaching for an existing one gets them nothing.
    """
    record = _session().evidence()
    serialised = json.dumps(record)

    assert "SECRET" not in serialised
    assert record["token_recorded"] is False
    assert not any("token" in str(v).lower() and "SECRET" in str(v) for v in record.values())
    # The signature is a credential too, for as long as the nonce lives.
    assert "signature" not in record


def test_a_signature_over_a_live_nonce_is_treated_as_a_secret() -> None:
    """Ten minutes is long enough to replay.

    `/auth/nonce` returns `expiresAt` ten minutes out, and anyone holding the
    signature over that message can complete the exchange as us within it. So the
    challenge is kept off the evidence record apart from its domain.
    """
    challenge = auth.Challenge(
        wallet="0x" + "11" * 20,
        nonce="deadbeef",
        message="termix-platform wants you to sign in with your Ethereum account:\n0x11",
        domain="termix-platform",
        chain_id=56,
        expires_at="2026-08-31T05:54:03.855Z",
    )
    record = _session(challenge=challenge).evidence()
    serialised = json.dumps(record)

    assert "deadbeef" not in serialised, "the nonce is half of a replay"
    assert "wants you to sign in" not in serialised
    assert record["domain"] == "termix-platform", "the domain is not a secret and is the point"
    assert record["siwe"] is True


def test_siwe_is_detected_rather_than_assumed() -> None:
    """A bare nonce and an EIP-4361 message are signed identically and mean
    different things: a signature over a bare nonce carries no domain binding, so
    it is replayable anywhere that asked for the same string."""
    siwe = auth.Challenge(
        wallet="0x11",
        nonce="n",
        message="termix-platform wants you to sign in with your Ethereum account:\n0x11",
        domain="termix-platform",
        chain_id=56,
        expires_at="",
    )
    bare = auth.Challenge(
        wallet="0x11", nonce="n", message="n", domain="", chain_id=56, expires_at=""
    )
    assert siwe.is_siwe
    assert not bare.is_siwe


def test_an_unauthenticated_client_raises_rather_than_returning_none() -> None:
    """A `None` token becomes `Authorization: Bearer None`, and the 401 that
    comes back reads as "the endpoint wants different credentials"."""

    class _Signer:
        address = "0x" + "11" * 20

    client = auth.TermixSession(_Signer(), 56)
    assert not client.authenticated
    with pytest.raises(auth.AuthFailed, match="not authenticated"):
        _ = client.session


def test_the_discovered_field_set_is_recorded() -> None:
    """Read one 400 at a time, not guessed.

    `/auth/wallet` names exactly one missing field per response, so the set was
    established by asking. Recorded here because a shape change should break a
    test rather than a demo.
    """
    assert auth.WALLET_FIELDS == ("walletAddress", "nonce", "signature")
    assert "message" in auth.NONCE_FIELDS and "expiresAt" in auth.NONCE_FIELDS


def test_more_than_one_token_key_is_accepted() -> None:
    """Their response shape is not documented.

    A client that looked only for `accessToken` and got `token` would report
    authenticated, hold nothing, and send no header — the failure that looks like
    an expired session forever.
    """
    assert len(auth.TOKEN_KEYS) > 1
    assert auth._first({"token": "t"}, auth.TOKEN_KEYS) == "t"
    assert auth._first({"accessToken": "a", "token": "t"}, auth.TOKEN_KEYS) == "a"
    assert auth._first({"nothing": "here"}, auth.TOKEN_KEYS) == ""
    assert auth._first({"token": ""}, auth.TOKEN_KEYS) == "", "empty is not a token"


def test_the_recorded_exchange_kept_no_credential() -> None:
    """The file on disk, checked rather than trusted."""
    from pathlib import Path

    record = Path(__file__).resolve().parents[2] / "vetting" / "identity" / "termix-auth.json"
    if not record.is_file():
        pytest.skip("no exchange recorded; scripts/termix_login.py --authenticate writes one")

    payload = json.loads(record.read_text())
    text = record.read_text()

    assert payload["token_recorded"] is False
    assert payload["authenticated"] is True
    # A JWT is three base64 segments; the header of the common one starts `eyJ`.
    assert "eyJ" not in text, "that looks like a JWT in a file"
    assert "Bearer " not in text
    for key in ("token", "accessToken", "refreshToken", "signature", "nonce"):
        assert key not in payload, f"{key} must not be recorded"


def test_sign_message_is_not_gated_on_the_dry_run_flag() -> None:
    """Read from the source, because the point is what the code does *not* do.

    `MISQUOTE_DRY_RUN` stops the wallet spending. Making it also gate signing
    would mean somebody sets it to 0 in order to log in and leaves it set — the
    flag's one job, traded for a convenience.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "packages" / "misquote" / "chain" / "signer.py"
    ).read_text()
    body = source[source.index("def sign_message") : source.index("def check_kill_switch")]

    assert "_dry_run" not in body, "the dry-run flag must not gate a signature"
    assert "authorising" in body, "an explicit argument is the guard instead"
    assert "check_kill_switch" in body, "but stop still means stop"
