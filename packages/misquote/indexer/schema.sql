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

-- How far the tape is complete. Advanced only to (head - confirmations), inside
-- the same transaction as the inserts it covers, so a crash can never leave a
-- gap between what was written and what the cursor claims was written.
CREATE TABLE IF NOT EXISTS cursor (
    pool       TEXT PRIMARY KEY,
    last_block INTEGER NOT NULL,
    updated_ts INTEGER NOT NULL
);
