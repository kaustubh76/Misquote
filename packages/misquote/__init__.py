"""Misquote — an agent marketplace whose numbers trace to chain state.

Layering contract, enforced by tests/test_layering.py:

    core, estimators, lvr, replay   PURE. stdlib only. No web3, no sqlite3, no
                                    asyncio, no requests, no os.environ, and no
                                    wall clock. Time arrives as an argument.

    indexer, chain                  I/O. May touch the network and the database.

    agents, ops, registry,          Drivers and surface. May import anything.
    sessions, tearsheet

The rule exists so that look-ahead in the replay engine is structurally
impossible rather than merely tested: a layer that cannot read a clock or a
database cannot read the future.
"""

__version__ = "0.1.0"
