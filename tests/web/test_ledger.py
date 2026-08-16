"""What is not built stays disclosed, and what is advertised stays real.

Two failures, both of which had already happened:

1. `Makefile` advertised `make warden`, `make tearsheet` and the second half of
   `make indexer` against three modules that do not exist. These are the exact
   commands `Readme.md` §9 quotes. A reader following the README hit an
   ImportError on the one command that runs the agent.

2. `agents/router/` is an empty directory and the card page showed three cards,
   so the fourth advertised category was absent rather than disclosed — which is
   the specific failure this product is named after.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from misquote.tearsheet import ledger

REPO = Path(__file__).resolve().parents[2]
MAKEFILE = REPO / "Makefile"

MODULE_INVOCATION = re.compile(r"python\s+-m\s+(misquote[\w.]*)")


def advertised_modules() -> list[str]:
    """Modules the Makefile actually invokes.

    Comment lines are stripped first. The Makefile documents this very test in a
    comment containing `python -m misquote.X`, and scanning raw text turns that
    prose into a phantom target that can never import.
    """
    recipe = "\n".join(
        line for line in MAKEFILE.read_text().splitlines() if not line.strip().startswith("#")
    )
    return sorted(set(MODULE_INVOCATION.findall(recipe)))


def test_every_advertised_module_actually_imports() -> None:
    """`python -m misquote.X` in the Makefile must resolve to something."""
    referenced = advertised_modules()
    assert referenced, "no `python -m misquote.…` targets found — has the Makefile moved?"

    broken: list[str] = []
    for name in referenced:
        try:
            importlib.import_module(name)
        except ImportError as exc:
            broken.append(f"{name}: {exc}")

    assert not broken, (
        "the Makefile advertises commands whose modules do not exist. Either "
        f"build them or stop advertising them: {broken}"
    )


def test_runnable_modules_have_an_entry_point() -> None:
    """Importing is not enough: `python -m <pkg>` needs a `__main__` module in it.

    `misquote.agents.warden` imported cleanly and still could not be executed,
    which is how `make warden` stayed broken while looking fine.
    """
    referenced = advertised_modules()

    missing: list[str] = []
    for name in referenced:
        module = importlib.import_module(name)
        is_package = hasattr(module, "__path__")
        if is_package and not importlib.util.find_spec(f"{name}.__main__"):
            missing.append(name)

    assert not missing, f"these are packages with no __main__.py, so `python -m` fails: {missing}"


@pytest.mark.parametrize("entry", ledger.NOT_BUILT, ids=lambda e: e.name)
def test_ledger_entries_still_describe_reality(entry: ledger.NotBuilt) -> None:
    """Nothing in the ledger has quietly been built.

    The failure mode is silent and in the flattering direction: someone builds
    the Router, the ledger keeps calling it missing, and the site under-claims.
    Less damaging than over-claiming, still wrong.

    The claim being checked comes from the evidence string's own wording, so an
    entry cannot be worded one way and verified another.
    """
    path_text, _, claim = entry.evidence.partition("—")
    path = REPO / path_text.strip()
    claim = claim.strip().lower()

    if "empty directory" in claim:
        if path.exists():
            contents = [p for p in path.iterdir() if p.name not in {".gitkeep", "__pycache__"}]
            assert not contents, (
                f"{entry.name} is listed as an empty directory, but {path_text.strip()} "
                f"now contains {[p.name for p in contents]} — update tearsheet/ledger.py"
            )

    elif "docstring only" in claim:
        assert path.exists(), f"{path_text.strip()} no longer exists"
        body = [
            line
            for line in path.read_text().splitlines()
            if line.strip() and not line.strip().startswith(("#", '"', "'"))
        ]
        assert not body, (
            f"{entry.name} is listed as a docstring-only stub, but {path_text.strip()} "
            "now has code — update tearsheet/ledger.py"
        )

    elif match := re.search(r"no (\S+\.\w+)", claim):
        # "packages/misquote/chain/ — no executor.py"
        # Any extension, not just .py: the vetting proof-of-concept that is still
        # missing is a Foundry script, and narrowing the evidence vocabulary to
        # Python would have forced a vaguer claim about a directory instead of a
        # precise one about a file.
        absent = path / match.group(1)
        assert not absent.exists(), (
            f"{entry.name} is listed as missing {match.group(1)}, but {absent} now "
            "exists — update tearsheet/ledger.py"
        )

    else:
        pytest.fail(
            f"{entry.name}'s evidence {entry.evidence!r} states no checkable claim. "
            "Use 'empty directory', 'docstring only', or 'no <file>.py'."
        )


def test_ledger_entries_are_complete() -> None:
    """Every entry carries all four fields a reader needs to check it."""
    for entry in ledger.NOT_BUILT:
        for field in ("name", "category", "what", "why", "evidence"):
            value = getattr(entry, field)
            assert value and value.strip(), f"{entry.name}.{field} is empty"


def test_stub_packages_are_all_disclosed() -> None:
    """A docstring-only package under misquote/ must appear in the ledger.

    This is the direction that matters: someone adds a placeholder package,
    the README implies it works, and nothing on the site says otherwise.
    """
    evidence = " ".join(e.evidence for e in ledger.NOT_BUILT)
    undisclosed: list[str] = []

    for init in (REPO / "packages" / "misquote").glob("*/__init__.py"):
        # A docstring-only `__init__.py` is ordinary Python, not a placeholder —
        # `tearsheet/` and `registry/` both have one and are fully implemented.
        # What marks a placeholder is a package with *nothing else in it*.
        siblings = [
            p
            for p in init.parent.iterdir()
            if p.name not in {"__init__.py", "__pycache__"} and not p.name.startswith(".")
        ]
        if siblings:
            continue

        body = [
            line
            for line in init.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        joined = "\n".join(body).strip()
        has_code = bool(body) and not joined.startswith(('"""', "'''"))
        if not has_code and init.parent.name not in evidence:
            undisclosed.append(str(init.relative_to(REPO)))

    assert not undisclosed, (
        f"these packages are placeholders and the ledger does not mention them: {undisclosed}"
    )
