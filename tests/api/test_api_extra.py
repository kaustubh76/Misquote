"""The guard `test_app.py` describes, in the one place it can actually fire.

`tests/api/test_app.py` opens with a module-level `pytest.importorskip("fastapi")`,
and its docstring says a companion test "keeps the skip from becoming permanent
unnoticed". That companion did not exist, and it could not have existed in that
file: the `importorskip` runs at import, so a test written below it is skipped by
exactly the condition it was meant to detect. A guard that disappears whenever
the thing it guards against happens is not a guard.

So it lives here, in a module that imports nothing optional and therefore always
runs. If the `api` extra ever falls out of this checkout, this goes red and names
the remedy — instead of nineteen API tests quietly reporting themselves as
skipped, which reads like a deliberate exclusion rather than a broken
environment.

`make setup` runs `uv sync --all-extras`, so a correctly provisioned checkout
always satisfies this.
"""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: The extra `render.yaml` installs (`pip install -e ".[api]"`) and the one the
#: API suite needs. Read from `pyproject.toml` rather than typed here, so
#: renaming the extra cannot leave this test asserting against a name nothing
#: declares any more.
EXTRA = "api"


def _declared() -> list[str]:
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    extras = data["project"]["optional-dependencies"]
    assert EXTRA in extras, (
        f"pyproject.toml declares no {EXTRA!r} extra. render.yaml installs "
        f'`.[{EXTRA}]` and tests/api/test_app.py skips on it.'
    )
    return extras[EXTRA]


def test_the_extra_declares_the_packages_the_service_imports() -> None:
    """`service.py` imports fastapi; uvicorn is how render.yaml starts it."""
    declared = " ".join(_declared())
    for package in ("fastapi", "uvicorn"):
        assert package in declared, f"the {EXTRA!r} extra does not declare {package!r}"


@pytest.mark.parametrize("module", ["fastapi", "uvicorn"])
def test_the_extra_is_installed_in_this_checkout(module: str) -> None:
    """The assertion `test_app.py`'s docstring promises.

    `find_spec` rather than an import: this asks whether the module is
    installed, which is the question, and does not pay for importing a web
    framework in a suite that is otherwise offline and fast.
    """
    assert importlib.util.find_spec(module) is not None, (
        f"{module!r} is not installed, so every test in tests/api/test_app.py is "
        f"skipping silently. Run `uv sync --extra {EXTRA}` (or `make setup`, "
        "which syncs all extras)."
    )
