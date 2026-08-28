"""Where the service reads from, resolved per call rather than at import.

Every path here is read from the environment on each call, never cached in a
module constant. That is not defensiveness — it is what makes the suite honest:
`tests/conftest.py`'s `_isolate_state` redirects `DB_PATH` and
`MISQUOTE_JOURNAL_DIR` into a `tmp_path` fixture, and a module-level
`Path(os.environ[...])` would have been resolved at import, before the fixture
ran. The tests would then read the developer's real 256MB tape and the
committed journals, pass, and say nothing about the code under test.

`service.ARTIFACTS` is the older exception: it *is* a module constant, and
`tests/api/test_app.py` monkeypatches the attribute rather than the environment
to work around that. New code does not add to that pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def db_path() -> Path:
    """The indexed tape. Same spelling `go_no_go.py` and the agents use."""
    return Path(os.environ.get("DB_PATH", REPO / "data" / "misquote.db"))


def journal_dir() -> Path:
    """Where the agents append their decision journals, one JSONL per agent."""
    return Path(os.environ.get("MISQUOTE_JOURNAL_DIR", REPO / "data" / "journal"))


def artifacts_dir() -> Path:
    """Where the generated artifacts live, resolved per call.

    `service.ARTIFACTS` is the same directory as a module constant, and the
    docstring above records why that is the older pattern rather than the one to
    copy: resolved at import, it defeats `_isolate_state` and lets a test read
    the developer's real artifacts while claiming to exercise the code.

    New readers come through here. `MISQUOTE_ARTIFACTS` is honoured for the same
    reason `service` honours it — a host may bundle the directory somewhere
    other than the checkout layout.
    """
    return Path(
        os.environ.get("MISQUOTE_ARTIFACTS", REPO / "apps" / "web" / "public" / "artifacts")
    )
