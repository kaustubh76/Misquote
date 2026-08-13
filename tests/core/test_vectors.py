"""Replay the golden vectors: our math against the real Solidity's answers.

The vectors in `tests/core/vectors/` were produced by
`scripts/gen_vectors.py`, which deploys `vetting/forge/src/Exposer.sol` — a thin
wrapper over upstream v3-core and v3-periphery at the commits pinned in
`ops/forge_deps.txt` — to a local chain and records what it returns.

So this file needs no network, no fork, and no foundry, yet every expected value
in it provably came from the reference implementation rather than from us. That
is the property that makes it worth running on every commit.

Comparison is exact integer equality throughout. There is no tolerance anywhere
in this file, deliberately: a tolerance is how an off-by-one in tick math
survives to production.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from misquote.core import fees, liquidity, tickmath

VECTOR_DIR = Path(__file__).parent / "vectors"


def load(name: str) -> list[dict[str, Any]]:
    path = VECTOR_DIR / f"{name}.json"
    if not path.exists():
        pytest.skip(f"{path.name} missing — run `make vectors`")
    return json.loads(path.read_text())["cases"]


def _int(case: dict[str, Any], key: str) -> int:
    return int(case[key])


def _expected(case: dict[str, Any]) -> int:
    return int(case["expected"])


def _expected_pair(case: dict[str, Any]) -> tuple[int, int]:
    a, b = case["expected"]
    return int(a), int(b)


def test_the_vectors_exist_and_are_substantial() -> None:
    """A silently-empty vector file would turn this whole module into a no-op."""
    groups = sorted(p.stem for p in VECTOR_DIR.glob("*.json"))
    assert "get_sqrt_ratio_at_tick" in groups
    assert "fee_growth_inside" in groups
    for group in groups:
        assert len(load(group)) > 0, f"{group}.json has no cases"


def test_constants_match_the_reference() -> None:
    for case in load("constants"):
        name = case["name"]
        assert getattr(tickmath, name) == _expected(case), name


def test_get_sqrt_ratio_at_tick() -> None:
    cases = load("get_sqrt_ratio_at_tick")
    for case in cases:
        tick = _int(case, "tick")
        assert tickmath.get_sqrt_ratio_at_tick(tick) == _expected(case), f"tick={tick}"
    assert len(cases) >= 2000


def test_get_tick_at_sqrt_ratio() -> None:
    cases = load("get_tick_at_sqrt_ratio")
    for case in cases:
        ratio = _int(case, "sqrt_price_x96")
        assert tickmath.get_tick_at_sqrt_ratio(ratio) == _expected(case), f"ratio={ratio}"
    assert len(cases) >= 2000


@pytest.mark.parametrize("token", ["0", "1"])
def test_amount_deltas_in_both_rounding_directions(token: str) -> None:
    """The rounding flag is the whole point: the pool rounds in its own favour,
    and a port that always rounds one way disagrees by a wei on half the calls."""
    fn = liquidity.get_amount0_delta if token == "0" else liquidity.get_amount1_delta
    cases = load(f"get_amount{token}_delta")
    for case in cases:
        got = fn(
            _int(case, "sqrt_a"),
            _int(case, "sqrt_b"),
            _int(case, "liquidity"),
            bool(case["round_up"]),
        )
        assert got == _expected(case), case
    assert any(c["round_up"] for c in cases) and any(not c["round_up"] for c in cases)


def test_get_amounts_for_liquidity() -> None:
    """What NonfungiblePositionManager implies a position holds."""
    for case in load("get_amounts_for_liquidity"):
        got = liquidity.get_amounts_for_liquidity(
            _int(case, "sqrt_price"),
            _int(case, "sqrt_a"),
            _int(case, "sqrt_b"),
            _int(case, "liquidity"),
        )
        assert got == _expected_pair(case), case


def test_get_liquidity_for_amounts() -> None:
    for case in load("get_liquidity_for_amounts"):
        got = liquidity.get_liquidity_for_amounts(
            _int(case, "sqrt_price"),
            _int(case, "sqrt_a"),
            _int(case, "sqrt_b"),
            _int(case, "amount0"),
            _int(case, "amount1"),
        )
        assert got == _expected(case), case


def test_fee_growth_inside_including_wrapped_accumulators() -> None:
    """The highest-value group in the file.

    Every accumulator here was drawn from the full uint256 range, so most cases
    have a subtraction that underflows and wraps. A port without the 256-bit mask
    fails these immediately — which is the point.
    """
    cases = load("fee_growth_inside")
    for case in cases:
        got = fees.fee_growth_inside(
            _int(case, "global0"),
            _int(case, "global1"),
            _int(case, "lower_outside0"),
            _int(case, "lower_outside1"),
            _int(case, "upper_outside0"),
            _int(case, "upper_outside1"),
            _int(case, "tick_current"),
            _int(case, "tick_lower"),
            _int(case, "tick_upper"),
        )
        assert got == _expected_pair(case), case

    # All three branches must be represented, or the coverage is an illusion.
    below = sum(1 for c in cases if _int(c, "tick_current") < _int(c, "tick_lower"))
    inside = sum(
        1 for c in cases if _int(c, "tick_lower") <= _int(c, "tick_current") < _int(c, "tick_upper")
    )
    above = sum(1 for c in cases if _int(c, "tick_current") >= _int(c, "tick_upper"))
    assert below > 0 and inside > 0 and above > 0, (below, inside, above)


def test_tokens_owed_including_wrapped_accumulators() -> None:
    cases = load("tokens_owed")
    for case in cases:
        got = fees.tokens_owed(_int(case, "last"), _int(case, "now"), _int(case, "liquidity"))
        assert got == _expected(case), case

    wrapped = sum(1 for c in cases if _int(c, "now") < _int(c, "last"))
    assert wrapped > 0, "no case actually wrapped, so the mask was never exercised"
