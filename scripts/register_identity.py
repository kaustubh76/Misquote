"""Register this project's four agents in the ERC-8004 registry it indexes.

    uv run python scripts/register_identity.py --chain 97               # plan only
    MISQUOTE_DRY_RUN=0 uv run python scripts/register_identity.py --chain 97 --broadcast
    uv run python scripts/register_identity.py --chain 97 --verify-only

## Why this exists

`Readme.md` says all four agents "register ERC-8004 identities". Nothing ever
had. The marketplace that surveyed four hundred agents in this registry, counted
how few of them resolve, and published the interval, had never appeared in it —
which makes the survey a thing done *to* other people.

## The shape: two transactions per agent, and why

`register(string)` mints to `msg.sender`, and the wallet holding a key on this
machine is a burn-in wallet, not the address this project publishes as its own.
So each agent is registered by the signer and then handed over with
`safeTransferFrom`. Eight transactions for four agents.

The alternative was putting the operator's key on this machine. It is a worse
trade: a submission identity whose key lives on a laptop that runs `make` is not
much of an identity, and the two-transaction path leaves a *better* record —
the mint and the handover are separately visible, so the claim "this address
owns these agents" is checkable without trusting anything this repository says.

## Dry run is the default, and it is not a stub

Without `--broadcast` this builds every transaction, estimates every one against
the live registry, prints the calldata size and the total gas, and sends
nothing. That is a real rehearsal: `estimate_gas` executes the call against
current state, so a registration that would revert fails here rather than after
the first three have already been written.

## What the record is, and when it is written

`vetting/identity/{chain}.json`, following `verify_erc8183.py` — the reading
half writes to `vetting/`, the publishing half (`make registry`) reads it and
needs no network.

The `checks` in that file are **read back from chain after the transfers**, not
copied from the receipts. A receipt says a transaction succeeded; it does not
say the registry now holds a card that resolves, or that the operator owns it.
Those are separate questions and they are the ones a reader cares about, so
`--verify-only` re-asks them without sending anything, and the answers include
running `erc8004.assess()` — the same gate this project applies to strangers —
over our own cards. A registration of ours that fails our own test is recorded
as a FAIL, because the alternative is a marketplace with a standard for
everybody else.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from misquote.chain.operator import (
    OPERATOR_KEY_ENV,
    declared_operator,
    declared_signer,
    operator_key,
)
from misquote.chain.signer import BscSigner
from misquote.registry import erc8004
from misquote.registry.cards import Card, build_cards
from misquote.registry.identity import IdentityWriter

REPO = Path(__file__).resolve().parents[1]
RECORD_DIR = REPO / "vetting" / "identity"
ARTIFACTS = REPO / "apps" / "web" / "public" / "artifacts"

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"

#: Same endpoints `verify_erc8183.py` uses. Chapel's log-serving endpoint is not
#: needed here — this reads state and sends transactions, never `eth_getLogs`
#: over a range.
RPCS: dict[int, tuple[str, ...]] = {
    56: ("https://bsc-rpc.publicnode.com", "https://bsc-dataseed.bnbchain.org"),
    97: (
        "https://bsc-testnet-rpc.publicnode.com",
        "https://data-seed-prebsc-1-s1.bnbchain.org:8545",
    ),
}

EXPLORERS = {56: "https://bscscan.com", 97: "https://testnet.bscscan.com"}


class Report:
    """The record. Same shape as `verify_erc8183.py`'s, so `CheckList` renders it."""

    def __init__(self, chain_id: int) -> None:
        self.chain_id = chain_id
        self.checks: list[dict[str, str]] = []
        self.agents: list[dict[str, Any]] = []
        self.block: int | None = None
        self.signer = ""
        self.owner = ""
        self.funding: dict[str, Any] | None = None

    def add(self, name: str, status: str, detail: str, provenance: str = "P-26") -> None:
        self.checks.append(
            {"name": name, "status": status, "detail": detail, "provenance": provenance}
        )
        print(
            f"  [{ {'PASS': 'ok  ', 'FAIL': 'FAIL', 'UNKNOWN': '????'}[status] }] {name}  {detail}"
        )

    @property
    def verdict(self) -> str:
        if any(c["status"] == FAIL for c in self.checks):
            return FAIL
        if any(c["status"] == UNKNOWN for c in self.checks) or not self.checks:
            return UNKNOWN
        return PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            # `surveyed` because every sibling record carries it and the shared
            # renderer branches on it — a block without one renders as a refusal
            # over a list of passing checks.
            "surveyed": True,
            "reason": "",
            "verdict": self.verdict,
            "registry": erc8004.IDENTITY_REGISTRY.get(self.chain_id, ""),
            "implementation": erc8004.IDENTITY_IMPLEMENTATION.get(self.chain_id, ""),
            "explorer": EXPLORERS.get(self.chain_id, ""),
            "block": self.block,
            "signer": self.signer,
            "owner": self.owner,
            "agents": self.agents,
            # Present only when this run moved gas. Omitted rather than null, so
            # a record with no funding line is a record where none happened.
            **({"funding": self.funding} if self.funding else {}),
            "checks": self.checks,
            "summary": {
                "registered": len(self.agents),
                "checked": len(self.checks),
                "failed": sum(1 for c in self.checks if c["status"] == FAIL),
                "unknown": sum(1 for c in self.checks if c["status"] == UNKNOWN),
            },
        }


