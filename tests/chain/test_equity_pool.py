"""The tokenized-equity venue, and the constant that would have been wrong.

`EQUITY_POOL` is TSLAx/USDT on PancakeSwap v3 — a *tokenized equity*, and the
reason this project can say anything about the TermiX track's equities category
at all. Nothing in the engine changes to price it; only the address does.

The offline tests here pin what was read off chain. The chain-marked one goes and
reads it again, because a recorded value that nobody re-reads is a value that
silently rots.
"""

from __future__ import annotations

import pytest

from misquote.chain.addresses import EQUITY_POOL, TARGET_POOL, TSLAX_MAINNET, USDT_MAINNET


def test_the_protocol_fee_differs_between_two_pools_on_the_same_dex() -> None:
    """Matrix P-8, corrected — and the reason `fee_protocol` has no default.

    The first version of this test asserted `EQUITY_POOL.fee_protocol == 0` and
    passed, because the value it was pinning had been read from `slot0[2]`
    (`observationIndex`) rather than `slot0[5]` (`feeProtocol`). A test that pins
    a wrong constant is worse than no test: it makes the mistake permanent and
    green.

    The finding survives in kind, not in degree. Two pools on one DEX really do
    charge different protocol fees, so no constant is right for both — but it is
    34% against 32%, not 34% against nothing.
    """
    assert TARGET_POOL.fee_protocol == 3400
    assert EQUITY_POOL.fee_protocol == 3200
    assert TARGET_POOL.fee_protocol != EQUITY_POOL.fee_protocol, "the whole point of P-8"

    assert TARGET_POOL.lp_fee_share == pytest.approx(0.66)
    assert EQUITY_POOL.lp_fee_share == pytest.approx(0.68)

    # The consequence, in the unit that reaches the headline number: what an LP
    # actually earns per swap, in basis points.
    assert TARGET_POOL.fee_pips / 100.0 * TARGET_POOL.lp_fee_share == pytest.approx(3.3)
    assert EQUITY_POOL.fee_pips / 100.0 * EQUITY_POOL.lp_fee_share == pytest.approx(17.0)

    # Assuming Uniswap's zero everywhere would inflate the flagship's LP income
    # by 1/0.66; assuming the flagship's 3400 on the equity pool understates it
    # by 2 points of protocol fee.
    assert 1.0 / TARGET_POOL.lp_fee_share == pytest.approx(1.515, abs=0.01)


def test_fee_protocol_cannot_be_defaulted_away() -> None:
    """A default would quietly reinstate the error the field exists to prevent."""
    import dataclasses

    from misquote.core.types import PoolMeta

    fields = {f.name: f for f in dataclasses.fields(PoolMeta)}
    fee_protocol = fields["fee_protocol"]
    assert fee_protocol.default is dataclasses.MISSING, "fee_protocol acquired a default"
    assert fee_protocol.default_factory is dataclasses.MISSING


def test_the_equity_pool_is_a_different_fee_tier_and_spacing() -> None:
    """0.25% -> spacing 50, per the factory constructor (matrix P-6). If the two
    pools shared a tier, running on both would prove much less."""
    assert EQUITY_POOL.fee_pips == 2500
    assert EQUITY_POOL.tick_spacing == 50
    assert EQUITY_POOL.w_min_ticks == 200  # 4 x spacing, spec section 3.2

    assert TARGET_POOL.fee_pips == 500
    assert TARGET_POOL.tick_spacing == 10
    assert TARGET_POOL.w_min_ticks == 40


def test_token_order_follows_address_sorting_not_the_pair_name() -> None:
    """v3 orders tokens by address. Getting this backwards inverts every price."""
    assert EQUITY_POOL.token0 == USDT_MAINNET
    assert EQUITY_POOL.token1 == TSLAX_MAINNET
    assert int(EQUITY_POOL.token0, 16) < int(EQUITY_POOL.token1, 16)


