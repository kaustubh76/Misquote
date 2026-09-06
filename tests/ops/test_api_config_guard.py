"""The one command that could dark-site the whole site, and the value it kept.

`make artifacts` runs `api-config` unconditionally, nothing in the build loads
`.env`, and `MISQUOTE_API_BASE` is not in `.env.example` — so a rebuild without
the variable inline wrote `base: null` over a working base, and every live
feature went dark with no error and no failing test. Commit `840b3dd` is that
happening; it was found by someone looking at the site.

The fix is small and the tests are the point of it: an empty base keeps what is
already published, `--allow-null` is how you mean it, and a fresh clone with no
`api.json` still publishes null without complaint — because null is a valid
answer and this is not a validity check. It is a refusal to lose a value that
nothing else in the build remembers.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "emit_api_config", REPO / "scripts" / "emit_api_config.py"
)
assert _spec and _spec.loader
emit = importlib.util.module_from_spec(_spec)
sys.modules["emit_api_config"] = emit
_spec.loader.exec_module(emit)

LIVE = "https://misquote-api.example"


def _published(out: Path) -> str | None:
    return json.loads((out / "api.json").read_text())["base"]


def _seed(out: Path, base: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "api.json").write_text(json.dumps(emit.config(base), indent=2, sort_keys=True) + "\n")


def test_an_unset_variable_keeps_the_base_that_is_already_published(tmp_path: Path) -> None:
    """The regression itself. Unset is an omission, not an instruction."""
    _seed(tmp_path, LIVE)

    assert emit.main(["--base", "", "--out", str(tmp_path)]) == 0
    assert _published(tmp_path) == LIVE


def test_the_kept_base_is_said_out_loud(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Keeping a value silently is its own way to be wrong later."""
    _seed(tmp_path, LIVE)
    emit.main(["--base", "", "--out", str(tmp_path)])

    printed = capsys.readouterr().out
    assert LIVE in printed
    assert "--allow-null" in printed, "a refusal that does not name its override is a wall"


def test_allow_null_blanks_it(tmp_path: Path) -> None:
    """Dark-siting stays possible, as one flag and a decision."""
    _seed(tmp_path, LIVE)

    assert emit.main(["--base", "", "--out", str(tmp_path), "--allow-null"]) == 0
    assert _published(tmp_path) is None


def test_a_fresh_clone_publishes_null_without_complaint(tmp_path: Path) -> None:
    """Null is the ordinary state of this file and not an error.

    Every page renders from the artifacts alone. A first `make artifacts` on a
    machine that has never had a backend must not fail, or the guard has cost
    more than the bug did.
    """
    assert emit.main(["--base", "", "--out", str(tmp_path)]) == 0
    assert _published(tmp_path) is None


def test_an_explicit_base_always_wins(tmp_path: Path) -> None:
    """Including one that replaces another — this guards absence, not change."""
    _seed(tmp_path, LIVE)

    assert emit.main(["--base", "https://elsewhere.example", "--out", str(tmp_path)]) == 0
    assert _published(tmp_path) == "https://elsewhere.example"


def test_an_unreadable_published_file_is_not_a_value_to_keep(tmp_path: Path) -> None:
    """A half-written `api.json` has no base in it, and must not stop the build."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "api.json").write_text('{"base": "https://tru')

    assert emit.main(["--base", "", "--out", str(tmp_path)]) == 0
    assert _published(tmp_path) is None


def test_the_committed_artifact_has_the_base_this_guard_exists_to_protect() -> None:
    """If this is null, the site in production is already dark."""
    base = json.loads((REPO / "apps" / "web" / "public" / "artifacts" / "api.json").read_text())[
        "base"
    ]
    assert base and base.startswith("https://"), (
        "apps/web/public/artifacts/api.json publishes no API base — every live "
        "feature on the deployed site is off, which is the state commit 840b3dd left"
    )
