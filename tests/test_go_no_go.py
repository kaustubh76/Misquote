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
    assert "engine change" in check.detail
    # Named — which is what this test is called and what the gate is for.
    #
    # The name moved out of `detail` into `data` when the summary became a
    # count, and that is a better artifact: six stale cards should not produce
    # six sentences. What it must not become is unnameable, so the assertion
    # follows the name rather than the prose it used to sit in.
    assert [b["artifact"] for b in check.data["behind"]] == ["warden.json"]
    assert check.data["behind"][0]["commits"] > 0


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
    assert "no commit at all" in check.detail
    assert check.data["unstamped"] == ["grid.json"]


def test_a_commit_this_repository_does_not_have_is_not_a_pass(tmp_path, monkeypatch) -> None:
    """Rebased, squashed, or generated on a branch nobody else has.

    `git log <unknown>..HEAD` exits non-zero, and reading that as "no commits
    since, therefore current" would turn the one unplaceable case into the
    cleanest possible green.
    """
    _artifacts(tmp_path, monkeypatch, {"build.json": {"build": {"git_sha": "0" * 40}}})

    check = gng.check_artifact_freshness()
    assert check.status == gng.UNVERIFIED
    # The *reason* travels with the artifact, in `data`, not in the count.
    # "1 record no commit at all" would be true of a card that simply has no
    # `git_sha`, and this case is different and worse: it has one, and the
    # repository has never heard of it.
    assert check.data["unstamped"] == [
        "build.json (records " + "0" * 40 + ", which this repository does not have)"
    ]


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


# --- badge coverage, derived from what is published --------------------------
#
# The gate this replaced compared one hand-maintained list against disk, so it
# agreed with itself while `TARGET_POOL_WIDE` was quoted by the advantage
# report's third task and named in no pool list in the repository.


def _coverage_fixture(tmp_path, monkeypatch, payloads: dict[str, dict], badges: list[str]):
    import json

    root = tmp_path / "apps" / "web" / "public" / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (root / name).write_text(json.dumps(payload))

    badge_dir = tmp_path / "vetting" / "badges"
    badge_dir.mkdir(parents=True, exist_ok=True)
    for address in badges:
        (badge_dir / f"{address.lower()}.json").write_text("{}")

    monkeypatch.setattr(gng, "REPO", tmp_path)


def test_pool_addresses_are_read_from_pool_fields_only(tmp_path, monkeypatch) -> None:
    """An artifact is full of addresses. A token, a router or a registry is not
    a pool going unvetted, and counting one would make this gate noise."""
    _coverage_fixture(
        tmp_path,
        monkeypatch,
        {
            "warden.json": {
                "pool": "PancakeSwap v3 WBNB/USDT 0.05% · 0xAAAA000000000000000000000000000000000001",
                "settlement_token": "0xBBBB000000000000000000000000000000000002",
            }
        },
        badges=[],
    )

    found = gng.published_pools()
    assert set(found) == {"0xaaaa000000000000000000000000000000000001"}
    assert "warden.json" in found["0xaaaa000000000000000000000000000000000001"]


def test_a_pool_the_site_quotes_but_nobody_verified_is_amber(tmp_path, monkeypatch) -> None:
    """The direction the real failure came from, and the one a list cannot
    catch: publishing a number about a pool that was never read from chain."""
    _coverage_fixture(
        tmp_path,
        monkeypatch,
        {"warden.json": {"pool": "some pool · 0xDEAD000000000000000000000000000000000001"}},
        badges=[],
    )

    check = gng.check_badge_coverage()
    assert check.status == gng.UNVERIFIED, check.detail
    assert "not in KNOWN_POOLS" in check.detail
    assert "warden.json" in check.detail, "the amber must name where it is published"


def test_a_verified_pool_with_no_badge_is_amber(tmp_path, monkeypatch) -> None:
    """The other half, which `make vet` satisfies and which is not sufficient
    on its own."""
    from misquote.chain.addresses import known_pools_on

    listed = known_pools_on(56)
    _coverage_fixture(tmp_path, monkeypatch, {}, badges=[p.address for p in listed[:-1]])

    check = gng.check_badge_coverage()
    assert check.status == gng.UNVERIFIED, check.detail
    assert listed[-1].label in check.detail


