"""The pool badge: eight checks, each one a defect this project actually hit.

Every check is tested twice — once with readings that should pass, once with the
readings that produced the original bug. A due-diligence check that has never
been shown to fail is a decoration.

The `UNKNOWN` behaviour is the load-bearing part. "We could not read it" and "we
read it and it was fine" are different claims, and a badge that collapses the
first into the second launders an absence of evidence into evidence of absence —
which is the move this project is named after.
"""

from __future__ import annotations

from misquote.vetting.badge import (
    FAIL,
    PASS,
    UNKNOWN,
    WARN,
    PoolReadings,
    evaluate,
)

POOL = "0x36696169C63e42cd08ce11f5deeBbCeBae652050"


def healthy(**overrides) -> PoolReadings:
    fields = {
        "address": POOL,
        "chain_id": 56,
        "recorded": {
            "fee_pips": 500,
            "tick_spacing": 10,
            "fee_protocol": 3400,
            "dec0": 18,
            "dec1": 18,
        },
        "resolved_by_factory": POOL,
        "fee_pips": 500,
        "tick_spacing": 10,
        "fee_protocol": 3400,
        "tick": -64180,
        "sqrt_price_x96": 3_204_810_498_611_732_818_824_713_025,
        "liquidity": 1_220_001_498_435_927_928_274_845,
        "token0": "0x55d398326f99059fF775485246999027B3197955",
        "token1": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "dec0": 18,
        "dec1": 18,
        "token0_code_size": 4413,
        "token1_code_size": 3124,
        "label": "test pool",
    }
    fields.update(overrides)
    return PoolReadings(**fields)


def status_of(badge, name: str) -> str:
    return next(c.status for c in badge.checks if c.name == name)


def test_a_healthy_pool_passes_every_check() -> None:
    badge = evaluate(healthy())
    assert badge.verdict == PASS
    assert badge.safe_to_provide
    assert len(badge.checks) == 9


# --- the one this module was built from -------------------------------------


def test_a_recorded_value_that_no_longer_matches_chain_fails() -> None:
    """The check that would have caught P-8 the first time.

    `EQUITY_POOL.fee_protocol` was recorded as 0, read from `slot0[2]` —
    `observationIndex` — rather than `slot0[5]`. Index 2 held a small plausible
    integer, nothing reverted, and the mistake was published. What eventually
    exposed it was two numbers in the same repository disagreeing, so the badge
    now makes that comparison itself.
    """
    badge = evaluate(healthy(fee_protocol=3200))  # chain says 3200, repo records 3400
    assert status_of(badge, "recorded values match chain") == FAIL
    assert badge.verdict == FAIL
    assert not badge.safe_to_provide

    detail = next(c.detail for c in badge.checks if c.name == "recorded values match chain")
    assert "recorded 3400" in detail and "chain says 3200" in detail


def test_nothing_recorded_is_a_warning_not_a_pass() -> None:
    """An unlisted pool has not been vetted before; that is worth saying."""
    badge = evaluate(healthy(recorded=None))
    assert status_of(badge, "recorded values match chain") == WARN
    assert badge.verdict == WARN
    assert badge.safe_to_provide, "a warning should not block, only qualify"


def test_a_recorded_value_that_could_not_be_read_is_unknown() -> None:
    badge = evaluate(healthy(fee_protocol=None))
    assert status_of(badge, "recorded values match chain") == UNKNOWN
    assert badge.verdict == UNKNOWN
    assert not badge.safe_to_provide, "unknown must not clear a pool"


# --- each check, shown failing ----------------------------------------------


def test_an_address_the_factory_does_not_resolve_fails() -> None:
    """P-6: Pancake deploys from its own deployer with a different init-code
    hash, so Uniswap's computeAddress returns well-formed wrong addresses."""
    badge = evaluate(healthy(resolved_by_factory="0x" + "1" * 40))
    assert status_of(badge, "factory resolves it") == FAIL
    assert badge.verdict == FAIL


