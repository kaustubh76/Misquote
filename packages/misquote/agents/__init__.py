"""The four agents. Thin drivers over the shared core.

DRIVER LAYER. An agent owns its loop, its executor, and its risk governor; it
owns no math. Warden, Grid, and Sentinel live here; Router is a separate BNB
Agent Studio CLI project under the top-level agents/router/.
"""
