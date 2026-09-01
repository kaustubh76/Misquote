"""Every record in `vetting/identity/`, held to the little they all promise.

`vetting/badges/` and `vetting/runs/` are both glob-checked. `vetting/identity/`
was not, despite being the directory `registry_report.py` reads **verbatim into
the published artifact** — whatever is in these files is what a reader is shown.

The nine records are genuinely different shapes (a chain survey, four escrow
runs, a session-key grant, an auth exchange, a listing finding), so this asserts
what is common and refuses to invent a schema they do not share. Two things
matter and both are about what reaches a page:

  * a record that a browser will be handed must not carry a secret, and
  * a record that says which network it describes must say one that exists,
    because that field is the only thing keeping the fork run and the mainnet
    run apart on `/registry`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
IDENTITY = REPO / "vetting" / "identity"
RECORDS = sorted(IDENTITY.glob("*.json"))

#: A field name that would hold a secret if it held anything.
SECRET_NAMES = re.compile(
    r"private|secret|mnemonic|seed|passphrase|password|bearer", re.IGNORECASE
)

#: 32 bytes of hex. A transaction hash is the same width, so the name is what
#: decides — this only ever runs on values whose key already sounds like a key.
KEY_WIDTH = re.compile(r"^0x[0-9a-fA-F]{64}$")

#: The networks a record may claim. `erc8183.py` admits two chains and a fork is
#: not a chain; anything else is a record describing a place we have not been.
NETWORKS = {"fork", "BSC mainnet", "BSC testnet", "chapel"}


def _walk(node: Any, trail: str = "") -> list[tuple[str, Any]]:
    if isinstance(node, dict):
        return [p for k, v in node.items() for p in _walk(v, f"{trail}.{k}" if trail else k)]
    if isinstance(node, list):
        return [p for i, v in enumerate(node) for p in _walk(v, f"{trail}[{i}]")]
    return [(trail, node)]


def test_there_are_records_at_all() -> None:
    """A glob that matches nothing passes every test below it."""
    assert RECORDS, f"no records under {IDENTITY.relative_to(REPO)}"


@pytest.mark.parametrize("record", RECORDS, ids=lambda p: p.name)
def test_each_record_is_a_json_object(record: Path) -> None:
    payload = json.loads(record.read_text())
    assert isinstance(payload, dict), "a list here would flatten into the artifact wrongly"
    assert payload, "an empty record publishes as an absence that is not one"


@pytest.mark.parametrize("record", RECORDS, ids=lambda p: p.name)
def test_no_record_carries_a_secret(record: Path) -> None:
    """These are published. A key in one is a key on the internet."""
    offenders = [
        f"{path} = {str(value)[:12]}…"
        for path, value in _walk(json.loads(record.read_text()))
        if SECRET_NAMES.search(path) and isinstance(value, str) and KEY_WIDTH.match(value)
    ]
    assert not offenders, f"{record.name} carries what looks like key material: {offenders}"


@pytest.mark.parametrize("record", RECORDS, ids=lambda p: p.name)
def test_a_declared_network_is_one_that_exists(record: Path) -> None:
    payload = json.loads(record.read_text())
    if "network" not in payload:
        pytest.skip(f"{record.name} makes no network claim")
    assert payload["network"] in NETWORKS, (
        f"{record.name} says network={payload['network']!r}. That field is what "
        "keeps the fork run and the mainnet run apart on /registry"
    )


@pytest.mark.parametrize("record", RECORDS, ids=lambda p: p.name)
def test_a_fork_record_never_claims_to_have_reached_mainnet(record: Path) -> None:
    """The misquote, in the one place it would be most expensive."""
    payload = json.loads(record.read_text())
    if payload.get("network") != "fork":
        pytest.skip(f"{record.name} is not a fork record")
    assert payload.get("escrowed_on_mainnet") in (False, None), (
        f"{record.name} runs on a fork and claims mainnet escrow"
    )
    assert "fork" in record.name, (
        f"{record.name} contains a fork record under a filename that does not say so"
    )


@pytest.mark.parametrize(
    "record", [p for p in RECORDS if p.name.startswith(("hire-", "refund-"))], ids=lambda p: p.name
)
def test_the_escrow_runs_share_their_grammar(record: Path) -> None:
    """The four the registry emitter publishes, which a page reads as one story."""
    payload = json.loads(record.read_text())

    assert isinstance(payload.get("job_id"), int), "a run without a job id is not a run"
    assert isinstance(payload.get("transactions"), list) and payload["transactions"], (
        "a run with no transactions recorded cannot be checked by anyone"
    )
    for step in payload["transactions"]:
        assert isinstance(step, dict) and step.get("call"), (
            f"{record.name} has a step that does not say which call it was: {step}"
        )
        # A step is either something that happened or something that refused.
        # "neither" is the state that lets a failure read as a success.
        assert (
            step.get("tx")
            or step.get("tx_hash")
            or step.get("ok") is not None
            or step.get("error")
            or step.get("reverted")
        ), f"{record.name} step {step.get('call')} records no outcome"