def tx_hex(value: str) -> str:
    """A transaction hash in the form everything else expects.

    `SentTransaction.tx_hash` is `HexBytes.hex()`, which on web3 7 returns bare
    hex with no `0x`. Every consumer of a hash wants the prefix: an explorer
    URL, a JSON-RPC argument, a person pasting it into a search box. The first
    run of this script recorded four `bscscan.com/tx/d800eff0…` links, which is
    the one thing the whole two-transaction shape existed to produce.

    Applied on the way into the record rather than inside `chain/signer.py`.
    The signer's field is what the node returned and other callers compare it to
    receipts; changing its shape to suit a URL would be fixing a presentation
    problem in the layer that has no presentation.
    """
    value = str(value)
    return value if value.startswith("0x") else "0x" + value


def connect(chain_id: int) -> Web3:
    for url in RPCS[chain_id]:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30}))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if w3.eth.chain_id == chain_id:
                print(f"  rpc      {url}")
                return w3
        except Exception:  # noqa: BLE001 — try the next endpoint
            continue
    raise SystemExit(f"no reachable RPC for chain {chain_id}: tried {RPCS[chain_id]}")


def api_base() -> str:
    """Where the cards will point. Read, not written — see `cards.py`."""
    path = ARTIFACTS / "api.json"
    if not path.exists():
        return ""
    return str(json.loads(path.read_text()).get("base") or "")


def carry_forward(record: dict[str, Any], report: Report) -> None:
    """Move facts a re-read cannot re-derive out of the old record into the new one.

    `--verify-only` builds a fresh `Report` and overwrites the file with it. That
    is right for the checks — they are the whole point of re-reading — and wrong
    for everything the checks do not measure. The funding transfer is measured
    once, when it happens; a later verification has no way to observe it and
    silently dropped it, which is the failure this repository is named after:
    a record that looks complete and has quietly lost a line.
    """
    report.signer = str(record.get("signer") or report.signer)
    if record.get("funding"):
        report.funding = record["funding"]


def load_record(chain_id: int) -> dict[str, Any]:
    path = RECORD_DIR / f"{chain_id}.json"
    if not path.exists():
        raise SystemExit(
            f"nothing recorded at {path.relative_to(REPO)} — there is nothing to "
            "verify. Register first."
        )
    return dict(json.loads(path.read_text()))


