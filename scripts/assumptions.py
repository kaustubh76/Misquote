"""The assumption sheet as an artifact, so the UI can link to it.

    uv run python scripts/assumptions.py

`docs/ASSUMPTIONS.md` opens by insisting it "is a product surface, not a note…
It renders in the UI, one click from every quote." It never did. Every caveat on
every card named an assumption — "published as assumption A6", "assumption A10",
"assumption P-1" — as inert text, so the sheet the whole argument rests on was
one the reader had to go and find.

## Why this reads two files

The caveat `tearsheet.generate` writes says *"the protocol takes 34% (assumption
P-1)"*. There is no P-1 in `ASSUMPTIONS.md`. It is a heading in
`REQUIREMENTS_MATRIX.md`, under a different numbering series with a different
heading level. A parser pointed at the assumption sheet alone would produce a
sheet that looks complete and a citation that 404s on the first click a judge
takes — which is a worse failure than not linking at all, because it is the
first thing anyone checks.

So both files are parsed, the union is published, and
`tests/web/test_citations.py` asserts that every citation appearing anywhere in
any emitted artifact resolves to an entry here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

# `## A1 · title` in the assumption sheet, `### P-1 · title` in the matrix.
# The separator is a middle dot in both, and the id series differ by design:
# A-numbers are assumptions, the matrix uses D/V/P/E/G for deviations, defects
# and so on. Both are cited from card text, so both are addressable.
HEADING = re.compile(r"^(#{2,4})\s+([A-Z]-?\d+)\s+·\s+(.+?)\s*$")
ANY_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

SERIES_KIND = {
    "A": "assumption",
    "D": "deviation",
    "V": "defect",
    "P": "correction",
    "E": "erratum",
    "G": "gap",
}


@dataclass
class Entry:
    id: str
    title: str
    kind: str
    source: str
    line: int
    blocks: list[dict[str, Any]] = field(default_factory=list)
    cited_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "source": self.source,
            "line": self.line,
            "blocks": self.blocks,
            "cited_by": sorted(set(self.cited_by)),
        }


def to_blocks(lines: list[str]) -> list[dict[str, Any]]:
    """Markdown to a small block list.

    Deliberately not a markdown library. The subset these two documents actually
    use is paragraphs, bullets, fenced code and tables, and a renderer that
    handles exactly that is easier to reason about than a dependency whose
    output has to be sanitised before it can be injected.
    """
    blocks: list[dict[str, Any]] = []
    buffer: list[str] = []
    bullets: list[str] = []
    code: list[str] | None = None
    table: list[str] = []

    def flush_paragraph() -> None:
        if buffer:
            blocks.append({"type": "p", "text": " ".join(buffer).strip()})
            buffer.clear()

    def flush_bullets() -> None:
        if bullets:
            blocks.append({"type": "ul", "items": list(bullets)})
            bullets.clear()

    def flush_table() -> None:
        if not table:
            return
        rows = [
            [cell.strip() for cell in row.strip().strip("|").split("|")]
            for row in table
            # The |---|---| separator row carries no content.
            if not re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", row)
        ]
        if rows:
            blocks.append({"type": "table", "head": rows[0], "rows": rows[1:]})
        table.clear()

    for raw in lines:
        line = raw.rstrip()

        if line.startswith("```"):
            if code is None:
                flush_paragraph()
                flush_bullets()
                flush_table()
                code = []
            else:
                blocks.append({"type": "code", "text": "\n".join(code)})
                code = None
            continue

        if code is not None:
            code.append(raw.rstrip("\n"))
            continue

        if line.startswith("|"):
            flush_paragraph()
            flush_bullets()
            table.append(line)
            continue
        flush_table()

        if re.match(r"^\s*[-*]\s+", line):
            flush_paragraph()
            bullets.append(re.sub(r"^\s*[-*]\s+", "", line))
            continue

        if not line.strip():
            flush_paragraph()
            flush_bullets()
            continue

        # A continuation of a bullet, not a new paragraph.
        if bullets and line.startswith("  "):
            bullets[-1] += " " + line.strip()
            continue

        flush_bullets()
        buffer.append(line.strip())

    flush_paragraph()
    flush_bullets()
    flush_table()
    if code:  # unterminated fence
        blocks.append({"type": "code", "text": "\n".join(code)})
    return blocks


def parse(path: Path) -> list[Entry]:
    """Every id-carrying heading in one document, with its body."""
    if not path.exists():
        raise FileNotFoundError(path)

    lines = path.read_text().splitlines()
    entries: list[Entry] = []
    current: Entry | None = None
    body: list[str] = []
    current_depth = 0

    for number, line in enumerate(lines, start=1):
        heading = HEADING.match(line)
        if heading:
            if current:
                current.blocks = to_blocks(body)
                entries.append(current)
            depth = len(heading.group(1))
            entry_id = heading.group(2)
            current = Entry(
                id=entry_id,
                title=heading.group(3),
                kind=SERIES_KIND.get(entry_id[0], "note"),
                source=str(path.relative_to(REPO)),
                line=number,
            )
            current_depth = depth
            body = []
            continue

        # A heading at the same level or higher ends the current entry. Without
        # this, "## Parameters" would be swallowed into A6, which sits directly
        # above it in the file.
        other = ANY_HEADING.match(line)
        if other and current and len(other.group(1)) <= current_depth:
            current.blocks = to_blocks(body)
            entries.append(current)
            current = None
            body = []
            continue

        if current:
            body.append(line)

    if current:
        current.blocks = to_blocks(body)
        entries.append(current)

    return entries


# `| **G-4** | `κ_default` | §5.2, referenced but never given a value | ... |`
#
# Not every published item is a heading. The gap parameters G-1..G-4 are rows in
# a table, and they are cited from prose and from `go_no_go.py`'s remedy text
# ("publish as G-4") exactly like the heading-shaped ones. A parser that only
# reads headings publishes a sheet that looks complete and leaves those four
# citations pointing at nothing.
TABLE_ENTRY = re.compile(r"^\|\s*\*\*([A-Z]-?\d+)\*\*\s*\|(.+)\|\s*$")


def parse_table_entries(path: Path) -> list[Entry]:
    """Entries defined as a bolded id in the first cell of a table row."""
    entries: list[Entry] = []
    lines = path.read_text().splitlines()

    # The nearest preceding header row, to label the cells.
    header: list[str] = []
    for number, line in enumerate(lines, start=1):
        if line.startswith("|") and not TABLE_ENTRY.match(line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not re.fullmatch(r"[\s:|-]+", line.strip().strip("|")):
                header = cells
            continue

        match = TABLE_ENTRY.match(line)
        if not match:
            continue

        entry_id = match.group(1)
        cells = [c.strip() for c in match.group(2).split("|")]
        labels = header[1:] if len(header) > 1 else []

        # The row's own cells become a two-column table, so the entry renders
        # with the same structure it has in the document.
        rows = [
            [labels[i] if i < len(labels) else f"column {i + 2}", cell]
            for i, cell in enumerate(cells)
            if cell
        ]
        title = cells[0].strip("`* ") if cells else entry_id

        entries.append(
            Entry(
                id=entry_id,
                title=title or entry_id,
                kind=SERIES_KIND.get(entry_id[0], "note"),
                source=str(path.relative_to(REPO)),
                line=number,
                blocks=[{"type": "table", "head": ["Field", "Value"], "rows": rows}],
            )
        )

    return entries


def section(path: Path, title: str) -> list[dict[str, Any]]:
    """One named, id-less section — Parameters, Target pool — as blocks."""
    lines = path.read_text().splitlines()
    collecting = False
    depth = 0
    body: list[str] = []

    for line in lines:
        heading = ANY_HEADING.match(line)
        if heading and heading.group(2).strip() == title:
            collecting = True
            depth = len(heading.group(1))
            continue
        if collecting and heading and len(heading.group(1)) <= depth:
            break
        if collecting:
            body.append(line)

    return to_blocks(body)


# The A-series never hyphenates (A1, A10); every other series always does
# (P-1, D-8, V-13). That distinction is load-bearing rather than cosmetic: a
# permissive `[AP]-?\d+` also matches the "P25" and "P75" in "a P25-P75 range",
# which appears in almost every caveat this scans. Those are percentiles, not
# citations, and linkifying them would point the reader's first click at an
# assumption that does not exist.
CITATION = re.compile(r"\bA\d+\b|\b[DVEGP]-\d+\b")


def citations_in(value: Any) -> set[str]:
    """Every assumption id mentioned anywhere in a JSON document."""
    found: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            found |= citations_in(item)
    elif isinstance(value, list):
        for item in value:
            found |= citations_in(item)
    elif isinstance(value, str):
        found |= set(CITATION.findall(value))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default=str(REPO / "apps" / "web" / "public" / "artifacts" / "assumptions.json")
    )
    args = parser.parse_args()

    sheet = REPO / "docs" / "ASSUMPTIONS.md"
    matrix = REPO / "docs" / "REQUIREMENTS_MATRIX.md"

    # Headings first, then table rows. A heading is the richer definition, so
    # where an id has both — as the G-series would if it ever gets promoted to
    # a section — the heading wins and the row is not a duplicate.
    entries = parse(sheet) + parse(matrix)
    heading_ids = {e.id for e in entries}
    table_entries = [
        e
        for e in parse_table_entries(sheet) + parse_table_entries(matrix)
        if e.id not in heading_ids
    ]

    by_id: dict[str, Entry] = {}
    duplicates: list[str] = []
    for entry in entries:
        if entry.id in by_id:
            duplicates.append(entry.id)
        else:
            by_id[entry.id] = entry

    for entry in table_entries:
        # A table id repeated across both documents is a definition and a
        # cross-reference, not a conflict: keep the first.
        by_id.setdefault(entry.id, entry)

    if duplicates:
        # Two entries answering to one anchor means a citation resolves to
        # whichever the parser happened to see first. Refuse rather than pick.
        print(f"error: duplicate ids across the two documents: {sorted(set(duplicates))}")
        return 1

    # Which artifacts cite which assumption, so an entry can show its callers.
    out_dir = Path(args.out).parent
    for artifact in sorted(out_dir.glob("*.json")):
        if artifact.name == "assumptions.json":
            continue
        try:
            data = json.loads(artifact.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for cited in citations_in(data):
            if cited in by_id:
                by_id[cited].cited_by.append(artifact.name)

    unresolved = sorted(
        {
            cited
            for artifact in out_dir.glob("*.json")
            if artifact.name != "assumptions.json"
            for cited in citations_in(json.loads(artifact.read_text()))
            if cited not in by_id
        }
    )

    payload = {
        "entries": [by_id[key].to_dict() for key in sorted(by_id, key=sort_key)],
        "sections": {
            "parameters": section(sheet, "Parameters"),
            "estimator_fits": section(sheet, "Estimator fits"),
            "target_pool": section(sheet, "Target pool"),
            "protocol_fee": section(sheet, "The protocol fee: an LP does not keep 0.05%"),
            "settled_vs_displayed": section(sheet, "What settles versus what is displayed"),
        },
        "sources": [str(sheet.relative_to(REPO)), str(matrix.relative_to(REPO))],
        "unresolved_citations": unresolved,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    print(f"{len(by_id)} entries -> {out}")
    if unresolved:
        print(f"  WARNING: cited but not found in either document: {unresolved}")
    return 0


def sort_key(entry_id: str) -> tuple[str, int]:
    match = re.match(r"([A-Z])-?(\d+)", entry_id)
    return (match.group(1), int(match.group(2))) if match else (entry_id, 0)


if __name__ == "__main__":
    sys.exit(main())
