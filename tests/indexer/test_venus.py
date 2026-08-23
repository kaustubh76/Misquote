"""The rate tape's guarantees: decoding, refusal, idempotence, and coverage.

`test_tape.py` makes the same argument for the pool tape and its opening
sentence transfers unchanged — the indexer exists to make *re-running a backfill
is a no-op* true. What differs here is the last section. For swaps, a quiet
window and an unfetched one are indistinguishable in the rows. For rates they
are indistinguishable **and the quiet one is normal**: over the same seven days
vUSDC logged 778 accruals against vUSDT's 159,178. Coverage is the only thing
that can separate them, so it gets more attention than it does for swaps.

Offline, against a temporary database and the committed log fixture.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from misquote.chain.venus import VUSDC, VUSDT
from misquote.estimators.apr import RateEvent
from misquote.indexer import store, venus

FIXTURE = (
    Path(__file__).resolve().parents[1] / "estimators" / "fixtures" / "venus_vusdt_accruals.json"
)


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    c = store.connect(str(tmp_path / "rates.db"))
    with c:
        venus.register_markets(c, (VUSDT, VUSDC))
    return c


def fixture_rows() -> list[dict]:
    return json.loads(FIXTURE.read_text())["accruals"]


def as_log(row: dict, address: str = VUSDT.address) -> dict:
    """A row from the fixture, back in the shape `eth_getLogs` returns."""
    data = b"".join(
        int(row[k]).to_bytes(32, "big")
        for k in ("cash_prior", "interest_accumulated", "borrow_index", "total_borrows")
    )
    return {
        "address": address,
        "blockNumber": row["block"],
        "logIndex": row["log_index"],
        "data": "0x" + data.hex(),
    }


def event(market: str, block: int, ts: int, index: int = 10**18) -> RateEvent:
    return RateEvent(
        market=market,
        block=block,
        log_index=0,
        ts=ts,
        cash_prior=10**18,
        interest_accumulated=0,
        borrow_index=index,
        total_borrows=10**18,
    )


# --- decoding ---------------------------------------------------------------


def test_a_real_log_decodes_to_the_values_the_fixture_recorded() -> None:
    """Against chain data, not against the encoder that produced it."""
    row = fixture_rows()[0]
    decoded = venus.decode_accrual(as_log(row), ts=row["ts"])

    assert decoded.market == VUSDT.key
    assert decoded.block == row["block"]
    assert decoded.borrow_index == int(row["borrow_index"])
    assert decoded.cash_prior == int(row["cash_prior"])
    assert decoded.total_borrows == int(row["total_borrows"])
    assert decoded.interest_accumulated == int(row["interest_accumulated"])


def test_total_borrows_prior_is_the_difference_the_formula_needs() -> None:
    """`total_borrows` in the log is *post*-accrual; utilisation needs the prior."""
    row = fixture_rows()[0]
    decoded = venus.decode_accrual(as_log(row), ts=row["ts"])
    assert decoded.total_borrows_prior == int(row["total_borrows"]) - int(
        row["interest_accumulated"]
    )


def test_short_data_raises_rather_than_being_padded() -> None:
    """A truncated log decoded leniently is a wrong rate that looks right."""
    row = fixture_rows()[0]
    log = as_log(row)
    log["data"] = log["data"][: 2 + 64]  # one word instead of four
    with pytest.raises(ValueError, match="expected 128"):
        venus.decode_accrual(log, ts=row["ts"])


def test_an_unverified_market_address_is_refused() -> None:
    """The guard `market_by_address` exists for.

    A market's `underlying_decimals` and `v_decimals` differ by ten and decide
    what its accumulator readings mean. Indexing an address nobody checked
    produces a complete, plausible, wrongly-scaled rate.
    """
    row = fixture_rows()[0]
    with pytest.raises(ValueError, match="not a Venus market"):
        venus.decode_accrual(as_log(row, address="0x" + "11" * 20), ts=row["ts"])


def test_the_accrue_topic_matches_the_signature_it_claims() -> None:
    from eth_utils import keccak

    assert (
        venus.ACCRUE_TOPIC
        == "0x" + keccak(text="AccrueInterest(uint256,uint256,uint256,uint256)").hex()
    )


# --- idempotence ------------------------------------------------------------


def test_writing_the_same_accruals_twice_inserts_nothing_the_second_time(conn) -> None:
    """The property that makes crash recovery "run it again"."""
    rows = fixture_rows()[:20]
    events = [venus.decode_accrual(as_log(r), ts=r["ts"]) for r in rows]
    txs = [f"0x{i:064x}" for i in range(len(events))]

    first = venus.write_accruals(conn, events, txs, markets=[VUSDT.key], covered=(1, 100))
    second = venus.write_accruals(conn, events, txs, markets=[VUSDT.key], covered=(1, 100))

    assert first > 0
    assert second == 0, "a re-run inserted rows, so the backfill is not idempotent"
    assert len(venus.load_accruals(conn, VUSDT.key)) == len(events)


def test_an_accrual_without_its_transaction_hash_is_refused(conn) -> None:
    with pytest.raises(ValueError, match="transaction hash"):
        venus.write_accruals(conn, [event(VUSDT.key, 1, 1)], [], markets=[VUSDT.key])


def test_accruals_load_back_in_chain_order(conn) -> None:
    events = [event(VUSDT.key, b, b * 10) for b in (3, 1, 2)]
    venus.write_accruals(conn, events, [f"0x{i:064x}" for i in range(3)], markets=[VUSDT.key])
    loaded = venus.load_accruals(conn, VUSDT.key)
    assert [e.block for e in loaded] == [1, 2, 3]


def test_a_borrow_index_larger_than_a_signed_64_bit_integer_survives(conn) -> None:
    """Every uint256 is TEXT for this reason. `borrowIndex` is ~1.5e18 and
    `totalBorrows` ~1.2e26; INTEGER would truncate silently."""
    big = 123_054_149_885_175_676_648_834_203
    venus.write_accruals(
        conn, [event(VUSDT.key, 1, 1, index=big)], ["0x" + "aa" * 32], markets=[VUSDT.key]
    )
    assert venus.load_accruals(conn, VUSDT.key)[0].borrow_index == big


# --- coverage: what was read, as distinct from what was found ---------------


def test_coverage_records_the_range_read_not_the_range_the_events_span(conn) -> None:
    """A chunk with no accruals in it is still a chunk that was read."""
    venus.write_accruals(conn, [], [], markets=[VUSDT.key], covered=(1000, 1999))
    assert venus.coverage(conn, VUSDT.key) == [(1000, 1999)]
    assert venus.load_accruals(conn, VUSDT.key) == []


def test_adjacent_ranges_merge_so_a_chunk_boundary_is_not_a_hole(conn) -> None:
    venus.write_accruals(conn, [], [], markets=[VUSDT.key], covered=(1000, 1999))
    venus.write_accruals(conn, [], [], markets=[VUSDT.key], covered=(2000, 2999))
    assert venus.coverage(conn, VUSDT.key) == [(1000, 2999)]


def test_a_real_gap_is_left_as_a_gap(conn) -> None:
    venus.write_accruals(conn, [], [], markets=[VUSDT.key], covered=(1000, 1999))
    venus.write_accruals(conn, [], [], markets=[VUSDT.key], covered=(3000, 3999))
    assert venus.coverage(conn, VUSDT.key) == [(1000, 1999), (3000, 3999)]
    assert venus.covered_span(conn, VUSDT.key) == (1000, 1999)


def test_coverage_is_per_market(conn) -> None:
    """One market's coverage must never stand in for another's — which is why
    this is a separate table from the pool tape's `covered`."""
    venus.write_accruals(conn, [], [], markets=[VUSDT.key], covered=(1000, 1999))
    assert venus.coverage(conn, VUSDC.key) == []


