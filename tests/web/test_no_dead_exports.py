"""An exported function nobody calls is a refactor that did not land.

## The failure this is built from

`components/Heading.tsx` shipped a working heading-level mechanism: a React
context, a `HeadingLevel` provider, and a `Section` that renders its title and
deepens the level for everything inside it. Its docstring described replacing
hardcoded `<h2>` tags with a level derived from the tree.

`Section` and `HeadingLevel` had **zero importers**. Nothing ever provided
`LevelContext`, so `useHeadingLevel()` returned its `createContext(2)` default
on every call and every `<Heading>` rendered an `h2` — exactly the hardcoded tag
the file said it had replaced. Seventeen card headings sat at the same level as
the section heading introducing them.

Nothing failed. The component was correct, the types were correct, the file
typechecked, and the outline was wrong on all seven pages, because *correct and
unreferenced* is indistinguishable from *absent* to everything except a reader.

`app/headings.test.tsx` now asserts the outline each page actually renders, so
that specific defect is held. This holds the shape of it: the next mechanism
written, exported, and never wired up.

## The rule

**Every exported `function` in `apps/web/src` must be named by at least one
other file.**

Deliberately narrower than "no unused exports":

*Functions only, not types.* `Loaded<T>` names `ArtifactError`; `AgentArtifact`
names `ReplayBlock`, `QuoteDetail` and six more. A consumer writes
`data.replay.fees_quote` and never types the word `ReplayBlock`, so those
exports look dead to any text scan while being load-bearing for the exported
type that references them. Deciding that properly needs a type checker, and the
defect above was a component, not an interface.

*Test files count as other files.* `Band.overlaps` is exported so
`Band.test.tsx` can pin it against `Comparison.ranges_overlap` in the Python —
which is a good reason to export something. A rule strict enough to reject that
would be a rule people delete. What this cannot then catch is a function
exported, tested, and wired to nothing; `headings.test.tsx` is the guard for
that class, because it renders the real pages.

*The framework's own exports are named, not pattern-matched.* Next calls
`generateMetadata` and `generateStaticParams` by convention, with no import
anywhere. They are listed below explicitly, so a typo'd `generateMetadatas`
still gets caught rather than waved through by a prefix rule.

*Default exports are out of scope, and not because they were inconvenient.* Next
resolves the default export of `page.tsx`, `layout.tsx` and `not-found.tsx` by
*position* — the identifier is a local label the framework never sees, so a name
scan can only ever produce noise about it. Worse, it produces the wrong kind:
`export default function Overview` passed this check purely because the word
"Overview" appears in someone else's prose, while `NotFound` failed for having
an unusual name. A rule whose verdict turns on vocabulary is not a rule. Every
route reached by a default export is covered where it means something — by
`app/pages.test.tsx`, which renders it, and by `check-pages.mjs`, which loads
the built page in a browser.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "apps" / "web" / "src"

#: Exports the Next.js App Router resolves by convention. Never imported.
#: `metadata` and `viewport` are consts, not functions, so they never reach the
#: check; they are listed because leaving them out would read as an oversight.
FRAMEWORK = frozenset(
    {
        "generateMetadata",
        "generateStaticParams",
        "generateViewport",
        "metadata",
        "viewport",
        "dynamic",
        "revalidate",
    }
)

#: `export function`, never `export default function` — see the module docstring
#: for why the default case is unscannable rather than merely awkward.
EXPORTED_FUNCTION = re.compile(r"^export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.M)


def sources() -> dict[Path, str]:
    return {
        path: path.read_text() for path in sorted(SRC.rglob("*")) if path.suffix in {".ts", ".tsx"}
    }


FILES = sources()


def exported_functions() -> list[tuple[Path, str]]:
    found = []
    for path, text in FILES.items():
        for name in EXPORTED_FUNCTION.findall(text):
            if name not in FRAMEWORK:
                found.append((path, name))
    return sorted(found, key=lambda pair: (str(pair[0]), pair[1]))


CASES = exported_functions()


def test_the_survey_found_something_to_check() -> None:
    """A regex that silently matches nothing passes every test below it.

    If `export function` is ever written differently across the whole app — or
    this file is pointed at a directory that moved — the parametrised test
    collects zero cases and reports green while checking nothing.
    """
    assert len(CASES) > 30, (
        f"only {len(CASES)} exported functions found under {SRC}; "
        "the pattern or the path is wrong, not the app"
    )


@pytest.mark.parametrize("path,name", CASES, ids=[f"{p.relative_to(SRC)}:{n}" for p, n in CASES])
def test_every_exported_function_is_named_somewhere_else(path: Path, name: str) -> None:
    ident = re.compile(rf"\b{re.escape(name)}\b")
    importers = [
        other.relative_to(SRC)
        for other, text in FILES.items()
        if other != path and ident.search(text)
    ]

    assert importers, (
        f"{path.relative_to(SRC)} exports `{name}` and no other file mentions it.\n"
        "Either wire it up — an exported component nobody renders is a refactor "
        "that did not land, and it fails silently because unreferenced code "
        "typechecks — or drop the `export` keyword and keep it private to this "
        "file. If it exists for the framework to call, add it to FRAMEWORK above "
        "with the convention that resolves it."
    )


def test_the_framework_list_stays_a_list_of_names() -> None:
    """Not a prefix or a suffix rule.

    `generateMetadatas` and `generateMetadata2` both satisfy any pattern loose
    enough to cover the two real names, and both are typos Next silently ignores
    — the page just gets the default title. Matching exactly means a typo shows
    up here as a dead export instead of as a wrong `<title>` nobody reads.
    """
    assert all(name.isidentifier() for name in FRAMEWORK)
    assert "generateMetadata" in FRAMEWORK
    assert not any("*" in name or name.endswith("_") for name in FRAMEWORK)
