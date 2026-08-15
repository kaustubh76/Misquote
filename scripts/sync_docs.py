"""Bring the measurable numbers in the judge's document up to date.

    uv run python scripts/sync_docs.py          # rewrite them
    uv run python scripts/sync_docs.py --check  # fail if they are stale

`docs/FOR_JUDGES.md` opens with commands and tells a judge to run them, so its
figures are checked more often than anything else here. They have drifted three
times — "395 tests" against a suite of 463, "455 tests: 436 offline" against
482, and `localhost:8080` after `make web` moved to 3000 — and each hand
correction drifted again within hours.

The project's answer to that everywhere else is to derive the number rather than
type it: `make showcase` regenerates the cards, `make assumptions` regenerates
the sheet. This is the same move for the one document that is prose. Add a test,
run `make judges`, and the sentence that quotes the count changes with it.

`tests/web/test_docs_match_reality.py` asserts the result, so a stale figure is
a failing test rather than something a reader has to notice.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
JUDGES = REPO / "docs" / "FOR_JUDGES.md"
MAKEFILE = REPO / "Makefile"


def collected() -> tuple[int, int]:
    """(offline, total), straight from pytest's own collector."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    text = result.stdout + result.stderr

    split = re.search(r"(\d+)/(\d+) tests collected", text)
    if split:
        return int(split.group(1)), int(split.group(2))
    plain = re.search(r"(\d+) tests collected", text)
    if plain:
        return int(plain.group(1)), int(plain.group(1))

    raise SystemExit(f"could not read a collection count from pytest:\n{text[-800:]}")


def web_port() -> str:
    """The port `make web` advertises in its own help text."""
    match = re.search(r"^web:.*?##.*?localhost:(\d+)", MAKEFILE.read_text(), re.MULTILINE)
    if not match:
        raise SystemExit("the `web` target no longer names a port in its help text")
    return match.group(1)


def rewrite(text: str) -> tuple[str, list[str]]:
    """Return the corrected document and a note of what moved."""
    offline, total = collected()
    port = web_port()
    changes: list[str] = []

    def sub(pattern: str, replacement, label: str) -> None:
        nonlocal text
        updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
        if count == 0:
            changes.append(f"!! {label}: pattern not found — has it been reworded?")
        elif updated != text:
            changes.append(label)
            text = updated

    sub(
        r"(make test\s+#\s*)(\d[\d,]*)( tests)",
        lambda m: f"{m.group(1)}{offline:,}{m.group(3)}".replace(",", ","),
        f"quickstart test count -> {offline}",
    )
    sub(
        r"(\*\*)(\d[\d,]*)( tests: )(\d[\d,]*)( offline, )(\d[\d,]*)( against a live chain)",
        lambda m: (
            f"{m.group(1)}{total}{m.group(3)}{offline}{m.group(5)}{total - offline}{m.group(7)}"
        ),
        f"headline counts -> {total}: {offline} offline, {total - offline} chain",
    )
    sub(
        r"(make web\s+#\s*http://localhost:)(\d+)",
        lambda m: f"{m.group(1)}{port}",
        f"web port -> {port}",
    )

    # Line counts quoted beside a path, e.g. "| The policy, 486 lines, pure |".
    def fix_lines(match: re.Match[str]) -> str:
        path = REPO / match.group(3)
        if not path.exists():
            return match.group(0)
        actual = len(path.read_text().splitlines())
        if int(match.group(2).replace(",", "")) == actual:
            return match.group(0)
        changes.append(f"{match.group(3)} -> {actual} lines")
        return match.group(0).replace(f"{match.group(2)} lines", f"{actual} lines", 1)

    text = re.sub(r"\|([^|]*?(\d[\d,]*) lines[^|]*?)\|\s*`([^`]+\.py)`\s*\|", fix_lines, text)

    return text, changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report staleness, write nothing")
    args = parser.parse_args()

    original = JUDGES.read_text()
    updated, changes = rewrite(original)

    if not changes:
        print(f"  {JUDGES.relative_to(REPO)} is current")
        return 0

    for change in changes:
        print(f"  {change}")

    if args.check:
        print("\n  stale — run `make judges`")
        return 1

    JUDGES.write_text(updated)
    print(f"\n  -> {JUDGES.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
