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


def test_the_module_table_is_empty_and_that_is_the_claim() -> None:
    """The ledger's evidence, asserted from the other side.

    `tests/web/test_ledger.py` reads this symbol to verify the published
    "not built" entry. Pinning it here as well means the two cannot drift into
    a state where the ledger says one thing and the API serves another.
    """
    assert keys.SESSION_KEY_MODULE == {}
    assert keys.SESSION_KEY_EVIDENCE == {}


def test_asking_whether_activation_is_possible_succeeds(client: TestClient) -> None:
    """200, because "no, and here is why" is a successful answer to that question.

    An error status for a truthful `available: false` would make the absence
    look like a fault in the service rather than a fact about the chain.
    """
    body = client.get("/sessions/capability").json()

    assert body["available"] is False
    assert body["module"] is None
    assert body["searched"], "a refusal must say where it looked"
    assert "verify" in body["reason"]


def test_the_plan_is_published_even_though_the_module_is_not(client: TestClient) -> None:
    """The transaction count is a fact about the caps subset, not about a deployment.

    Revoking is one transaction whether or not anyone has deployed the module,
    and that is the product's central activation claim — so it must be checkable
    before there is an address, or it is only a sentence in a README.
    """
    body = client.get("/sessions/capability").json()

    assert [step["name"] for step in body["revoke_plan"]] == ["revoke"]
    assert len(body["grant_plan"]) == 2, "approve then grant — the approve is the forgotten one"
    assert all(step["sender"] == "owner" for step in body["grant_plan"] + body["revoke_plan"])


def test_reading_a_wallet_s_grants_is_501_and_not_404(client: TestClient) -> None:
    """404 would say the route does not exist. It does; the deployment does not."""
    response = client.get("/sessions/0x1234567890123456789012345678901234567890")
    assert response.status_code == 501

    detail = response.json()["detail"]
    assert "record it in" in detail["remedy"]
    # The distinction the status code exists for.
    assert "not a claim that" in detail["note"]


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
