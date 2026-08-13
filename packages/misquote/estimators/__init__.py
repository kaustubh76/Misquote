"""Trailing-only parameter estimation (spec section 5).

PURE LAYER. Every estimator carries a decision timestamp and hard-asserts that
each ingested event is at or before it. That assert is test T3, implemented in
code rather than in review, and it is unconditional in both the live and the
replay driver.
"""
