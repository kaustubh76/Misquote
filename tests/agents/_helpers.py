"""Fixtures shared by the replay tests.

A plain module rather than `conftest.py` because these are called with
arguments, and rather than one test file importing another because that makes
the import order load-bearing.
"""

from __future__ import annotations

import dataclasses
import random
import struct

from misquote.core.tickmath import get_sqrt_ratio_at_tick
from misquote.core.types import Event, PoolMeta

META = PoolMeta(
    address="0x36696169C63e42cd08ce11f5deeBbCeBae652050",
    chain_id=56,
    token0="0x55d398326f99059fF775485246999027B3197955",
    token1="0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    dec0=18,
    dec1=18,
    fee_pips=500,
    tick_spacing=10,
    fee_protocol=3400,
)

POOL_LIQUIDITY = 1_275_390_104_039_763_402_054_142
START_TS = 1_700_000_000


def make_events(count: int = 1500, *, seed: int = 7, swap_size: int = 10**21) -> list[Event]:
    rng = random.Random(seed)
    events: list[Event] = []
    tick, ts = -64180, START_TS
    fee = swap_size * 500 // 10**6
    for i in range(count):
        tick += rng.choice((-9, -4, 0, 4, 9))
        ts += rng.randint(5, 45)
        events.append(
            Event(
                block=1_000_000 + i,
                log_index=0,
                ts=ts,
                kind="swap",
                tx=f"0x{i:064x}",
                amount0=swap_size,
                amount1=-swap_size,
                sqrt_price_x96=get_sqrt_ratio_at_tick(tick),
                liquidity=POOL_LIQUIDITY,
                tick=tick,
                protocol_fee0=fee * 3400 // 10_000,
                protocol_fee1=0,
            )
        )
    return events


def fingerprint(decisions) -> bytes:
    """Every float packed to its exact bits, so 'identical' means identical.

    `Decision` is frozen and hashable precisely so this is cheap. Comparing
    reprs or rounding to a tolerance would let a real divergence through.
    """
    out = bytearray()
    for decision in decisions:
        for field in dataclasses.astuple(decision):
            if isinstance(field, float):
                out += struct.pack("<d", field)
            elif isinstance(field, tuple):
                for name, value in field:
                    out += name.encode()
                    out += struct.pack("<d", float(value))
            else:
                out += repr(field).encode()
    return bytes(out)
