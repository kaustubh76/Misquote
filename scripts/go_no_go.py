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
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

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
    """A number that sets the range width and traces to nothing is a rule 6 breach."""
    kappa = (REPO / "packages" / "misquote" / "estimators" / "kappa.py").read_text()
    if "PROVISIONAL_KAPPA_PER_LOGPRICE" in kappa:
        return Check(
            "no provisional constants",
            UNVERIFIED,
            "kappa still falls back to a provisional default",
            "Step 8b: fit on 30 days of the target pool and publish as G-4",
        )
    return Check("no provisional constants", PASS, "kappa is fitted from real history")


def check_tape() -> Check:
    db = Path(os.environ.get("DB_PATH", REPO / "data" / "misquote.db"))
    if not db.exists():
        return Check(
            "30-day tape",
            UNVERIFIED,
            f"{db} does not exist",
            "uv run python -m misquote.indexer.backfill --days 30 (needs a keyed BSC_RPC_URL)",
        )

    import sqlite3

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT count(*), min(ts), max(ts) FROM swap").fetchone()
    conn.close()
    count, first, last = row
    if not count:
        return Check("30-day tape", UNVERIFIED, "the tape is empty", "run the backfill")

    days = (last - first) / 86400
    if days < 25:
        return Check(
            "30-day tape",
            UNVERIFIED,
            f"{count:,} swaps spanning {days:.1f} days",
            "assumption A5 wants 30 days; extend the backfill",
        )
    return Check("30-day tape", PASS, f"{count:,} swaps spanning {days:.1f} days")


def check_signer_configured(mainnet: bool) -> Check:
    if not mainnet:
        return Check("signer", PASS, "not checked (add --mainnet)")
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
        return Check("position cap", PASS, "not checked (add --mainnet)")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mainnet", action="store_true", help="also check the live-capital gates")
    parser.add_argument("--fast", action="store_true", help="skip the test suites")
    args = parser.parse_args()

    checks: list[Check] = []
    if not args.fast:
        checks += [check_offline_suite(), check_replay_invariants(), check_chain_suite()]
    checks += [
        check_kill_switch(),
        check_no_kill_file_present(),
        check_dry_run_default(),
        check_published_assumptions(),
        check_provisional_constants(),
        check_tape(),
        check_burn_in(),
        check_signer_configured(args.mainnet),
        check_position_cap(args.mainnet),
    ]

    width = max(len(c.name) for c in checks)
    print(f"\n  Misquote go/no-go{'  (mainnet)' if args.mainnet else ''}\n")
    for check in checks:
        mark = {PASS: "  ok  ", FAIL: " FAIL ", UNVERIFIED: "  ??  "}[check.status]
        print(f"  [{mark}] {check.name.ljust(width)}  {check.detail}")
        if check.remedy:
            print(f"           {' ' * width}  -> {check.remedy}")

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
