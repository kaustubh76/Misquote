"""Where an artifact field is just a Python constant, it must still equal it.

`index.json`'s `not_built` block is a copy of `tearsheet.ledger.NOT_BUILT`,
written whenever `make showcase-demo` last ran. For eleven commits it was a copy
of a *superseded* version, so the site told readers that `vetting/badges/` was
an empty directory and that the badge generator did not exist — while two
generated badges sat in that directory — and omitted two disclosures the ledger
had since added.

Nothing caught it. `tests/web/test_ledger.py` checks `ledger.py` against the
filesystem, which was passing and correct. Nobody checked the artifact against
`ledger.py`.

## The rule this file encodes

Assert parity wherever an artifact field is a **projection**: a Python constant,
or a pure function cheap enough to call in a test. Never where the field is the
**record of an execution**.

`status.json` is the clear exclusion. Re-deriving it means re-running every
readiness gate — subprocesses, a test suite, a chain — so a parity test would
either take minutes or fake the run, and a faked run is worth less than no test.
The agent artifacts' numeric content is the same kind of thing: a thirty-minute
replay. Their *schema* is covered by `test_artifact_contract.py`, which is the
right split.

The cost of this file is real and worth stating: once it exists, every edit to
`ledger.py` needs `make showcase-demo` in the same commit. That is the guard
working. The alternative is what we had.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from misquote.chain.addresses import TARGET_POOL
from misquote.registry import erc8004, erc8183
from misquote.tearsheet import ledger, pools, vectors

REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO / "apps" / "web" / "public" / "artifacts"


def _script(name: str, module_name: str):
    """`scripts/` is not a package, so import an emitter by path."""
    spec = importlib.util.spec_from_file_location(module_name, REPO / "scripts" / name)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


showcase = _script("showcase.py", "misquote_showcase_emitter")
assumptions = _script("assumptions.py", "misquote_assumptions_emitter")
venue = _script("venue_report.py", "misquote_venue_emitter")


def dotted(document: Any, path: str) -> Any:
    for part in path.split("."):
        document = document[part]
    return document


def as_json(value: Any) -> Any:
    """What the value looks like once it has been through JSON.

    Chain-id maps are keyed by int in Python and by string in the artifact,
    because JSON has no integer keys. Comparing the two raw reports a mismatch
    on every such map while the addresses agree exactly — a guard that cries
    about serialisation is one people learn to skip.
    """
    return json.loads(json.dumps(value, sort_keys=True, default=str))


# (artifact, dotted field, what it is a projection of)
PROJECTIONS: tuple[tuple[str, str, Callable[[], Any]], ...] = (
    ("index.json", "not_built", ledger.to_dicts),
    ("index.json", "badge", lambda: showcase.COUNTERFACTUAL_BADGE),
    ("index.json", "pool", lambda: TARGET_POOL.label),
    ("index.json", "pool_address", lambda: TARGET_POOL.address),
    ("registry.json", "hire_flow.transaction_count", erc8183.transaction_count),
    ("registry.json", "hire_flow.client_transaction_count", erc8183.client_transaction_count),
    ("registry.json", "hire_flow.states", lambda: list(erc8183.STATES)),
    ("registry.json", "hire_flow.terminal_states", lambda: list(erc8183.TERMINAL)),
    ("registry.json", "identity.identity_registry", lambda: erc8004.IDENTITY_REGISTRY),
    ("registry.json", "identity.reputation_note", lambda: erc8004.REPUTATION_IS_NOT_DISPLAYED),
    # The whole corpus block: case counts, seeds, digests and the upstream
    # commits. A pure function of files on disk, which is what makes it
    # assertable — and what makes it worth asserting, since `make vectors` can
    # regenerate those files and leave the published counts describing a corpus
    # that no longer exists.
    ("vectors.json", "corpus", vectors.corpus),
    # `venue.json` is a projection end to end — it reads no chain, no database
    # and no recorded run, so every field is re-derivable in a test. The whole
    # payload is compared below; these three are named separately because they
    # are the figures a reader would quote, and a diff of the entire document
    # says "something moved" where these say what.
    ("venue.json", "fee_overstatement", lambda: venue.fee_overstatement(TARGET_POOL.fee_protocol)),
    (
        "venue.json",
        "unmintable_remainder",
        lambda: venue.unmintable_remainder(TARGET_POOL.tick_spacing),
    ),
    ("venue.json", "divergences", venue.divergences),
    # `pools.json` is **not** a projection end to end — it reads the indexed tape,
    # so its bands cannot be re-derived without one. The ladder can: it is a
    # module constant, and it is the field a reader would check first, because a
    # ladder that quietly stopped bracketing A18's floor and A19's ceiling would
    # turn the width comparison into one that cannot disagree with them.
    ("pools.json", "width_ladder", lambda: list(pools.WIDTH_LADDER)),
)


@pytest.mark.parametrize(
    "artifact,field,derive", PROJECTIONS, ids=[f"{a}:{f}" for a, f, _ in PROJECTIONS]
)
def test_the_artifact_still_matches_what_it_projects(
    artifact: str, field: str, derive: Callable[[], Any]
) -> None:
    path = ARTIFACTS / artifact
    if not path.exists():
        pytest.skip(f"no {artifact}; run `make artifacts`")

    published = dotted(json.loads(path.read_text()), field)
    expected = as_json(derive())

    assert published == expected, (
        f"{artifact}:{field} no longer matches the Python it is a copy of. "
        "The Python is the source — regenerate the artifact in the same commit "
        "as the change that moved it (`make artifacts`, or the one emitter that "
        "writes this file)."
    )


def test_the_ledger_parity_is_ordered_not_just_set_equal() -> None:
    """Order is rendered, so order is part of the claim.

    `LedgerTable` and the Overview both map over `not_built` in artifact order.
    A set comparison would let the disclosures silently reshuffle.
    """
    path = ARTIFACTS / "index.json"
    if not path.exists():
        pytest.skip("no index.json")

    published = json.loads(path.read_text())["not_built"]
    assert [entry["name"] for entry in published] == [e.name for e in ledger.NOT_BUILT]


def test_the_published_assumption_sheet_still_matches_its_sources() -> None:
    """The whole sheet, re-derived from the two documents it is made of.

    Its own line entry above would not be enough: the failure was not one field
    drifting but the entire artifact freezing while `docs/REQUIREMENTS_MATRIX.md`
    moved underneath it. `P-10` and `P-11` were missing outright, and every
    matrix line number rendered on the page was wrong — `P-9` published as
    `:435` while sitting at 578, `P-6` as `:587` while sitting at 750. Those
    render as precise source citations, `docs/REQUIREMENTS_MATRIX.md:435`, which
    is exactly the kind of number a reader goes and checks.

    Qualifies under this file's rule because re-deriving it is two markdown
    files parsed and a directory of small JSON globbed — milliseconds, and
    already factored out as `build_payload` so this test calls the emitter
    rather than a copy of it.

    The cost is the same one the module docstring already states: an edit to
    either source document needs `make assumptions` in the same commit. That is
    the guard working, and the alternative is a page confidently citing line
    numbers that moved months ago.
    """
    path = ARTIFACTS / "assumptions.json"
    if not path.exists():
        pytest.skip("no assumptions.json; run `make assumptions`")

    published = json.loads(path.read_text())
    expected = as_json(
        assumptions.build_payload(
            REPO / "docs" / "ASSUMPTIONS.md",
            REPO / "docs" / "REQUIREMENTS_MATRIX.md",
            ARTIFACTS,
        )
    )

    # Ids first. A whole-payload mismatch prints two 80KB documents, and the
    # question a reader has is almost always "which entry moved".
    assert [e["id"] for e in published["entries"]] == [e["id"] for e in expected["entries"]], (
        "the published sheet no longer holds the same entries as its sources — "
        "run `make assumptions`"
    )
    moved = [
        e["id"]
        for e, w in zip(published["entries"], expected["entries"], strict=True)
        if (e["source"], e["line"]) != (w["source"], w["line"])
    ]
    assert not moved, f"these entries cite a source line they have moved away from: {moved}"

    assert published == expected, (
        "assumptions.json no longer matches what the emitter derives from "
        "docs/ASSUMPTIONS.md and docs/REQUIREMENTS_MATRIX.md. The documents are "
        "the source — regenerate in the same commit that edits them "
        "(`make assumptions`)."
    )


def test_status_is_deliberately_not_projected() -> None:
    """A record of an execution, and the reason this file does not cover it.

    Stated as a test rather than only as prose, so that adding `status.json` to
    PROJECTIONS is a deliberate act with a failing test to argue with.
    """
    assert not any(artifact == "status.json" for artifact, _, _ in PROJECTIONS), (
        "status.json records a go/no-go run. Re-deriving it means re-running "
        "every gate, and a faked run is worth less than no test."
    )


def test_the_vector_verification_is_deliberately_not_projected() -> None:
    """The corpus is asserted above. Whether it still replays is not.

    `vectors.json` carries both halves on purpose, and only one of them belongs
    here. The corpus is files on disk. The verification is the outcome of
    `pytest tests/core/test_vectors.py`, and there is no way to re-derive it
    that is not simply running the suite again — inside a test, from a test
    about that suite.

    Worth stating as a test rather than only in prose, because the two blocks
    sit side by side in one artifact and the obvious next edit is to widen the
    entry above from `corpus` to the whole document. That would either make
    this file spawn a pytest subprocess or, far worse, quietly assert that a
    recorded PASS equals a recorded PASS — which proves the file can be read.

    The staleness question that *does* matter is handled where it can be:
    `vectors_report.py` re-digests the corpus at publish time and compares it
    against what the receipt says it replayed, so a receipt that has been
    invalidated reports as stale instead of as a pass.
    """
    projected = [field for artifact, field, _ in PROJECTIONS if artifact == "vectors.json"]
    assert projected == ["corpus"], (
        f"vectors.json should project its corpus and nothing else, got {projected}. "
        "The verification block is the outcome of a test run."
    )


def test_the_whole_venue_artifact_is_re_derivable() -> None:
    """Not a field at a time — the entire document, minus its build stamp.

    `venue.json` earns this because it reads nothing external: no chain, no
    database, no recorded run. Every value in it is a constant or a pure
    function of one, so there is no reason to assert a subset and a good reason
    not to — the page it feeds is an argument that the details were got right,
    and a page like that cannot afford a figure that drifted from the code it
    describes.

    The build stamp is excluded because it carries a timestamp and a git sha,
    which are the two things that are *supposed* to differ between runs.
    """
    path = ARTIFACTS / "venue.json"
    if not path.exists():
        pytest.skip("no venue.json; run `make venue`")

    published = json.loads(path.read_text())
    published.pop("build", None)

    assert published == as_json(venue.build_payload()), (
        "venue.json no longer matches `scripts/venue_report.py`. Every field in "
        "it is derived from a Python constant or a pure function, so this means "
        "the constant moved and the artifact did not — run `make venue`."
    )
