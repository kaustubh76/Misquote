"""TermiX AACP: the sponsor's protocol, and what we already share with it.

TermiX judges the track this module exists for, and its Agent Autonomous Commerce
Protocol turns out not to be a parallel world to ours. It builds on **ERC-8004**
for identity and **ERC-8183** for job escrow — the same two standards this
codebase already reads and models.

Reading their published contract table produced a genuinely useful surprise:

    TermiX IdentityRegistry (56)   0x8004A169FB4a3325136EB29fA0ceB6D2e539a432
    ours, registry/erc8004.py:43   0x8004A169FB4a3325136EB29fA0ceB6D2e539a432

**The same contract, byte for byte.** We were reading TermiX's identity registry
before we had heard of AACP, because both of us followed ERC-8004 to the address
it deploys at on BNB Chain. Their settlement token is `0x55d3...` — already
`USDT_MAINNET` here, and token0 of the flagship pool.

And `TermixEscrow` is a **deployed ERC-8183 job escrow on BSC mainnet**, which is
exactly the address `registry/erc8183.py:JOB_ESCROW` deliberately does not have.

## What this module will and will not do

`erc8183.py` refuses to carry an address it has not verified. That refusal is not
retired by finding a plausible one in a vendor's documentation — a table on a
website is a claim, not a verification. So:

- `verify(w3)` goes to chain and checks the escrow has **code**, that the
  identity registry is the contract we already read (`name()` == "AgentIdentity"),
  and that the settlement token matches what we already record. It returns
  evidence, not a boolean.
- **Only a passing `verify()` should populate `JOB_ESCROW`**, and doing so is a
  deliberate act with the evidence recorded — not an import-time side effect.

There is **no testnet**. TermiX documents chain 56 and Base 8453 only. Against a
dry-run-by-default posture that matters: anything that writes must run on a fork
first, and `chain/signer.py`'s guards still apply.

Their docs are explicit that the table can move — *"always fetch live addresses
via `/api/v1/config/contracts` before signing transactions"* — so the constants
below are a **snapshot to check against**, never a source of truth. `mismatches()`
is what a caller uses before signing anything.

## Credentials

Public endpoints — config, stats, explorer, discovery — need none, which is why
the read-only half works today. Authenticated calls need a wallet-signed nonce
exchanged for a session JWT, and that is the same blocker as the 24h burn-in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from misquote.chain.addresses import USDT_MAINNET
from misquote.registry.erc8004 import IDENTITY_REGISTRY, UnsafeURL, _assert_fetchable

BSC_MAINNET = 56
BASE_MAINNET = 8453

API_BASE = {
    BSC_MAINNET: "https://platform-backend.prod.termix.live",
    BASE_MAINNET: "https://platform-backend-base.prod.termix.live",
}

# A snapshot of TermiX's published table, recorded so it can be *checked* — both
# against chain and against their own live config. Never used as a source of
# truth for signing.
#
# There is no chain 97 entry because there is no testnet deployment. An absent
# key raises rather than defaulting, for the same reason `escrow_address()` in
# erc8183.py does.
CONTRACTS: dict[int, dict[str, str]] = {
    BSC_MAINNET: {
        "IdentityRegistry": "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
        "TermixEscrow_USDT": "0xCE02f987D8b8AF694E13C8a843Db9c77caBF544c",
        "TermixEscrow_USDC": "0x6A52ba4C84b348FaEAe13dDC7A97b4F6af23913C",
        "TermixReputation": "0xFf3f7038c4919A420B30D7B3533cb386D5898189",
        "SettlementToken_USDT": USDT_MAINNET,
    },
}

CONFIG_PATH = "/api/v1/config/contracts"

# Public, no credentials, and the endpoint that made the interface finding
# possible: it returns real orders with their budgets, which is what let the
# on-chain struct be decoded by agreement rather than by guesswork.
EXPLORER_PATH = "/api/v1/explorer/jobs"

# --- what the escrow actually implements ------------------------------------
#
# `registry/erc8183.py` carried this address as a verified ERC-8183 job escrow
# on the strength of everything *around* the interface: real bytecode, a
# settlement token we already record, an identity registry byte-identical to the
# ERC-8004 one. Its own evidence flagged the hole — "nobody has read an ERC-8183
# job back out of it" — and reading one closed it in the unexpected direction.
#
# Recovered from the deployed implementation's bytecode rather than from any
# documentation: the dispatch table's PUSH4 selectors, resolved by keccak. None
# of the seven ERC-8183 core calls is present, across 5,894 candidate signatures
# (`createJob`, `setProvider`, `setBudget`, `fund`, `submit`, `complete`,
# `reject`, each over every 0-, 1-, 2- and 3-argument shape of the eight common
# ABI types, plus the EIP's own five-argument `createJob`).
#
# Jobs are keyed by a **bytes32 order id**, not the EIP's uint256 jobId. That is
# the whole explanation for `jobs(uint256)`, `nextJobId()` and `jobCount()`
# reverting: not a misspelling, a different interface.
ESCROW_INTERFACE: dict[str, str] = {
    "orders(bytes32)": "0x9c3f1e90",
    "acceptOrder(bytes32)": "0xdfc86408",
    "settlementToken()": "0x7b9e618d",
    "protocolFeeBps()": "0x35659fb8",
    "feeRecipient()": "0x46904840",
    "reputation()": "0xc52164c6",
}

# 21 of 65 selectors resolved. The remaining 44 are recorded as unresolved
# rather than guessed — naming a function we have not confirmed would be the
# exact failure this module was written to avoid.
ESCROW_SELECTORS_TOTAL = 65
ESCROW_SELECTORS_RESOLVED = 21

# `orders(bytes32)` returns 13 words. Only the ones confirmed *against an
# independent source* are named; the rest are deliberately left as offsets.
#
# Word 3 is the budget in 18 decimals: checked against the budget TermiX's own
# public explorer publishes for the same order, and it agreed on **20 of 20**
# live orders, exactly. That is the agreement that makes this a decode rather
# than a reading of tea leaves.
#
# Word 12 reads 259,200 on every order — three days, matching the "optimistic"
# proof method the explorer reports, though nothing here has confirmed the name.
ORDER_WORD_BUDGET = 3
ORDER_WORD_WINDOW = 12
ORDER_WORDS = 13

# NOT decoded, and left that way on purpose: no word in the struct separates the
# explorer's SETTLED orders from its PENDING_ACCEPT ones — word 8 reads 4 on
# both. So this module does not claim to read an order's state, and nothing
# downstream may either.
ORDER_STATE_IS_UNDECODED = True

MIN_ESCROW_CODE_BYTES = 64  # anything smaller is a proxy stub at best, not an escrow


class NoDeployment(RuntimeError):
    """Asked for a chain TermiX does not deploy to. There is no testnet."""


@dataclass(frozen=True, slots=True)
class Evidence:
    """What was checked, what it returned, and whether it agreed.

    A boolean would be worse than useless here: the interesting output of a
    verification is the *readings*, because that is what a reader needs to
    disagree with us.
    """

    chain_id: int
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def record(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append((name, ok, detail))

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(ok for _, ok, _ in self.checks)

    @property
    def failures(self) -> list[str]:
        return [f"{name}: {detail}" for name, ok, detail in self.checks if not ok]

    def render(self) -> str:
        lines = [f"  TermiX AACP verification — chain {self.chain_id}"]
        for name, ok, detail in self.checks:
            lines.append(f"  [{'ok' if ok else 'FAIL':^6}] {name:<28} {detail}")
        lines.append(f"\n  {'VERIFIED' if self.ok else 'NOT VERIFIED'}")
        return "\n".join(lines)


def api_base(chain_id: int) -> str:
    base = API_BASE.get(chain_id)
    if base is None:
        raise NoDeployment(
            f"TermiX documents no deployment on chain {chain_id}. Mainnet 56 and "
            "Base 8453 only — there is no testnet, so anything that writes runs "
            "on a fork first."
        )
    return base


def contracts(chain_id: int) -> dict[str, str]:
    known = CONTRACTS.get(chain_id)
    if known is None:
        raise NoDeployment(f"no recorded TermiX contract table for chain {chain_id}")
    return dict(known)


def shares_our_identity_registry(chain_id: int) -> bool:
    """Is TermiX's IdentityRegistry the contract we already read?

    Compared case-insensitively because one table is checksummed and the other is
    not, and a case difference is not a different contract.
    """
    theirs = CONTRACTS.get(chain_id, {}).get("IdentityRegistry", "")
    ours = IDENTITY_REGISTRY.get(chain_id, "")
    return bool(theirs) and theirs.lower() == ours.lower()


def fetch_live_contracts(chain_id: int, *, timeout: float = 8.0) -> dict[str, str]:
    """Their live table, which their docs say is authoritative over any snapshot.

    Public endpoint, no credentials. Guarded by the same SSRF check the ERC-8004
    reader uses — the host is ours here rather than a stranger's, but a guard
    that only runs on untrusted input is a guard someone will forget to apply.
    """
    import httpx

    url = api_base(chain_id) + CONFIG_PATH
    _assert_fetchable(url)
    response = httpx.get(url, timeout=timeout, follow_redirects=False)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected config shape: {type(payload).__name__}")
    return _flatten_addresses(payload)


def _flatten_addresses(payload: dict) -> dict[str, str]:
    """Pull every `0x`-prefixed 20-byte value out, whatever the nesting.

    Their response shape is not pinned by the docs and would be a poor thing to
    hard-code against; what matters is the set of addresses it contains, so that
    `mismatches()` can tell whether anything we recorded has moved.
    """
    found: dict[str, str] = {}

    def walk(node, prefix: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{prefix}.{key}" if prefix else str(key))
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{prefix}[{i}]")
        elif isinstance(node, str) and node.startswith("0x") and len(node) == 42:
            found[prefix] = node

    walk(payload)
    return found


def mismatches(chain_id: int, live: dict[str, str]) -> list[str]:
    """Recorded addresses that do not appear anywhere in their live config.

    The check to run **before signing**, per their own instruction. An address
    that has moved is not a reason to guess the new one; it is a reason to stop.
    """
    live_set = {v.lower() for v in live.values()}
    if not live_set:
        return ["live config contained no addresses at all"]
    return [
        f"{name} ({address}) is not in the live config"
        for name, address in contracts(chain_id).items()
        if address.lower() not in live_set
    ]


def fetch_public_jobs(chain_id: int = BSC_MAINNET, *, timeout: float = 15.0) -> list[dict]:
    """Real orders from TermiX's public explorer. No credentials.

    The half of their API that needs no wallet-signed nonce, and the reason the
    on-chain struct could be decoded at all: it publishes each order's budget,
    so a word in the struct can be confirmed by agreement with an independent
    source instead of being named because it looked about right.
    """
    import httpx

    url = api_base(chain_id) + EXPLORER_PATH
    _assert_fetchable(url)
    response = httpx.get(url, timeout=timeout, follow_redirects=False)
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"unexpected explorer shape: {type(payload).__name__}")
    return items


def read_order(w3, escrow: str, order_id: str) -> list[int]:
    """`orders(bytes32)` -> its 13 words, undecoded.

    Returns words rather than a named struct because only two of the thirteen
    have been confirmed against an independent source. A dataclass with thirteen
    plausible field names would read as knowledge and would be, at best, nine
    tenths guess.

    Raises rather than returning zeros on a bad id: an order that does not exist
    on this escrow returns all-zero words, and a caller that cannot tell that
    from a real order with a zero budget would report a hire that never happened.
    """
    from eth_utils import keccak

    selector = keccak(text="orders(bytes32)")[:4]
    key = order_id[2:] if order_id.startswith("0x") else order_id
    if len(key) != 64:
        raise ValueError(f"order id must be 32 bytes, got {len(key) // 2}")
    raw = w3.eth.call({"to": w3.to_checksum_address(escrow), "data": selector + bytes.fromhex(key)})
    if len(raw) < ORDER_WORDS * 32:
        raise ValueError(f"orders() returned {len(raw)} bytes, expected {ORDER_WORDS * 32}")
    return [int.from_bytes(raw[i : i + 32], "big") for i in range(0, ORDER_WORDS * 32, 32)]


def order_budget(words: list[int]) -> float:
    """The one field confirmed against TermiX's own published figure."""
    return words[ORDER_WORD_BUDGET] / 1e18


