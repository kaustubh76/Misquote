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

import pytest

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


# --- the tape gate measured the wrong thing ---------------------------------


def _tape_db(tmp_path, monkeypatch, runs, *, record_coverage=True):
    """A database holding `runs` of read blocks, and nothing between them."""
    from misquote.chain.addresses import pool_for
    from misquote.core.tickmath import get_sqrt_ratio_at_tick
    from misquote.core.types import Event, PoolMeta
    from misquote.indexer import store

    ref = pool_for(56)
    db = tmp_path / "tape.db"
    conn = store.connect(db)
    store.register_pool(
        conn,
        PoolMeta(
            address=ref.address,
            chain_id=56,
            token0=ref.token0,
            token1=ref.token1,
            dec0=ref.dec0,
            dec1=ref.dec1,
            fee_pips=ref.fee_pips,
            tick_spacing=ref.tick_spacing,
            fee_protocol=ref.fee_protocol,
        ),
    )
    for lo, hi in runs:
        events = [
            Event(
                block=block,
                log_index=0,
                ts=int(block * 0.45),
                kind="swap",
                tx=f"0x{block:064x}",
                amount0=-(10**20),
                amount1=10**20,
                sqrt_price_x96=get_sqrt_ratio_at_tick(-64180),
                liquidity=10**24,
                tick=-64180,
            )
            for block in (lo, hi)
        ]
        store.write_events(
            conn,
            ref.address,
            events,
            advance_cursor_to=hi,
            covered=(lo, hi) if record_coverage else None,
            now_ts=0,
        )
    conn.close()
    monkeypatch.setenv("DB_PATH", str(db))


DAY_IN_BLOCKS = int(86_400 / 0.45)


def test_a_tape_with_a_hole_in_it_does_not_pass(tmp_path, monkeypatch) -> None:
    """One day at each end of a twenty-six day span.

    `(max(ts) - min(ts)) / 86400` calls that twenty-six days and passed the gate.
    It is the shape every interrupted backfill leaves, and the shape the tail
    creates on purpose when it primes the cursor at the head.
    """
    _tape_db(
        tmp_path,
        monkeypatch,
        [(0, DAY_IN_BLOCKS), (25 * DAY_IN_BLOCKS, 26 * DAY_IN_BLOCKS)],
    )

    check = gng.check_tape()
    assert check.status == gng.UNVERIFIED, check.detail
    assert "unbroken" in check.detail


def test_an_unbroken_thirty_days_does_pass(tmp_path, monkeypatch) -> None:
    """The other half: the gate must still be reachable, or it is a gate that
    can never go green and says nothing."""
    _tape_db(tmp_path, monkeypatch, [(0, 30 * DAY_IN_BLOCKS)])

    check = gng.check_tape()
    assert check.status == gng.PASS, check.detail


def test_rows_without_recorded_coverage_are_unknown_not_complete(tmp_path, monkeypatch) -> None:
    """A database written before coverage existed holds real events and no record
    of what was read to find them. The badge's rule: unknown does not become
    pass, however many rows are in the table."""
    _tape_db(tmp_path, monkeypatch, [(0, 30 * DAY_IN_BLOCKS)], record_coverage=False)

    check = gng.check_tape()
    assert check.status == gng.UNVERIFIED
    assert "no coverage recorded" in check.detail


# --- nothing asked whether a card still matched the engine -------------------


def _artifacts(tmp_path, monkeypatch, files: dict[str, dict]):
    """An artifact directory holding exactly `files`, and nothing else."""
    import json

    directory = tmp_path / "artifacts"
    directory.mkdir()
    for name, payload in files.items():
        (directory / name).write_text(json.dumps(payload))
    monkeypatch.setattr(gng, "ARTIFACTS", directory)
    monkeypatch.setattr(gng, "REPLAY_ARTIFACTS", tuple(files))
    return directory


def _head() -> str:
    import subprocess

    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=gng.REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_a_card_generated_at_head_is_current(tmp_path, monkeypatch) -> None:
    """The only state that earns a green tick: nothing has landed since."""
    _artifacts(tmp_path, monkeypatch, {"build.json": {"build": {"git_sha": _head()}}})

    check = gng.check_artifact_freshness()
    assert check.status == gng.PASS, check.detail