def test_a_fee_tier_pancake_does_not_deploy_fails() -> None:
    """Uniswap has a 3000 tier. Pancake does not, so a pool claiming one is not
    the contract you think it is."""
    badge = evaluate(healthy(fee_pips=3000, tick_spacing=60, recorded=None))
    assert status_of(badge, "tick spacing matches tier") == FAIL


def test_a_spacing_that_contradicts_the_tier_fails() -> None:
    badge = evaluate(healthy(tick_spacing=60, recorded=None))
    assert status_of(badge, "tick spacing matches tier") == FAIL


def test_ethereum_decimals_on_a_bsc_stablecoin_are_reported() -> None:
    """BSC's USDT is 18 decimals. Assuming Ethereum's 6 misprices every position
    by twelve orders of magnitude — so the badge reports what it read."""
    badge = evaluate(healthy(dec0=6, recorded=None))
    assert status_of(badge, "decimals read") == PASS
    detail = next(c.detail for c in badge.checks if c.name == "decimals read")
    assert "token0 6" in detail, "the reading has to be visible to be disagreed with"


def test_implausible_decimals_fail() -> None:
    badge = evaluate(healthy(dec0=0, recorded=None))
    assert status_of(badge, "decimals read") == FAIL


def test_a_pool_pinned_at_the_edge_of_the_tick_range_fails() -> None:
    """Chapel's WBNB/USDT: a real address, a real contract, initialised at
    MAX_TICK and never seeded. It cannot be provided to."""
    badge = evaluate(healthy(tick=887_270, recorded=None))
    assert status_of(badge, "initialised and not pinned") == FAIL
    assert status_of(badge, "a mintable range exists") == FAIL, "w_min cannot fit there"


def test_an_uninitialised_pool_fails() -> None:
    badge = evaluate(healthy(sqrt_price_x96=0, recorded=None))
    assert status_of(badge, "initialised and not pinned") == FAIL


def test_a_pool_with_no_liquidity_fails() -> None:
    """The 1.00% TSLAx/USDT pool is exactly this: it exists on paper."""
    badge = evaluate(healthy(liquidity=0, recorded=None))
    assert status_of(badge, "liquidity supports a position") == FAIL
    assert badge.verdict == FAIL


def test_a_thin_pool_warns_rather_than_fails() -> None:
    """Thin is a reason to qualify a quote, not to refuse the pool — the quote
    would describe the pool rather than the strategy."""
    badge = evaluate(healthy(liquidity=10**12, recorded=None))
    assert status_of(badge, "liquidity supports a position") == WARN
    assert badge.verdict == WARN
    assert badge.safe_to_provide


def test_a_token_with_no_code_fails() -> None:
    badge = evaluate(healthy(token1_code_size=0, recorded=None))
    assert status_of(badge, "both tokens are contracts") == FAIL


# --- the refusal ------------------------------------------------------------


def test_every_unreadable_field_produces_unknown_never_pass() -> None:
    """Read nothing at all and the badge must clear nothing at all."""
    blank = PoolReadings(address=POOL, chain_id=56)
    badge = evaluate(blank)
    assert badge.verdict == UNKNOWN
    assert not badge.safe_to_provide
    assert all(c.status in (UNKNOWN, WARN) for c in badge.checks)
    assert not any(c.status == PASS for c in badge.checks), "a blank read passed something"


def test_fail_outranks_unknown_outranks_warn() -> None:
    """Precedence, because the worst thing found is the thing that matters."""
    assert evaluate(healthy(liquidity=0, fee_protocol=None)).verdict == FAIL
    assert evaluate(healthy(fee_protocol=None)).verdict == UNKNOWN
    assert evaluate(healthy(recorded=None)).verdict == WARN


def test_every_check_cites_where_it_came_from() -> None:
    """A check with no provenance is a check somebody thought sounded prudent."""
    for check in evaluate(healthy()).checks:
        assert check.provenance.strip(), f"{check.name} cites nothing"
        assert len(check.provenance) > 20


def test_the_badge_serialises_for_the_web_page() -> None:
    import json

    payload = evaluate(healthy()).to_dict()
    assert payload["verdict"] == PASS
    assert payload["safe_to_provide"] is True
    assert len(payload["checks"]) == 9
    assert json.loads(json.dumps(payload)) == payload
