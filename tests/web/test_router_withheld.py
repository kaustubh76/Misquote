"""The Router card when there is no rate tape, and why it must still be a card.

`artifacts:` lists `router-card`, and the emitter used to `return 1` when fewer
than two Venus markets had accruals. On a clean checkout that stopped the whole
chain: no advantage report, no registry, no assumptions, no judges, no status.
`showcase-auto` degrades to a labelled synthetic tape in the same situation; this
had no fallback, and a *fabricated* lending tape is the one thing this repo will
not produce.

So it publishes its own refusal instead. The tests here pin the two things that
went wrong when it did:

1. it must exit 0 and still register in the index, or the fourth category
   silently disappears — which this repo has already shipped once;
2. it must carry **exactly** the same field set as the quoted card, or a clean
   checkout emits an artifact that fails `test_artifact_contract`. That happened
   on the first attempt, and it is invisible on any machine that has a tape.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EMITTER = REPO / "scripts" / "router_showcase.py"
REAL = REPO / "apps" / "web" / "public" / "artifacts" / "router.json"


def flatten(obj: object, prefix: str = "") -> set[str]:
    """Dotted leaf paths, the same shape `test_artifact_contract.flatten` uses."""
    out: set[str] = set()
    if isinstance(obj, dict):
        if not obj:
            return {prefix} if prefix else set()
        for key, value in obj.items():
            out |= flatten(value, f"{prefix}.{key}" if prefix else key)
    else:
        out.add(prefix)
    return out


@pytest.fixture(scope="module")
def withheld(tmp_path_factory) -> dict:
    """Run the real emitter against a database with no accruals."""
    work = tmp_path_factory.mktemp("withheld")
    db = work / "notape.db"

    from misquote.indexer import store

    conn = store.connect(str(db))
    conn.close()

    out = work / "artifacts"
    out.mkdir()
    # The emitter merges into an existing index; give it one to merge into.
    (out / "index.json").write_text(json.dumps({"agents": [], "not_built": []}) + "\n")

    result = subprocess.run(
        [sys.executable, str(EMITTER), "--db", str(db), "--out", str(out)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, (
        "the emitter exited non-zero with no rate tape, which is what stopped "
        f"`make artifacts` completing on a clean checkout:\n{result.stdout}\n{result.stderr}"
    )
    card = json.loads((out / "router.json").read_text())
    card["_index"] = json.loads((out / "index.json").read_text())
    return card


def test_it_refuses_rather_than_quoting(withheld: dict) -> None:
    assert withheld["quote"]["sufficient"] is False
    note = withheld["quote"]["note"]
    assert "make venus" in note, f"the refusal does not name the command that fixes it: {note!r}"


def test_the_fourth_category_still_appears(withheld: dict) -> None:
    """A withheld card that nothing lists is the same disappearance as no card."""
    slugs = [a.get("slug") for a in withheld["_index"]["agents"]]
    assert "router" in slugs, f"Router is not in the index: {slugs}"


def test_it_carries_exactly_the_quoted_card_s_fields(withheld: dict) -> None:
    """The assertion that would have caught the original break.

    The withheld payload is built from literals while the quoted one is built
    from `AllocationQuote.to_dict()` and the driver's result. They agree only
    because someone keeps them in step by hand, and nothing but this notices
    when they stop.
    """
    if not REAL.exists():
        pytest.skip("no quoted card to compare against; run `make router-card`")

    quoted = flatten(json.loads(REAL.read_text()))
    refused = flatten({k: v for k, v in withheld.items() if k != "_index"})

    missing = quoted - refused
    extra = refused - quoted
    assert not missing, (
        "the withheld card omits fields the quoted one publishes, so a clean "
        f"checkout emits an artifact that fails its own contract: {sorted(missing)}"
    )
    assert not extra, f"the withheld card publishes fields the quoted one does not: {sorted(extra)}"


def test_it_records_no_tape_rather_than_a_zero_length_one(withheld: dict) -> None:
    """`source` must not claim a tape it never read."""
    assert withheld["source"] == "none"
    assert withheld["replay"]["hours"] == 0.0
