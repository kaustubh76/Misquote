"""The numbers in the judge's document must be the numbers the commands produce.

`docs/FOR_JUDGES.md` opens with five commands and tells a judge to run them. It
has drifted three times: "395 tests" when the suite collected 463, "455 tests:
436 offline" when it was 482, and `http://localhost:8080` after `make web`
moved to port 3000. Each was corrected by hand, and each drifted again within
hours, because nothing was watching.

That is the same failure the product argues against — a published figure that
was true when written and is quoted long after it stopped being true — printed
in the one document written specifically to be trusted. So it is a test now.

The counts come from running pytest's collector rather than from counting
`def test_`: the documented figures include parametrised cases, and a naive
count would disagree with the number a judge actually sees.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
JUDGES = REPO / "docs" / "FOR_JUDGES.md"
MAKEFILE = REPO / "Makefile"


def collected() -> tuple[int, int]:
    """(offline, total) as pytest itself reports them.

    A subprocess, so it is the real collector on the real tree rather than an
    approximation of it. `-p no:cacheprovider` keeps it from writing state into
    the run that spawned it.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    text = result.stdout + result.stderr

    # "511/539 tests collected (28 deselected)" when a marker filter applies,
    # "539 tests collected" when nothing is deselected.
    split = re.search(r"(\d+)/(\d+) tests collected", text)
    if split:
        return int(split.group(1)), int(split.group(2))
    plain = re.search(r"(\d+) tests collected", text)
    if plain:
        return int(plain.group(1)), int(plain.group(1))

    pytest.fail(f"could not read a collection count from pytest:\n{text[-800:]}")


@pytest.fixture(scope="module")
def judges() -> str:
    if not JUDGES.exists():
        pytest.skip("no FOR_JUDGES.md")
    return JUDGES.read_text()


def test_the_headline_test_counts_are_the_real_ones(judges: str) -> None:
    """`**539 tests: 511 offline, 28 against a live chain or a fork.**`"""
    match = re.search(
        r"\*\*(\d[\d,]*) tests: (\d[\d,]*) offline, (\d[\d,]*) against a live chain",
        judges,
    )
    assert match, "the headline test-count sentence is missing or has been reworded"

    total, offline, chain = (int(g.replace(",", "")) for g in match.groups())
    real_offline, real_total = collected()

    assert (total, offline, chain) == (real_total, real_offline, real_total - real_offline), (
        f"FOR_JUDGES.md says {total} tests: {offline} offline, {chain} chain — "
        f"pytest collects {real_total}: {real_offline} offline, "
        f"{real_total - real_offline} chain. Run `make judges`."
    )


def test_the_quickstart_test_count_is_the_real_one(judges: str) -> None:
    """`make test   # 511 tests, no network, ~35s` — the first thing anyone runs."""
    match = re.search(r"make test\s+#\s*(\d[\d,]*) tests", judges)
    assert match, "the `make test` quickstart line is missing or has been reworded"

    documented = int(match.group(1).replace(",", ""))
    real_offline, _ = collected()
    assert documented == real_offline, (
        f"the quickstart says `make test` runs {documented} tests; it collects "
        f"{real_offline}. Run `make judges`."
    )


def test_the_documented_port_is_the_one_the_target_serves(judges: str) -> None:
    """A judge following the quickstart must not get connection-refused."""
    documented = re.search(r"make web\s+#\s*http://localhost:(\d+)", judges)
    assert documented, "the `make web` quickstart line is missing or has been reworded"

    recipe = MAKEFILE.read_text()
    # The target's own help text is the claim the Makefile makes about itself.
    target = re.search(r"^web:.*?##.*?localhost:(\d+)", recipe, re.MULTILINE)
    assert target, "the `web` target no longer names a port in its help text"

    assert documented.group(1) == target.group(1), (
        f"FOR_JUDGES.md sends a judge to port {documented.group(1)}; "
        f"`make web` serves {target.group(1)}. Run `make judges`."
    )


def test_documented_line_counts_are_the_real_ones(judges: str) -> None:
    """Rows like `| The policy, 454 lines, pure | \\`…/policy.py\\` |`.

    A line count is the cheapest possible claim to check and the easiest to
    leave behind — this one was two revisions stale.
    """
    wrong: list[str] = []

    for row in re.finditer(r"\|([^|]*?(\d[\d,]*) lines[^|]*?)\|\s*`([^`]+\.py)`\s*\|", judges):
        claimed = int(row.group(2).replace(",", ""))
        path = REPO / row.group(3)
        if not path.exists():
            wrong.append(f"{row.group(3)} does not exist")
            continue
        actual = len(path.read_text().splitlines())
        if claimed != actual:
            wrong.append(f"{row.group(3)}: documented {claimed} lines, actually {actual}")

    assert not wrong, "\n".join([*wrong, "Run `make judges`."])