def repair_links(agent: dict[str, Any], chain_id: int) -> dict[str, Any]:
    """Re-derive an entry's hashes and URLs from the hashes it holds.

    `--verify-only` is the step that re-reads chain and rewrites the checks, so
    it is also the natural place to correct a record written by an earlier
    version of this script — rather than hand-editing a file whose whole claim
    is that nothing in it was hand-entered. Idempotent: an already-correct entry
    comes back unchanged.
    """
    explorer = EXPLORERS.get(chain_id, "")
    fixed = dict(agent)
    register_tx = tx_hex(fixed.get("register_tx", ""))
    transfer_tx = tx_hex(fixed.get("transfer_tx", ""))
    fixed["register_tx"] = register_tx
    fixed["transfer_tx"] = transfer_tx
    fixed["register_url"] = f"{explorer}/tx/{register_tx}"
    fixed["transfer_url"] = f"{explorer}/tx/{transfer_tx}"
    return fixed


def plan(writer: IdentityWriter, cards: tuple[Card, ...], owner: str) -> int:
    """Build and estimate every transaction. Sends nothing, returns total gas."""
    total = 0
    for card in cards:
        call = writer.contract.functions.register(card.token_uri)
        try:
            gas = call.estimate_gas({"from": writer.signer.address})
        except Exception as error:  # noqa: BLE001
            print(f"  [FAIL] {card.agent}: register would revert — {error}")
            return -1
        # The transfer cannot be estimated: the token does not exist yet, and a
        # made-up id would estimate a different transaction. Priced from the one
        # measurement we do have rather than guessed at — an ERC-721 transfer is
        # dominated by the same two storage writes on any implementation.
        total += gas + 60_000
        print(f"  [plan] {card.agent:9s} {card.uri_bytes:5d} B card, register ~{gas:,} gas")
    print(f"  [plan] {len(cards)} agents, ~{total:,} gas including transfers, to {owner}")
    return total


def register_all(
    writer: IdentityWriter, cards: tuple[Card, ...], owner: str, report: Report
) -> None:
    """Two transactions per agent, recorded as they land.

    Recorded *inside* the loop rather than after it: if the fourth agent
    reverts, the three that succeeded are already on chain and the file has to
    say so. A record written only on full success would describe a state that
    does not exist.
    """
    explorer = EXPLORERS.get(writer.chain_id, "")
    for card in cards:
        agent_id, registered = writer.register(card.token_uri)
        print(f"  [sent] {card.agent:9s} id {agent_id}  register {registered.tx_hash}")
        transferred = writer.transfer(agent_id, owner)
        print(f"  [sent] {card.agent:9s} id {agent_id}  transfer {transferred.tx_hash}")
        register_tx, transfer_tx = tx_hex(registered.tx_hash), tx_hex(transferred.tx_hash)
        report.agents.append(
            {
                "agent": card.agent,
                "name": card.name,
                "agent_id": agent_id,
                "token_uri_bytes": card.uri_bytes,
                "register_tx": register_tx,
                "transfer_tx": transfer_tx,
                "register_block": registered.block,
                "gas_used": registered.gas_used + transferred.gas_used,
                "register_url": f"{explorer}/tx/{register_tx}",
                "transfer_url": f"{explorer}/tx/{transfer_tx}",
                "agent_url": f"{explorer}/token/{writer.address}?a={agent_id}",
            }
        )


