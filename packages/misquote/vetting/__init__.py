"""Pool due diligence: the badge, and the reader that fills it in.

Split so the judgement is pure. `badge.evaluate` is a function of readings and
needs no network, which is what lets every check be tested offline; `read.py` is
the only part that touches an endpoint.
"""
