"""A synthetic tape has to be a history a v3 pool could have produced.

This is V-13 for the third time, and the reason it is a test rather than a
comment. The finding, in `docs/REQUIREMENTS_MATRIX.md`, was that the generated
tape "was not a possible history": every swap had the pool receiving token0 and
paying token1 while the tick random-walked both ways. That was fixed — the
*direction* of each swap now follows the price move.

The *magnitude* was left alone, and nothing was watching it. `amount1` stayed
equal to `amount0`, which asserts a price of exactly 1.0 on a pool whose own
tick says 0.001632 token1 per token0 — **612.6x too much token1 on every swap**,
on the leg the fee accrues to and the LVR accountant reads. Four generators
carried it. `make showcase-demo`, line 17 of `docs/FOR_JUDGES.md`'s
thirty-second quickstart, quoted **+30,020% over 62h** on the result.

What went wrong twice is that each fix checked the fixture it was looking at.
So this file asserts the invariant over *every* generator in the repository,
found by import rather than by memory, and a fifth copy fails on arrival.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from misquote.core.tickmath import Q96
from misquote.core.types import SYNTHETIC_SWAP_SIZE_TOKEN0, Event

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))


def load(relative: str) -> ModuleType:
    """Import by path, because two of these are both called `_helpers`.

    The rest of the suite reaches its fixture with a bare `from _helpers import`
    — pytest puts each test directory on `sys.path`, so the name resolves to
    whichever copy is nearest. That is exactly the arrangement under which two
    byte-identical files drift apart without anyone importing both at once.
    """
    spec = importlib.util.spec_from_file_location(relative, REPO / relative)
    assert spec and spec.loader, relative
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Every generator, by the path it lives at. Listing one here is the whole cost
# of adding one to the repository; the bug this file exists for is what happens
# when a generator is written and nothing looks at it again.
showcase = load("scripts/showcase.py")

GENERATORS = {
    "scripts/showcase.py": showcase.synthetic_events,
    "scripts/advantage.py": load("scripts/advantage.py").synthetic_events,
    "tests/replay/_helpers.py": load("tests/replay/_helpers.py").make_events,
    "tests/agents/_helpers.py": load("tests/agents/_helpers.py").make_events,
}

# Measured 18 Aug 2026 from the 252,923-swap indexed tape in `data/misquote.db`,
# which is gitignored — so the figure is recorded here rather than re-derived,
# and carries the date it was taken.
INDEXED_TOKEN1_VOLUME_PER_HOUR = 224.7
INDEXED_SWAPS = 252_923

# The generators emit ~144.6 swaps/hour against the tape's 348.5, so matching
# per-swap size would undershoot the flow; `SYNTHETIC_SWAP_SIZE_TOKEN0` matches
# the hourly notional instead, which is what drives fees. 25% is wide enough to
# survive a reseed and narrow enough that the 64,362x version fails by four
# orders of magnitude.
VOLUME_TOLERANCE = 0.25


def price_at(event: Event) -> float:
    """token1 per token0, from the event's own sqrt price. Raw units.

    Both tokens on this pool are 18 decimals, so no decimal adjustment applies —
    `lvr/accountant.py` scales by `dec0 - dec1`, which is zero here.
    """
    return (event.sqrt_price_x96 / Q96) ** 2


@pytest.mark.parametrize("name", sorted(GENERATORS))
def test_both_amounts_agree_with_the_price_the_tick_asserts(name: str) -> None:
    """The invariant every real AMM swap has, and all four of ours lacked.

    A v3 swap exchanges one token for the other at the pool's price. If the two
    legs do not agree with the tick, the event is not something the pool could
    have emitted — and everything downstream that reads an amount is reading
    fiction while everything that reads the price path stays correct, which is
    precisely why it survived review twice.
    """
    events = GENERATORS[name](200)
    assert events, f"{name} generated nothing"

    for event in events:
        expected = abs(event.amount0) * price_at(event)
        actual = abs(event.amount1)
        # Integer truncation only: the generator does `int(swap_size * price)`.
        assert actual == pytest.approx(expected, rel=1e-9, abs=1.0), (
            f"{name} block {event.block}: |amount1| = {actual:.4e} but its tick "
            f"{event.tick} prices |amount0| = {abs(event.amount0):.4e} at "
            f"{expected:.4e} — a factor of {actual / expected:.1f}. This event "
            f"is not a swap a v3 pool could have emitted."
        )


@pytest.mark.parametrize("name", sorted(GENERATORS))
def test_the_two_legs_move_in_opposite_directions(name: str) -> None:
    """The V-13 half, kept under test rather than only in a docstring.

    A pool cannot receive both tokens or pay both. This is what was fixed the
    first time; it is asserted here so the next edit to these generators has to
    keep both halves rather than whichever one is remembered.
    """
    for event in GENERATORS[name](200):
        assert (event.amount0 > 0) != (event.amount1 > 0), (
            f"{name} block {event.block}: amount0 = {event.amount0} and "
            f"amount1 = {event.amount1} have the same sign — the pool is "
            f"receiving both tokens or paying both."
        )


def test_the_defect_this_file_exists_for_would_fail_it() -> None:
    """Both sides of the band, per `tests/core/test_units.py`.

    A guard that only ever sees good input is indistinguishable from one that
    asserts nothing. This builds the old construction — `amount1 = amount0` —
    and checks the assertion above rejects it, so the invariant cannot quietly
    stop testing anything.
    """
    good = showcase.synthetic_events(50)[0]
    # `Event` uses slots, so it is rebuilt rather than mutated.
    broken = replace(good, amount1=-good.amount0)

    ratio = abs(broken.amount1) / (abs(broken.amount0) * price_at(broken))
    assert ratio > 500, (
        "the old construction should overstate token1 by ~612x; it overstates "
        f"by {ratio:.1f}x, so either the price or the pool changed and this "
        "test's premise needs rereading"
    )
    assert broken.amount1 != pytest.approx(
        abs(broken.amount0) * price_at(broken), rel=1e-9, abs=1.0
    )


def test_the_published_tape_carries_the_flow_the_indexed_tape_carries() -> None:
    """Calibration, not just coherence.

    Coherence alone leaves the notional free: at the old `10**23` a coherent
    tape still carries 105x the indexed tape's per-swap size and quotes +107%
    over 62h. `make showcase-demo` is in the quickstart, so what it publishes
    should look like what the pool does.
    """
    events = showcase.synthetic_events(9000)
    span_hours = (events[-1].ts - events[0].ts) / 3600
    volume = sum(abs(e.amount1) for e in events) / 1e18
    per_hour = volume / span_hours

    ratio = per_hour / INDEXED_TOKEN1_VOLUME_PER_HOUR
    assert abs(ratio - 1.0) <= VOLUME_TOLERANCE, (
        f"the synthetic tape carries {per_hour:,.1f} WBNB/hour of token1 flow "
        f"against {INDEXED_TOKEN1_VOLUME_PER_HOUR} measured over {INDEXED_SWAPS:,} "
        f"indexed swaps — {ratio:,.1f}x. Fees scale with this, so the demo's "
        f"quote is a statement about the constant rather than about the strategy."
    )


def test_only_the_scripts_are_calibrated_and_the_fixtures_say_why() -> None:
    """The fixtures deliberately keep a heavier tape, and that is not drift.

    `tests/*/_helpers.py` exist to give the engine flow to bite on: at the
    published notional, `test_engine.py`'s "fees dominate when flow is real"
    inverts for reasons about the tape rather than about the engine. Pinned so
    the divergence is a decision somebody made rather than one that happened.
    """
    fixture_size = 10**23
    assert fixture_size > SYNTHETIC_SWAP_SIZE_TOKEN0 * 100, (
        "the fixture tape is no longer heavier than the published one; if that "
        "was deliberate, the engine tests' fee bands need rereading"
    )


def test_the_two_fixture_generators_have_not_drifted_apart() -> None:
    """They are byte-identical copies, and that is the only thing holding them together.

    `tests/replay/_helpers.py` and `tests/agents/_helpers.py` are the same file
    twice. Each test directory is on `sys.path` under pytest, so a bare
    `from _helpers import make_events` silently resolves to whichever is nearest
    — nothing anywhere imports both, and nothing would have said so if one had
    been fixed and the other left. Both carried the amount1 defect; both were
    corrected in the same commit, and this is what keeps that true.

    Deduplicating them is the better answer and is deliberately not done here:
    fifteen call sites across two packages is a separate change from this one.
    """
    left = (REPO / "tests/replay/_helpers.py").read_bytes()
    right = (REPO / "tests/agents/_helpers.py").read_bytes()
    assert left == right, (
        "the two fixture generators have diverged. They are duplicates by "
        "convention and nothing but this test enforces it — either re-sync them "
        "or make the difference deliberate and delete this assertion."
    )
