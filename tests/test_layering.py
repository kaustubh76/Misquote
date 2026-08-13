"""The purity firewall.

The replay engine's no-look-ahead guarantee rests on a structural claim: the
layers that compute numbers cannot reach the network, the database, or the
clock, so they cannot reach the future. This test is what makes that claim
true rather than aspirational, and it runs on every commit.

It is deliberately blunt. A pure module that needs `os.environ` has a design
problem, not a test problem — pass the value in as an argument.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "packages" / "misquote"

PURE_LAYERS = ("core", "estimators", "lvr", "replay")
IO_LAYERS = ("chain", "indexer")
DRIVER_LAYERS = ("agents", "ops", "registry", "sessions", "tearsheet")

BANNED_STDLIB = frozenset(
    {
        "asyncio",
        "sqlite3",
        "socket",
        "subprocess",
        "os",
        "time",
        "datetime",
        "random",
        "threading",
        "multiprocessing",
        "pathlib",
        "tempfile",
        "shutil",
        "logging",
    }
)

BANNED_THIRD_PARTY = frozenset(
    {
        "web3",
        "eth_account",
        "eth_utils",
        "eth_abi",
        "requests",
        "httpx",
        "websockets",
        "urllib",
        "urllib3",
        "dotenv",
        "fastapi",
        "uvicorn",
        "prometheus_client",
        "telegram",
    }
)

# One banned import, one named file, one reason. An exemption is module-wide,
# never layer-wide, and `test_every_exemption_points_at_a_real_file` deletes it
# from usefulness the moment the file it names disappears.
#
# The entry this dict exists for arrives with the tape in Step 11:
# `replay/tape.py` gets `sqlite3`, because holding a cursor instead of a list is
# exactly what keeps the frontier bound inside a SQL parameter and leaves no
# in-memory future to leak.
EXEMPTIONS: dict[str, frozenset[str]] = {}


def _imported_modules(node: ast.Import | ast.ImportFrom) -> list[str]:
    """Top-level external module names one import statement introduces."""
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if node.level:  # relative — resolved against our own package, never external
        return []
    return [(node.module or "").split(".")[0]]


def _misquote_layers(node: ast.Import | ast.ImportFrom, path: Path) -> list[str]:
    """Misquote sub-packages a statement pulls in: `misquote.chain.signer` -> 'chain'."""
    if isinstance(node, ast.ImportFrom) and node.level:
        # `from ..chain import signer` inside core/policy.py resolves against the
        # file's own position in the tree.
        base = path.relative_to(PKG).parts[:-1]
        up = node.level - 1
        prefix = base[: len(base) - up] if up <= len(base) else ()
        parts = [*prefix, *((node.module or "").split(".") if node.module else [])]
        return [parts[0]] if parts else []

    if isinstance(node, ast.ImportFrom):
        dotted = node.module or ""
        if dotted == "misquote":  # `from misquote import chain`
            return [alias.name for alias in node.names]
        names = [dotted]
    else:
        names = [alias.name for alias in node.names]

    layers = []
    for name in names:
        parts = name.split(".")
        if parts[0] == "misquote" and len(parts) > 1:
            layers.append(parts[1])
    return layers


def _python_files(layer: str) -> list[Path]:
    return sorted((PKG / layer).rglob("*.py"))


def _imports_in(path: Path) -> list[ast.Import | ast.ImportFrom]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)]


def _rel(path: Path) -> str:
    return path.relative_to(PKG).as_posix()


@pytest.mark.parametrize("layer", PURE_LAYERS)
def test_pure_layer_takes_no_capabilities(layer: str) -> None:
    """A layer that cannot read a clock or a socket cannot read the future."""
    violations = []
    for path in _python_files(layer):
        allowed = EXEMPTIONS.get(_rel(path), frozenset())
        for node in _imports_in(path):
            for mod in _imported_modules(node):
                if mod in allowed:
                    continue
                if mod in BANNED_STDLIB or mod in BANNED_THIRD_PARTY:
                    violations.append(f"{_rel(path)}:{node.lineno} imports {mod!r}")
    assert not violations, "pure layer reached for a capability:\n  " + "\n  ".join(violations)


@pytest.mark.parametrize("layer", PURE_LAYERS)
def test_pure_layer_does_not_import_impure_layers(layer: str) -> None:
    """core/ must not be able to spend money, even transitively."""
    forbidden = set(IO_LAYERS) | set(DRIVER_LAYERS)
    violations = []
    for path in _python_files(layer):
        for node in _imports_in(path):
            for target in _misquote_layers(node, path):
                if target in forbidden:
                    violations.append(f"{_rel(path)}:{node.lineno} imports misquote.{target}")
    assert not violations, "pure layer imported an impure one:\n  " + "\n  ".join(violations)


def test_core_does_not_depend_on_other_pure_layers() -> None:
    """core/ is the base of the tower: tick math and the policy depend on nothing of ours."""
    violations = []
    for path in _python_files("core"):
        for node in _imports_in(path):
            for target in _misquote_layers(node, path):
                if target != "core":
                    violations.append(f"{_rel(path)}:{node.lineno} imports misquote.{target}")
    assert not violations, "core reached upward:\n  " + "\n  ".join(violations)


def test_the_firewall_actually_fires() -> None:
    """A guardrail nobody has seen fail is a guardrail nobody knows works."""
    src = (
        "import web3\n"
        "from time import time\n"
        "from misquote.chain import signer\n"
        "from ..indexer import backfill\n"
    )
    stmts = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import | ast.ImportFrom)]
    here = PKG / "core" / "policy.py"

    banned = BANNED_STDLIB | BANNED_THIRD_PARTY
    assert [m for s in stmts for m in _imported_modules(s) if m in banned] == ["web3", "time"]
    assert [t for s in stmts for t in _misquote_layers(s, here)] == ["chain", "indexer"]


def test_every_exemption_points_at_a_real_file() -> None:
    """Exemptions rot silently once the file they name is renamed or deleted."""
    missing = [name for name in EXEMPTIONS if not (PKG / name).exists()]
    assert not missing, f"stale exemption for a file that no longer exists: {missing}"