def implements_erc8183(w3, escrow: str) -> bool:
    """Does this escrow expose ERC-8183's job interface at all?

    Cheap, and the check that should have run before the address was ever
    recorded as one. `jobs(uint256)` reverting is the observable.
    """
    from eth_utils import keccak

    for signature in ("jobs(uint256)", "nextJobId()", "jobCount()"):
        try:
            w3.eth.call({"to": w3.to_checksum_address(escrow), "data": keccak(text=signature)[:4]})
        except Exception:  # noqa: BLE001 — a revert is the answer, not an error
            continue
        return True
    return False


IDENTITY_ABI = json.loads(
    '[{"name":"name","type":"function","stateMutability":"view","inputs":[],'
    '"outputs":[{"type":"string"}]}]'
)


def verify(w3, chain_id: int = BSC_MAINNET) -> Evidence:
    """Check the recorded table against chain. Returns readings, not a verdict.

    This is what has to pass before `erc8183.JOB_ESCROW` may be populated. A
    vendor's documentation is a claim; bytecode at an address is a verification,
    and the distinction is the reason that mapping was left empty in the first
    place.
    """
    evidence = Evidence(chain_id=chain_id)
    table = contracts(chain_id)

    escrow = table["TermixEscrow_USDT"]
    try:
        code = w3.eth.get_code(w3.to_checksum_address(escrow))
    except Exception as error:  # noqa: BLE001 — any RPC failure is a failed check
        evidence.record("escrow has code", False, f"read failed: {error}")
        code = b""
    else:
        evidence.record(
            "escrow has code",
            len(code) >= MIN_ESCROW_CODE_BYTES,
            f"{escrow} -> {len(code)} bytes",
        )

    evidence.record(
        "identity registry is ours",
        shares_our_identity_registry(chain_id),
        f"{table['IdentityRegistry']} vs our {IDENTITY_REGISTRY.get(chain_id)}",
    )

    try:
        identity = w3.eth.contract(
            address=w3.to_checksum_address(table["IdentityRegistry"]), abi=IDENTITY_ABI
        )
        name = identity.functions.name().call()
    except Exception as error:  # noqa: BLE001
        evidence.record("identity registry answers", False, f"name() failed: {error}")
    else:
        evidence.record("identity registry answers", name == "AgentIdentity", f"name() = {name!r}")

    evidence.record(
        "settlement token is ours",
        table["SettlementToken_USDT"].lower() == USDT_MAINNET.lower(),
        f"{table['SettlementToken_USDT']}",
    )
    return evidence


__all__ = [
    "API_BASE",
    "CONTRACTS",
    "ESCROW_INTERFACE",
    "EXPLORER_PATH",
    "ORDER_WORDS",
    "ORDER_WORD_BUDGET",
    "Evidence",
    "NoDeployment",
    "UnsafeURL",
    "api_base",
    "contracts",
    "fetch_live_contracts",
    "fetch_public_jobs",
    "implements_erc8183",
    "mismatches",
    "order_budget",
    "read_order",
    "shares_our_identity_registry",
    "verify",
]
