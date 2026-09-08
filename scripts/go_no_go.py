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
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from misquote.tearsheet import provenance
from misquote.tearsheet.generate import unbroken_runs

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

#: What `vetting/` records call a reading that did not happen. This module
#: calls the same state UNVERIFIED; the two vocabularies meet here rather
#: than in a bare string comparison inside a gate.
UNVERIFIED_ON_DISK = "UNKNOWN"


@dataclass(slots=True)
class Check:
    name: str
    status: str
    detail: str
    remedy: str = ""

    #: Machine-readable findings, for a renderer that needs more than the prose.
    #:
    #: `detail` is a sentence for a terminal and for `/status`, and it is the
    #: right shape there. It is the wrong shape for any other page: the engine
    #: check builds "warden.json is 1 engine commit(s) behind eb040ed;
    #: grid.json is 1 …", and a view that wanted to say "these figures predate
    #: an engine change" beside the figures would have to parse that back —
    #: a second implementation of a rule this file owns, drifting the moment
    #: the wording changes.
    #:
    #: Omitted from the payload when absent, so a check that has nothing
    #: structured to say does not publish an empty object suggesting it might.
    data: dict[str, Any] | None = None

    @property
    def blocking(self) -> bool:
        return self.status != PASS


#: Long enough for the suite it actually has to run.
#:
#: 900s was a knife-edge: `make test` is 2,378 offline tests over a 252,923-swap
#: tape and measures **775s** on an idle machine, so anything else running turned
#: a passing suite into `timed out after 900s` — a red gate reporting on the
#: host, not the work. Raising the ceiling changes nothing about what is checked.
SUITE_TIMEOUT = 2400


#: How much of each stream a gate gets to see. Per stream, deliberately.
#:
#: This was one `[-4000:]` over `stdout + stderr` — a concatenation, not an
#: interleave — so a command that is chatty on stderr silently evicted every
#: word it wrote to stdout. `make web-check` is that command: `check-pages.mjs`
#: prints its verdict on stdout and the static server it loads from logs every
#: request to stderr, thousands of lines of them. The gate's whole view of the
#: only check that runs real layout was
#:
#:     ::1 - - [06/Sep/2026 15:42:27] "GET /tape/index.txt…" 200 -
#:
#: with "every route clean in both themes and at 390px" cut off some four
#: thousand characters earlier. Reading the tail of each stream costs nothing
#: and means neither can hide the other.
STREAM_TAIL = 4000


def _run(command: list[str], timeout: int = SUITE_TIMEOUT) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command, cwd=REPO, capture_output=True, text=True, timeout=timeout, check=False
        )
        return result.returncode, result.stdout[-STREAM_TAIL:] + result.stderr[-STREAM_TAIL:]
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


def check_lint() -> Check:
    """`make lint`: ruff over the whole tree.

    **This gate never ran ruff.** Fifteen checks, three of them shelling out to
    pytest and one to `make web-check`, and the linter that every file in the
    repository is written to satisfy was not among them — nor is there a CI file
    anywhere, so nothing but a human ever ran it.

    That is a small hole with a specific consequence: `ruff` here catches unused
    imports and undefined names, which is the class of defect that survives a
    green suite by living on a path no test takes. `tests/test_no_dead_definitions.py`
    exists for exactly that class and cannot see inside a function body.

    FAIL rather than UNVERIFIED when ruff is absent, unlike the browser suite:
    ruff is a **core** dependency in `pyproject.toml`, so a machine that cannot
    run it has a broken install rather than a missing optional toolchain.
    """
    code, output = _run(["make", "lint"], timeout=300)
    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    last = lines[-1] if lines else "no output"
    if code != 0:
        named = [line for line in lines if line.startswith(("packages/", "scripts/", "tests/"))][:3]
        return Check("lint", FAIL, "; ".join(named) or last, "make lint")
    return Check("lint", PASS, last)


def _summary_line(lines: list[str], marker: str, fallback: str) -> str:
    """A tool's own result line, rather than whatever it printed last.

    vitest ends a **passing** run with a node warning —

        (Use `node --trace-warnings ...` to show where the warning was created)

    — so `lines[-1]` published that as the gate's detail and `/status` showed it
    to a reader as the result of the component suite, backticks and all. The
    line that says what happened is `Tests  469 passed (469)`, three above it.
    """
    return next((line for line in reversed(lines) if line.startswith(marker)), fallback)


def check_web_component_suite() -> Check:
    """`make web-test`: vitest over the component layer.

    **Also never run by this gate, and the omission was easy to miss** because
    `check_web_browser_suite` sits right here and looks like it covers the web.
    It does not: `web-check` loads the built export in Chromium, and `web-test`
    is 405 jsdom tests over the components and the artifact contract. They catch
    different things — the browser pass found routes fetching from page-relative
    paths, and the component pass is what holds the field contract, the prose
    rendering and the dead-export scan.

    With no CI file in the repository, neither ran anywhere except by hand.

    UNVERIFIED when node is absent, for the reason the browser suite gives.
    """
    code, output = _run(["make", "web-test"], timeout=SUITE_TIMEOUT)
    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    last = lines[-1] if lines else "no output"

    if "command not found" in output or "ENOENT" in output:
        return Check(
            "web component suite",
            UNVERIFIED,
            "node or pnpm is not installed, so no component test ran",
            "install the node toolchain, then make web-test",
        )
    if code != 0:
        failed = [line for line in lines if "FAIL" in line or "✕" in line][:3]
        return Check(
            "web component suite",
            FAIL,
            "; ".join(failed) or last,
            "make web-test",
        )
    return Check("web component suite", PASS, _summary_line(lines, "Tests ", last))


