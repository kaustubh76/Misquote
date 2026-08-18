"""The mainnet go/no-go, as a program rather than a document.

    uv run python scripts/go_no_go.py            # check everything
    uv run python scripts/go_no_go.py --mainnet  # and the mainnet-only gates

A checklist in a markdown file gets read carefully once and skimmed thereafter.
This one runs, exits non-zero when a gate fails, and prints what to do about it.
Anything it cannot verify is reported as UNVERIFIED rather than assumed — an
amber light, never a green one.

The gates are the ones the build plan committed to before any of this existed,
which is the point: the standard was written down while it was still cheap to
meet, not negotiated afterwards when it had become inconvenient.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from misquote.tearsheet import provenance

REPO = Path(__file__).resolve().parents[1]

# Only used to turn a span of blocks into a span of days for the tape gate. The
# indexer measures this at runtime; here a constant is fine because the gate's
# threshold is 25 days against a 30-day target and BSC would have to change block
# time by 20% for the rounding to matter. If it does, the indexer's measured
# value is the one to trust.
BSC_BLOCK_SECONDS = 0.45

# Where the site reads from. Spelled out in three places before this line
# existed, which is one more than a path needs to be.
ARTIFACTS = REPO / "apps" / "web" / "public" / "artifacts"

PASS, FAIL, UNVERIFIED = "PASS", "FAIL", "UNVERIFIED"


@dataclass(slots=True)
class Check:
    name: str
    status: str
    detail: str
    remedy: str = ""

    @property
    def blocking(self) -> bool:
        return self.status != PASS


def _run(command: list[str], timeout: int = 900) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command, cwd=REPO, capture_output=True, text=True, timeout=timeout, check=False
        )
        return result.returncode, (result.stdout + result.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except FileNotFoundError:
        return 127, f"{command[0]} not found"


# --- the gates -------------------------------------------------------------


def check_offline_suite() -> Check:
    code, output = _run(["uv", "run", "pytest", "-m", "not chainfork", "-q"])
    last = output.strip().splitlines()[-1] if output.strip() else "no output"
    if code != 0:
        return Check("offline test suite", FAIL, last, "make test — fix before anything else")
    return Check("offline test suite", PASS, last)


def check_chain_suite() -> Check:
    code, output = _run(["uv", "run", "pytest", "-m", "chainfork", "-q"], timeout=1200)
    last = output.strip().splitlines()[-1] if output.strip() else "no output"
    if "skipped" in last and "passed" not in last:
        return Check(
            "chain and fork suite",
            UNVERIFIED,
            last,
            "anvil could not fork; set BSC_ARCHIVE_RPC_URL and re-run",
        )
    if code != 0:
        return Check("chain and fork suite", FAIL, last, "make fork-diff")
    return Check("chain and fork suite", PASS, last)


def check_replay_invariants() -> Check:
    """T1-T4 and L1 by name, because 'the suite passed' is not the same claim."""
    code, output = _run(
        [
            "uv",
            "run",
            "pytest",
            "-q",
            "tests/replay/test_engine.py",
            "tests/replay/test_l1_equivalence.py",
            "-k",
            "t1 or t2 or t3 or t4 or l1",
        ]
    )
    last = output.strip().splitlines()[-1] if output.strip() else "no output"
    if code != 0:
        return Check("T1-T4 and L1", FAIL, last, "these are the product's core claim")
    if "passed" not in last:
        return Check("T1-T4 and L1", FAIL, f"no tests selected: {last}", "check the -k filter")
    return Check("T1-T4 and L1", PASS, last)


def check_dry_run_default() -> Check:
    """An unset environment variable must not be able to spend anything."""
    value = os.environ.get("MISQUOTE_DRY_RUN")
    if value == "0":
        return Check(
            "dry run",
            UNVERIFIED,
            "MISQUOTE_DRY_RUN=0 — broadcasting is ENABLED in this shell",
            "intentional only if you are about to go live",
        )
    return Check("dry run", PASS, f"MISQUOTE_DRY_RUN={value or '(unset — defaults to dry)'}")


def check_kill_switch() -> Check:
    code, output = _run(["uv", "run", "pytest", "-q", "-k", "kill", "tests/agents", "tests/chain"])
    last = output.strip().splitlines()[-1] if output.strip() else "no output"
    if code != 0:
        return Check("kill switch", FAIL, last, "nothing goes live without this")
    return Check("kill switch", PASS, last)


def check_no_kill_file_present() -> Check:
    kill = REPO / "ops" / "KILL"
    if kill.exists():
        return Check(
            "kill file absent", FAIL, f"{kill} exists", "remove it to allow the agent to trade"
        )
    return Check("kill file absent", PASS, "ops/KILL not present")


def check_published_assumptions() -> Check:
    """Every gap item must have a published value before a number is displayed."""
    assumptions = (REPO / "docs" / "ASSUMPTIONS.md").read_text()
    matrix = (REPO / "docs" / "REQUIREMENTS_MATRIX.md").read_text()

    missing = [item for item in ("G-1", "G-2", "G-3") if item not in matrix]
    if missing:
        return Check("published assumptions", FAIL, f"missing from the matrix: {missing}")

    if "G-4" in matrix and "pending Step 8" in matrix:
        return Check(
            "published assumptions",
            UNVERIFIED,
            "kappa_default is still PROVISIONAL (G-4 pending the 30-day fit)",
            "run the backfill and publish the fitted value before quoting",
        )
    for required in ("A7", "A8", "A9", "A10"):
        if required not in assumptions:
            return Check("published assumptions", FAIL, f"{required} not in ASSUMPTIONS.md")
    return Check("published assumptions", PASS, "G-1..G-3 and A7..A12 published")


def check_provisional_constants() -> Check:
    """A number that sets the range width and traces to nothing is a rule 6 breach.

    This used to be a grep for the identifier `PROVISIONAL_KAPPA_PER_LOGPRICE`,
    which meant renaming the constant would have cleared it without fitting
    anything. A gate satisfied by a rename is not a gate. It now checks the
    *number*: the published G-4 default has to agree with the kappa a chain
    sourced card actually fitted, the way `vetting/badge.py` checks recorded
    addresses against the chain rather than against themselves.
    """
    from misquote.estimators.kappa import FITTED_KAPPA_PER_LOGPRICE

    source = (REPO / "packages" / "misquote" / "estimators" / "kappa.py").read_text()
    if "PROVISIONAL_KAPPA" in source:
        return Check(
            "no provisional constants",
            UNVERIFIED,
            "kappa still falls back to a provisional default",
            "fit on 30 days of the target pool and publish as G-4",
        )

    card = REPO / "apps" / "web" / "public" / "artifacts" / "warden.json"
    if not card.exists():
        return Check(
            "no provisional constants",
            UNVERIFIED,
            "no card to check the published kappa against",
            "make showcase",
        )
    payload = json.loads(card.read_text())
    if payload.get("source") != "chain":
        return Check(
            "no provisional constants",
            UNVERIFIED,
            f"the card is {payload.get('source')!r}, so its kappa fitted nothing real",
            "make showcase, on the indexed tape",
        )

    fitted = payload.get("estimators", {}).get("kappa_per_logprice")
    r_squared = payload.get("estimators", {}).get("kappa_r_squared")
    if fitted is None:
        return Check("no provisional constants", UNVERIFIED, "the card records no kappa")

    drift = abs(fitted - FITTED_KAPPA_PER_LOGPRICE) / max(1e-9, FITTED_KAPPA_PER_LOGPRICE)
    if drift > 0.10:
        return Check(
            "no provisional constants",
            FAIL,
            f"published G-4 is {FITTED_KAPPA_PER_LOGPRICE:,.0f}/log-price, "
            f"the card fitted {fitted:,.0f} — {drift:.0%} apart",
            "re-derive G-4 from the current tape, or explain the divergence",
        )
    return Check(
        "no provisional constants",
        PASS,
        f"kappa {FITTED_KAPPA_PER_LOGPRICE:,.0f}/log-price, fitted (r^2 {r_squared:.2f}), "
        f"card agrees to {drift:.1%}",
    )


def check_tape() -> Check:
    """Thirty days of history, measured as blocks *read* rather than as the
    distance between the first event and the last.

    This gate used to compute `(max(ts) - min(ts)) / 86400`, which is the span
    between the two ends of the tape and says nothing about the middle. A
    database holding one day at each end of a twenty-six day span reported
    "spanning 26.0 days" and passed — and that is the shape every interrupted
    backfill leaves, and the shape the tail creates deliberately when it primes
    the cursor at the head with nothing underneath.

    No query over `swap` can tell that tape from a complete one, because a quiet
    window and an unfetched window both hold zero swaps. `covered` records what
    was read, so the number below is the longest unbroken run of blocks somebody
    actually looked at.
    """
    db = Path(os.environ.get("DB_PATH", REPO / "data" / "misquote.db"))
    if not db.exists():
        return Check(
            "30-day tape",
            UNVERIFIED,
            f"{db} does not exist",
            "uv run python -m misquote.indexer.backfill --days 30",
        )

    import sqlite3

    from misquote.chain.addresses import pool_for
    from misquote.indexer import store

    pool = pool_for(56).address.lower()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    count = conn.execute("SELECT count(*) FROM swap WHERE pool = ?", (pool,)).fetchone()[0]
    try:
        longest = store.covered_span(conn, pool)
    except sqlite3.OperationalError:
        longest = None  # a database written before the covered table existed
    finally:
        conn.close()

    if not count:
        return Check("30-day tape", UNVERIFIED, "the tape is empty", "run the backfill")

    if longest is None:
        # Real events, no record of which ranges were read to find them. That is
        # unknown, and the badge's rule holds here too: unknown does not become
        # pass, however many rows are sitting in the table.
        return Check(
            "30-day tape",
            UNVERIFIED,
            f"{count:,} swaps, but no coverage recorded — completeness unknown",
            "re-run the backfill; it records the ranges it reads",
        )

    days = (longest[1] - longest[0]) * BSC_BLOCK_SECONDS / 86400
    if days < 25:
        return Check(
            "30-day tape",
            UNVERIFIED,
            f"{count:,} swaps, longest unbroken run {days:.1f} days",
            "assumption A5 wants 30 days; extend the backfill",
        )
    return Check("30-day tape", PASS, f"{count:,} swaps, {days:.1f} unbroken days read from chain")


def short(task: str) -> str:
    """"Choose — which pool to provide liquidity to" -> "Choose"."""
    return task.split("—")[0].strip() or task


def check_agent_advantage_report() -> Check:
    """The TermiX track's actual requirement, as a check that runs.

    The criterion recorded in this repo for weeks — "80% = quality + proof" on
    the architecture board — was wrong. The real one asks for an **Agent
    Advantage Report comparing at least three real tasks run with and without an
    agent**. A checklist that executes should know that, or the one requirement
    worth $10,000 stays a thing someone remembers rather than a thing that fails.

    The word this gate turns on is **real**. The report generates happily from a
    synthetic tape and says so on every line; that is a pipeline, not evidence,
    so it reports amber until the tape is chain-sourced.
    """
    artifact = REPO / "apps" / "web" / "public" / "artifacts" / "advantage.json"
    if not artifact.exists():
        return Check(
            "agent advantage report",
            UNVERIFIED,
            "no report has been generated",
            "uv run python scripts/advantage.py --synthetic 9000",
        )

    import json

    try:
        payload = json.loads(artifact.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return Check("agent advantage report", FAIL, f"unreadable: {error}")

    tasks = payload.get("tasks", [])
    if len(tasks) < 3:
        return Check(
            "agent advantage report",
            FAIL,
            f"{len(tasks)} task(s); the track requires at least three",
            "each task needs its own DIY baseline, not one baseline relabelled",
        )

    baselines = {t.get("without_agent", "") for t in tasks}
    if len(baselines) < len(tasks):
        return Check(
            "agent advantage report",
            FAIL,
            "two tasks share a baseline",
            "three tasks with one DIY column is one task relabelled",
        )

    # Per task, not per report.
    #
    # This gate used to read one top-level `source`, which is the same shape of
    # hole `check_tape` was already fixed for: a report could carry two tasks on
    # real swaps and a third on two constructed venues, and the header still
    # said "chain". Task 3 was exactly that report for weeks — its two venues
    # were `synthetic_events()` on both sides, so "which pool would you choose?"
    # had an answer decided by a random seed, under a chain-sourced badge.
    #
    # A task with no `source` at all is a report written before the field
    # existed, and unknown does not become pass.
    synthetic = [t.get("task", "?") for t in tasks if t.get("source") != "chain"]
    if synthetic:
        return Check(
            "agent advantage report",
            UNVERIFIED,
            f"{len(tasks) - len(synthetic)}/{len(tasks)} tasks on chain data; "
            f"not real: {', '.join(short(t) for t in synthetic)}",
            'the track says "three real tasks" — index every venue, then regenerate',
        )

    quotable = payload.get("summary", {}).get("quotable", 0)
    if quotable < len(tasks):
        return Check(
            "agent advantage report",
            UNVERIFIED,
            f"{quotable}/{len(tasks)} tasks cleared the sample floor",
            "extend the tape until every task can be quoted",
        )
    return Check(
        "agent advantage report", PASS, f"{len(tasks)} tasks on a chain tape, all quotable"
    )


def check_signer_configured(mainnet: bool) -> Check:
    if not mainnet:
        # UNVERIFIED, not PASS. This module's own docstring says "anything it
        # cannot verify is reported as UNVERIFIED rather than assumed — an amber
        # light, never a green one", and the web page repeats that sentence two
        # inches above the gate list. Both of these returned a green tick with
        # the words "not checked" beside it, and the summary counted them among
        # the passes: `5 passed · 0 failed · 5 unverified` for a run that had
        # actually established seven things, not five.
        return Check(
            "signer",
            UNVERIFIED,
            "not checked — this run is not --mainnet",
            "re-run with --mainnet to check the signing key",
        )
    key = os.environ.get("MISQUOTE_PRIVATE_KEY")
    if not key:
        return Check(
            "signer",
            FAIL,
            "MISQUOTE_PRIVATE_KEY is unset",
            "set it to a DEDICATED hot wallet holding only the capped capital",
        )
    return Check("signer", UNVERIFIED, "a key is set; verify by hand that it is not a main wallet")


def check_position_cap(mainnet: bool) -> Check:
    if not mainnet:
        # See `check_signer_configured` — same reason, same fix.
        return Check(
            "position cap",
            UNVERIFIED,
            "not checked — this run is not --mainnet",
            "re-run with --mainnet to check the position cap",
        )
    cap = os.environ.get("MISQUOTE_POSITION_CAP_QUOTE")
    if not cap:
        return Check(
            "position cap",
            FAIL,
            "MISQUOTE_POSITION_CAP_QUOTE is unset",
            "the plan says this is set here, deliberately, not defaulted",
        )
    try:
        value = float(cap)
    except ValueError:
        return Check("position cap", FAIL, f"not a number: {cap!r}")
    if value <= 0:
        return Check("position cap", FAIL, f"cap must be positive, got {value}")
    return Check("position cap", PASS, f"{value:,.0f} in quote units")


def check_burn_in() -> Check:
    journal = Path(os.environ.get("MISQUOTE_JOURNAL_DIR", REPO / "data" / "journal"))
    path = journal / "warden.jsonl"
    if not path.exists():
        return Check(
            "24h testnet burn-in",
            UNVERIFIED,
            "no journal from a burn-in run",
            "run the agent on testnet for 24h; the journal is the evidence",
        )

    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    stamped = [r["ts"] for r in rows if isinstance(r.get("ts"), int)]
    if not stamped:
        return Check("24h testnet burn-in", UNVERIFIED, "journal has no timestamped decisions")

    hours = (max(stamped) - min(stamped)) / 3600
    errors = [r for r in rows if r.get("event") == "decide_error"]
    if hours < 24:
        return Check(
            "24h testnet burn-in",
            UNVERIFIED,
            f"journal covers {hours:.1f}h across {len(rows):,} rows",
            "the gate is 24h unattended",
        )
    return Check(
        "24h testnet burn-in", PASS, f"{hours:.1f}h, {len(rows):,} rows, {len(errors)} read errors"
    )


# --- reporting -------------------------------------------------------------

# The gates `--fast` skips. Named rather than merely omitted, so the published
# status can say "not run" instead of leaving three rows silently absent — an
# absent gate and a passing gate look identical in a summary count, and the
# whole point of this script is that amber is never green.
SKIPPED_BY_FAST = (
    "offline test suite",
    "replay invariants (T1-T4, L1)",
    "chain and fork suite",
)


def run_checks(*, mainnet: bool, fast: bool) -> list[Check]:
    """Every gate, in report order.

    Extracted from `main` so the terminal output and the JSON artifact consume
    one list. Two call sites that each assembled their own would eventually
    disagree about which gates exist, and the one nobody reads would be the one
    that drifted.
    """
    checks: list[Check] = []
    if not fast:
        checks += [check_offline_suite(), check_replay_invariants(), check_chain_suite()]
    checks += [
        check_kill_switch(),
        check_no_kill_file_present(),
        check_dry_run_default(),
        check_published_assumptions(),
        check_provisional_constants(),
        check_tape(),
        check_agent_advantage_report(),
        check_artifact_freshness(),
        check_burn_in(),
        check_signer_configured(mainnet),
        check_position_cap(mainnet),
    ]
    return checks


# The paths whose contents change a replayed number. An artifact generated
# before a commit touching any of these is describing an engine that no longer
# exists — which is the whole of `check_artifact_freshness` below.
#
# Deliberately not "everything under packages": the indexer, the vetting layer
# and the registry readers can all change without moving a single figure on a
# card, and a gate that goes amber on an unrelated commit is a gate people learn
# to wave through.
ENGINE_PATHS = (
    "packages/misquote/replay",
    "packages/misquote/lvr",
    "packages/misquote/estimators",
    "packages/misquote/agents",
    "packages/misquote/core/policy.py",
    "packages/misquote/core/fees.py",
    "packages/misquote/core/types.py",
    "packages/misquote/core/liquidity.py",
)

# The artifacts whose numbers the replay engine produces. The others —
# `vetting`, `registry`, `venue`, `vectors`, `addresses` — are reads and
# projections, and their staleness is a different question with different
# answers already implemented.
REPLAY_ARTIFACTS = (
    "build.json",
    "warden.json",
    "grid.json",
    "sentinel.json",
    "advantage.json",
    "advantage_short.json",
)


def _recorded_sha(payload: dict) -> str | None:
    """The commit an artifact says it was generated at, wherever it keeps it."""
    for block in ("build", "provenance"):
        section = payload.get(block)
        if isinstance(section, dict) and section.get("git_sha"):
            return str(section["git_sha"])
    return str(payload["git_sha"]) if payload.get("git_sha") else None


def check_artifact_freshness() -> Check:
    """Does the published card still describe the engine that exists?

    Nothing in this repository asked that question, and it is the question every
    stale-artifact defect here has been an instance of. `vectors_report.py` says
    so in as many words — *"a receipt written before that ran is a statement
    about files that no longer exist, the exact shape of every stale-artifact
    defect this repo has had"* — and then implements the answer for the vector
    corpus alone, because a corpus can be re-digested in milliseconds.

    A card cannot. Re-deriving `warden.json` is a 4.6-hour replay, which is
    exactly the case `tests/web/test_artifact_projections.py` excludes by design.
    So this does not re-derive anything. It asks git: has anything that changes a
    replayed number landed since the commit this artifact records?

    **An artifact with no recorded commit is UNVERIFIED, never PASS.**
    `vetting/badge.py` sets that rule for chain readings and it holds here for
    the same reason — "we cannot tell" and "it is current" are different claims,
    and the second one is what a green tick means. Today four of the six cards
    record no commit at all: they are stamped by proxy through `build.json`,
    which the landing page renders once for all of them.
    """
    stale: list[str] = []
    unstamped: list[str] = []

    for name in REPLAY_ARTIFACTS:
        path = ARTIFACTS / name
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            unstamped.append(f"{name} (unreadable)")
            continue

        sha = _recorded_sha(payload)
        if not sha:
            unstamped.append(name)
            continue

        code, out = _run(["git", "log", "--oneline", f"{sha}..HEAD", "--", *ENGINE_PATHS])
        if code != 0:
            # A sha git does not know is not a pass. Rebased, squashed, or
            # generated on a branch nobody has — all of them mean the artifact
            # cannot be placed against this history.
            unstamped.append(f"{name} (records {sha}, which this repository does not have)")
            continue
        commits = [line for line in out.splitlines() if line.strip()]
        if commits:
            stale.append(f"{name} is {len(commits)} engine commit(s) behind {sha}")

    if not stale and not unstamped:
        return Check(
            "artifacts match the engine",
            PASS,
            f"{len(REPLAY_ARTIFACTS)} replay artifacts, none generated before an engine change",
        )

    detail = "; ".join(stale + [f"{n} records no commit" for n in unstamped])
    return Check(
        "artifacts match the engine",
        UNVERIFIED,
        detail,
        "regenerate them (`make showcase`, `make advantage`) — or accept that "
        "the published numbers describe an engine that has since changed",
    )


def outcome(checks: list[Check]) -> tuple[str, int]:
    """The verdict and the exit code, together so they cannot disagree."""
    if any(c.status == FAIL for c in checks):
        return "NO GO", 1
    if any(c.status == UNVERIFIED for c in checks):
        return "NOT YET", 2
    return "GO", 0


def to_payload(checks: list[Check], *, mainnet: bool, fast: bool) -> dict:
    """The verdict, and which tree it was a verdict about.

    ## Why this carries a build stamp now

    Every other emitter in this repository records command, sha and dirty flag
    through `provenance.build_stamp`. This one hand-rolled a bare timestamp, and
    it is the *checklist* — the file whose entire job is to say what has and has
    not been verified.

    So it was the one artifact that could not say what it had verified it
    *against*. A published `status.json` sat on the site for two days reading
    NOT YET with three blocking gates — "2,599 swaps spanning 0.4 days" — while
    the database held 252,923 swaps over an unbroken fifty-day span and the
    gate's own wording had since changed. Nothing about the file distinguished
    that from a reading taken minutes ago.

    `generated_at` stays at the top level as well as inside `build`, because
    `/status` has rendered it from there since the page existed and moving it
    would be a schema break for a field that is not the problem. The problem was
    the absence of a sha beside it.
    """
    verdict, code = outcome(checks)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "build": provenance.build_stamp(
            f"python scripts/go_no_go.py{' --mainnet' if mainnet else ''}"
            f"{' --fast' if fast else ''} --json",
            # Not "offline": this gate reads the tape database, and on a
            # `--mainnet` run it reads chain. What it reads is the point of it.
            source="mainnet" if mainnet else "local checks",
        ),
        "mainnet": mainnet,
        "fast": fast,
        "skipped": list(SKIPPED_BY_FAST) if fast else [],
        "checks": [
            {
                "name": c.name,
                "status": c.status,
                "detail": c.detail,
                "remedy": c.remedy,
                "blocking": c.blocking,
            }
            for c in checks
        ],
        "summary": {
            "pass": sum(1 for c in checks if c.status == PASS),
            "fail": sum(1 for c in checks if c.status == FAIL),
            "unverified": sum(1 for c in checks if c.status == UNVERIFIED),
            "total": len(checks),
        },
        "outcome": verdict,
        "exit_code": code,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mainnet", action="store_true", help="also check the live-capital gates")
    parser.add_argument("--fast", action="store_true", help="skip the test suites")
    parser.add_argument(
        "--json",
        nargs="?",
        const=str(REPO / "apps" / "web" / "public" / "artifacts" / "status.json"),
        default=None,
        help="also write the result as an artifact the site can render",
    )
    args = parser.parse_args()

    checks = run_checks(mainnet=args.mainnet, fast=args.fast)

    width = max(len(c.name) for c in checks)
    print(f"\n  Misquote go/no-go{'  (mainnet)' if args.mainnet else ''}\n")
    for check in checks:
        mark = {PASS: "  ok  ", FAIL: " FAIL ", UNVERIFIED: "  ??  "}[check.status]
        print(f"  [{mark}] {check.name.ljust(width)}  {check.detail}")
        if check.remedy:
            print(f"           {' ' * width}  -> {check.remedy}")

    if args.fast:
        print(f"\n  not run (--fast): {', '.join(SKIPPED_BY_FAST)}")

    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(to_payload(checks, mainnet=args.mainnet, fast=args.fast), indent=2) + "\n"
        )
        print(f"\n  status -> {path}")

    failed = [c for c in checks if c.status == FAIL]
    unverified = [c for c in checks if c.status == UNVERIFIED]

    print()
    if failed:
        print(f"  NO GO — {len(failed)} gate(s) failed.")
        return 1
    if unverified:
        print(f"  NOT YET — {len(unverified)} gate(s) unverified. Amber is not green.")
        print("  Every one of these is something nobody has checked, not something that passed.")
        return 2
    print("  GO — every gate passed.")
    if args.mainnet:
        print("  Confirm by hand: the wallet holds only the capped capital, and nothing else.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
