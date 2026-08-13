"""Signed writes and live reads against BSC.

I/O LAYER. Kept separate from indexer/ so the layering test can ban the pure
layers from importing it — nothing that computes a number is allowed to also be
able to spend money.
"""
