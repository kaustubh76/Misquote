-- The tape: BSC pool events, stored so a quote can be reproduced from a file.
--
-- Three decisions here are load-bearing, and each of them is a bug that would
-- otherwise be found much later and much more expensively.
--
-- 1. Every uint256/int256 value is TEXT, never INTEGER. SQLite's INTEGER is a
--    signed 64-bit value and `sqrtPriceX96` and `liquidity` overflow it
--    *silently* — no error, just a plausible-looking wrong number. This is the
--    single most likely source of data corruption in the whole system.
--
-- 2. Every event table is keyed on (tx, log_index) and written with
--    INSERT OR IGNORE, so re-running a backfill over an already-ingested range
--    changes nothing. Crash recovery is "run it again", with no reconciliation
--    step to get wrong.
--
-- 3. Amounts are stored exactly as emitted, which means *gross of the fee*.
--    Deriving net amounts is the accountant's job; storing a lossy net here
--    would make the fee unrecoverable, and forming LVR deltas from gross
--    amounts computes LVR minus fees, which loses equation (3)'s non-negativity
--    guarantee. See requirements matrix P-2.

PRAGMA journal_mode = WAL;      -- the Warden reads while the indexer writes
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS pool (
    address       TEXT PRIMARY KEY,
    chain_id      INTEGER NOT NULL,
    token0        TEXT NOT NULL,
    token1        TEXT NOT NULL,
    dec0          INTEGER NOT NULL,
    dec1          INTEGER NOT NULL,
    fee_pips      INTEGER NOT NULL,
    tick_spacing  INTEGER NOT NULL,
    created_block INTEGER
);

CREATE TABLE IF NOT EXISTS block (
    chain_id INTEGER NOT NULL,
    number   INTEGER NOT NULL,
    ts       INTEGER NOT NULL,
    PRIMARY KEY (chain_id, number)
);

-- Swap(sender, recipient, amount0, amount1, sqrtPriceX96, liquidity, tick)
-- amount0/amount1 are signed from the POOL's perspective and gross of the fee.
CREATE TABLE IF NOT EXISTS swap (
    pool           TEXT NOT NULL,
    block          INTEGER NOT NULL,
    log_index      INTEGER NOT NULL,
    tx             TEXT NOT NULL,
    ts             INTEGER NOT NULL,
    sender         TEXT,
    recipient      TEXT,
    amount0        TEXT NOT NULL,
    amount1        TEXT NOT NULL,
    sqrt_price_x96 TEXT NOT NULL,
    liquidity      TEXT NOT NULL,
    tick           INTEGER NOT NULL,
    -- Pancake-only: how much of this swap's fee the protocol took before LPs
    -- saw any of it. Uniswap's Swap event has no equivalent.
    protocol_fee0  TEXT NOT NULL DEFAULT '0',
    protocol_fee1  TEXT NOT NULL DEFAULT '0',
    PRIMARY KEY (tx, log_index)
);
CREATE INDEX IF NOT EXISTS swap_pool_time ON swap (pool, ts, block, log_index);

CREATE TABLE IF NOT EXISTS mint (
    pool       TEXT NOT NULL,
    block      INTEGER NOT NULL,
    log_index  INTEGER NOT NULL,
    tx         TEXT NOT NULL,
    ts         INTEGER NOT NULL,
    owner      TEXT,
    tick_lower INTEGER NOT NULL,
    tick_upper INTEGER NOT NULL,
    amount     TEXT NOT NULL,
    amount0    TEXT NOT NULL,
    amount1    TEXT NOT NULL,
    PRIMARY KEY (tx, log_index)
);
CREATE INDEX IF NOT EXISTS mint_pool_time ON mint (pool, ts, block, log_index);

CREATE TABLE IF NOT EXISTS burn (
    pool       TEXT NOT NULL,
    block      INTEGER NOT NULL,
    log_index  INTEGER NOT NULL,
    tx         TEXT NOT NULL,
    ts         INTEGER NOT NULL,
    owner      TEXT,
    tick_lower INTEGER NOT NULL,
    tick_upper INTEGER NOT NULL,
    amount     TEXT NOT NULL,
    amount0    TEXT NOT NULL,
    amount1    TEXT NOT NULL,
    PRIMARY KEY (tx, log_index)
);
CREATE INDEX IF NOT EXISTS burn_pool_time ON burn (pool, ts, block, log_index);

-- Periodic multicall snapshot of pool state.
--
-- `fee_protocol` is here rather than on `pool` because it is governance-settable
-- per pool: a replay of last month's history must use last month's value, not
-- today's. On the target pool it is 3400, so LPs keep 66% of every fee — see
-- requirements matrix P-1.
CREATE TABLE IF NOT EXISTS pool_state (
    pool                     TEXT NOT NULL,
    block                    INTEGER NOT NULL,
    ts                       INTEGER NOT NULL,
    sqrt_price_x96           TEXT NOT NULL,
    tick                     INTEGER NOT NULL,
    liquidity                TEXT NOT NULL,
    fee_growth_global0_x128  TEXT NOT NULL,
    fee_growth_global1_x128  TEXT NOT NULL,
    fee_protocol             INTEGER NOT NULL,
    PRIMARY KEY (pool, block)
);

