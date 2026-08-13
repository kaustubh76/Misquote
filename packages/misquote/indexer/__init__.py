"""BSC event ingestion into a local SQLite tape.

I/O LAYER. Chunked eth_getLogs with idempotent inserts, so re-running a backfill
is a no-op and crash recovery is "run it again". The tape it produces is a file
we can checksum and ship, which is what lets a judge reproduce a quote.
"""
