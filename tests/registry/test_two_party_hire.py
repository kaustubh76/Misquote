"""The provider is somebody else, and a test that says so.

Every hire this repository has recorded — chapel 746, mainnet 56681 and 56718,
and every fork rehearsal — puts **one address in both the client and the provider
column**. Not because that is the product: `hire_mainnet.py` hardcoded
`provider=signer.address` with the comment "client and provider, so settle
returns it", and `BscSigner` could only reach `MISQUOTE_PRIVATE_KEY`, so the one
wallet whose key lives in a keystore could not sign at all.

A marketplace whose only proven delivery is the buyer delivering to themselves is
the misquote this project is named after, applied to its own escrow. So the
distinctness is the claim, and a claim that is only *displayed* is one the next
reader can misread — which is the failure `studio.json`'s delivery entry made
three times running, each time by recording a blocker one level above the real
one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RECORDS = REPO / "vetting" / "identity"

#: Records that are hires. A file that stops being one should fail loudly here
#: rather than be skipped into silence.
HIRES = ("hire-mainnet-56.json", "hire-mainnet-56-submitted.json", "hire-97.json")


def _load(name: str) -> dict | None:
    path = RECORDS / name
    if not path.exists():
        return None
    return json.loads(path.read_text())


#: `hire_agent.py` writes no `provider` at all, so the chapel record cannot say
#: who was hired — only who paid. Named here rather than quietly tolerated: it is
#: a real gap in that record, it is the older runner's, and the point of writing
#: it down is that the omission must not spread to the mainnet ones.
NAMES_NO_PROVIDER = frozenset({"hire-97.json"})


@pytest.mark.parametrize("name", HIRES)
def test_every_hire_record_names_both_parties(name: str) -> None:
    """Both fields exist and are addresses, whoever they turn out to be."""
    record = _load(name)
    if record is None:
        pytest.skip(f"{name} has not been run")

    roles = ("client",) if name in NAMES_NO_PROVIDER else ("client", "provider")
    for role in roles:
        value = record.get(role)
        assert isinstance(value, str) and value.startswith("0x") and len(value) == 42, (
            f"{name} does not record a {role} address; a hire with an unnamed party "
            f"cannot be checked for the thing this file exists to check"
        )

    # The exemption has to keep earning itself. If `hire_agent.py` ever starts
    # recording a provider, this allowlist is stale and should shrink rather than
    # sit here excusing a record that no longer needs excusing.
    if name in NAMES_NO_PROVIDER:
        assert record.get("provider") is None, (
            f"{name} now records a provider, so it no longer belongs in "
            f"NAMES_NO_PROVIDER — remove it and let the assertion above cover it"
        )


def test_a_two_party_record_really_has_two_parties() -> None:
    """`two_party: true` has to mean the addresses differ.

    Asserted rather than displayed. `hire_flow` renders five proof blocks and a
    reader comparing two 42-character strings across them will not notice that
    they are the same one — which is exactly how a self-hire came to be published
    for weeks as evidence of hiring.
    """
    claimed = {
        name: record
        for name in HIRES
        if (record := _load(name)) is not None and record.get("two_party")
    }
    for name, record in claimed.items():
        assert record["client"].lower() != record["provider"].lower(), (
            f"{name} claims two_party and names one address twice: {record['client']}"
        )

    # Not a bare `assert claimed` — no two-party hire has been run yet, and a
    # test that fails until one is would be red for a reason unrelated to the
    # code. What it must not do is pass while a record claims the property and
    # contradicts it, which is what the loop above catches.
    if not claimed:
        pytest.skip("no two-party hire on record yet")


def test_a_deliverable_that_claims_a_file_commits_to_that_file() -> None:
    """The hash on chain has to be the hash of the thing it names.

    `submit`'s 32 bytes are opaque — `hire.py` says so: "nothing on chain
    interprets it, so this does not pretend to". That makes the commitment worth
    exactly as much as the record tying it to a file, and worth nothing if the
    two ever drift.
    """
    from web3 import Web3

    checked = 0
    for name in HIRES:
        record = _load(name)
        if record is None or not record.get("deliverable"):
            continue
        note = record["deliverable"]
        path = REPO / note["file"]
        if not path.exists():
            pytest.fail(
                f"{name} commits to {note['file']}, which is not in the repository. "
                f"A hash of a file nobody can fetch is a hash of nothing."
            )
        blob = path.read_bytes()
        assert len(blob) == note["bytes"], (
            f"{name}'s deliverable is {len(blob)} bytes and the record says "
            f"{note['bytes']} — the file has changed since it was committed to"
        )
        assert Web3.keccak(blob).hex() == note["keccak256"], (
            f"{name}'s recorded hash is not the hash of {note['file']} as it "
            f"stands now. The on-chain commitment is to the old bytes."
        )
        checked += 1

    if not checked:
        pytest.skip("no hire has committed to a file yet")