def verify(
    w3: Web3, chain_id: int, agents: list[dict[str, Any]], owner: str, report: Report
) -> None:
    """Re-read every registration from chain and judge it by our own gate."""
    registry = erc8004.IdentityRegistry(w3, chain_id)
    report.block = int(w3.eth.block_number)

    # Before anything about our own agents. `IDENTITY_REGISTRY` is a proxy, and
    # every claim this script makes about what the registry *can do* —
    # `register(string)` exists, `safeTransferFrom` exists — was checked against
    # the implementation recorded in `erc8004.IDENTITY_IMPLEMENTATION`. An
    # upgrade behind the proxy leaves that recording pointing at a contract that
    # is no longer there, and leaves the selector test in
    # `tests/registry/test_identity.py` checking bytecode nobody calls.
    #
    # Reported rather than raised: an upgraded proxy does not un-register
    # anything, so the identities below are still ours and still readable. What
    # changes is that our note about *why* the calls worked has gone stale.
    recorded = erc8004.IDENTITY_IMPLEMENTATION.get(chain_id, "")
    try:
        slot = w3.eth.get_storage_at(
            Web3.to_checksum_address(erc8004.IDENTITY_REGISTRY[chain_id]),
            erc8004.IMPLEMENTATION_SLOT,
        )
        live = Web3.to_checksum_address("0x" + slot.hex()[-40:])
    except Exception as error:  # noqa: BLE001
        report.add("registry implementation unchanged", UNKNOWN, f"slot unreadable: {error}")
    else:
        report.add(
            "registry implementation unchanged",
            PASS if live.lower() == recorded.lower() else FAIL,
            f"EIP-1967 slot holds {live}"
            + ("" if live.lower() == recorded.lower() else f", recorded {recorded}"),
        )

    if not agents:
        report.add("agents registered", UNKNOWN, "nothing has been registered yet")
        return

    # Rebuilt with the ids the record already knows, because a card that has
    # been through `setAgentURI` carries its own `registrations` entry and one
    # rebuilt without them is a different document. Comparing against the
    # pre-registration shape reported all four as drifted the first time this
    # ran, which is the check working and the comparison being wrong.
    base = api_base()
    ids = {a["agent"]: int(a["agent_id"]) for a in agents if a.get("upgrade_tx")}
    expected = (
        {c.agent: c for c in build_cards(api_base=base, ids=ids, chain_id=chain_id)} if base else {}
    )

    for entry in agents:
        agent, agent_id = entry["agent"], int(entry["agent_id"])

        try:
            holder = registry.owner(agent_id)
        except Exception as error:  # noqa: BLE001
            report.add(f"{agent} #{agent_id} exists", UNKNOWN, f"ownerOf reverted: {error}")
            continue

        report.add(
            f"{agent} #{agent_id} is owned by the operator",
            PASS if holder.lower() == owner.lower() else FAIL,
            f"ownerOf returns {holder}",
        )

        card = registry.card(agent_id)
        assessment = erc8004.assess(card)
        report.add(
            f"{agent} #{agent_id} resolves",
            PASS if card.fetched else FAIL,
            f"the card is {'on chain' if card.on_chain else 'remote'} and "
            + ("decoded" if card.fetched else f"did not: {card.error}"),
        )
        # The whole reason this check is here. `substantive` is what decides
        # whether a *stranger's* agent is shown as real on /registry; ours is
        # held to it by the same function, not by a copy of its rules.
        report.add(
            f"{agent} #{agent_id} passes our own listing bar",
            PASS if assessment.substantive else FAIL,
            "erc8004.assess() says substantive"
            if assessment.substantive
            else "; ".join(assessment.notes) or "not substantive",
        )

        if agent in expected:
            on_chain_uri = registry.token_uri(agent_id)
            report.add(
                f"{agent} #{agent_id} holds the card we built",
                PASS if on_chain_uri == expected[agent].token_uri else FAIL,
                "tokenURI is byte-identical to the rebuilt card"
                if on_chain_uri == expected[agent].token_uri
                else "tokenURI differs from what cards.py builds today",
            )