def test_no_coverage_recorded_reads_as_unknown_not_as_nothing(conn) -> None:
    """Empty means "we do not know", never "nothing was there"."""
    assert venus.coverage(conn, VUSDT.key) == []
    assert venus.covered_span(conn, VUSDT.key) is None


def test_rows_and_coverage_are_written_in_one_transaction(conn) -> None:
    """A crash between them would leave coverage claiming more than the tape holds.

    Forced by making the coverage write fail: the rows must not survive it.
    """
    events = [event(VUSDT.key, 1, 1)]
    original = venus._record_covered

    def explode(*args, **kwargs):
        raise sqlite3.OperationalError("simulated crash between rows and coverage")

    venus._record_covered = explode
    try:
        with pytest.raises(sqlite3.OperationalError):
            venus.write_accruals(
                conn, events, ["0x" + "bb" * 32], markets=[VUSDT.key], covered=(1, 2)
            )
    finally:
        venus._record_covered = original

    assert venus.load_accruals(conn, VUSDT.key) == [], (
        "rows survived a failure that aborted the coverage write, so the two "
        "are not in one transaction"
    )


# --- the reserve factor is a series, not a constant -------------------------


def test_the_reserve_factor_in_force_at_a_block_is_the_one_before_it(conn) -> None:
    """Applying today's governance parameter to last month's history is P-1's
    shape: a protocol cut read as a constant."""
    venus.write_accruals(
        conn,
        [],
        [],
        markets=[VUSDT.key],
        covered=(1, 10_000),
        reserve_factors=[(VUSDT.key, 100, 1000, 10**17), (VUSDT.key, 5000, 2000, 2 * 10**17)],
    )
    assert venus.reserve_factor_at(conn, VUSDT.key, 4999) == pytest.approx(0.1)
    assert venus.reserve_factor_at(conn, VUSDT.key, 5000) == pytest.approx(0.2)


def test_an_unrecorded_reserve_factor_is_none_not_a_default(conn) -> None:
    """None so the caller must decide, and say which value it used."""
    assert venus.reserve_factor_at(conn, VUSDT.key, 1) is None