def test_a_card_generated_before_an_engine_commit_is_named(tmp_path, monkeypatch) -> None:
    """The defect this gate exists for.

    The published cards were replayed at a capital basis of 1000, with a sigma
    estimator that clipped 27.8% of its own sample and an LVR equation clamping
    a price it should not have — four consecutive fixes to the quote's inputs
    landed after they were written, and nothing anywhere noticed.
    """
    import subprocess

    # The oldest commit that touched the replay engine, which is by definition
    # behind every engine change since. Derived rather than pinned: a hardcoded
    # sha would stop being behind anything the day history is rewritten.
    old = subprocess.run(
        ["git", "log", "--format=%H", "--reverse", "--", *gng.ENGINE_PATHS],
        cwd=gng.REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()[0]
    _artifacts(tmp_path, monkeypatch, {"warden.json": {"provenance": {"git_sha": old}}})

    check = gng.check_artifact_freshness()
    assert check.status == gng.UNVERIFIED
    assert "warden.json" in check.detail
    assert "engine commit" in check.detail


def test_a_card_with_no_recorded_commit_is_unverified_not_green(tmp_path, monkeypatch) -> None:
    """ "We cannot tell" is not "it is current", and only one of them is a tick.

    This is the state four of the six published cards are in: they carry no
    `git_sha` of their own and are stamped by proxy through `build.json`, which
    the landing page renders once for all of them. A gate that passed on a
    missing reading would certify precisely the artifacts nothing can place.
    """
    _artifacts(tmp_path, monkeypatch, {"grid.json": {"replay": {"net_quote": -1.0}}})

    check = gng.check_artifact_freshness()
    assert check.status == gng.UNVERIFIED
    assert "records no commit" in check.detail


def test_a_commit_this_repository_does_not_have_is_not_a_pass(tmp_path, monkeypatch) -> None:
    """Rebased, squashed, or generated on a branch nobody else has.

    `git log <unknown>..HEAD` exits non-zero, and reading that as "no commits
    since, therefore current" would turn the one unplaceable case into the
    cleanest possible green.
    """
    _artifacts(tmp_path, monkeypatch, {"build.json": {"build": {"git_sha": "0" * 40}}})

    check = gng.check_artifact_freshness()
    assert check.status == gng.UNVERIFIED
    assert "does not have" in check.detail


def test_a_commit_touching_nothing_the_engine_owns_leaves_it_current(tmp_path, monkeypatch) -> None:
    """The gate has to be quiet about changes that cannot move a number.

    A gate that goes amber on a README edit is one people learn to wave through,
    and then it is not a gate. `ENGINE_PATHS` is deliberately narrower than
    `packages/` for this reason.
    """
    import subprocess

    # The most recent commit that touched *only* docs and the front end.
    log = subprocess.run(
        ["git", "log", "--format=%H", "-40"],
        cwd=gng.REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    for sha in log:
        touched = subprocess.run(
            ["git", "log", "--oneline", f"{sha}..HEAD", "--", *gng.ENGINE_PATHS],
            cwd=gng.REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if not touched:
            _artifacts(tmp_path, monkeypatch, {"build.json": {"build": {"git_sha": sha}}})
            assert gng.check_artifact_freshness().status == gng.PASS
            return
    pytest.skip("every commit in the last 40 touched the engine")


# --- the advantage report's per-task provenance -----------------------------
#
# The gate read one top-level `source` field. A report can carry two tasks on
# real swaps and a third on two constructed venues, and that header still says
# "chain" — which is the same shape of hole `check_tape` was fixed for, and the
# shape task 3 actually had: both of its venues were `synthetic_events()`, so
# "which pool would you choose?" was answered by a random seed under a
# chain-sourced badge.


def _advantage_artifact(tmp_path, monkeypatch, sources, *, drop_source=False):
    """Write a minimal advantage.json with one task per entry in `sources`."""
    import json

    names = ["Earn — fees", "Protect — one-way flow", "Choose — which pool"]
    tasks = []
    for name, source in zip(names, sources, strict=True):
        task = {"task": name, "without_agent": f"baseline for {name}"}
        if not drop_source:
            task["source"] = source
        tasks.append(task)

    artifact = tmp_path / "apps" / "web" / "public" / "artifacts" / "advantage.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps({"source": "chain", "tasks": tasks, "summary": {"quotable": len(tasks)}})
    )
    monkeypatch.setattr(gng, "REPO", tmp_path)
    return artifact


def test_one_synthetic_task_keeps_the_report_off_green(tmp_path, monkeypatch) -> None:
    """Two real tasks and one constructed one is two real tasks, not three.

    The header says "chain" here, which is exactly the report this gate used to
    pass. The track asks for three real tasks and the arithmetic is not ours to
    round up.
    """
    _advantage_artifact(tmp_path, monkeypatch, ["chain", "chain", "synthetic"])

    check = gng.check_agent_advantage_report()
    assert check.status == gng.UNVERIFIED, check.detail
    assert "2/3" in check.detail
    assert "Choose" in check.detail, "the amber must name which task is not real"


def test_three_chain_tasks_pass(tmp_path, monkeypatch) -> None:
    """The gate must still be reachable, or it is one that can never go green."""
    _advantage_artifact(tmp_path, monkeypatch, ["chain", "chain", "chain"])

    check = gng.check_agent_advantage_report()
    assert check.status == gng.PASS, check.detail


def test_a_report_predating_the_field_is_unknown_not_real(tmp_path, monkeypatch) -> None:
    """No per-task `source` is a report written before provenance was recorded.

    Its header may well say "chain". That is the claim, not the evidence, and
    unknown does not become pass — the same rule the vetting badge and
    `check_tape` already hold to.
    """
    _advantage_artifact(tmp_path, monkeypatch, ["chain"] * 3, drop_source=True)

    check = gng.check_agent_advantage_report()
    assert check.status == gng.UNVERIFIED, check.detail
