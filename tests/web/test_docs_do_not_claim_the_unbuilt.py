"""No document may claim, in the present tense, a capability the ledger denies.

`Readme.md` said Router was **"Deployed via BNB Agent Studio CLI
(native-citizenship proof)"** while `tearsheet/ledger.py` listed that exact
deployment as not built, and `Readme.md` itself contradicted the claim again
two hundred lines further down. Three statements, two of them wrong, and the
whole suite green — because nothing read the prose against the ledger.

That is the failure this repository is named for, committed against itself, and
it survived for weeks in the first document anybody opens.

The check is deliberately narrow. It cannot understand English, so it does not
try: each entry contributes a short phrase that would only appear in a sentence
asserting the thing exists, and the phrase is asserted absent unless the same
line also carries a qualifier. What that catches is the specific shape that got
through — a bare boast in a bullet list.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Documents a judge reads. Not the ledger itself, and not the matrix, which is
#: a record of corrections and quotes wrong claims on purpose in order to
#: correct them.
DOCS = ("Readme.md", "docs/FOR_JUDGES.md")

#: A phrase that only appears in a sentence claiming the capability is real,
#: paired with the ledger entry that says it is not.
BOASTS = {
    "Deployed via BNB Agent Studio CLI": "Agent Studio deployment",
    "deployed through the Agent Studio": "Agent Studio deployment",
}

#: Words that turn a claim into a description of a claim. A line carrying one is
#: discussing the capability rather than asserting it.
QUALIFIERS = re.compile(
    r"\bnot\b|\bnever\b|\bis open\b|\bwould\b|\bnot done\b|\bnot built\b|"
    r"\bon the ledger\b|\bopen\b|\bunbuilt\b",
    re.IGNORECASE,
)


@pytest.mark.parametrize("document", DOCS)
def test_no_document_boasts_of_something_the_ledger_denies(document: str) -> None:
    import sys

    sys.path.insert(0, str(REPO / "packages"))
    from misquote.tearsheet import ledger

    unbuilt = {entry.name for entry in ledger.NOT_BUILT}
    text = (REPO / document).read_text()

    offenders: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for phrase, entry in BOASTS.items():
            if phrase.lower() not in line.lower():
                continue
            if entry not in unbuilt:
                continue  # it got built; the boast is now true
            if QUALIFIERS.search(line):
                continue
            offenders.append(f"{document}:{number} claims {phrase!r}, which '{entry}' denies")

    assert not offenders, (
        "a document asserts a capability the ledger lists as not built: "
        f"{offenders}. Either build it and remove the ledger entry, or say what "
        "is true — this is the mistake the project is named after, made about "
        "ourselves"
    )


#: Where each ledger entry is disclosed to a judge, in that document's own words.
#:
#: A map rather than a name match. `FOR_JUDGES.md` is prose and the ledger holds
#: dataclass names; requiring the two to use identical strings would push the
#: prose around to satisfy a test, which is the wrong direction. What this
#: catches instead is a *new* ledger entry with nowhere to point — the state the
#: Agent Studio deployment was in, sitting at `not_built[0]` in the JSON the site
#: renders and absent from the judges' document entirely.
DISCLOSED_AS = {
    "Agent Studio deployment": "Agent Studio deployment",
    # Was "Releasing an escrowed job on mainnet" until `submit` mined on job
    # 56718. Release is half done and the entry says which half.
    "ERC-8183 escrow": "Settling an escrowed job on mainnet",
    "Signing on mainnet": "mainnet is refused in code",
    "Altana session keys: the caps": "Session keys are half built",
    "Vetting proof-of-concepts: the five readings": (
        "Five of the nine badge checks have no executable proof-of-concept"
    ),
}


def test_every_unbuilt_entry_is_disclosed_to_a_judge() -> None:
    """A gap a judge cannot find is not disclosed, whatever the artifact says."""
    import sys

    sys.path.insert(0, str(REPO / "packages"))
    from misquote.tearsheet import ledger

    judges = (REPO / "docs" / "FOR_JUDGES.md").read_text().lower()
    names = {entry.name for entry in ledger.NOT_BUILT}

    unmapped = names - set(DISCLOSED_AS)
    assert not unmapped, (
        f"these ledger entries name no passage in FOR_JUDGES.md: {sorted(unmapped)}. "
        "Add the disclosure, then map it here — an entry the site publishes as "
        "not built and the judges' document never mentions is a gap that is only "
        "disclosed to whoever opens the JSON"
    )

    stale = sorted(set(DISCLOSED_AS) - names)
    assert not stale, f"these are mapped and no longer on the ledger: {stale}"

    missing = [
        f"{name} -> {phrase!r}"
        for name, phrase in DISCLOSED_AS.items()
        if phrase.lower() not in judges
    ]
    assert not missing, f"the disclosure these point at is gone from FOR_JUDGES.md: {missing}"
