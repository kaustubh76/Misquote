"""A client module may not reach the filesystem, and the failure is silent.

`apps/web/src/lib/build-artifact.ts` reads an artifact off disk while the site is
being built, so that the static export contains numbers rather than a spinner.
It imports `node:fs`. A `"use client"` module that pulls it in has crossed a
boundary that must not be crossed.

## Why this is a test and not a convention

`lib/routes.ts` documents the mirror-image mistake — importing a value out of a
client module into a server one — and it is self-punishing: the build stops at
prerender with `TypeError: g.LINKS.map is not a function`. Loud, immediate,
findable.

This direction is quiet. `readArtifact` wraps its read in `try/catch` and returns
`undefined` on any failure, because a missing artifact is a state the site
renders on purpose. Pulled into a client graph it therefore does not throw — it
returns nothing, every page seeded from it falls back to the spinner it was
converted to avoid, the client fetch covers for it a moment later, and the build
is green. The property would be gone and the only symptom would be an export
that quietly stopped containing figures.

Which is exactly how the export came to contain none for months: every check in
this repository runs JavaScript, so nothing could see the difference.

The Python side has had this rule since the beginning — `tests/test_layering.py`,
"the purity firewall", walks imports and forbids the pure layer from reaching the
network, the database or the clock. This is the same rule for the other language.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WEB_SRC = REPO / "apps" / "web" / "src"

#: Anything that only exists on a server. `node:path` is harmless on its own —
#: it is listed because it travels with `node:fs` and its presence in a client
#: file is the same mistake caught one import earlier.
SERVER_ONLY = ("node:fs", "node:path", "@/lib/build-artifact", "lib/build-artifact")

#: Matches the directive whether it is single or double quoted, and only when it
#: is the first statement — which is the only position where it means anything.
CLIENT = re.compile(r'^\s*["\']use client["\'];', re.M)

IMPORT = re.compile(r'^\s*import\s.*?from\s+["\']([^"\']+)["\'];', re.M | re.S)


def sources() -> list[Path]:
    return sorted(
        p
        for p in [*WEB_SRC.rglob("*.ts"), *WEB_SRC.rglob("*.tsx")]
        if not p.name.endswith((".test.ts", ".test.tsx"))
    )


def is_client(text: str) -> bool:
    """`"use client"` has to be the first statement, so only look at the top."""
    head = "".join(text.splitlines(keepends=True)[:5])
    return bool(CLIENT.search(head))


@pytest.mark.parametrize("path", sources(), ids=lambda p: str(p.relative_to(WEB_SRC)))
def test_no_client_module_reaches_the_filesystem(path: Path) -> None:
    text = path.read_text()
    if not is_client(text):
        return

    reached = [m for m in IMPORT.findall(text) if m in SERVER_ONLY]
    assert not reached, (
        f"{path.relative_to(REPO)} is a client component and imports {reached}. "
        "A filesystem read in a client graph does not fail — `readArtifact` "
        "returns undefined, the page falls back to its spinner, and the export "
        "silently stops containing numbers. Read the artifact in the `page.tsx` "
        "above this file and pass it down as an initial value."
    )


def test_the_reader_is_imported_only_by_server_components() -> None:
    """The same rule from the other end, so neither direction is the only guard."""
    offenders = []
    for path in sources():
        text = path.read_text()
        if not any(m in SERVER_ONLY for m in IMPORT.findall(text)):
            continue
        if is_client(text):
            offenders.append(str(path.relative_to(REPO)))

    assert not offenders, f"client modules importing a server-only module: {offenders}"


def test_the_guard_would_catch_the_import_it_exists_for() -> None:
    """Both sides of the band, per `tests/core/test_units.py`.

    A guard that has only ever seen good input is indistinguishable from one that
    asserts nothing — and this one is a regex over source text, which is exactly
    the kind that stops matching without stopping passing.
    """
    bad = '"use client";\n\nimport { readArtifact } from "@/lib/build-artifact";\n'
    assert is_client(bad)
    assert [m for m in IMPORT.findall(bad) if m in SERVER_ONLY] == ["@/lib/build-artifact"]

    good = 'import { readArtifact } from "@/lib/build-artifact";\n'
    assert not is_client(good)

    # And the directive must be at the top to count: the string appearing inside
    # a docstring or a comment further down is not a directive.
    mentioned = '/** A note about "use client" modules. */\nimport x from "node:fs";\n'
    assert not is_client(mentioned)


def test_at_least_one_server_component_actually_reads_an_artifact() -> None:
    """Otherwise the rule above is vacuously true and the property is gone.

    This is the canary `test_no_dead_exports.py` keeps for the same reason: a
    boundary test passes perfectly on a codebase where nobody crosses the
    boundary because nobody uses the thing.
    """
    readers = [p.relative_to(WEB_SRC) for p in sources() if "@/lib/build-artifact" in p.read_text()]
    assert len(readers) >= 2, (
        f"only {len(readers)} module(s) read an artifact at build time: {readers}. "
        "The static export renders what these read; if they are gone, so is it."
    )
