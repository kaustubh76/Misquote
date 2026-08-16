"""A script in `package.json` must be a script you can run.

`tests/web/test_make_targets.py` holds the same property for `make`: a target
named in prose has to exist. This is the other half of the repo's command
surface, and it was in worse shape, because a Makefile at least fails loudly
when you type a target it does not have.

## What was here

    "lint": "eslint ."

`eslint` appeared in no dependency list in this repo, and no ESLint config file
existed anywhere. The script had never run — `pnpm lint` exited with
`sh: eslint: command not found` — for the entire life of the front-end. Nothing
noticed, because nothing invokes it: not the Makefile, not CI, not the docs.
It was a claim that the TypeScript was linted, sitting in the file people read
to find out what a project checks.

    "start": "next start"

The same shape. `next.config.ts` sets `output: "export"`; `next start` refuses
to run against an exported build and tells you to use a static server, which is
what `make web-static` does. Boilerplate from `create-next-app` that stopped
being true the moment the export decision was made.

## The two directions

A command surface can be wrong in two ways, and this file checks both:

1. **A script exists but cannot run** — its binary is not installed. That is the
   defect above, and it is invisible until somebody types the command.
2. **Prose names a script that does not exist** — the failure
   `test_make_targets.py` was written for, in the other package manager.

Neither check runs anything. Resolving a binary means looking in
`node_modules/.bin`, which is cheap and does not need a network, a build, or a
browser.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "apps" / "web"
PACKAGE = APP / "package.json"
SELF = Path(__file__).resolve()

#: pnpm's own subcommands. `pnpm exec playwright ...` in the Makefile is not a
#: reference to a script called "exec", and treating it as one would report a
#: missing script for a line that works.
PNPM_BUILTINS = frozenset(
    {
        "install",
        "add",
        "remove",
        "update",
        "exec",
        "dlx",
        "run",
        "why",
        "list",
        "store",
        "audit",
        "link",
        "publish",
        "config",
    }
)

#: `pnpm <name>` in a Makefile recipe or inside backticks. Same anchoring
#: argument as `test_make_targets.py`: English says "pnpm" never, so no
#: backtick is needed for shell lines, but prose mentions are required to be
#: quoted so a sentence about pnpm in general is not read as an invocation.
INVOKED = re.compile(r"(?:^|`|\$ |&& )pnpm\s+(-{0,2}[a-z][a-z0-9:-]*)", re.M)

SCANNED = (".md", ".py", ".ts", ".tsx", ".mjs")
SKIP = frozenset({"node_modules", ".next", "out", ".venv", "__pycache__", ".git"})


def scripts() -> dict[str, str]:
    return json.loads(PACKAGE.read_text()).get("scripts", {})


def binaries() -> set[str]:
    """Everything pnpm would put on `PATH` for a script in this package.

    Both the app-local `.bin` and the workspace root's, because pnpm hoists
    shared dependencies to the root of a workspace and a script finds either.
    """
    found: set[str] = set()
    for root in (APP, REPO):
        bindir = root / "node_modules" / ".bin"
        if bindir.is_dir():
            found.update(p.name for p in bindir.iterdir())
    return found


#: Runnable without being installed: shell builtins and things Node ships.
ALWAYS_AVAILABLE = frozenset({"node", "npx", "pnpm", "sh", "bash", "cd", "rm", "cp", "echo"})

SCRIPTS = sorted(scripts().items())


def test_the_package_has_scripts_to_check() -> None:
    """Guards against a moved or renamed `package.json` reporting green."""
    assert PACKAGE.is_file(), f"no {PACKAGE}"
    assert len(SCRIPTS) >= 3, f"only {len(SCRIPTS)} scripts found; has the app moved?"


@pytest.mark.parametrize("name,command", SCRIPTS, ids=[n for n, _ in SCRIPTS])
def test_every_script_resolves_to_an_installed_binary(name: str, command: str) -> None:
    binary = command.split()[0]
    if binary in ALWAYS_AVAILABLE:
        return

    available = binaries()
    if not available:
        pytest.skip("no node_modules/.bin — run `make setup`")

    assert binary in available, (
        f'apps/web/package.json declares "{name}": "{command}", and `{binary}` is '
        "not installed in this workspace — the script has never been able to run.\n"
        "Either add the dependency that provides it, or delete the script. A "
        "script that names a tool the project does not have reads as a check "
        "that happens, and it is the file people open to find out what a "
        "project checks."
    )


def test_no_prose_names_a_script_that_was_removed() -> None:
    """The mirror of `test_make_targets.py`, for the other command surface."""
    declared = set(scripts())
    missing: dict[str, list[str]] = {}

    for path in REPO.rglob("*"):
        if path.suffix not in SCANNED or not path.is_file():
            continue
        if SKIP & set(path.relative_to(REPO).parts) or path == SELF:
            continue
        for name in INVOKED.findall(path.read_text()):
            if name.startswith("-") or name in PNPM_BUILTINS or name in declared:
                continue
            missing.setdefault(name, []).append(path.relative_to(REPO).as_posix())

    assert not missing, (
        "these are invoked as pnpm scripts but apps/web/package.json declares "
        f"no such script: { {k: sorted(set(v)) for k, v in sorted(missing.items())} }"
    )


def test_the_prose_scan_is_actually_finding_invocations() -> None:
    """A pattern that matches nothing passes the check above for free."""
    found: set[str] = set()
    for path in (REPO / "Makefile", APP / "next.config.ts"):
        found.update(INVOKED.findall(path.read_text()))

    assert {"build", "dev", "test"} <= found, f"only matched {sorted(found)}"
