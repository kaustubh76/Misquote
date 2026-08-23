"""The four agents. Thin drivers over the shared core.

DRIVER LAYER. An agent owns its loop, its executor, and its risk governor; it
owns no math.

All four live here. This said "Warden, Grid, and Sentinel live here; Router is a
separate BNB Agent Studio CLI project under the top-level agents/router/" — two
lines under a first line reading "The four agents", and naming a directory that
has never existed. Router replays a different tape with a different driver, so
its card comes from `scripts/router_showcase.py` rather than
`scripts/showcase.py`; the Agent Studio *deployment* is a separate thing and is
on the not-built ledger.
"""
