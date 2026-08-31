"""Activation, refused in the shape that says which thing is missing.

Every assertion here is about the difference between *the capability does not
exist* and *you have nothing*. They are one HTTP status apart and they are not
the same sentence, and the whole reason this surface can be built before a
verified deployment exists is that it keeps them apart.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="the `api` extra is not installed — `uv sync --extra api`")

from fastapi.testclient import TestClient  # noqa: E402

from misquote.api import service as api  # noqa: E402
from misquote.sessions import keys  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


def test_the_module_is_verified_and_the_validator_is_not() -> None:
    """The ledger's evidence, asserted from the other side.

    This used to assert `SESSION_KEY_MODULE == {}`, and the module's own
    docstring predicted the day it would go red: "the day someone records a
    verified address, that test goes red and the ledger entry has to be
    rewritten". Both happened.

    What the entry claims now is narrower and still checkable: the keystore is
    verified on both chains, and **no validator module is** — which is where an
    allowlist and a spend cap would be enforced. Pinning both halves here means
    the ledger cannot say the caps are missing while the API serves them, or the
    reverse.
    """
    assert set(keys.SESSION_KEY_MODULE) == {56, 97}
    assert set(keys.SESSION_KEY_CONTROLLER) == {56, 97}
    assert set(keys.SESSION_KEY_EVIDENCE) == {56, 97}

    assert keys.VALIDATOR_MODULE == {}, (
        "a verified validator module would mean the caps are enforced, which is "
        "what the ledger entry says is not built"
    )

    for chain, readings in keys.SESSION_KEY_EVIDENCE.items():
        assert any("NOT VERIFIED" in line for line in readings), (
            f"chain {chain}'s evidence records what was read and not what those "
            f"readings fail to establish — which is the half P-18 was about"
        )


def test_asking_whether_activation_is_possible_succeeds(client: TestClient) -> None:
    """200 either way, which is why the status code did not change when the answer did.

    An error status for a truthful `available: false` would have made an absence
    look like a fault in the service; the same reasoning makes 200 right now that
    the answer is yes.
    """
    body = client.get("/sessions/capability").json()

    assert body["available"] is True
    assert body["module"], "a verified module must be published, not just claimed"
    assert body["searched"], "an answer must still say where it looked"
    assert body["evidence"], "and what it read"


def test_the_search_list_names_the_source_that_was_missed() -> None:
    """The defect was the search list, not the search.

    `SEARCHED` named three files under `vetting/addresses/` — all of them this
    repository's own output — and the module concluded from their contents that
    no session-key module had been verified anywhere. A search of your own
    output directory reported as a search of the world can only ever tell you
    what you already knew, and the addresses were in a package this repository
    had already read a different table out of.
    """
    joined = " ".join(keys.SEARCHED)
    assert "altananetwork/sdk" in joined, (
        "the SDK is where the addresses were the whole time; a search list that "
        "omits it repeats P-24"
    )


def test_the_capability_separates_what_is_read_from_what_is_not() -> None:
    """Four promises with no implementation between them, split into two lists.

    `readable_without_a_signer` used to name the allowlist, the spend cap, the
    expiry and revocation — and no function read any of them. Reading the
    deployment did not turn four promises into four reads: two of them are
    enforced somewhere this repository has not looked, so they moved to a field
    that says so rather than staying in a list that implies otherwise.
    """
    body = client_capability()

    assert body["readable_without_a_signer"]
    assert body["not_readable_here"], (
        "the allowlist and the spend cap are not readable here, and a capability "
        "that omits the field reads as one where everything is"
    )
    joined = " ".join(body["not_readable_here"]).lower()
    assert "allowlist" in joined and "spend cap" in joined


def client_capability() -> dict:
    return keys.capability(97)


def test_the_plan_is_published_even_though_the_module_is_not(client: TestClient) -> None:
    """The transaction count is a fact about the caps subset, not about a deployment.

    Revoking is one transaction whether or not anyone has deployed the module,
    and that is the product's central activation claim — so it must be checkable
    before there is an address, or it is only a sentence in a README.
    """
    body = client.get("/sessions/capability").json()

    assert [step["name"] for step in body["revoke_plan"]] == ["revokeKey"]
    # Still two, and for none of the reasons it used to give. The old plan was
    # `approve` then `grant`, on the theory that a spend cap needs an ERC-20
    # allowance to the module. There is no approve: the fee is native BNB paid as
    # the call's value. What the second transaction really is, is a bootstrap —
    # `registerKey` on a fresh wallet reverts `KeyStore: account not
    # bootstrapped`, and the root key it registers must not expire.
    assert [step["name"] for step in body["grant_plan"]] == [
        "initialRegisterKey",
        "registerKey",
    ]
    assert [s.name for s in keys.grant_plan(bootstrapped=True)] == ["registerKey"], (
        "the bootstrap is once per wallet, and whether it is needed is readable "
        "rather than assumed"
    )
    assert all(step["sender"] == "owner" for step in body["grant_plan"] + body["revoke_plan"])


def test_reading_a_wallet_s_grants_refuses_rather_than_inventing_a_zero(
    client: TestClient,
) -> None:
    """This was 501 — "the route is real and the deployment is not" — and the
    deployment is real now, so the refusal moved rather than disappeared.

    `tests/conftest.py` points every RPC variable at a blackhole, so in the suite
    this exercises the path most likely to be seen in a demo on a host with no
    endpoint: the chain cannot be reached. **503, never `[]`.** A wallet holding
    no grants and a wallet nobody could ask about are different answers, and only
    one of them is a fact about the wallet.
    """
    response = client.get("/sessions/0x1234567890123456789012345678901234567890")
    assert response.status_code in (502, 503), (
        "an unreachable chain is an absent capability, not an empty wallet"
    )

    detail = response.json()["detail"]
    assert "note" in detail


def test_no_grant_read_ever_returns_an_empty_list(client: TestClient) -> None:
    """An empty list is indistinguishable from a wallet holding no grants.

    That confusion is the one this surface exists to avoid, so the absent
    capability refuses rather than returning a plausible zero.
    """
    body = client.get("/sessions/0x1234567890123456789012345678901234567890").json()
    assert "detail" in body
    assert "grants" not in body


def test_a_grant_with_no_allowlist_is_refused_in_the_type() -> None:
    """A session key that may call anything is not a bounded grant.

    Enforced in `__post_init__` rather than at a call site, because the point of
    the caps subset is that the unbounded case cannot be constructed.
    """
    with pytest.raises(ValueError, match="not a bounded grant"):
        keys.Cap(targets=(), token="0x0", amount=1, expiry_ts=1)
