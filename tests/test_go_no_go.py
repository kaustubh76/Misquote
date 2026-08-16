"""A gate that was not run may not report a pass.

`scripts/go_no_go.py` opens by stating its own rule: "Anything it cannot verify
is reported as UNVERIFIED rather than assumed — an amber light, never a green
one." `/status` repeats the sentence two inches above the gate list it renders.

Two gates broke it. Without `--mainnet`, `check_signer_configured` and
`check_position_cap` returned:

    Check("signer", PASS, "not checked (add --mainnet)")

A green tick, with the words "not checked" printed beside it, counted into the
summary as a pass — so an offline run reported `5 passed · 0 failed ·
5 unverified` for a run that had established five things and skipped two. The
overall verdict was unaffected, because five other gates were already amber; the
count was simply wrong, and it was wrong in the direction that flatters.

Nothing tested this file at all before now.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "scripts" / "go_no_go.py"

#: Phrases that describe a check which did not happen. A `Check` carrying one of
#: these is reporting an absence, and an absence is never a pass.
DID_NOT_RUN = ("not checked", "not run", "skipped", "was not asked", "did not run")


def load():
    spec = importlib.util.spec_from_file_location("misquote_go_no_go", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gng = load()


def test_no_pass_is_constructed_with_a_detail_that_says_it_did_not_run() -> None:
    """Read off the source, so a new gate is covered the moment it is written.

    Calling every gate instead would need a chain, a tape and a filled journal —
    which is how a rule like this ends up tested for two functions and not for
    the eighth one somebody adds later.
    """
    offenders: list[str] = []

    for node in ast.walk(ast.parse(SOURCE.read_text())):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Check"):
            continue
        if len(node.args) < 3:
            continue

        status = node.args[1]
        detail = node.args[2]
        is_pass = isinstance(status, ast.Name) and status.id == "PASS"
        text = detail.value if isinstance(detail, ast.Constant) else ""

        if is_pass and isinstance(text, str) and any(p in text.lower() for p in DID_NOT_RUN):
            name = node.args[0]
            label = name.value if isinstance(name, ast.Constant) else "?"
            offenders.append(f"line {node.lineno}: {label!r} -> PASS, {text!r}")

    assert not offenders, (
        "these gates report a pass for a check that did not happen, which is the "
        "one thing this script's docstring promises it never does:\n  " + "\n  ".join(offenders)
    )


def test_the_mainnet_only_gates_are_amber_when_the_run_is_not_mainnet() -> None:
    """The two that were wrong, called directly. Both are pure."""
    for check in (gng.check_signer_configured(False), gng.check_position_cap(False)):
        assert check.status == gng.UNVERIFIED, (
            f"{check.name} reports {check.status} without --mainnet; it checked nothing"
        )
        assert check.remedy, f"{check.name} is amber and says nothing about how to make it green"


def test_the_scan_is_looking_at_real_gate_constructions() -> None:
    """A scan that matches no `Check(...)` passes the rule above for free."""
    calls = [
        node
        for node in ast.walk(ast.parse(SOURCE.read_text()))
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Check"
    ]
    assert len(calls) > 20, f"only {len(calls)} Check() constructions found in {SOURCE}"


def test_unverified_keeps_the_verdict_off_green() -> None:
    """Amber has to mean something, or moving a gate to amber costs nothing.

    Both fixes above turn a green tick amber. That is only an improvement if an
    amber gate actually withholds the go-ahead — otherwise the change is
    cosmetic and the next person is free to revert it.
    """
    checks = [
        gng.Check("a", gng.PASS, "fine"),
        gng.Check("b", gng.UNVERIFIED, "could not tell"),
    ]
    verdict, code = gng.outcome(checks)
    assert verdict == "NOT YET"
    assert code == 2

    verdict, code = gng.outcome([gng.Check("a", gng.PASS, "fine")])
    assert verdict == "GO"
    assert code == 0
