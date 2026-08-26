"""The declared position cap, and the approval that had no production caller.

Both were checklist items rather than code. `MISQUOTE_POSITION_CAP_QUOTE` was
read by `scripts/go_no_go.py` and by nothing else, so the gate a reader takes as
"capital is capped" capped nothing at runtime; `ensure_allowance` had three call
sites and all three were tests, so every mint in the suite met an allowance
production would never have set.

These run offline. The cap arithmetic is pure, and the allowance question is
about call order, so neither needs a chain.
"""

from __future__ import annotations

import pytest

from misquote.chain.nfpm import POSITION_CAP_ENV, _cap_from_env
from misquote.core.errors import PositionCapExceeded
from misquote.core.tickmath import Q96

# WBNB/USDT 0.05%: both sides 18 decimals, so the decimal adjustment is 1.0 and
# the arithmetic below is readable rather than a wall of exponents.
DEC0 = DEC1 = 18


def value_quote(amount0: int, amount1: int, sqrt_price: int, dec0: int, dec1: int) -> float:
    """The same conversion `PositionManager._position_value_quote` makes."""
    price = ((sqrt_price / Q96) ** 2) * 10.0 ** (dec0 - dec1)
    return amount1 / 10.0**dec1 + (amount0 / 10.0**dec0) * price


# --- the parser: absent is permissive, malformed is not --------------------


def test_an_unset_cap_reads_as_no_cap(monkeypatch) -> None:
    monkeypatch.delenv(POSITION_CAP_ENV, raising=False)
    assert _cap_from_env() is None


def test_a_malformed_cap_raises_rather_than_reading_as_absent(monkeypatch) -> None:
    """`None` is the permissive branch, so a typo must not fall into it.

    The same rule `chain/operator.py::_parse` applies to a mistyped address: a
    value that cannot be parsed is not the same as no value, and treating it as
    one disables the check it was set to enable.
    """
    monkeypatch.setenv(POSITION_CAP_ENV, "1.0e")
    with pytest.raises(ValueError, match="is not a number"):
        _cap_from_env()

    monkeypatch.setenv(POSITION_CAP_ENV, "0")
    with pytest.raises(ValueError, match="must be positive"):
        _cap_from_env()

    monkeypatch.setenv(POSITION_CAP_ENV, "-3")
    with pytest.raises(ValueError, match="must be positive"):
        _cap_from_env()


def test_whitespace_is_not_a_cap(monkeypatch) -> None:
    monkeypatch.setenv(POSITION_CAP_ENV, "   ")
    assert _cap_from_env() is None


# --- the arithmetic --------------------------------------------------------


def test_the_cap_is_measured_in_token1_across_both_legs() -> None:
    """A position is two tokens, and the cap is one number.

    At price 1.0 a position holding one of each is worth two, not one — the
    error a cap that only looked at `amount1` would make, and it would let
    through a position twice the declared size.
    """
    at_one = int(Q96)  # sqrt(1.0) * 2**96, so price == 1.0
    assert value_quote(10**18, 10**18, at_one, DEC0, DEC1) == pytest.approx(2.0)
    assert value_quote(0, 10**18, at_one, DEC0, DEC1) == pytest.approx(1.0)
    assert value_quote(10**18, 0, at_one, DEC0, DEC1) == pytest.approx(1.0)


def test_the_error_names_the_size_the_cap_and_the_unit() -> None:
    """An operator reading this has to be able to act on it without the source."""
    error = PositionCapExceeded(2.5, 1.0, "token1")
    text = str(error)

    assert "2.500000" in text and "1.000000" in text and "token1" in text
    assert POSITION_CAP_ENV in text, "say which knob to turn"
    assert "Refusing rather than resizing" in text
    assert error.value_quote == 2.5 and error.cap_quote == 1.0


# --- the allowance, as a question about call order -------------------------


class FakeEth:
    @staticmethod
    def get_transaction_receipt(_tx_hash):
        # No IncreaseLiquidity log, so `_token_id_from` returns None. This test
        # is about call order, not about token-id extraction, which
        # `tests/chain/test_executor.py` covers against a real fork.
        return {"logs": []}


class FakeW3:
    eth = FakeEth()


class RecordingManager:
    """A `PositionManager` shape that records the order it was called in.

    Not a mock of the chain: the question is whether `ChainExecutor.mint`
    approves before it mints, which is answerable without one.
    """

    def __init__(self, meta) -> None:
        self.meta = meta
        self.w3 = FakeW3()
        self.calls: list[tuple[str, object]] = []

    def _sqrt_price_now(self) -> int:
        return int(Q96)

    def ensure_allowance(self, token: str, amount: int):
        self.calls.append(("approve", token))
        return None

    def mint(self, lower, upper, amount0, amount1, **_):
        self.calls.append(("mint", (amount0, amount1)))

        class Sent:
            tx_hash = "0x" + "00" * 32

        return Sent()


def test_the_executor_approves_both_tokens_before_it_mints() -> None:
    """`ensure_allowance` had no production caller, so a first real mint would
    have failed at `estimate_gas` for want of an approval nobody made."""
    from misquote.chain.executor import ChainExecutor
    from misquote.core.types import PoolMeta

    meta = PoolMeta(
        address="0x36696169C63e42cd08ce11f5deeBbCeBae652050",
        chain_id=56,
        token0="0x55d398326f99059fF775485246999027B3197955",
        token1="0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        dec0=DEC0,
        dec1=DEC1,
        fee_pips=500,
        tick_spacing=10,
        fee_protocol=3400,
    )
    manager = RecordingManager(meta)
    ChainExecutor(manager).mint(-100, 100, 10**18, 0)

    kinds = [kind for kind, _ in manager.calls]
    assert kinds == ["approve", "approve", "mint"], f"got {kinds}"

    approved = [arg for kind, arg in manager.calls if kind == "approve"]
    assert approved == [meta.token0, meta.token1], "both legs, in pool order"
