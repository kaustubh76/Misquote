"""The four published records, and the absence that used to be unpublishable.

`registry_report.py` reads `vetting/identity/*.json` into the registry artifact:
the chapel run, the fork proof, the mainnet run, and the refund. Each had a
fallback for the file not being there, each fallback read well, and **none of
them could be published**.

`{"ran": False, "reason": ...}` is two keys. The contract in
`tests/web/test_artifact_contract.py` declares between seventeen and twenty-four
per record, and `reason` was not among them. So on any machine without the
record files — a fresh clone that has never run `make prove-escrow` — the
emitter produced a payload that failed the contract in both directions at once:
fifteen fields undelivered and one undeclared. The honest-absence branch was
unreachable in practice and nothing said so, because no test ever called these
functions. This file calls them.

The load-bearing assertion is `test_an_absent_record_satisfies_the_contract`:
absence must carry every key presence carries. Everything else here is a
consequence of that.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    """By path, because neither `scripts/` nor `tests/` is a package."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


registry_report = _load("registry_report", REPO / "scripts" / "registry_report.py")
contract = _load("artifact_contract", REPO / "tests" / "web" / "test_artifact_contract.py")

#: Each helper, the path constants it consults, and the artifact key it fills.
RECORDS = (
    ("_hire_proof", ("HIRE_PROOF_PATH",), "proof"),
    ("_hire_fork_proof", ("HIRE_FORK_PATH",), "fork_proof"),
    ("_hire_mainnet_proof", ("HIRE_MAINNET_PATH",), "mainnet_proof"),
    ("_refund_proof", ("REFUND_MAINNET_PATH", "REFUND_FORK_PATH"), "refund_proof"),
)


def _absent(monkeypatch: pytest.MonkeyPatch, paths: tuple[str, ...]) -> None:
    for name in paths:
        monkeypatch.setattr(registry_report, name, Path("/nonexistent/never-written.json"))


def _declared_for(key: str) -> set[str]:
    prefix = f"hire_flow.{key}."
    return {
        path[len(prefix) :]
        for path in contract.REGISTRY_FIELDS
        if path.startswith(prefix)
    }


def _delivered(payload: dict[str, Any]) -> set[str]:
    """The leaves this payload contributes, flattened the way the contract is."""
    out: set[str] = set()

    def walk(node: Any, trail: str) -> None:
        if isinstance(node, dict) and node:
            for name, value in node.items():
                walk(value, f"{trail}.{name}" if trail else name)
        else:
            out.add(trail)

    walk(payload, "")
    return out


@pytest.mark.parametrize(("helper", "paths", "key"), RECORDS)
def test_an_absent_record_satisfies_the_contract(
    monkeypatch: pytest.MonkeyPatch, helper: str, paths: tuple[str, ...], key: str
) -> None:
    """The bug this file exists for: an absence must be publishable.

    Not "must look reasonable" — must carry exactly the leaves the artifact
    contract declares, because `make registry` on a machine without the record
    files has to produce something the test suite accepts.
    """
    _absent(monkeypatch, paths)
    payload = getattr(registry_report, helper)()

    assert payload["ran"] is False
    assert payload["reason"], "an absence that does not say why is not an honest one"

    missing = _declared_for(key) - _delivered(payload)
    assert not missing, (
        f"{helper}() with no record on disk delivers none of {sorted(missing)}, "
        f"which the contract declares — this is the shape that could not be published"
    )


@pytest.mark.parametrize(("helper", "paths", "key"), RECORDS)
def test_absence_and_presence_are_the_same_shape(
    monkeypatch: pytest.MonkeyPatch, helper: str, paths: tuple[str, ...], key: str
) -> None:
    """A consumer must not have to ask which branch produced its dict."""
    present = set(getattr(registry_report, helper)())
    _absent(monkeypatch, paths)
    absent = set(getattr(registry_report, helper)())
    assert present == absent, (
        f"{helper}() changes shape depending on whether the file exists: "
        f"only-when-present {sorted(present - absent)}, "
        f"only-when-absent {sorted(absent - present)}"
    )


@pytest.mark.parametrize(("helper", "paths", "key"), RECORDS)
def test_a_record_on_disk_is_reported_as_run(
    helper: str, paths: tuple[str, ...], key: str
) -> None:
    """`ran` is set here rather than trusted to the writer.

    It used to be trusted, and unevenly: `_hire_proof` patched it in while its
    three siblings did not, which worked only because three writers happened to
    set it and one did not. `hire-97.json` still has no `ran` of its own.
    """
    if not any(getattr(registry_report, name).is_file() for name in paths):
        pytest.skip(f"no record on disk for {helper}")

    payload = getattr(registry_report, helper)()
    assert payload["ran"] is True
    assert payload["reason"] is None
    assert (REPO / payload["record"]).is_file(), (
        "the published `record` must name the file the contents came from"
    )


@pytest.mark.parametrize(("helper", "paths", "key"), RECORDS)
def test_an_unreadable_record_is_an_absence_and_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    helper: str,
    paths: tuple[str, ...],
    key: str,
) -> None:
    broken = tmp_path / "half-written.json"
    broken.write_text('{"ran": true, "job_id":')  # a run killed mid-write
    for name in paths:
        monkeypatch.setattr(registry_report, name, broken)

    payload = getattr(registry_report, helper)()
    assert payload["ran"] is False
    assert "could not be read" in payload["reason"]
    assert not (_declared_for(key) - _delivered(payload))


def test_the_refund_never_claims_mainnet_from_a_fork_file() -> None:
    """The check nothing made, on the distinction this project is named for.

    `_refund_proof` prefers `refund-56.json` over `refund-fork-56.json`, and
    publishes whichever it finds with the file's own `network` field. Copy the
    fork record onto the mainnet filename and the page reads "refund, on BSC
    mainnet" with nothing objecting. The two facts have to agree.
    """
    payload = registry_report._refund_proof()
    if not payload["ran"]:
        pytest.skip("no refund record on disk")

    from_mainnet_file = payload["record"].endswith("refund-56.json")
    says_fork = payload["network"] == "fork"
    assert from_mainnet_file != says_fork, (
        f"{payload['record']} declares network={payload['network']!r}. A record in "
        "the mainnet filename may not say 'fork', and one in the fork filename may "
        "not say anything else"
    )


def test_every_deployment_is_one_the_registry_verified() -> None:
    """The addresses a browser is handed to send money to.

    They reach the UI as artifact data so there is one source of truth. That is
    only worth anything if the emitter cannot invent an entry `erc8183.py` has
    not admitted.
    """
    from misquote.registry import erc8183

    deployments = registry_report._deployments()
    assert deployments, "the console has no addresses to offer on any chain"

    for chain, entry in deployments.items():
        assert str(entry["chain_id"]) == chain, "keyed by a chain it does not describe"
        verified = erc8183.contracts_for(int(chain))
        for role, address in verified.items():
            assert entry[role] == address, f"chain {chain} {role} disagrees with erc8183.py"
        assert entry["explorer"].startswith("https://"), chain
        assert entry["name"], chain

    assert set(deployments) == {str(c) for c in erc8183.JOB_ESCROW}, (
        "every verified deployment is offered, and nothing else is"
    )
