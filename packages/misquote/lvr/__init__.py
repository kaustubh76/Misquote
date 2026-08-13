"""Realized loss-versus-rebalancing, computed from chain events (spec section 4).

PURE LAYER. Model-free and settlement-grade: LVR is measured per swap off the
v3 bonding curve, never from the closed-form sigma^2 P^2 |V''| / 2 expression,
because a settlement number must not depend on a model.
"""