#: Where the published API base lives, and how long a cold instance takes.
#:
#: The browser check loads routes that read the live API. The API is on a free
#: plan that spins down after about fifteen minutes idle, and the offline suite
#: ahead of it in this gate takes five to thirteen — so the gate reliably put the
#: instance to sleep and then failed the one check that needs it awake, with
#: `page.goto: Timeout 60000ms exceeded — still in flight: 60s …/tape`. Twice out
#: of four runs. Nothing about the page was disproven either time.
API_CONFIG = REPO / "apps" / "web" / "public" / "artifacts" / "api.json"
WAKE_TIMEOUT_S = 90


def _wake_api() -> str | None:
    """Knock on the published API base and wait for it to get up.

    Returns the base it woke, or None if there is none configured — an export
    with no backend is the ordinary case and not a failure.
    """
    try:
        base = json.loads(API_CONFIG.read_text()).get("base")
    except (OSError, json.JSONDecodeError):
        return None
    if not base:
        return None

    try:
        with urllib.request.urlopen(f"{base}/tape", timeout=WAKE_TIMEOUT_S):
            pass
    except Exception:  # noqa: BLE001 — a sleeping instance is the case being handled
        pass
    return base


def check_web_browser_suite() -> Check:
    """`make web-check`: the built export, loaded in a real browser.

    The only gate here that runs layout, and the only one that can see what
    every other check is blind to. `check-pages.mjs` records what it caught that
    nothing else did: every route but "/" fetching its artifacts from a
    page-relative path and rendering an error state, while the whole suite was
    green.

    It is also the only place the simulation guarantee can actually be tested.
    `lib/api.test.ts` asserts against a stubbed fetch that a scenario issues no
    request to the API; this asserts it against Chromium loading the real
    export, which is where the claim has to hold.

    **UNVERIFIED, never FAIL, when the toolchain is absent.** It needs Chromium
    and a production build, and a machine without them has not failed a check —
    it has not run one. The same shape as `check_chain_suite` when anvil cannot
    fork: an amber light carrying the remedy, because a red one for a missing
    browser teaches people to ignore the colour.
    """
    base = _wake_api()
    code, output = _run(["make", "web-check"], timeout=SUITE_TIMEOUT)
    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    last = lines[-1] if lines else "no output"

    if (
        "playwright install" in output
        or "Executable doesn't exist" in output
        or "command not found" in output
    ):
        return Check(
            "web browser suite",
            UNVERIFIED,
            "Chromium is not installed, so no route was loaded",
            "cd apps/web && pnpm exec playwright install chromium, then make web-check",
        )

    if code != 0:
        # The failure lines, not the last line. `check-pages.mjs` prints an
        # enumerated list and then exits, so the tail is the exit noise while
        # the routes that failed are three lines above it.
        #
        # `FAIL` first, because that is how the tool marks them and the fallback
        # is a heuristic: "starts with / or contains ': '" also matches
        # `make: *** [web-check] Error 1`, and a run whose only failure line had
        # no colon in it published the make error as the finding.
        named = [line for line in lines if line.startswith("FAIL") or " FAIL " in line][:3]
        named = named or [line for line in lines if line.startswith("/") or ": " in line][-3:]

        # A sleeping backend is not a failing page. Waking it above makes this
        # rare rather than impossible — the instance can go back to sleep
        # between the knock and the route that reads it — and reporting red for
        # it would teach a reader to discount the colour, which is the same
        # argument the missing-Chromium branch above makes.
        failures = [line for line in lines if "still in flight" in line]
        if base and failures and all(base in line for line in failures):
            return Check(
                "web browser suite",
                UNVERIFIED,
                f"{base} did not answer inside the page's timeout; "
                f"{len(failures)} route(s) never finished loading",
                f"curl {base}/tape to wake it, then make web-check",
            )

        return Check(
            "web browser suite",
            FAIL,
            "; ".join(named) or last,
            "make web-check — each failure names the route and the viewport",
        )

    # `check-pages.mjs` closes with "every route clean in both themes and at
    # 390px…", and then the static server it loaded from goes on logging
    # requests until it is killed — so `lines[-1]` was an access log line, and
    # the gate published `::1 - - [06/Sep/2026 14:45:08] "GET /tape/index.txt…"`
    # as the result of every route in two themes at two viewports.
    return Check("web browser suite", PASS, _summary_line(lines, "every route clean", last))


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
    # A7..A11, and the range in the detail must be the range that was checked.
    #
    # This read "G-1..G-3 and A7..A12 published" while looping over A7..A10, so
    # it claimed two assumptions it never looked at and one — **A12** — that has
    # never existed; the sheet stops at A11. A green tick asserting a fact about
    # a document it did not read is the same defect the mainnet-only gates had,
    # and this one also escaped the repo: `status.json` carried the string, the
    # citation extractor found "A12" in it, and the assumption link on that card
    # pointed at nothing. Derived from the loop below so the two cannot drift.
    required = ("A7", "A8", "A9", "A10", "A11")
    for item in required:
        if item not in assumptions:
            return Check("published assumptions", FAIL, f"{item} not in ASSUMPTIONS.md")
    return Check(
        "published assumptions",
        PASS,
        f"G-1..G-3 and {required[0]}..{required[-1]} published",
    )


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
    """ "Choose — which pool to provide liquidity to" -> "Choose"."""
    return task.split("—")[0].strip() or task


