"""The no-look-ahead replay engine — the Personal Quote Engine core (spec section 6).

PURE LAYER (the tape's sqlite3 handle is the single, deliberate exception, and it
is confined to tape.py).

Engine.step() executes nothing. It ingests events up to the decision time,
updates estimators, builds an Observation, and returns a Decision. The live
driver and the replay driver share it byte for byte, which is what makes
"same code path, different input wallet" a provable claim rather than a promise.
"""