def test_the_gate_is_reachable_when_everything_lines_up(tmp_path, monkeypatch) -> None:
    """A gate that can never go green says nothing."""
    from misquote.chain.addresses import known_pools_on

    listed = known_pools_on(56)
    _coverage_fixture(
        tmp_path,
        monkeypatch,
        {"warden.json": {"pool": f"flagship · {listed[0].address}"}},
        badges=[p.address for p in listed],
    )

    check = gng.check_badge_coverage()
    assert check.status == gng.PASS, check.detail


# --- the signer gate, which used to end on a manual step -------------------
#
# Its last line was "a key is set; verify by hand that it is not a main wallet".
# A gate whose remedy is a human is the gate in front of the write path that
# nobody runs. These are the branches that replaced it.

# A key and the address it signs for. Written out rather than derived, so a
# change in `eth_account` shows up here as a failure rather than as agreement
# between two calls to the same function.
GATE_KEY = "0x" + "11" * 32
GATE_ADDRESS = "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A"


def test_the_signer_gate_passes_when_the_key_signs_for_the_declared_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MISQUOTE_PRIVATE_KEY", GATE_KEY)
    monkeypatch.setenv("MISQUOTE_OPERATOR_ADDRESS", GATE_ADDRESS.lower())
    monkeypatch.delenv("MISQUOTE_SIGNER_ADDRESS", raising=False)
    check = gng.check_signer_configured(True)
    assert check.status == gng.PASS
    assert GATE_ADDRESS in check.detail


def test_the_signer_gate_fails_when_the_key_signs_for_somebody_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case this gate exists for, and the case this checkout is in."""
    monkeypatch.setenv("MISQUOTE_PRIVATE_KEY", GATE_KEY)
    monkeypatch.setenv("MISQUOTE_OPERATOR_ADDRESS", "0x" + "22" * 20)
    monkeypatch.delenv("MISQUOTE_SIGNER_ADDRESS", raising=False)
    check = gng.check_signer_configured(True)
    assert check.status == gng.FAIL
    # Both addresses, because "the key is wrong" and "the declaration is wrong"
    # are different repairs and the gate cannot know which one is meant.
    assert GATE_ADDRESS in check.detail
    assert "0x" + "22" * 20 in check.detail.lower()


def test_the_signer_gate_stays_amber_when_nothing_is_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unchanged for anyone who has not opted in — and it says what would make
    it green, which the sentence it replaced did not."""
    monkeypatch.setenv("MISQUOTE_PRIVATE_KEY", GATE_KEY)
    monkeypatch.delenv("MISQUOTE_OPERATOR_ADDRESS", raising=False)
    monkeypatch.delenv("MISQUOTE_SIGNER_ADDRESS", raising=False)
    check = gng.check_signer_configured(True)
    assert check.status == gng.UNVERIFIED
    assert "MISQUOTE_OPERATOR_ADDRESS" in check.remedy


