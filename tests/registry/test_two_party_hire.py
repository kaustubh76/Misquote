"""The provider is somebody else, and a test that says so.

**On mainnet**, every hire this repository has recorded puts one address in both
the client and the provider column — 56681 and 56718 both. Not because that is
the product: `hire_mainnet.py` hardcoded `provider=signer.address` with the
comment "client and provider, so settle returns it", and `BscSigner` could only
reach `MISQUOTE_PRIVATE_KEY`, so the one wallet whose key lives in a keystore
could not sign at all.

The first version of this docstring said "and every fork rehearsal", and that was
wrong in the flattering direction — the correction belongs here rather than in a
git message nobody reads twice. `prove_escrow_fund.py` has driven two genuinely
distinct parties since it was written: anvil's account 0 funds, account 1 submits,
and `settled` is true. So the *mechanism* is proven and only the mainnet record
is not, which is a narrower and more useful claim than the one I made.

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
HIRES = (
    "hire-mainnet-56.json",
    "hire-mainnet-56-submitted.json",
    "hire-97.json",
    # The one that already has two parties, included so the suite has a positive
    # case and not only an absence. It is a fork and says so; what it proves is
    # the mechanism, not that money moved between strangers.
    "hire-fork-56.json",
)


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


def _two_parties(record: dict) -> bool:
    """Two distinct addresses, judged by the addresses and not by a label.

    The flag is only written by today's `hire_mainnet.py`; `hire-fork-56.json`
    predates it and has had two genuinely distinct parties since it was written.
    Keying off the label would have made this suite skip past its only positive
    case while reporting "no two-party hire on record" — a guard declaring the
    absence of the very thing sitting next to it.
    """
    client, provider = record.get("client"), record.get("provider")
    return bool(client and provider and client.lower() != provider.lower())


def test_the_two_party_flag_agrees_with_the_addresses() -> None:
    """A record claiming `two_party` must name two, and vice versa.

    Asserted rather than displayed. `hire_flow` renders five proof blocks and a
    reader comparing two 42-character strings across them will not notice that
    they are the same one — which is exactly how a self-hire came to be published
    as evidence of hiring.
    """
    for name in HIRES:
        record = _load(name)
        if record is None or "two_party" not in record:
            continue
        assert record["two_party"] == _two_parties(record), (
            f"{name} says two_party={record['two_party']} while naming "
            f"client={record.get('client')} and provider={record.get('provider')}"
        )


def test_the_flow_has_been_driven_by_two_distinct_parties() -> None:
    """Somewhere, a provider that is not the buyer has submitted.

    `prove_escrow_fund.py` does this on every run — anvil's account 0 funds and
    account 1 submits — so the mechanism is proven even though no *mainnet*
    record has ever shown it. That distinction is the honest one, and it is the
    one the first version of this file got wrong in the flattering direction.
    """
    two_party = {name: r for name in HIRES if (r := _load(name)) and _two_parties(r)}
    assert two_party, (
        "no record anywhere names a client and a provider that differ, so nothing "
        "here demonstrates hiring somebody else. `make prove-escrow` writes one."
    )

    # And at least one of them got the money to the other end.
    settled = [name for name, r in two_party.items() if r.get("settled")]
    assert settled, (
        f"two parties appear in {sorted(two_party)} and none of those runs settled, "
        f"so the provider was named but never paid"
    )


def test_no_mainnet_hire_has_two_parties_yet() -> None:
    """The gap, asserted so it cannot close silently.

    This is the one that should start failing. When a mainnet run finally names a
    provider that is not the buyer, this test breaks and has to be deleted — which
    is the right direction for a test whose whole subject is an absence, and the
    opposite of the ledger entry that stayed true three times while describing the
    wrong floor.
    """
    mainnet = {
        name: r
        for name in ("hire-mainnet-56.json", "hire-mainnet-56-submitted.json")
        if (r := _load(name)) is not None
    }
    for name, record in mainnet.items():
        assert not _two_parties(record), (
            f"{name} now names two distinct parties on mainnet. That is the thing "
            f"this repository wanted; delete this test and say so on /registry."
        )


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
