"""`git_dirty` must be able to be false.

The field claims something specific: this artifact cannot be reproduced from
the commit it names. `BuildStamp` renders it on every page of the site,
`api/service.py` aggregates the dirty ones into a census at `/artifacts`, and
sends it per-artifact as `X-Misquote-Dirty`.

It was computed as `bool(git status --porcelain)`, which made it structurally
always true. `make artifacts` runs thirteen emitters in sequence — the first
writes on a clean tree and stamps false, and every one after it stamps true
because the tree now contains the artifact the previous emitter just wrote.
Regenerating five in a row produced one false and four trues, in emitter order,
with no source edit anywhere.

So the tests below are in two halves, and the second is the important one: the
exclusion must not swallow a real input change. An uncommitted estimator, chain
address or hand-written assumption still makes an artifact unreproducible, and
`docs/ASSUMPTIONS.md` is deliberately *not* in `GENERATED` for that reason.
"""

from __future__ import annotations

import pytest

from misquote.tearsheet.provenance import GENERATED, _touched


def porcelain(*paths: str) -> str:
    return "".join(f" M {path}\n" for path in paths)


@pytest.mark.parametrize("path", GENERATED)
def test_the_pipelines_own_output_is_not_a_dirty_tree(path: str) -> None:
    """Every declared output, including one inside the artifacts directory."""
    written = f"{path}index.json" if path.endswith("/") else path
    assert _touched(porcelain(written)) == []


def test_an_uncommitted_input_is_still_a_dirty_tree() -> None:
    assert _touched(porcelain("packages/misquote/estimators/sigma.py")) == [
        "packages/misquote/estimators/sigma.py"
    ]


def test_a_hand_written_assumption_still_counts() -> None:
    """`docs/ASSUMPTIONS.md` is an input to `make assumptions`, not its output.

    Excluding it because it lives under `docs/` alongside the generated reports
    would hide the one edit most likely to change what an artifact means.
    """
    assert _touched(porcelain("docs/ASSUMPTIONS.md")) == ["docs/ASSUMPTIONS.md"]
    assert _touched(porcelain("docs/REQUIREMENTS_MATRIX.md")) == ["docs/REQUIREMENTS_MATRIX.md"]


def test_output_and_input_together_are_dirty() -> None:
    """The mixed case, which is what a real regeneration mid-edit looks like."""
    assert _touched(
        porcelain("apps/web/public/artifacts/venue.json", "packages/misquote/replay/ranges.py")
    ) == ["packages/misquote/replay/ranges.py"]


def test_a_rename_is_judged_by_its_destination() -> None:
    """Porcelain writes `XY old -> new`, and the destination is what exists now."""
    assert _touched("R  scripts/old.py -> apps/web/public/artifacts/new.json") == []
    assert _touched("R  apps/web/public/artifacts/old.json -> scripts/new.py") == ["scripts/new.py"]


def test_an_untracked_artifact_is_not_a_dirty_tree() -> None:
    """A brand-new artifact is `??`, not ` M`, and is still this pipeline's output."""
    assert _touched("?? apps/web/public/artifacts/brand_new.json") == []


def test_a_blank_or_short_line_is_ignored_rather_than_indexed() -> None:
    """Guards the slice. An empty trailing line must not become a path of `''`."""
    assert _touched("\n\n M scripts/x.py\n") == ["scripts/x.py"]
