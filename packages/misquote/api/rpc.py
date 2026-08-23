"""One connection helper, so two routes cannot disagree about what "no RPC" means.

Same preference order as `scripts/registry_report.py`: `BSC_RPC_URL` when set —
faster, and it will not disappear — then the public endpoints the indexer
already uses. Refusing rather than returning `None` is the load-bearing part: a
caller that forgets to check a `None` builds an answer out of a missing
connection, and the resulting response is a confident empty wallet rather than
"we could not look".

`tests/conftest.py` points every RPC variable at `http://127.0.0.1:1/blackhole`,
so in the suite this function is exercised as a refusal. That is deliberate — the
refusal is the path most likely to be seen in a demo, on a host with no key
configured, and it is the one worth having tested.
"""

from __future__ import annotations

import os
from typing import Any

from misquote.api.errors import refuse

DEFAULT_CHAIN_ID = 56


def connect(chain_id: int = DEFAULT_CHAIN_ID) -> Any:
    """A Web3 bound to `chain_id`, or a refusal naming how many endpoints were tried."""
    from web3 import HTTPProvider, Web3

    from misquote.indexer.reader import PUBLIC_RPCS

    keyed = os.environ.get("BSC_RPC_URL")
    candidates = [keyed] if keyed else list(PUBLIC_RPCS.get(chain_id, ()))

    for url in candidates:
        try:
            w3 = Web3(HTTPProvider(url, request_kwargs={"timeout": 15}))
            if w3.eth.chain_id == chain_id:
                return w3
        except Exception:  # noqa: BLE001 — try the next one
            continue

    raise refuse(
        503,
        error=f"no endpoint answered for chain {chain_id} ({len(candidates)} tried)",
        remedy="set BSC_RPC_URL",
        note="No read was attempted. This is an absent capability, not an absent result.",
    )