def fund_operator(w3: Web3, chain_id: int, amount_wei: int, report: Report) -> str:
    """Send the operator enough gas to sign for itself, from the delegate.

    A plain value transfer, built here rather than through `BscSigner.build`,
    which takes a contract call. It still goes through `send()`, so the kill
    switch, the chain assertion, the dry-run refusal and the declared-wallet
    check all apply — none of which is worth bypassing for the sake of a
    six-line transaction.

    Recorded in the same file as everything else. The alternative is a transfer
    that happened in somebody's terminal and is remembered by nobody, which is
    the shape of provenance this repository exists to argue against.
    """
    key = os.environ.get("MISQUOTE_PRIVATE_KEY")
    if not key:
        raise SystemExit("MISQUOTE_PRIVATE_KEY is unset; there is nothing funded to send from")

    signer = BscSigner(w3, key, kill_file=REPO / "ops" / "KILL")
    operator = declared_operator()
    assert operator is not None  # main() has already refused without one

    balance = w3.eth.get_balance(signer.address)
    if balance <= amount_wei:
        raise SystemExit(
            f"{signer.address} holds {balance / 1e18:.6f} and cannot send "
            f"{amount_wei / 1e18:.6f} plus fees"
        )

    transaction = {
        "from": signer.address,
        "to": Web3.to_checksum_address(operator),
        "value": int(amount_wei),
        "chainId": signer.chain_id,
        "nonce": w3.eth.get_transaction_count(signer.address, "pending"),
        "gas": 21_000,
        "gasPrice": w3.eth.gas_price,
    }
    sent = signer.send(transaction)
    tx = tx_hex(sent.tx_hash)
    print(f"  [sent] funded operator with {amount_wei / 1e18:.6f}  {tx}")
    report.funding = {
        "from": signer.address,
        "to": operator,
        "amount": f"{amount_wei / 1e18:.6f}",
        "tx": tx,
        "url": f"{EXPLORERS.get(chain_id, '')}/tx/{tx}",
    }
    return tx