def published_pools() -> dict[str, set[str]]:
    """Pool addresses the site publishes, read from the fields that hold pools.

    The README's promise is *"every pool a listed agent touches gets a
    due-diligence badge"*, and "touches" was being approximated by a constant a
    human maintains. It is observable instead — but only if it is read
    precisely: an artifact is full of addresses, and a token, a router or a
    registry is not a pool going unvetted. A regex over the whole file would
    make this gate noise, and a gate that is noise gets ignored.

    So each shape is read where pools actually live:

        warden/grid/sentinel.json   "pool": "<label> · 0x…"
        venue.json                  pools[].address
        vetting.json                pools[].pool
        advantage.json              tasks[].venue, once it names addresses

    That difference is not academic. `TARGET_POOL_WIDE` was quoted by the Agent
    Advantage Report's third task while absent from every pool list in the
    repository, and a check written against those lists agreed with itself the
    whole time.

    Returns address -> the artifacts naming it, so a failure can say where.
    """
    import json
    import re

    found: dict[str, set[str]] = {}
    address = re.compile(r"0x[0-9a-fA-F]{40}")
    artifacts = REPO / "apps" / "web" / "public" / "artifacts"
    if not artifacts.is_dir():
        return found

    def note(value: object, source: str) -> None:
        """Record every address in a field known to name a pool."""
        if isinstance(value, str):
            for hit in address.findall(value):
                found.setdefault(hit.lower(), set()).add(source)

    for path in sorted(artifacts.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue

        note(payload.get("pool"), path.name)
        for entry in payload.get("pools") or []:
            if isinstance(entry, dict):
                note(entry.get("address"), path.name)
                note(entry.get("pool"), path.name)
        for entry in payload.get("tasks") or []:
            if isinstance(entry, dict):
                note(entry.get("venue"), path.name)

    return found


def check_rate_tape() -> Check:
    """Does the Venus rate tape span enough *read* blocks for Router to quote?

    `check_tape` makes this argument for swaps. It matters more here, and the
    extra turn of the screw is worth stating: for a pool, a quiet window and an
    unfetched window are indistinguishable in the rows. For a lending market
    they are indistinguishable **and the quiet one is normal** — over the same
    seven days vUSDT logged 159,178 accruals and vUSDC logged 778. "No rows" is
    the healthy state of a thin market, so nothing in `accrue` can separate a
    market that did not move from a request nobody made.

    `venus_covered` can, and it is the only thing that can, so it is what this
    reads. Unrecorded coverage is UNVERIFIED, never PASS — `vetting/badge.py`
    sets that rule and it holds wherever "we cannot tell" and "it is fine" would
    otherwise render the same.

    The floor is the replay's own: `replay/allocation.py`'s `MIN_WINDOW_HOURS`
    is 24h and the emitter cuts the tape into windows half its span, so a tape
    shorter than 48 hours cannot produce a single quotable window.
    """
    db = Path(os.environ.get("DB_PATH", REPO / "data" / "misquote.db"))
    if not db.exists():
        return Check("Venus rate tape", UNVERIFIED, f"no database at {db}", "make venus")

    try:
        from misquote.chain.venus import markets_on
        from misquote.indexer import store, venus
    except Exception as error:  # noqa: BLE001
        return Check("Venus rate tape", UNVERIFIED, f"could not import the reader: {error}")

    markets = markets_on(56)
    if not markets:
        return Check("Venus rate tape", UNVERIFIED, "no verified Venus markets are recorded")

    try:
        conn = store.connect(str(db))
    except Exception as error:  # noqa: BLE001
        return Check("Venus rate tape", UNVERIFIED, f"could not open {db}: {error}")

    unrecorded: list[str] = []
    spans: list[tuple[str, float]] = []
    for market in markets:
        run = venus.covered_span(conn, market.key)
        if run is None:
            unrecorded.append(market.symbol)
            continue
        rows = venus.load_accruals(conn, market.key)
        inside = [e for e in rows if run[0] <= e.block <= run[1]]
        hours = (inside[-1].ts - inside[0].ts) / 3600 if len(inside) >= 2 else 0.0
        spans.append((market.symbol, hours))

    if unrecorded:
        return Check(
            "Venus rate tape",
            UNVERIFIED,
            f"no coverage recorded for {', '.join(unrecorded)} — an unfetched "
            f"window and a market that did not accrue are the same empty list",
            "make venus",
        )

    # Twice the replay's window floor, because the emitter cuts each window at
    # half the tape's span — so a tape under 2 x MIN_WINDOW_HOURS yields no
    # quotable window at all. Derived rather than restated: the docstring above
    # already explained the arithmetic and then wrote 48.0 anyway.
    from misquote.replay import allocation as _allocation  # noqa: PLC0415

    floor = 2 * _allocation.MIN_WINDOW_HOURS
    short = [f"{name} {hours:.1f}h" for name, hours in spans if hours < floor]
    if short:
        return Check(
            "Venus rate tape",
            UNVERIFIED,
            f"below the {floor:.0f}h floor: {'; '.join(short)}",
            "make venus VENUS_DAYS=7",
        )

    detail = ", ".join(f"{name} {hours / 24:.1f}d" for name, hours in spans)
    return Check("Venus rate tape", PASS, f"{len(spans)} market(s) read unbroken: {detail}")


def check_badge_coverage() -> Check:
    """Two claims, and the second is the one a list cannot make for itself.

    1. Every pool address a published artifact quotes is one we verified on
       chain — we do not publish a number about a pool nobody read.
    2. Every verified pool on this chain has a due-diligence badge on disk.

    `make vet` writing badges satisfies (2) and says nothing about (1), which is
    the direction the failure actually came from.

    UNVERIFIED rather than FAIL: an unbadged or unrecognised pool is a check
    nobody ran, and this module's rule is that unknown is amber, never green.
    """
    from misquote.chain.addresses import KNOWN_POOLS, known_pools_on

    badges = REPO / "vetting" / "badges"
    listed = known_pools_on(56)
    if not listed:
        return Check("badge coverage", FAIL, "no pools are listed for chain 56")

    verified = {pool.address.lower() for pool in KNOWN_POOLS}

    # (1) Published, but never verified on chain. `published_pools` reads only
    # the fields that hold pools, so anything here is a pool the site is
    # quoting — not a token or a router that happened to match a regex.
    quoted = published_pools()
    unrecognised = sorted(
        f"{address[:10]} (in {', '.join(sorted(sources))})"
        for address, sources in quoted.items()
        if address not in verified
    )
    if unrecognised:
        return Check(
            "badge coverage",
            UNVERIFIED,
            f"published pool(s) not in KNOWN_POOLS: {'; '.join(unrecognised)}",
            "verify the pool against chain and record it, or stop publishing it",
        )

    # (2) Verified, but never badged.
    missing = [
        pool.label for pool in listed if not (badges / f"{pool.address.lower()}.json").exists()
    ]
    if missing:
        return Check(
            "badge coverage",
            UNVERIFIED,
            f"{len(listed) - len(missing)}/{len(listed)} listed pools badged; "
            f"missing: {', '.join(missing)}",
            "make vet — a pool the marketplace lists but has not vetted is the "
            "claim this layer exists to make good on",
        )

    published = sum(1 for address in quoted if address in verified)
    return Check(
        "badge coverage",
        PASS,
        f"all {len(listed)} listed pools badged; {published} quoted by artifacts, "
        "all of them verified",
    )


def check_docs_current() -> Check:
    """The document a judge is told to read first must agree with its artifacts.

    `docs/FOR_JUDGES.md` carried **two contradictory tables of the same result**,
    ninety lines apart, one of them a stale copy of a synthetic run — with an
    entire narrative resting on it. Nobody typed a wrong number on purpose; the
    artifact was regenerated and the prose was not, three times, which is what
    `scripts/sync_docs.py` was written for and what its `--check` mode has been
    able to detect for as long as it has existed while being wired to nothing.

    UNVERIFIED rather than FAIL: prose behind its artifact is a step nobody ran,
    not a check that failed, and `make judges` is the step.
    """
    script = REPO / "scripts" / "sync_docs.py"
    if not script.exists():
        return Check("judge document current", UNVERIFIED, "scripts/sync_docs.py is missing")

    result = subprocess.run(
        [sys.executable, str(script), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return Check("judge document current", PASS, "every derived figure matches its artifact")

    drifted = [
        line.strip()
        for line in (result.stdout + result.stderr).splitlines()
        if line.strip() and not line.strip().startswith("->")
    ]
    return Check(
        "judge document current",
        UNVERIFIED,
        "; ".join(drifted[:3]) or "sync_docs --check reported drift",
        "make judges — the numbers a judge reads must be the numbers we published",
    )


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

    # A task is a (baseline, agent) pair, not a baseline.
    #
    # This compared baselines alone, which caught the thing it was written for —
    # three tasks with one DIY column is one task relabelled — and also caught
    # something legitimate the moment the report grew a fifth task. Earn and
    # Market-make measure Warden and Grid against the *same* passive position,
    # which is what a control is for; replaying the identical baseline twice
    # would burn an hour and a half to produce two identical columns and would
    # satisfy this check by doing it.
    #
    # So the pair. Two tasks sharing a baseline *and* an agent are one task
    # written twice, and that is still refused.
    pairs = {(t.get("without_agent", ""), t.get("with_agent", "")) for t in tasks}
    if len(pairs) < len(tasks):
        return Check(
            "agent advantage report",
            FAIL,
            "two tasks share both a baseline and an agent",
            "the same comparison twice is one task relabelled",
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

    # The track's bar is **three** real tasks run both ways, not "every task we
    # can think of clears the floor".
    #
    # This required all of them, and that punished the one behaviour this
    # marketplace is selling. Adding the equities task — a real BNB Chain venue
    # measured and withheld, because 85 swaps over 4.1 days cannot support the
    # twenty windows A5 asks for — would have turned a green gate amber for
    # publishing a refusal, while leaving it green for not looking at all. A
    # gate that prefers silence to a measured negative is pointed the wrong way.
    #
    # So the floor is the track's, and the withheld ones are named rather than
    # hidden: a reader of this line learns both numbers.
    quotable = payload.get("summary", {}).get("quotable", 0)
    withheld = [t.get("task", "?") for t in tasks if not t.get("quotable")]
    if quotable < 3:
        return Check(
            "agent advantage report",
            UNVERIFIED,
            f"{quotable}/{len(tasks)} tasks cleared the sample floor; the track asks for three",
            "extend the tape until at least three tasks can be quoted",
        )
    detail = f"{quotable} of {len(tasks)} tasks quotable on a chain tape"
    if withheld:
        detail += f" · withheld and said so: {', '.join(short(t) for t in withheld)}"
    return Check("agent advantage report", PASS, detail)


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

    # This gate used to end here, on "a key is set; verify by hand that it is
    # not a main wallet". A checklist that executes should not have a manual
    # step as its last instruction, and this one sits directly in front of the
    # only code path that can spend anything.
    #
    # `MISQUOTE_OPERATOR_ADDRESS` is what makes it checkable: the key derives an
    # address, the operator declares one, and they agree or they do not. Still
    # not a claim that the wallet is dedicated — nothing on chain distinguishes
    # a hot wallet from a main one — but "the key is the one you said it would
    # be" is a different and stronger statement than "somebody looked".
    try:
        from misquote.chain.operator import (
            OPERATOR_ENV,
            ROLE_ENV,
            SIGNER_ENV,
            declared_operator,
            declared_wallets,
            role_for,
        )
    except ImportError as error:  # pragma: no cover — the package is a dependency
        return Check("signer", UNVERIFIED, f"cannot read the declaration: {error}")

    try:
        wallets = declared_wallets()
        operator = declared_operator()
    except ValueError as error:
        # Malformed, not absent. The parser raises rather than returning None
        # precisely so this lands on FAIL instead of quietly taking the amber
        # branch below.
        return Check("signer", FAIL, str(error), "fix or unset the declaration")

    if not wallets:
        return Check(
            "signer",
            UNVERIFIED,
            f"a key is set; {OPERATOR_ENV} is not, so nothing checked which wallet it is",
            f"declare the wallet with {OPERATOR_ENV} and this gate compares it against the key",
        )

    try:
        from eth_account import Account

        signing_for = Account.from_key(key).address
    except (ValueError, TypeError) as error:
        return Check("signer", FAIL, f"MISQUOTE_PRIVATE_KEY is not a key: {error}")

    # Read off the guard rather than compared again here. Two implementations of
    # "is this key allowed" drift, and the one in the gate is the copy nobody
    # notices going stale — it is not the one standing in front of `send()`.
    role = role_for(signing_for)
    facts = {"signing_for": signing_for, "role": role or "undeclared", "declared": wallets}
    if operator is not None:
        facts["operator"] = operator

    if role is None:
        named = ", ".join(f"{ROLE_ENV[r]}={a}" for r, a in sorted(wallets.items()))
        return Check(
            "signer",
            FAIL,
            f"the key signs for {signing_for}, which is neither declared wallet ({named})",
            "one of them is wrong; broadcasting would spend from an undeclared wallet",
            data=facts,
        )

    if role != "operator":
        # Amber, and this is the whole reason the two variables are separate.
        # The key matches what was declared, so nothing is misconfigured — but
        # what a green tick here would imply is "the operator signed this", and
        # what actually happened is "a wallet the operator nominated signed
        # this". Those are different claims to anyone reading the ledger, and
        # the weaker one does not get the stronger one's colour.
        return Check(
            "signer",
            UNVERIFIED,
            f"the key signs for {signing_for}, declared as a delegate of {operator}",
            f"green needs the operator's own key; unset {SIGNER_ENV} if that is what you meant",
            data=facts,
        )

    return Check(
        "signer",
        PASS,
        f"the key signs for the declared operator {signing_for}",
        data=facts,
    )


#: The two identity records, in the order this gate prefers them. Mainnet first
#: because it is the stronger claim and the one TermiX's explorer indexes.
IDENTITY_MAINNET = REPO / "vetting" / "identity" / "56.json"
IDENTITY_CHAPEL = REPO / "vetting" / "identity" / "97.json"


def check_identities_registered() -> Check:
    """The README's four-agent claim, as a check that runs.

    `Readme.md` has said all four agents "register ERC-8004 identities" since
    before any of them existed, and for the whole of that time the registry
    package could only read. A claim in a README is not a gate; this is.

    Reads the record rather than the chain, following every other gate here —
    `scripts/register_identity.py --verify-only` is the step that re-reads, and
    a checklist that opened four RPC connections would be a checklist people
    stop running. What it does insist on is that the record's own verdict came
    from those re-reads: a file whose checks are empty is UNVERIFIED, not PASS.

    **Mainnet first.** This read `97.json` and nothing else, which was right when
    chapel was the only place the four agents existed. `56.json` records the same
    four on BSC mainnet with twenty-one read-backs, all passing, owned by the
    same address — and it is the registration TermiX's explorer actually indexes,
    since that indexes mainnet mints. Preferring it is a stronger claim from the
    same shape of evidence, not a looser one, and the detail names the chain so
    which was read is never in doubt.
    """
    found = next(
        ((c, r) for c, r in ((56, IDENTITY_MAINNET), (97, IDENTITY_CHAPEL)) if r.exists()),
        None,
    )
    if found is None:
        return Check(
            "agent identities",
            UNVERIFIED,
            "no agent has been registered on chain",
            "MISQUOTE_DRY_RUN=0 uv run python scripts/register_identity.py --broadcast",
        )
    chain, record = found
    where = CHAIN_NAMES.get(chain, f"chain {chain}")

    try:
        payload = json.loads(record.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return Check("agent identities", FAIL, f"unreadable: {error}")

    agents = payload.get("agents") or []
    checks = payload.get("checks") or []
    owner = str(payload.get("owner") or "")

    if not checks:
        return Check(
            "agent identities",
            UNVERIFIED,
            f"{len(agents)} registered, and nothing has been read back from chain",
            f"uv run python scripts/register_identity.py --chain {chain} --verify-only",
        )

    # Four, because four is what the marketplace lists and what the README
    # claims. Three registered agents is not "mostly true", it is a different
    # claim that nobody has made.
    expected = 4
    if len(agents) < expected:
        return Check(
            "agent identities",
            FAIL,
            f"{len(agents)} of {expected} agents registered: "
            f"{', '.join(a.get('agent', '?') for a in agents) or 'none'}",
            "the README says all four; register the rest or change the README",
            data={"agents": agents, "owner": owner},
        )

    failed = [c["name"] for c in checks if c.get("status") == FAIL]
    if failed:
        return Check(
            "agent identities",
            FAIL,
            f"{len(failed)} chain read-back(s) failed: {', '.join(short(n) for n in failed[:3])}",
            "a registration that fails our own listing bar is worse than none",
            data={"agents": agents, "owner": owner},
        )

    unknown = [c["name"] for c in checks if c.get("status") == UNVERIFIED_ON_DISK]
    if unknown:
        return Check(
            "agent identities",
            UNVERIFIED,
            f"{len(unknown)} read-back(s) could not be made: {short(unknown[0])}",
            f"uv run python scripts/register_identity.py --chain {chain} --verify-only",
            data={"agents": agents, "owner": owner},
        )

    return Check(
        "agent identities",
        PASS,
        f"{len(agents)} agents registered on {where} and owned by {owner}",
        data={"agents": agents, "owner": owner},
    )


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


#: The agent whose burn-in the gate is about. Spec section 10's acceptance list
#: names the Warden and nothing else, so the others are reported and not gated —
#: but they are *reported*, which is the half that was missing.
BURN_IN_AGENT = "warden"

#: Named once. It was `24h testnet burn-in`, and the word that changed is the
#: one this project stopped being able to honour — see `check_burn_in`.
BURN_IN_GATE = "24h unattended burn-in"

#: How the detail says where a run happened. Short, because it goes on a card.
CHAIN_NAMES = {56: "BSC mainnet", 97: "chapel"}


def _journal_summary(path: Path) -> dict[str, Any]:
    """One agent's journal: its longest unbroken run, and what chain it was on."""
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            # A half-written final line is what a killed process leaves. Skipping
            # it loses one decision; refusing the whole file loses the evidence.
            continue

    stamps = [r["ts"] for r in rows if isinstance(r.get("ts"), int)]
    runs = unbroken_runs(stamps)
    longest = max((end - start for start, end in runs), default=0)
    chains = {r["chain_id"] for r in rows if isinstance(r.get("chain_id"), int)}
    return {
        "agent": path.stem,
        "rows": len(rows),
        "runs": len(runs),
        "hours": longest / 3600,
        "span_hours": ((max(stamps) - min(stamps)) / 3600) if stamps else 0.0,
        "chains": chains,
        # `run_start` records whether the process could spend. A burn-in that
        # could and one that could not are different claims, and the gate has to
        # be able to say which it is looking at rather than implying the
        # stronger one by not mentioning it.
        "can_sign": {r["can_sign"] for r in rows if isinstance(r.get("can_sign"), bool)},
        "errors": sum(1 for r in rows if r.get("event") == "decide_error"),
        "reconciled": any("reconciled" in r for r in rows if r.get("event") == "run_start"),
    }


def check_burn_in() -> Check:
    """24 hours *unattended*, measured as the longest unbroken run.

    ## Three defects this had, and the third is the one that matters

    **It read one hardcoded file**, `warden.jsonl`. Journals became per-agent, so
    Grid, Sentinel and Router write files this gate could not see — a 24-hour
    Grid burn-in would have left it reporting 0.0h.

    **It never checked the chain**, in a gate called `24h testnet burn-in`.

    **And it computed `(max(ts) - min(ts)) / 3600`.** The journal is opened in
    append mode, so that is the distance between the two ends of the file and says
    nothing about the middle: **two ten-minute runs a day apart reported 25h and
    passed.** The remediation line said "the gate is 24h *unattended*", which is
    exactly what a span cannot distinguish.

    `check_tape` had this defect and fixed it, in those words — *"a database
    holding one day at each end of a twenty-six day span reported 'spanning 26.0
    days' and passed"*. The lesson was recorded there as a fact about the tape
    rather than as a habit about time, so it did not generalise. Both numbers are
    now the longest unbroken run.

    ## Why it is no longer the *testnet* burn-in

    It required `chains == {97}`, which made it a gate this project could never
    pass once it decided to spend its remaining days on mainnet. A gate that
    cannot pass is not a standard, and one relaxed to let a run through is not
    one either — so the chapel requirement is **replaced rather than dropped**:

    - no `chain_id` anywhere is UNVERIFIED, where it used to be a footnote on a
      pass. That was the "it never checked the chain" defect surviving in the one
      case where the journal cannot say;
    - **more than one chain is UNVERIFIED.** Not hypothetical: `warden.jsonl`
      already holds chain-56 rows, so any chapel run appended to it produces a
      single "unbroken" stretch spanning two deployments;
    - and the detail always names the chain **and whether the run could spend**,
      from `run_start`'s `can_sign`. On mainnet `--broadcast` is refused in code,
      so a mainnet burn-in is a day of reading and deciding with signing
      impossible — a narrower claim than a chapel run that could sign, and the
      gate has to say which one it is rather than leaving a green tick to imply
      the wider one.
    """
    journal = Path(os.environ.get("MISQUOTE_JOURNAL_DIR", REPO / "data" / "journal"))
    if not journal.is_dir():
        return Check(
            BURN_IN_GATE,
            UNVERIFIED,
            "no journal directory from a burn-in run",
            "run the agent for 24h; the journal is the evidence",
        )

    summaries = sorted(
        (_journal_summary(p) for p in journal.glob("*.jsonl")), key=lambda s: -s["hours"]
    )
    if not summaries:
        return Check(
            BURN_IN_GATE,
            UNVERIFIED,
            "no journal from a burn-in run",
            "run the agent for 24h; the journal is the evidence",
        )

    others = ", ".join(f"{s['agent']} {s['hours']:.1f}h" for s in summaries if s["hours"])
    mine = next((s for s in summaries if s["agent"] == BURN_IN_AGENT), None)
    if mine is None:
        return Check(
            BURN_IN_GATE,
            UNVERIFIED,
            f"no {BURN_IN_AGENT} journal; found {others or 'nothing timestamped'}",
            f"the gate is the {BURN_IN_AGENT}'s — spec section 10 names it",
        )

    if not mine["rows"] or not mine["hours"]:
        return Check(BURN_IN_GATE, UNVERIFIED, f"{BURN_IN_AGENT} journal has no timestamped rows")

    if not mine["chains"]:
        return Check(
            BURN_IN_GATE,
            UNVERIFIED,
            f"{BURN_IN_AGENT} journal records no chain_id, so which network it ran "
            f"against is unknown",
            "re-run the agent; `run_start` records the chain",
        )

    # One run, one deployment. `warden.jsonl` is appended to, so a chapel run
    # after a mainnet one leaves a stretch with no gap in it that is nonetheless
    # two different chains — and the hours would be counted across both.
    if len(mine["chains"]) > 1:
        return Check(
            BURN_IN_GATE,
            UNVERIFIED,
            f"{BURN_IN_AGENT} journal mixes chain(s) {sorted(mine['chains'])}; "
            f"an unbroken run across two deployments is not one run",
            "burn in on one chain, into a journal that holds only that run",
        )

    chain = next(iter(mine["chains"]))
    where = CHAIN_NAMES.get(chain, f"chain {chain}")
    # `True` in the set means at least one run could spend. Absent means the
    # journal predates the field, which is not the same as "it could not".
    if mine["can_sign"] == {False}:
        spending = "signing refused"
    elif True in mine["can_sign"]:
        spending = "able to sign"
    else:
        spending = "signing capability unrecorded"

    detail = (
        f"{BURN_IN_AGENT} longest unbroken run {mine['hours']:.1f}h on {where}, "
        f"{spending} — across {mine['runs']} run(s), {mine['rows']:,} rows"
    )
    if mine["span_hours"] - mine["hours"] > 1:
        # The number the old gate would have reported, kept beside the real one.
        detail += f" (file spans {mine['span_hours']:.1f}h — the gate is the run, not the span)"
    if not mine["reconciled"]:
        detail += "; no run_start records `reconciled`, so this journal predates the boot reconcile"
    if others and others != f"{BURN_IN_AGENT} {mine['hours']:.1f}h":
        detail += f". Also: {others}"

    if mine["hours"] < 24:
        return Check(BURN_IN_GATE, UNVERIFIED, detail, "the gate is 24h unattended")
    return Check(BURN_IN_GATE, PASS, f"{detail}, {mine['errors']} read errors")


# --- reporting -------------------------------------------------------------

# The gates `--fast` skips. Named rather than merely omitted, so the published
# status can say "not run" instead of leaving three rows silently absent — an
# absent gate and a passing gate look identical in a summary count, and the
# whole point of this script is that amber is never green.
SKIPPED_BY_FAST = (
    "offline test suite",
    "replay invariants (T1-T4, L1)",
    # The only gate that runs real layout, and the only place the claim that a
    # simulated page never reaches the API can actually be tested. Skipped by
    # `--fast` because `make status` writes `/status` from the fast pass and a
    # gate that shells out to a production build does not belong on a target the
    # artifact pipeline runs.
    "web browser suite",
    # Skipped by `--fast` for the same reason: `make status` writes `/status`
    # from the fast pass, and a gate that shells out to node does not belong on
    # a target the artifact pipeline runs. Both are in the full gate, which is
    # the point — neither was in *any* gate before, and with no CI file in this
    # repository that meant ruff and 405 component tests ran only when a human
    # remembered.
    "web component suite",
    "lint",
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
        checks += [
            check_offline_suite(),
            check_replay_invariants(),
            check_lint(),
            check_web_component_suite(),
            check_web_browser_suite(),
            check_chain_suite(),
        ]
    checks += [
        check_kill_switch(),
        check_no_kill_file_present(),
        check_dry_run_default(),
        check_published_assumptions(),
        check_provisional_constants(),
        check_tape(),
        check_rate_tape(),
        check_badge_coverage(),
        check_docs_current(),
        check_agent_advantage_report(),
        check_escrow_flow(),
        check_artifact_freshness(),
        check_identities_registered(),
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
    # Router's half of the engine. `replay/` and `estimators/` above already
    # cover its driver and its APR estimator; this is the types module whose
    # refusals decide what a venue quote may say.
    "packages/misquote/core/allocation.py",
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
    # The fourth category. Added with the agent rather than after it: without
    # this line Router's card would be the only published replay that could go
    # stale against an engine change with nothing to notice, which is the exact
    # question this check exists to ask.
    "router.json",
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


def _parties(proof: dict[str, Any]) -> str:
    """Who the money moved between, judged by the addresses.

    The gate reported a job id, an amount and a chain, and never said whether
    the buyer and the seller were the same wallet — which is the one thing a
    marketplace's own hire has to demonstrate. `/status` renders this string, so
    the omission was on the readiness page as well as on `/registry`.

    By the addresses and not by `two_party`, for the reason
    `tests/registry/test_two_party_hire.py::_two_parties` gives: the fork record
    predates that flag and has had two distinct parties since it was written, so
    reading the label would report this project's one settled two-party run as a
    self-hire. `lib/escrow.ts::partiesDiffer` decides it the same way in the
    browser.

    Deliberately not a verdict. A self-hire is not a failure of the escrow — the
    mechanism works either way — and turning this amber would report a missing
    *demonstration* as a broken *gate*, which is the confusion this file's own
    UNVERIFIED tier exists to avoid.
    """
    client, provider = proof.get("client"), proof.get("provider")
    if not client or not provider:
        return ""
    if client.lower() == provider.lower():
        return " One wallet was both client and provider, so this proves the escrow and hires nobody."
    return f" Two parties: {client[:10]} paid, {provider[:10]} delivered."


def check_escrow_flow() -> Check:
    """The hire itself, which no gate covered.

    The advantage report proves an agent beats doing the job yourself. This is
    the other half of the same track's question: that hiring one is a thing this
    marketplace can actually do, on a chain, with money.

    Nothing checked it. `grep -i "escrow\\|8183\\|hire"` over this file returned
    comments, and the whole flow was held up by a sentence in `SUBMISSION.md`.
    That is how the browser came to pass a zero hook for the life of the console
    — every `createJob` sent from the site reverted `HookRequired()`, and the
    only thing that would have said so was somebody pressing the button.

    Three claims, in the order they can be lost:

    - **funded** — `fund` moved the payment token into a job on mainnet.
    - **reclaimed** — `claimRefund` moved it back out. Escrow that cannot be
      recovered is a donation, and this is the half that shows the way out.
    - **settled** — the release path. It has run on a fork and never on
      mainnet: `settle` reverts `NotDecided()` until the OptimisticPolicy's
      seven-day window has run. That is a wait rather than a gap, and it is
      reported amber with the date rather than counted as done.
    """
    artifact = REPO / "apps" / "web" / "public" / "artifacts" / "registry.json"
    if not artifact.exists():
        return Check(
            "erc-8183 escrow",
            UNVERIFIED,
            "no registry artifact has been generated",
            "make registry",
        )

    import json

    try:
        flow = json.loads(artifact.read_text()).get("hire_flow", {})
    except (OSError, json.JSONDecodeError) as error:
        return Check("erc-8183 escrow", FAIL, f"unreadable: {error}")

    mainnet = flow.get("mainnet_proof") or {}
    refund = flow.get("refund_proof") or {}

    if not mainnet.get("ran"):
        return Check(
            "erc-8183 escrow",
            UNVERIFIED,
            mainnet.get("reason") or "no mainnet hire is on record",
            "MISQUOTE_DRY_RUN=0 make hire-mainnet",
        )

    # `escrowed_on_mainnet` and `escrowed` are different claims and the fork
    # record carries both, so the narrower one is the one asked for here.
    if not mainnet.get("escrowed_on_mainnet"):
        return Check(
            "erc-8183 escrow",
            FAIL,
            f"job {mainnet.get('job_id')} ran but escrowed nothing on mainnet",
            "check the payment token balance before fund()",
        )

    job = mainnet.get("job_id")
    budget = mainnet.get("budget")
    escrowed = f"job {job} escrowed {budget} on chain {mainnet.get('chain_id')}"
    # Appended to whichever branch fires rather than spliced into `escrowed`,
    # which put it in the middle of "escrowed X ... and was reclaimed".
    parties = _parties(mainnet)

    if not refund.get("refunded"):
        return Check(
            "erc-8183 escrow",
            UNVERIFIED,
            f"{escrowed}; nothing has been reclaimed, so the way out is unproven.{parties}",
            "make claim-refund",
        )

    # The one call that has never run outside a fork.
    submitted = flow.get("submit_proof") or {}
    due = submitted.get("settle_earliest_utc")
    if not submitted.get("settled"):
        return Check(
            "erc-8183 escrow",
            UNVERIFIED,
            f"{escrowed} and was reclaimed; settle has run on a fork only"
            + (f", and opens {due}" if due else "")
            + f".{parties}",
            f"make hire-mainnet ARGS='--settle {submitted.get('job_id')}'"
            if submitted.get("job_id")
            else "settle after the dispute window",
        )

    return Check("erc-8183 escrow", PASS, f"{escrowed}, reclaimed, and settled.{parties}")


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
    behind: list[dict[str, Any]] = []

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
            behind.append({"artifact": name, "recorded_sha": sha, "commits": len(commits)})

    if not stale and not unstamped:
        return Check(
            "artifacts match the engine",
            PASS,
            f"{len(REPLAY_ARTIFACTS)} replay artifacts, none generated before an engine change",
        )

    parts = []
    if stale:
        parts.append(f"{len(stale)} replay artifact(s) were generated before an engine change")
    if unstamped:
        parts.append(f"{len(unstamped)} record no commit at all")
    detail = "; ".join(parts)
    return Check(
        "artifacts match the engine",
        UNVERIFIED,
        detail,
        "regenerate them (`make showcase`, `make advantage`) — or accept that "
        "the published numbers describe an engine that has since changed",
        # The same finding, structured, so a page can say it beside the figures
        # rather than only in the checklist. `behind` is the actionable half —
        # `unstamped` means we cannot tell, which is a different claim and is
        # kept separate for the reason `vetting/badge.py` gives: unknown does
        # not become pass, and it does not become fail either.
        data={"behind": behind, "unstamped": unstamped},
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
                **({"data": c.data} if c.data else {}),
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
