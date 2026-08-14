"""Every assumption a card cites must resolve to something a reader can open.

`docs/ASSUMPTIONS.md` opens: "This file is a product surface, not a note. It
renders in the UI, one click from every quote." The click is the part that has
to work. A card that says "(assumption P-1)" and links to a page with no P-1 on
it is worse than one that does not link at all — it is the first thing a judge
checks, and it fails in front of them.

P-1 is exactly that case: the caveat calls it an assumption, and it is a heading
in `docs/REQUIREMENTS_MATRIX.md`, not in the assumption sheet.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO / "apps" / "web" / "public" / "artifacts"


def _load_emitter():
    """Import scripts/assumptions.py without putting scripts/ on sys.path.

    The tests must use the *same* citation regex the emitter uses rather than a
    copy — a second definition would drift, which is the exact failure the
    regex-parity test below exists to catch.
    """
    spec = importlib.util.spec_from_file_location(
        "misquote_assumptions_emitter", REPO / "scripts" / "assumptions.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_emitter = _load_emitter()
CITATION = _emitter.CITATION
citations_in = _emitter.citations_in


@pytest.fixture(scope="module")
def sheet() -> dict:
    path = ARTIFACTS / "assumptions.json"
    if not path.exists():
        pytest.skip("no assumption sheet; run `make assumptions`")
    return json.loads(path.read_text())


def test_every_citation_in_every_artifact_resolves(sheet: dict) -> None:
    known = {entry["id"] for entry in sheet["entries"]}

    unresolved: dict[str, set[str]] = {}
    for artifact in sorted(ARTIFACTS.glob("*.json")):
        if artifact.name == "assumptions.json":
            continue
        cited = citations_in(json.loads(artifact.read_text()))
        missing = cited - known
        if missing:
            unresolved[artifact.name] = missing

    assert not unresolved, (
        "artifacts cite assumptions that appear in neither source document, so "
        f"the link on the card goes nowhere: { {k: sorted(v) for k, v in unresolved.items()} }"
    )


def test_the_emitter_agrees_with_itself(sheet: dict) -> None:
    assert sheet["unresolved_citations"] == [], (
        f"the emitter recorded unresolved citations: {sheet['unresolved_citations']}"
    )


def test_percentile_labels_are_not_mistaken_for_citations() -> None:
    """P25 and P75 are percentiles. They must not linkify.

    A permissive `[AP]-?\\d+` matches both, and the phrase "a P25-P75 range"
    appears in almost every caveat on the site — so the product's own headline
    term would have rendered as two links to assumptions that do not exist.
    """
    text = "Every quote is a P25-P75 range (assumption A5), net of the 34% cut (P-1)."
    found = set(CITATION.findall(text))
    assert found == {"A5", "P-1"}, found
    assert "P25" not in found and "P75" not in found


def test_the_ui_regex_matches_the_python_one() -> None:
    """Two regexes, one rule. They must not drift.

    The TypeScript copy in `Cite.tsx` decides what becomes a link; the Python
    copy decides what gets published as linkable. If they disagree, the UI
    either produces dead links or silently drops live ones.
    """
    source = (REPO / "apps" / "web" / "src" / "components" / "Cite.tsx").read_text()
    match = re.search(r"const CITATION = /(.+?)/g;", source)
    assert match, "could not find the CITATION regex in Cite.tsx"

    ts = match.group(1)
    # JS and Python spell this identically; compare the pattern text directly.
    assert ts == CITATION.pattern, (
        f"Cite.tsx uses /{ts}/ but scripts/assumptions.py uses "
        f"/{CITATION.pattern}/ — they must be the same rule"
    )


def test_every_assumption_referenced_by_the_ui_exists(sheet: dict) -> None:
    """Hardcoded `<Cite id="A8" />` calls must point at real entries."""
    known = {entry["id"] for entry in sheet["entries"]}
    web = REPO / "apps" / "web" / "src"

    bad: list[str] = []
    for path in [*web.rglob("*.tsx"), *web.rglob("*.ts")]:
        if path.name.endswith((".test.ts", ".test.tsx")):
            continue
        for match in re.finditer(
            r'cite=["\']([^"\']+)["\']|id=["\']([A-Z]-?\d+)["\']', path.read_text()
        ):
            cited = match.group(1) or match.group(2)
            if cited and re.fullmatch(r"[A-Z]-?\d+", cited) and cited not in known:
                bad.append(f"{path.relative_to(REPO)} cites {cited}")

    assert not bad, f"the UI cites assumptions that do not exist: {sorted(bad)}"