def upgrade_cards(
    writer: IdentityWriter, agents: list[dict[str, Any]], chain_id: int, *, broadcast: bool
) -> bool:
    """Rewrite each recorded agent's card to the complete one. Operator signs.

    The four chapel identities were registered and handed over before anyone had
    looked at what a listing actually reads, so their cards carry neither an
    image nor a back-reference to their own registry entry. `setAgentURI` is
    owner-only and they are owned by the operator, so this is the one path that
    can correct them — and it is why `MISQUOTE_OPERATOR_PRIVATE_KEY` exists.

    Returns False when nothing could be done, so the caller can exit non-zero
    without this function deciding the process's fate.
    """
    base = api_base()
    ids = {a["agent"]: int(a["agent_id"]) for a in agents}
    complete = {c.agent: c for c in build_cards(api_base=base, ids=ids, chain_id=chain_id)}
    explorer = EXPLORERS.get(chain_id, "")

    for entry in agents:
        card = complete.get(entry["agent"])
        if card is None:
            print(f"  [skip] {entry['agent']}: no card is built for this agent any more")
            continue

        current = writer.token_uri(int(entry["agent_id"]))
        if current == card.token_uri:
            print(f"  [ok  ] {entry['agent']:9s} #{entry['agent_id']} already holds this card")
            continue

        if not broadcast:
            gas = writer.contract.functions.setAgentURI(
                int(entry["agent_id"]), card.token_uri
            ).estimate_gas({"from": writer.signer.address})
            print(
                f"  [plan] {entry['agent']:9s} #{entry['agent_id']} "
                f"{len(current)}B -> {card.uri_bytes}B, ~{gas:,} gas"
            )
            continue

        sent = writer.set_agent_uri(int(entry["agent_id"]), card.token_uri)
        tx = tx_hex(sent.tx_hash)
        print(f"  [sent] {entry['agent']:9s} #{entry['agent_id']} setAgentURI {tx}")
        entry["upgrade_tx"] = tx
        entry["upgrade_url"] = f"{explorer}/tx/{tx}"
        entry["token_uri_bytes"] = card.uri_bytes
        entry["gas_used"] = int(entry.get("gas_used", 0)) + sent.gas_used

    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chain", type=int, default=97, choices=(56, 97))
    ap.add_argument(
        "--broadcast",
        action="store_true",
        help="actually send. Needs MISQUOTE_DRY_RUN=0; without this it plans only.",
    )
    ap.add_argument(
        "--fund-operator",
        metavar="TBNB",
        help="send this much gas from the delegate to the operator first, e.g. 0.01",
    )
    ap.add_argument(
        "--upgrade-cards",
        action="store_true",
        help="rewrite recorded agents' cards to the complete shape. Operator signs.",
    )
    ap.add_argument(
        "--verify-only",
        action="store_true",
        help="re-read what is already recorded and rewrite the checks",
    )
    ap.add_argument("--out", default=None, help="where to record (default vetting/identity/N.json)")
    args = ap.parse_args()

    out = Path(args.out) if args.out else RECORD_DIR / f"{args.chain}.json"
    report = Report(args.chain)

    owner = declared_operator()
    if not owner:
        raise SystemExit(
            "MISQUOTE_OPERATOR_ADDRESS is unset. The identities have to be "
            "transferred to something, and this script will not invent it."
        )
    report.owner = owner

    print(f"\nERC-8004 identities, chain {args.chain}")
    w3 = connect(args.chain)

    if args.upgrade_cards:
        record = load_record(args.chain)
        report.agents = [repair_links(a, args.chain) for a in (record.get("agents") or [])]
        carry_forward(record, report)
        if not report.agents:
            raise SystemExit("nothing recorded to upgrade")

        key = operator_key()
        if key is None:
            raise SystemExit(
                "setAgentURI is owner-only and these identities are owned by the "
                f"operator, so this needs {OPERATOR_KEY_ENV}. Unset, there is no "
                "way to correct a card after it has been handed over — which is "
                "the argument for completing it before the transfer instead."
            )

        if args.fund_operator and args.broadcast:
            fund_operator(w3, args.chain, int(float(args.fund_operator) * 10**18), report)

        signer = BscSigner(w3, key, kill_file=REPO / "ops" / "KILL")
        balance = w3.eth.get_balance(signer.address)
        print(f"  operator {signer.address}  balance {balance / 1e18:.6f}")
        if args.broadcast and balance == 0:
            raise SystemExit(
                f"the operator holds no gas on chain {args.chain}, so it cannot "
                "sign anything. Send it a little from the wallet in "
                "MISQUOTE_PRIVATE_KEY, which is funded, and re-run."
            )

        writer = IdentityWriter(signer)
        print(f"  registry {writer.address}\n")
        if not args.broadcast:
            print("  planning only — pass --broadcast to send\n")
        upgrade_cards(writer, report.agents, args.chain, broadcast=args.broadcast)
        if not args.broadcast:
            print("\nNothing was sent. Re-run with MISQUOTE_DRY_RUN=0 --broadcast.")
            return 0
        print()
        verify(w3, args.chain, report.agents, owner, report)

    elif args.verify_only:
        record = load_record(args.chain)
        report.agents = [repair_links(a, args.chain) for a in (record.get("agents") or [])]
        carry_forward(record, report)
        print(f"  verify   {len(report.agents)} recorded registration(s)\n")
        verify(w3, args.chain, report.agents, owner, report)
    else:
        base = api_base()
        cards = build_cards(api_base=base)
        print(f"  cards    {len(cards)} built against {base}")
        print(f"  owner    {owner}")

        signer = BscSigner(w3, kill_file=REPO / "ops" / "KILL")
        report.signer = signer.address
        declared = declared_signer()
        print(
            f"  signer   {signer.address}"
            + (" (declared)" if declared else "")
            + (f"  balance {w3.eth.get_balance(signer.address) / 1e18:.6f}")
        )
        writer = IdentityWriter(signer)
        print(f"  registry {writer.address}\n")

        if not args.broadcast:
            print("  planning only — pass --broadcast to send\n")
            if plan(writer, cards, owner) < 0:
                return 1
            print("\nNothing was sent. Re-run with MISQUOTE_DRY_RUN=0 --broadcast.")
            return 0

        if signer.dry_run:
            raise SystemExit(
                "--broadcast was passed and MISQUOTE_DRY_RUN is not 0, so the "
                "signer would refuse on the first send. Set it on this one "
                "command; never in .env."
            )

        register_all(writer, cards, owner, report)
        print()
        verify(w3, args.chain, report.agents, owner, report)

    print(f"\nverdict  {report.verdict}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
    print(f"recorded -> {out.relative_to(REPO)}")
    print("republish with `make registry`")
    return 0 if report.verdict == PASS else 1


if __name__ == "__main__":
    sys.exit(main())
