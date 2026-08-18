"""Public definitions nothing ever uses.

`apps/web` has had this check for TypeScript for a while. Python did not, and the
gap cost something: `replay/driver.py:passive_result` sat there building a
`ReplayResult` that nothing called — not the showcase, not the advantage report,
not one test — while `tearsheet/advantage.py` cited it by name as built
machinery. Being named in prose is most of why it survived.

That one mattered because it answered a **live** question by a different rule:
`in_range_samples` per swap event, where the driver counts per decision sample.
InRange% is on every card and gates G-3's floor. Dead code is tolerable; dead
code with a plausible name that answers a live question differently is a trap.

**Identifiers, not text.** A regex would have counted that docstring mention as a
use, which is exactly how it hid. This walks the AST and collects names actually
loaded, called, imported or accessed as attributes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "packages" / "misquote"
SEARCHED = (REPO / "packages", REPO / "scripts", REPO / "tests")

#: Names that are allowed to have no call site, each with the reason. A `Protocol`
#: is a real exception — it constrains by being *annotated*, and annotations are
#: strings under `from __future__ import annotations`, so the AST cannot see them.
#: Anything else here should be viewed with suspicion.
ALLOWED: dict[str, str] = {
    "Tape": (
        "Protocol describing the tape interface. Currently annotates nothing — "
        "`ReplayDriver.run(self, tape, ...)` is untyped — so it documents rather "
        "than constrains. Kept because the description is worth having; noted "
        "because a Protocol nobody annotates with enforces nothing."
    ),
    "fetch_live_contracts": (
        "AACP C1. TermiX's docs say their live contract table is authoritative "
        "over any snapshot, and this fetches it so `mismatches()` can compare. "
        "Nothing calls it yet because nothing signs yet — the check belongs on "
        "the signing path, and that path does not exist. Built ahead, and "
        "recorded as built-ahead rather than allowed to look wired."
    ),
}


def _python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in str(p)]


def _public_definitions() -> dict[str, tuple[Path, int]]:
    """Module-level `def`/`class` in the package, excluding `_private` ones."""
    found: dict[str, tuple[Path, int]] = {}
    for path in _python_files(PACKAGE):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                if not node.name.startswith("_"):
                    found[node.name] = (path.relative_to(REPO), node.lineno)
    return found


def _used_identifiers() -> set[str]:
    used: set[str] = set()
    for root in SEARCHED:
        for path in _python_files(root):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Name):
                    used.add(node.id)
                elif isinstance(node, ast.Attribute):
                    used.add(node.attr)
                elif isinstance(node, ast.ImportFrom):
                    used.update(alias.name for alias in node.names)
                elif isinstance(node, ast.Import):
                    used.update(alias.name.split(".")[-1] for alias in node.names)
    return used


DEFINITIONS = _public_definitions()
USED = _used_identifiers()


def test_the_survey_found_something_to_check() -> None:
    """A survey that collects nothing passes every assertion built on it.

    Ported in spirit from the TypeScript version, which carries the same guard
    for the same reason.
    """
    assert len(DEFINITIONS) > 150, f"only {len(DEFINITIONS)} definitions — the walk is broken"
    assert len(USED) > 500, f"only {len(USED)} identifiers — the corpus is not being read"
    assert "quote" in USED and "ReplayDriver" in USED


@pytest.mark.parametrize("name", sorted(DEFINITIONS))
def test_every_public_definition_is_used_somewhere(name: str) -> None:
    if name in ALLOWED:
        pytest.skip(ALLOWED[name])
    path, lineno = DEFINITIONS[name]
    assert name in USED, (
        f"{path}:{lineno} defines {name!r} and nothing loads, calls, imports or "
        "accesses it anywhere in packages/, scripts/ or tests/. Delete it, wire "
        "it up, or add it to ALLOWED with the reason."
    )


def test_the_allowance_list_does_not_outlive_its_entries() -> None:
    """An exemption for a name that no longer exists is a claim about nothing,
    and it will quietly cover the next definition to take that name."""
    stale = [name for name in ALLOWED if name not in DEFINITIONS]
    assert stale == [], f"ALLOWED covers names that are gone: {stale}"
