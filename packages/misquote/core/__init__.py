"""Pure math: Uniswap/Pancake v3 tick arithmetic and the Avellaneda-Stoikov policy.

PURE LAYER. stdlib only, integers where the chain uses integers. Every function
here is a deterministic function of its arguments — no clock, no I/O, no config.

`policy.decide()` is the whole point: it takes an Observation of scalars and
returns a Decision. It never sees an event, a cursor, or a database handle, so
it cannot look ahead.
"""
