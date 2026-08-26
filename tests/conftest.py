"""Test-suite safety rails.

This project signs transactions that move real capital and appends to a journal
that is submission evidence. Four fixtures make it impossible for a test to do
either by accident, and a fourth keeps the machine's own configuration out
of the results. They are autouse and unconditional: opting out is an
explicit marker on the test, visible in the source and in `-v` output, never a
default.

Ported in spirit from Mission Control's `tests/conftest.py`, which uses the same
three-fixture shape for the same reason.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

DEAD_RPC = "http://127.0.0.1:1/blackhole"


@pytest.fixture(autouse=True)
def _no_declared_wallets(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test inherits the developer's `.env`.

    `chain/operator.py` reads two variables, and both change what the write path
    and the go/no-go do. A shell with `.env` exported — which is how every
    `make` target that touches a chain is meant to be run — therefore decided
    the branch for any test that had not thought to clear *both*. The suite
    passed on a clean shell and failed on a configured one, which is the worst
    version of a test failure: it appears when someone finishes setting the
    project up.

    Cleared rather than set to a fixture value. "Nothing declared" is the
    permissive branch, so this fixture cannot mask a guard that should have
    fired; a test that wants a declaration states it, and the statement is
    visible in the test rather than inherited from the machine.
    """
    for name in ("MISQUOTE_OPERATOR_ADDRESS", "MISQUOTE_SIGNER_ADDRESS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_real_signing(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test signs a transaction unless it says so out loud.

    Opt in with `@pytest.mark.live_signing`. Everything else gets a signer whose
    send path raises, so a refactor that accidentally routes a unit test through
    the write path fails loudly instead of broadcasting.
    """
    if request.node.get_closest_marker("live_signing"):
        return

    monkeypatch.setenv("MISQUOTE_DRY_RUN", "1")

    try:
        from misquote.chain import signer as signer_mod
    except ImportError:
        return  # write path not built yet; the env guard above still holds

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(
            "this test tried to sign a transaction. Mark it @pytest.mark.live_signing "
            "if that is genuinely what you meant."
        )

    for name in ("BscSigner", "Signer"):
        cls = getattr(signer_mod, name, None)
        if cls is not None and hasattr(cls, "send"):
            monkeypatch.setattr(cls, "send", _refuse, raising=True)


@pytest.fixture(autouse=True)
def _no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every RPC at a black hole unless the test asked for a fork.

    A unit test that quietly starts hitting a public endpoint gets slow, flaky,
    and rate-limited in that order. `@pytest.mark.chainfork` is the opt-in, and
    `make fork-diff` is where those run.
    """
    if request.node.get_closest_marker("chainfork"):
        return
    for var in ("BSC_RPC_URL", "BSC_TESTNET_RPC_URL", "BSC_FORK_RPC_URL", "CEX_FEED_URL"):
        monkeypatch.setenv(var, DEAD_RPC)


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the database and the journal into a per-test directory.

    `data/journal/*.jsonl` is the tearsheet's only input and is committed to the
    repo as evidence. A test appending one synthetic row to it would corrupt a
    number a judge is meant to be able to audit.
    """
    db = tmp_path / "misquote.db"
    journal = tmp_path / "journal"
    journal.mkdir()

    monkeypatch.setenv("DB_PATH", str(db))
    monkeypatch.setenv("MISQUOTE_JOURNAL_DIR", str(journal))
    # The job store, for the same reason as the two above. Without this the
    # first job test writes `data/jobs.db` into the repository and every
    # subsequent run inherits whatever the last one queued — including, once
    # `POST /quote` exists, a real 4.6-hour replay left in `queued`.
    monkeypatch.setenv("MISQUOTE_JOBS_DB", str(tmp_path / "jobs.db"))


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def pytest_report_header(config: pytest.Config) -> list[str]:
    mode = "DRY" if os.environ.get("MISQUOTE_DRY_RUN", "1") != "0" else "LIVE"
    return [f"misquote: signing={mode} · autouse rails: no-signing, no-network, isolated-state"]


PRUNED = ("missing trie node", "required historical state unavailable", "state not available")


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Turn a pruned-state RPC error into a skip that names the cause.

    anvil forks from a public endpoint, which serves only recent state. A run
    that takes a minute can outlive the window: the node prunes the block the
    fork is pinned to and every later `eth_call` fails with `missing trie node`.
    Nothing in this repository can prevent that, and `BSC_ARCHIVE_RPC_URL` is
    exactly the knob that does.

    Reporting it as a failure would make the chain suite intermittently red for
    a reason nobody can fix, and a suite that is sometimes red for no reason
    teaches people to ignore it being red for a real one. So it is reported as
    what it is: a test that could not run.

    Deliberately narrow. Only these three phrases, all of them the node saying
    it no longer has the data — never a revert, never a gas estimate, never a
    wrong number.
    """
    outcome = yield
    report = outcome.get_result()
    # Every phase, not just `call`. A fixture that closes leftover positions
    # touches the chain too, and a pruned node fails it during *setup* — which
    # reports as an ERROR rather than a failure and slipped past the first
    # version of this hook entirely.
    if not (report.failed or report.outcome == "failed"):
        return
    text = str(getattr(call, "excinfo", "") or "")
    if any(phrase in text for phrase in PRUNED):
        report.outcome = "skipped"
        # pytest reads a skip's longrepr as (path, lineno, reason). Setting a
        # bare string here — and, worse, setting `wasxfail` — made it render as
        # XFAIL, which is a different claim: "expected to fail" says we knew the
        # code was wrong, where the truth is that the test could not run.
        reason = (
            f"{item.nodeid}: the forked node pruned the state this test needed "
            f"(during {report.when}). Set BSC_ARCHIVE_RPC_URL to a node that "
            "serves archive state and re-run.\n\n"
            "Measured: the executor module alone passes 13 of 13 in under a "
            "minute. The whole chain suite takes nine, spins up one anvil per "
            "module, and every one of them proxies its state reads to the same "
            "free endpoints — so the later modules outlive the window."
        )
        report.longrepr = (str(item.fspath), item.location[1] or 0, f"Skipped: {reason}")
        return

    # Not a phrase we recognise, so the verdict stands — converting an unknown
    # failure into a skip is how a real defect gets filed as weather.
    #
    # But it still ran against a fork of a pruning node, and the same test has
    # been observed passing alone, skipping as pruned, and failing outright on
    # three consecutive runs of this module. A note costs nothing and points at
    # the check that distinguishes the two cases; without it the natural reading
    # of a red chain suite is that the code changed.
    if item.get_closest_marker("chainfork"):
        report.sections.append(
            (
                "fork note",
                "This ran against anvil forked from a free BSC endpoint, which "
                "serves only recent state.\n"
                "If it passes in isolation (`-k <name>`) but fails in the module, "
                "suspect upstream\npruning rather than this change, and set "
                "BSC_ARCHIVE_RPC_URL to confirm.",
            )
        )