def test_a_malformed_declaration_fails_rather_than_going_amber(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Amber and red mean different things to whoever reads this.

    Amber is "nobody has set this up yet" and is expected on most runs. A typed
    declaration that does not parse is a misconfiguration, and reporting it as
    amber would file it under the one status a reader is used to waving through.
    """
    monkeypatch.setenv("MISQUOTE_PRIVATE_KEY", GATE_KEY)
    monkeypatch.setenv("MISQUOTE_OPERATOR_ADDRESS", "0xnope")
    monkeypatch.delenv("MISQUOTE_SIGNER_ADDRESS", raising=False)
    check = gng.check_signer_configured(True)
    assert check.status == gng.FAIL


def test_an_unparseable_key_fails_the_gate_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`go_no_go.py` is a checklist. A gate that raises takes the whole
    checklist down and reports nothing about the other twenty."""
    monkeypatch.setenv("MISQUOTE_PRIVATE_KEY", "not-a-key")
    monkeypatch.setenv("MISQUOTE_OPERATOR_ADDRESS", GATE_ADDRESS)
    monkeypatch.delenv("MISQUOTE_SIGNER_ADDRESS", raising=False)
    check = gng.check_signer_configured(True)
    assert check.status == gng.FAIL
    assert "not a key" in check.detail


def test_the_signer_gate_is_amber_when_a_delegate_signs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing is misconfigured — the key is exactly what was declared — and it
    still is not green. A green tick here reads as "the operator signed this",
    and what happened is "a wallet the operator nominated signed this"."""
    monkeypatch.setenv("MISQUOTE_PRIVATE_KEY", GATE_KEY)
    monkeypatch.setenv("MISQUOTE_OPERATOR_ADDRESS", "0x" + "22" * 20)
    monkeypatch.setenv("MISQUOTE_SIGNER_ADDRESS", GATE_ADDRESS)
    check = gng.check_signer_configured(True)
    assert check.status == gng.UNVERIFIED
    assert "delegate" in check.detail
    assert check.data["operator"] != check.data["signing_for"]


def test_a_delegate_declaration_that_does_not_match_the_key_still_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property the second variable must not cost. Naming another wallet is
    the escape hatch; naming none is not."""
    monkeypatch.setenv("MISQUOTE_PRIVATE_KEY", GATE_KEY)
    monkeypatch.setenv("MISQUOTE_OPERATOR_ADDRESS", "0x" + "22" * 20)
    monkeypatch.setenv("MISQUOTE_SIGNER_ADDRESS", "0x" + "33" * 20)
    check = gng.check_signer_configured(True)
    assert check.status == gng.FAIL
    assert "MISQUOTE_SIGNER_ADDRESS" in check.detail


# --- the burn-in gate -------------------------------------------------------
#
# `test_a_tape_with_a_hole_in_it_does_not_pass` above is the same test for the
# same defect on a different quantity. The tape gate computed
# `(max(ts) - min(ts))` and passed a database holding one day at each end of a
# twenty-six day span; the burn-in gate computed `(max(ts) - min(ts))` and passed
# two ten-minute runs a day apart. One was fixed and the lesson was recorded as a
# fact about tapes, so it did not reach the other.


def _journal(tmp_path, monkeypatch, files: dict[str, list[dict]]):
    """A journal directory, written the way `Journal.write` writes one."""
    import json

    gng = load()
    directory = tmp_path / "journal"
    directory.mkdir(exist_ok=True)
    for name, rows in files.items():
        (directory / f"{name}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setenv("MISQUOTE_JOURNAL_DIR", str(directory))
    return gng


def _run(
    start: int,
    hours: float,
    *,
    chain_id: int = 97,
    interval: int = 5,
    can_sign: bool | None = False,
) -> list[dict]:
    """One continuous run: a `run_start` and a decision every `interval` seconds.

    `can_sign=None` writes no such field, which is what a journal from before
    the entrypoint recorded it looks like.
    """
    rows = [
        {
            "event": "run_start",
            "agent": "warden",
            "chain_id": chain_id,
            "reconciled": True,
            "ts": start,
            **({} if can_sign is None else {"can_sign": can_sign}),
        }
    ]
    for offset in range(0, int(hours * 3600), interval):
        rows.append({"event": "decision", "ts": start + offset})
    return rows


def test_two_short_runs_a_day_apart_do_not_pass(tmp_path, monkeypatch) -> None:
    """The defect, stated as a test.

    The journal is opened in append mode, so one file holds every run the agent
    has ever made. `(max - min)` over that file is the distance between the two
    ends and says nothing about the middle — so ten minutes on Monday and ten
    minutes on Tuesday reported **25.0h** and passed a gate whose own remediation
    line reads "the gate is 24h *unattended*".
    """
    gng = _journal(
        tmp_path,
        monkeypatch,
        {"warden": _run(0, 10 / 60) + _run(25 * 3600, 10 / 60)},
    )
    check = gng.check_burn_in()

    assert check.status == gng.UNVERIFIED, check.detail
    assert "2 run(s)" in check.detail
    # The number the old gate would have printed, carried beside the real one so
    # a reader can see which question is being answered.
    # The number the old gate would have printed is ~25h (the gap plus the run);
    # the real one is ~0.2h. Both appear, so a reader can see which question is
    # being answered rather than having to know.
    assert "file spans 25." in check.detail
    assert "unbroken run 0.2h" in check.detail


def test_one_unbroken_day_does_pass(tmp_path, monkeypatch) -> None:
    """A gate that can never go green says nothing."""
    gng = _journal(tmp_path, monkeypatch, {"warden": _run(0, 24.5)})
    check = gng.check_burn_in()

    assert check.status == gng.PASS, check.detail
    assert "1 run(s)" in check.detail


def test_a_mainnet_day_is_a_burn_in_and_the_detail_says_what_kind(tmp_path, monkeypatch) -> None:
    """The requirement that was `chains == {97}`, and what replaced it.

    That gate could not be passed by a project spending its last days on
    mainnet, and a gate that cannot pass is not a standard. But relaxing it to
    "any chain" would drop a real distinction, so the distinction moved into the
    detail: on mainnet `--broadcast` is refused in `agents/warden/__main__.py`,
    so a mainnet burn-in is a day of reading and deciding with signing
    impossible. Narrower than a chapel run that could sign, and said rather than
    implied by a green tick.
    """
    gng = _journal(tmp_path, monkeypatch, {"warden": _run(0, 24.5, chain_id=56)})
    check = gng.check_burn_in()

    assert check.status == gng.PASS, check.detail
    assert "on BSC mainnet" in check.detail
    assert "signing refused" in check.detail


def test_a_journal_that_mixes_chains_is_not_one_run(tmp_path, monkeypatch) -> None:
    """The discriminator kept in place of the one removed.

    Not hypothetical: `data/journal/warden.jsonl` in this repository already
    holds chain-56 rows, so a chapel run appended to it leaves a stretch with no
    gap in it that is nonetheless two deployments — and the hours would be
    counted across both as though one process had survived them.
    """
    rows = _run(0, 12.5, chain_id=56) + _run(12 * 3600 + 1900, 12.5, chain_id=97)
    gng = _journal(tmp_path, monkeypatch, {"warden": rows})
    check = gng.check_burn_in()

    assert check.status == gng.UNVERIFIED, check.detail
    assert "mixes chain(s) [56, 97]" in check.detail


def test_a_run_that_could_spend_is_not_reported_as_one_that_could_not(
    tmp_path, monkeypatch
) -> None:
    """Green means 24h; the detail says how much was at risk while it ran."""
    gng = _journal(tmp_path, monkeypatch, {"warden": _run(0, 24.5, chain_id=97, can_sign=True)})
    check = gng.check_burn_in()

    assert check.status == gng.PASS, check.detail
    assert "on chapel" in check.detail
    assert "able to sign" in check.detail


def test_a_journal_with_no_chain_id_cannot_say_where_it_ran(tmp_path, monkeypatch) -> None:
    """This used to be a footnote appended to a **pass**.

    "It never checked the chain" was the defect; a gate that notes the absence
    of a chain_id in prose and then goes green is that defect surviving in the
    one case where the journal cannot answer.
    """
    rows = [{k: v for k, v in row.items() if k != "chain_id"} for row in _run(0, 24.5)]
    gng = _journal(tmp_path, monkeypatch, {"warden": rows})
    check = gng.check_burn_in()

    assert check.status == gng.UNVERIFIED, check.detail
    assert "no chain_id" in check.detail


def test_other_agents_journals_are_visible_rather_than_ignored(tmp_path, monkeypatch) -> None:
    """Journals became per-agent, and this gate read one hardcoded filename.

    `Journal` writes `{agent}.jsonl`, so every agent but the Warden landed in a
    file the gate could not see. A 24-hour Grid burn-in left it reporting 0.0h —
    not wrong about the Warden, and silent about the evidence that existed.
    """
    gng = _journal(
        tmp_path,
        monkeypatch,
        {"warden": _run(0, 1), "grid": _run(0, 3), "sentinel": _run(0, 2)},
    )
    check = gng.check_burn_in()

    assert check.status == gng.UNVERIFIED
    assert "grid 3.0h" in check.detail and "sentinel 2.0h" in check.detail


def test_a_missing_warden_journal_says_what_it_did_find(tmp_path, monkeypatch) -> None:
    """ "No burn-in" and "a burn-in by a different agent" are different facts."""
    gng = _journal(tmp_path, monkeypatch, {"grid": _run(0, 25)})
    check = gng.check_burn_in()

    assert check.status == gng.UNVERIFIED
    assert "no warden journal" in check.detail
    assert "grid 25.0h" in check.detail


def test_a_half_written_final_line_loses_one_row_not_the_file(tmp_path, monkeypatch) -> None:
    """What a killed process leaves. Refusing the whole file would lose the
    evidence the run is trying to produce."""
    import json

    gng = load()
    directory = tmp_path / "journal"
    directory.mkdir(exist_ok=True)
    rows = _run(0, 24.5)
    text = "".join(json.dumps(r) + "\n" for r in rows) + '{"event": "decis'
    (directory / "warden.jsonl").write_text(text)
    monkeypatch.setenv("MISQUOTE_JOURNAL_DIR", str(directory))

    check = gng.check_burn_in()
    assert check.status == gng.PASS, check.detail


def test_the_gap_threshold_is_derived_from_the_cadences() -> None:
    """Not a round number somebody liked.

    The policy decides every 5s and the chain is polled every 60s, so the
    threshold has to sit above the poll interval — comfortably, or a slow tick
    reads as a restart — and below anything a crash-and-restart could hide in.
    """
    from misquote.chain.live_source import DEFAULT_POLL_SECONDS
    from misquote.tearsheet.generate import MAX_JOURNAL_GAP_S, unbroken_runs

    # `MAX_JOURNAL_GAP_S` rather than the gate's own copy: the rule moved into
    # `tearsheet/generate.py`, beside the thing that reads journals, when a
    # second reader of the same files turned out to be measuring them a
    # different way. One name, so it cannot come to mean two things.
    assert MAX_JOURNAL_GAP_S > DEFAULT_POLL_SECONDS * 5
    assert MAX_JOURNAL_GAP_S < 3600, "an hour-long hole is a restart, not a tick"

    # And it must actually split on that boundary.
    assert len(unbroken_runs([0, MAX_JOURNAL_GAP_S + 1])) == 2
    assert len(unbroken_runs([0, MAX_JOURNAL_GAP_S - 1])) == 1


#: A passing vitest run, tail-first as `check_web_component_suite` sees it.
VITEST_TAIL = """
 Test Files  43 passed (43)
      Tests  469 passed (469)
   Start at  14:05:57
   Duration  21.76s (transform 2.71s, setup 9.44s)

(node:48257) ExperimentalWarning: localStorage is not available
(Use `node --trace-warnings ...` to show where the warning was created)
"""


def test_a_passing_component_suite_publishes_its_result_and_not_its_trailer() -> None:
    """What `/status` showed a reader as the result of 469 tests.

    vitest prints a node warning after its summary, so `lines[-1]` was

        (Use `node --trace-warnings ...` to show where the warning was created)

    and that is what the gate published as `detail` — rendered on `/status` in
    monospace under "web component suite", backticks and all. It also made
    `test_prose_is_rendered` go red, which is how it was found: the field had
    become markdown-bearing without anybody writing markdown.
    """
    module = load()
    lines = [line.strip() for line in VITEST_TAIL.strip().splitlines() if line.strip()]

    detail = module._summary_line(lines, "Tests ", lines[-1])

    assert detail == "Tests  469 passed (469)"
    assert "trace-warnings" not in detail


#: A passing `make web-check`, whose static server logs on after the check.
WEB_CHECK_TAIL = """
  ok    nothing animates under reduce   47 routes

  every route clean in both themes and at 390px, with 47 distinct titles.
::1 - - [06/Sep/2026 14:45:08] "GET /tape/index.txt?_rsc=doD_FWmrzap9 HTTP/1.1" 200 -
"""


def test_a_passing_browser_suite_publishes_its_result_and_not_the_server_log() -> None:
    """The same shape, one gate over. `check-pages.mjs` finishes and the static
    server it loaded from keeps logging until it is killed, so the last line was
    an HTTP access log — published as the result of every route in two themes at
    two viewports."""
    module = load()
    lines = [line.strip() for line in WEB_CHECK_TAIL.strip().splitlines() if line.strip()]

    detail = module._summary_line(lines, "every route clean", lines[-1])

    assert detail.startswith("every route clean in both themes")
    assert "GET /" not in detail


#: A `make web-check` run where the only thing that went wrong was a cold API.
ASLEEP = """
  FAIL  tape-dark-1280                  page.goto: Timeout 60000ms exceeded. — still in flight: 60s https://misquote-api.example/tape
  1 failure(s):
make: *** [web-check] Error 1
"""

#: And one where a route is genuinely broken.
BROKEN = """
  FAIL  vetting-dark-390                 2 animation(s) still running — CSSTransition
  1 failure(s):
make: *** [web-check] Error 1
"""


def _browser_gate(monkeypatch: pytest.MonkeyPatch, output: str, base: str | None):
    monkeypatch.setattr(gng, "_wake_api", lambda: base)
    monkeypatch.setattr(gng, "_run", lambda *a, **k: (2, output))
    return gng.check_web_browser_suite()


def test_a_sleeping_backend_is_amber_and_not_a_failing_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate put the API to sleep itself and then failed the check that needs it.

    The offline suite ahead of this one runs for five to thirteen minutes and
    the API spins down after about fifteen idle, so `page.goto` timed out
    waiting on `/tape` — twice in four runs. Nothing about the page was
    disproven either time. Red for it teaches a reader to discount the colour,
    which is the argument the missing-Chromium branch already makes.
    """
    check = _browser_gate(monkeypatch, ASLEEP, "https://misquote-api.example")

    assert check.status == gng.UNVERIFIED
    assert "misquote-api.example" in check.detail
    assert "wake it" in (check.remedy or "")


def test_a_route_that_actually_broke_is_still_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """The half that matters: amber is for the backend, not for the page.

    The detail names the route too. It used to be chosen by "starts with / or
    contains a colon-space", which `make: *** [web-check] Error 1` satisfies and
    a failure line without a colon does not — so the finding published for this
    exact case was the make error.
    """
    check = _browser_gate(monkeypatch, BROKEN, "https://misquote-api.example")

    assert check.status == gng.FAIL
    assert "animation" in check.detail
    assert "vetting-dark-390" in check.detail


def test_a_timeout_against_something_that_is_not_the_api_is_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A route hanging on a third party is a page problem and reads as one."""
    hung = ASLEEP.replace("misquote-api.example", "cdn.somewhere-else.example")
    check = _browser_gate(monkeypatch, hung, "https://misquote-api.example")

    assert check.status == gng.FAIL


def test_waking_an_api_that_is_not_configured_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An export with no backend is the ordinary case, not a broken one."""
    monkeypatch.setattr(gng, "API_CONFIG", REPO / "no" / "such" / "api.json")
    assert gng._wake_api() is None


def test_a_chatty_stderr_does_not_evict_what_the_tool_said_on_stdout() -> None:
    """The reason two gates published their tools' noise instead of their results.

    `_run` capped `stdout + stderr` — a concatenation — at four thousand
    characters, so the tail is stderr's whenever stderr is long, and everything
    the command wrote to stdout is gone. `make web-check` writes its verdict to
    stdout and serves the built site from a `http.server` that logs every
    request to stderr, thousands of lines; the gate for the only check that runs
    real layout could see nothing but access logs.

    Asserted against a real subprocess rather than a stub, because the defect is
    in how the two streams are joined and a stub would join them however this
    test decided to.
    """
    module = load()
    noise = "x" * (module.STREAM_TAIL * 3)
    _, output = module._run(
        [
            sys.executable,
            "-c",
            f"import sys; print('every route clean'); sys.stderr.write({noise!r})",
        ]
    )

    assert "every route clean" in output, (
        "stderr evicted stdout, which is the bug — the tool's own result is the "
        "half a gate exists to publish"
    )
    assert output.rstrip().endswith("x"), "and the stderr tail is still there to diagnose with"


def test_a_tool_that_prints_no_summary_still_gets_a_detail() -> None:
    """The fallback is the old behaviour, not an empty string or a crash."""
    module = load()
    lines = ["something went sideways"]

    assert module._summary_line(lines, "Tests ", lines[-1]) == "something went sideways"


# --- the escrow gate --------------------------------------------------------
#
# Added because nothing covered the hire at all. The advantage report gate
# proves an agent beats doing the job yourself; this is the other half of the
# same track's question, and it was held up by a sentence in a document.


def test_the_escrow_gate_reports_what_is_on_record() -> None:
    """It reads the artifact rather than a memory, and never opens green."""
    check = gng.check_escrow_flow()
    assert check.name == "erc-8183 escrow"
    assert check.status in (gng.PASS, gng.FAIL, gng.UNVERIFIED)
    if check.status != gng.PASS:
        assert check.remedy, "the escrow gate is not green and says nothing about how to make it"


def test_the_escrow_gate_will_not_call_a_fork_run_a_mainnet_one() -> None:
    """`escrowed` and `escrowed_on_mainnet` are different claims.

    `prove_escrow_fund.py` writes `escrowed: true` and `escrowed_on_mainnet:
    false` on every fork run, deliberately. A gate reading the wider field would
    go green on a rehearsal.
    """
    source = SOURCE.read_text()
    gate = source[
        source.index("def check_escrow_flow") : source.index("def check_artifact_freshness")
    ]
    assert "escrowed_on_mainnet" in gate
    assert "settle" in gate, "the one call never run outside a fork is not mentioned"


def test_the_escrow_gate_says_who_the_money_moved_between() -> None:
    """A job id and an amount, with nobody named, is not a hire.

    The detail string reached `/status` saying "job 56681 escrowed 1e17 on chain
    56 and was reclaimed" — every fact except the one a marketplace has to
    demonstrate. `/registry` had the same hole and the addresses were in the
    artifact for both of them the whole time.
    """
    same = {"client": "0x0c501EE1", "provider": "0x0c501ee1"}
    both = {"client": "0x0c501EE1924bfb91", "provider": "0xdEaF6a182ECfb667"}

    # Casing is not identity. Checksummed and lower-case spellings of one wallet
    # are one wallet, and reading them as two would report a self-hire as the
    # thing this project is still waiting for.
    assert "hires nobody" in gng._parties(same)
    assert "Two parties" in gng._parties(both)

    # Silence rather than a guess: `hire_agent.py` records no provider, and
    # answering "one wallet" there would publish a self-hire nobody recorded.
    assert gng._parties({"client": "0x0c501EE1"}) == ""
    assert gng._parties({}) == ""


def test_the_parties_clause_changes_the_words_and_not_the_verdict(monkeypatch) -> None:
    """A missing demonstration is not a broken mechanism, and it is appended.

    Two properties in one, because they failed together on the first attempt.

    `fund` and `claimRefund` both mined on mainnet whoever signed them, so
    turning this gate amber because one wallet stood on both sides would report
    a working escrow as a failing one. The distinctness belongs in the detail,
    where a reader can weigh it; `tests/registry/test_two_party_hire.py` is what
    actually asserts the gap.

    And it goes on the end. Spliced into `escrowed` it landed mid-sentence —
    "escrowed 1e17 on chain 56, with one wallet as both client and provider and
    was reclaimed" — which is how a true clause becomes an unreadable one.
    """
    before = gng.check_escrow_flow()
    monkeypatch.setattr(gng, "_parties", lambda proof: "")
    after = gng.check_escrow_flow()

    assert before.status == after.status, "naming the parties changed the verdict"
    assert before.detail != after.detail, "the gate computes the clause and never prints it"
    assert before.detail.startswith(after.detail), (
        "the parties clause is spliced into the middle of the sentence rather "
        "than appended to it"
    )


def test_the_escrow_gate_is_in_the_run() -> None:
    """A gate nothing calls is a gate that cannot fail."""
    source = SOURCE.read_text()
    assert "check_escrow_flow()," in source, "check_escrow_flow is defined and never run"
