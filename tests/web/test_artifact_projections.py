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
from misquote.tearsheet import ledger

REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO / "apps" / "web" / "public" / "artifacts"


def _load_showcase():
    """`scripts/` is not a package, so import the emitter by path."""
    spec = importlib.util.spec_from_file_location(
        "misquote_showcase_emitter", REPO / "scripts" / "showcase.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


showcase = _load_showcase()


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


def test_status_is_deliberately_not_projected() -> None:
    """A record of an execution, and the reason this file does not cover it.

    Stated as a test rather than only as prose, so that adding `status.json` to
    PROJECTIONS is a deliberate act with a failing test to argue with.
    """
    assert not any(artifact == "status.json" for artifact, _, _ in PROJECTIONS), (
        "status.json records a go/no-go run. Re-deriving it means re-running "
        "every gate, and a faked run is worth less than no test."
    )