def test_the_engine_prices_the_equity_pool_with_no_changes() -> None:
    """The generality claim, run rather than asserted.

    Same driver, same agents, a different tick spacing and a different protocol
    fee. If anything in the engine had been specialised to the flagship pool's
    parameters, this is where it would show.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from advantage import synthetic_events
    from misquote.core.types import PoolMeta
    from misquote.replay.driver import ReplayDriver
    from misquote.replay.tape import MemoryTape

    meta = PoolMeta(
        address=EQUITY_POOL.address,
        chain_id=EQUITY_POOL.chain_id,
        token0=EQUITY_POOL.token0,
        token1=EQUITY_POOL.token1,
        dec0=EQUITY_POOL.dec0,
        dec1=EQUITY_POOL.dec1,
        fee_pips=EQUITY_POOL.fee_pips,
        tick_spacing=EQUITY_POOL.tick_spacing,
        fee_protocol=EQUITY_POOL.fee_protocol,
    )
    result = ReplayDriver(meta, capital_quote=1000.0).run(MemoryTape(synthetic_events(600)))

    assert result.samples > 0
    assert result.mints >= 1
    # Every range the policy chose is mintable on a spacing-50 pool.
    for decision in result.decisions:
        assert decision.half_width_ticks % EQUITY_POOL.tick_spacing == 0
        if decision.target_lower is not None:
            assert decision.target_lower % EQUITY_POOL.tick_spacing == 0
            assert decision.target_upper % EQUITY_POOL.tick_spacing == 0


@pytest.mark.chainfork
def test_the_equity_pool_still_reads_as_recorded() -> None:
    """Go and check. A recorded chain value nobody re-reads is one that rots.

    Liquidity is deliberately not pinned — it moves. Identity, tier, spacing and
    the protocol fee are.
    """
    from web3 import Web3

    from misquote.chain.addresses import MAINNET

    w3 = None
    for url in (
        "https://bsc-rpc.publicnode.com",
        "https://bsc-dataseed.bnbchain.org",
        "https://bsc-dataseed1.defibit.io",
    ):
        try:
            candidate = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 12}))
            if candidate.eth.chain_id == 56:
                w3 = candidate
                break
        except Exception:  # noqa: BLE001 — any endpoint failure means try the next
            continue
    if w3 is None:
        pytest.skip("no BSC endpoint answered")

    token = w3.eth.contract(
        address=Web3.to_checksum_address(TSLAX_MAINNET),
        abi=[
            {
                "name": "symbol",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [{"type": "string"}],
            },
            {
                "name": "decimals",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [{"type": "uint8"}],
            },
        ],
    )
    assert token.functions.symbol().call() == "TSLAx"
    assert token.functions.decimals().call() == EQUITY_POOL.dec1

    factory = w3.eth.contract(
        address=Web3.to_checksum_address(MAINNET.factory),
        abi=[
            {
                "name": "getPool",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint24"}],
                "outputs": [{"type": "address"}],
            },
        ],
    )
    resolved = factory.functions.getPool(
        Web3.to_checksum_address(TSLAX_MAINNET),
        Web3.to_checksum_address(USDT_MAINNET),
        EQUITY_POOL.fee_pips,
    ).call()
    assert resolved.lower() == EQUITY_POOL.address.lower(), "the factory resolves a different pool"

    pool = w3.eth.contract(
        address=Web3.to_checksum_address(EQUITY_POOL.address),
        abi=[
            {
                "name": "slot0",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [
                    {"type": "uint160"},
                    {"type": "int24"},
                    {"type": "uint16"},
                    {"type": "uint16"},
                    {"type": "uint16"},
                    {"type": "uint32"},
                    {"type": "bool"},
                ],
            },
            {
                "name": "tickSpacing",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [{"type": "int24"}],
            },
            {
                "name": "token0",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [{"type": "address"}],
            },
        ],
    )
    assert pool.functions.tickSpacing().call() == EQUITY_POOL.tick_spacing
    assert pool.functions.token0().call().lower() == EQUITY_POOL.token0.lower()

    # P-8: index **5**, not 2. Index 2 is observationIndex, and reading it is
    # how this pool came to be recorded as charging no protocol fee at all.
    # Pancake packs the field as fee0 | (fee1 << 16), both uint16.
    slot0 = pool.functions.slot0().call()
    assert (slot0[5] & 0xFFFF) == EQUITY_POOL.fee_protocol
    assert slot0[2] != EQUITY_POOL.fee_protocol or EQUITY_POOL.fee_protocol == 0, (
        "index 2 is observationIndex; if it happens to equal the protocol fee "
        "this assertion is not distinguishing them"
    )
