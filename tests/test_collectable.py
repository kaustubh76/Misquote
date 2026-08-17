"""Two test files with one basename take down the whole suite, not just themselves.

`tests/` is not a package, so pytest derives a module name from each file's
basename alone. Two files called `test_addresses.py` — one under `tests/chain/`,
one under `tests/vetting/` — produce one module name, the second to be collected
raises `import file mismatch`, and the run ends:

    2 failed, 643 passed, 40 errors
    !!!!!! Interrupted: 1 error during collection !!!!!!

Forty errors and an interrupted run, from a filename. Nothing in that output
names the cause, and the two files involved are individually fine: `pytest
tests/vetting -q` passes, `pytest tests/chain -q` passes, and only the whole
suite breaks. That is the worst shape a failure can have.

A `__init__.py` package marker also fixes it, and was tried first. It works, but
it rests on package semantics that shift with `--import-mode`, and it leaves the
trap armed for whoever adds the next duplicate basename. A guard names the problem
in the words of the fix.
"""

from __future__ import annotations

import collections
from pathlib import Path

TESTS = Path(__file__).resolve().parent

#: Directories that carry their own `__init__.py`, and so may repeat a basename.
#: Empty, deliberately — see the module docstring. If a package marker is ever
#: added, list the directory here so this test keeps meaning what it says.
PACKAGED: frozenset[str] = frozenset()


def test_no_two_test_files_share_a_basename() -> None:
    by_name: dict[str, list[str]] = collections.defaultdict(list)

    for path in sorted(TESTS.rglob("test_*.py")):
        if "__pycache__" in path.parts:
            continue
        if any(part in PACKAGED for part in path.parts):
            continue
        by_name[path.name].append(str(path.relative_to(TESTS.parent)))

    clashes = {name: paths for name, paths in by_name.items() if len(paths) > 1}

    assert not clashes, (
        "these test files share a basename, which gives them one module name and "
        "breaks collection for the entire suite — not just for them:\n  "
        + "\n  ".join(f"{name}: {', '.join(paths)}" for name, paths in sorted(clashes.items()))
        + "\nRename one. `tests/chain/test_addresses.py` and the address checks "
        "under `tests/vetting/` hit this; the second became "
        "`test_address_checks.py`."
    )


def test_the_scan_is_looking_at_the_real_suite() -> None:
    """A glob that matches nothing passes the rule above for free."""
    found = [p for p in TESTS.rglob("test_*.py") if "__pycache__" not in p.parts]
    assert len(found) > 30, f"only {len(found)} test files found under {TESTS}"
