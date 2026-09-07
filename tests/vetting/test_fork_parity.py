"""The bridge under the differential corpus, and the ways it could rot.

`make vectors` proves this repository's Python against **Uniswap's** Solidity.
That is only a statement about PancakeSwap because the fork left those libraries
alone, and until `scripts/verify_fork_parity.py` existed that step was two
comments. These tests hold the check itself: that its comparison is loose enough
to survive a licence header and strict enough to catch a changed constant, and
that the set it compares stays the set the vectors actually exercise.

Nothing here reaches the network. The recorded run is read from disk where it
exists and skipped where it does not, and the one assertion about the live
repository — that its copies are identical — is the script's job, not a test's.
"""

from __future__ import annotations

import json
import re

import pytest

from misquote.tearsheet.provenance import REPO

_script_path = REPO / "scripts" / "verify_fork_parity.py"


def _load_script():
    """The emitter, imported by path — it lives in `scripts/`, not the package.

    `tests/web/test_artifact_projections.py` does the same for the same reason.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("misquote_fork_parity", _script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parity = _load_script()


# --- what the comparison must and must not swallow --------------------------


def test_a_licence_header_and_a_rewrapped_ternary_are_not_a_divergence() -> None:
    """The three differences that are real and are not arithmetic.

    PancakeSwap changes the SPDX line, runs prettier over the file, and rewrites
    one import path. A byte comparison would fail on all three and report a fork
    that had changed nothing.
    """
    uniswap = """
        // SPDX-License-Identifier: BUSL-1.1
        pragma solidity >=0.5.0;
        import '@uniswap/v3-core/contracts/libraries/FullMath.sol';
        library L {
            function f(uint256 a) internal pure returns (uint256) {
                uint256 q =
                    (
                        a <= 100
                            ? a << 96
                            : a
                    );
                return q;
            }
        }
    """
    pancakeswap = """
        // SPDX-License-Identifier: GPL-2.0-or-later
        pragma solidity >=0.5.0;
        import '@pancakeswap/v3-core/contracts/libraries/FullMath.sol';
        /// @notice a doc comment upstream does not have
        library L {
            function f(uint256 a) internal pure returns (uint256) {
                uint256 q = (a <= 100 ? a << 96 : a);
                return q;
            }
        }
    """

    assert parity.normalise(uniswap) == parity.normalise(pancakeswap)


def _library(body: str) -> str:
    return f"library L {{ function f(uint256 a) internal pure returns (uint256) {{ {body} }} }}"


ORIGINAL = _library("uint256 q = (a <= 100 ? a << 96 : a); return q;")


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ("uint256 q = (a <= 101 ? a << 96 : a); return q;", "a changed constant"),
        ("uint256 q = (a >= 100 ? a << 96 : a); return q;", "a flipped comparison"),
        ("uint256 q = (a <= 100 ? a << 95 : a); return q;", "a changed shift"),
        ("uint256 q = (a <= 100 ? a << 96 : a); return a;", "a changed return"),
    ],
)
def test_a_changed_expression_is_a_divergence(body: str, why: str) -> None:
    """The whole point. A comparison that tolerates these tolerates a mispriced
    position, silently, on every quote this project publishes."""
    changed = _library(body)

    assert parity.normalise(ORIGINAL) != parity.normalise(changed), why


def test_a_comment_cannot_smuggle_a_token_in() -> None:
    """Comments are stripped, so nothing inside one reaches the comparison."""
    assert parity.normalise("// uint256 x = 1;\nlibrary L {}") == parity.normalise("library L {}")


# --- the set compared is the set the vectors exercise -----------------------


def test_every_library_the_exposer_imports_is_checked_for_parity() -> None:
    """A library added to `Exposer.sol` and not to `LIBRARIES` would be fuzzed
    against Uniswap and never checked against PancakeSwap — the exact gap this
    script was written to close, reopened one import at a time."""
    exposer = REPO / "vetting" / "forge" / "src" / "Exposer.sol"
    if not exposer.is_file():
        pytest.skip("no Exposer.sol")

    imported = set(re.findall(r"libraries/(\w+)\.sol", exposer.read_text()))
    compared = {name for name, _local, _remote in parity.LIBRARIES}

    assert imported <= compared, f"fuzzed but never checked against the fork: {imported - compared}"


def test_the_remote_paths_are_pinned_to_a_commit_and_not_to_a_branch() -> None:
    """A record that reads `main` describes whatever `main` was that afternoon."""
    assert re.fullmatch(r"[0-9a-f]{40}", parity.PANCAKE_COMMIT)
    assert parity.PANCAKE_COMMIT in parity.raw_url("projects/x.sol")


# --- three outcomes, and the one that must never be a pass ------------------


def test_an_unreadable_reference_is_unavailable_and_not_a_pass() -> None:
    """`vetting/forge/lib` is gitignored. On a machine that has never run
    `make setup` there is nothing to compare against, and reporting that as
    agreement is the failure mode this repository has already shipped."""
    missing = parity.compare_one("TickMath", "nowhere/TickMath.sol", "projects/x.sol")

    assert missing["status"] == "UNAVAILABLE"
    assert "make setup" in missing["detail"]


# --- the recorded run -------------------------------------------------------


def test_the_recorded_run_covers_every_library_and_agrees_with_itself() -> None:
    """What is on disk, checked for internal consistency rather than re-fetched."""
    path = REPO / "vetting" / "runs" / "fork-parity.json"
    if not path.is_file():
        pytest.skip("no fork-parity run; run `make fork-parity`")

    run = json.loads(path.read_text())

    assert run["libraries"] == len(run["checks"]) == len(parity.LIBRARIES)
    assert run["identical"] == sum(1 for c in run["checks"] if c["status"] == "PASS")
    # The outcome cannot read PASS while a check does not.
    if run["outcome"] == "PASS":
        assert run["identical"] == run["libraries"]
    assert run["pancakeswap"]["commit"] == parity.PANCAKE_COMMIT, (
        "the recorded run was taken against a different commit than the script now pins"
    )