-- Where reading stopped. Advanced only to (head - confirmations), inside the
-- same transaction as the inserts it covers, so a crash can never leave a gap
-- between what was written and what the cursor claims was written.
--
-- **This is a resume point, not a claim of completeness**, and it used to say it
-- was one. It is a single high-water mark maintained with max(), so it cannot
-- describe a tape with a hole in it — and the tail *starts* by putting it at the
-- head with nothing underneath, which is exactly such a tape. See `covered`.
CREATE TABLE IF NOT EXISTS cursor (
    pool       TEXT PRIMARY KEY,
    last_block INTEGER NOT NULL,
    updated_ts INTEGER NOT NULL
);

-- Which block ranges were actually *read*, as distinct from which ones produced
-- events.
--
-- The distinction is the whole point: a quiet 5,000-block window and a window
-- nobody ever fetched both contain zero swaps, and no query over `swap` can tell
-- them apart. So "how much real history do we hold" was being answered by
-- `max(ts) - min(ts)`, which measures the distance between the two ends of the
-- tape and says nothing whatever about the middle. A tape holding one day at
-- each end of a twenty-six-day span reported "spanning 26 days" and passed the
-- readiness gate. Every interrupted backfill produces that shape.
--
-- Ranges are merged on insert, so coverage is a minimal ordered set and a gap is
-- a real gap rather than a chunk boundary. Written in the same transaction as
-- the rows, for the same reason the cursor is.
--
-- Note that a database predating this table reports **no** coverage rather than
-- full coverage. That is deliberate and it is the badge's rule: unknown does not
-- become pass. We cannot honestly reconstruct which ranges an older run read.
CREATE TABLE IF NOT EXISTS covered (
    pool       TEXT NOT NULL,
    from_block INTEGER NOT NULL,
    to_block   INTEGER NOT NULL,
    PRIMARY KEY (pool, from_block)
);
CREATE INDEX IF NOT EXISTS covered_pool_range ON covered (pool, to_block);

-- --------------------------------------------------------------------------
-- The rate tape: Venus Core Pool accruals.
--
-- Same three rules as the pool tape above, and the first one bites harder here.
-- `borrow_index` is ~1.5e18 and `total_borrows` ~1.2e26; both overflow SQLite's
-- signed 64-bit INTEGER silently, and a borrow index off by a factor is a rate
-- off by a factor with nothing to notice it. TEXT, like everything else here.
--
-- Keyed on (tx, log_index) with INSERT OR IGNORE, so a re-run is a no-op.

CREATE TABLE IF NOT EXISTS venus_market (
    address      TEXT PRIMARY KEY,
    chain_id     INTEGER NOT NULL,
    symbol       TEXT NOT NULL,
    underlying   TEXT NOT NULL,
    underlying_decimals INTEGER NOT NULL,
    v_decimals   INTEGER NOT NULL,
    comptroller  TEXT NOT NULL
);

-- One AccrueInterest log. Every input the supply-rate formula needs is here
-- except the reserve factor, which is governance-settable and lives below —
-- so a rate can be recomputed from this table alone, without re-reading chain
-- state that has since moved.
CREATE TABLE IF NOT EXISTS accrue (
    market               TEXT NOT NULL,
    block                INTEGER NOT NULL,
    log_index            INTEGER NOT NULL,
    tx                   TEXT NOT NULL,
    ts                   INTEGER NOT NULL,
    cash_prior           TEXT NOT NULL,
    interest_accumulated TEXT NOT NULL,
    borrow_index         TEXT NOT NULL,
    total_borrows        TEXT NOT NULL,
    PRIMARY KEY (tx, log_index)
);
CREATE INDEX IF NOT EXISTS accrue_market_time ON accrue (market, ts, block, log_index);

-- The reserve factor as of a block, not as of now.
--
-- Kept as a series for the same reason `pool_state` keeps `fee_protocol` as one:
-- it is governance-settable, and a replay of last month's history must use last
-- month's value. Reading today's and applying it backwards would silently
-- misprice every earlier window.
CREATE TABLE IF NOT EXISTS reserve_factor (
    market   TEXT NOT NULL,
    block    INTEGER NOT NULL,
    ts       INTEGER NOT NULL,
    mantissa TEXT NOT NULL,
    PRIMARY KEY (market, block)
);

-- Which block ranges were actually read, per market.
--
-- Separate from `covered` rather than sharing it, because the pool tape and the
-- rate tape are backfilled independently and a shared table would let one
-- market's coverage claim another's. The distinction it encodes matters more
-- here than for swaps: a market that did not accrue and a market nobody fetched
-- both produce zero rows, and for the thin markets the first is *common* —
-- vUSDC accrues about twice per 5,000 blocks. Coverage is the only thing that
-- can tell them apart.
CREATE TABLE IF NOT EXISTS venus_covered (
    market     TEXT NOT NULL,
    from_block INTEGER NOT NULL,
    to_block   INTEGER NOT NULL,
    PRIMARY KEY (market, from_block)
);
CREATE INDEX IF NOT EXISTS venus_covered_range ON venus_covered (market, to_block);
