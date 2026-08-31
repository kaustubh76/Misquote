"""Run Sentinel against a live chain, without the ability to spend.

    uv run python -m misquote.agents.sentinel --seconds 600
    make sentinel

Sentinel is the agent that earned the engine's generality argument: its primary
signal *is* §3.4's swap-imbalance z-score, and running it is what proved that arm
had been passing a hardcoded `0.0` and could never fire (the third verification
pass's finding, matrix V-3). Warden could not have found it — it reaches the same
pull through either arm, so a dead arm looks like a quiet one.

The same applies to the live driver. Sentinel is the policy most likely to notice
if the live path and the replay path ever diverge on the imbalance estimator,
because it is the one with nothing else to fall back on.

See `agents/grid/__main__.py` for why neither of these existed until the policy
seam reached `WardenLive`.
"""

from __future__ import annotations

import sys

from misquote.agents.sentinel.policy import SentinelParams, sentinel_policy
from misquote.agents.warden.__main__ import run_agent


def main(argv: list[str] | None = None) -> int:
    return run_agent(
        name="sentinel",
        policy=sentinel_policy(SentinelParams()),
        argv=argv,
        description=__doc__,
    )


if __name__ == "__main__":
    sys.exit(main())
