"""Test-suite safety rails.

This project signs transactions that move real capital and appends to a journal
that is submission evidence. Three fixtures make it impossible for a test to do
either by accident. They are autouse and unconditional: opting out is an
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


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def pytest_report_header(config: pytest.Config) -> list[str]:
    mode = "DRY" if os.environ.get("MISQUOTE_DRY_RUN", "1") != "0" else "LIVE"
    return [f"misquote: signing={mode} · autouse rails: no-signing, no-network, isolated-state"]
