"""What is not built, named in one place so the UI cannot quietly omit it.

A marketplace page that shows fewer cards than it advertises categories is
telling the truth about the ones it shows and lying by omission about the rest.
All four are built now; what remains on this list is narrower and is named. `Readme.md` §1
advertises four categories, `docs/FOR_JUDGES.md` is explicit that one of them
does not exist, and the card page had no way to say so — absence rendered as
absence.

So the gaps are data. Each one names what it would have been, why it is not, and
the path a reader can check the claim against, and `tests/web/test_ledger.py`
asserts that nothing here has quietly been built and that nothing built has
quietly been left out.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class NotBuilt:
    """One advertised capability that does not exist, and the evidence."""

    name: str
    category: str
    what: str  # what it would have done
    why: str  # why it is not there
    evidence: str  # the path a reader can check


NOT_BUILT: tuple[NotBuilt, ...] = (
    # Router was here, and is not any more: the fourth category is built.
    # `agents/router/policy.py` is the switching boundary, `replay/allocation.py`
    # replays it over a Venus rate tape, and `apps/web/public/artifacts/router.json`
    # is the card. What it needed was the second venue model this entry named as
    # the reason for cutting it — `chain/venus.py`, verified three ways, plus
    # `estimators/apr.py`, which derives a realized rate rather than quoting one.
    #
    # `tests/web/test_ledger.py::test_ledger_entries_still_describe_reality` is
    # what forced this deletion, by failing the moment `agents/router/` stopped
    # being an empty directory. That is the ledger working in the direction
    # nobody designs for: it disclosed a gap, and then refused to keep
    # disclosing one that had closed.
    #
    # What is still *not* built is the Agent Studio CLI deployment that entry
    # also mentioned. It is a separate claim and it has its own entry below.
    NotBuilt(
        name="Agent Studio deployment",
        category="Yield",
        what=(
            "Router registered and deployed through the BNB Agent Studio CLI, as the "
            "native-citizenship proof — an ERC-8004 identity of its own, an ERC-8183 "
            "task interface, and x402 self-funding."
        ),
        why=(
            "The agent is built and replays on a chain tape; the deployment is not, "
            "and it needs a funded wallet. Registration writes an identity on chain "
            "and the x402 path funds it, neither of which this repository will do "
            "from an unfunded posture — the same gate that keeps `make warden` on "
            "the recording executor. Two of the vendor's own links are also dead: "
            "`studio.bnbchain.org` does not resolve, and the npm package's declared "
            "repository, github.com/bnb-chain/bnbagent-studio, returns 404. The "
            "artifact is real and signed; its source is not readable."
        ),
        evidence="packages/misquote/agents/router/ — no studio.py",
    ),
    NotBuilt(
        name="Altana session keys",
        category="Activation",
        what=(
            "The caps subset: allowlist, spend cap, expiry, Keystore, and one-"
            "transaction revoke, so hiring an agent is bounded and reversible."
        ),
        why=(
            "The caps subset is enumerated and priced — `sessions/keys.py` "
            "publishes the grant as two transactions and the revoke as one — but "
            "no Altana session-key module has been verified on either network, so "
            "there is no address to send them to. That is why no page here has a "
            "Hire button: the button would not do anything."
        ),
        evidence="packages/misquote/sessions/keys.py — SESSION_KEY_MODULE is empty",
    ),
    NotBuilt(
        name="Vetting proof-of-concepts",
        category="Due diligence",
        what=(
            'The second half of "they flag, we prove": each badge finding '
            "shipping a Foundry script that demonstrates it on a mainnet fork, so "
            "a claim about a pool is executable rather than assertable."
        ),
        why=(
            # "eight" for as long as this entry has existed. `badge.py` runs nine
            # `_check_*` functions and its own docstring says nine; the site
            # renders this sentence directly above a card listing all nine, so
            # the miscount was visible on the page it qualifies.
            # `test_ledger.test_the_ledger_counts_the_checks_that_exist` counts
            # the functions rather than trusting either prose.
            "The badge itself is built — `python -m misquote.vetting` reads nine "
            "checks off chain and writes vetting/badges/<pool>.json — and the fork "
            "lab under vetting/forge exists and runs. Nothing joins them: a FAIL "
            "today is a sentence, not a transaction that reverts."
        ),
        evidence="vetting/forge/script/ — no Badge.s.sol",
    ),
    NotBuilt(
        name="Signing on a live chain",
        category="Operations",
        what=(
            "`make warden` broadcasting the decisions it already makes correctly, "
            "against chapel or mainnet, rather than recording them."
        ),
        why=(
            "The executor now exists and is proven. `chain/executor.py` mints, "
            "recentres and withdraws through the verified NonfungiblePositionManager, "
            "and nine tests exercise it against a forked BSC with real "
            "transactions — including that a recentre which cannot open leaves the "
            "wallet flat rather than stranded, and that a withdrawal reaches the "
            "wallet rather than stopping at `tokensOwed`. The agent also now "
            "reconciles against the chain on boot, so a restart adopts the "
            "position the wallet really holds instead of minting a second one "
            "over the top of it — which is what made an unattended run unsafe. "
            "What is missing is a funded wallet and the decision to use one: "
            "`make warden` is still wired to the recording executor, and the "
            "go/no-go is the gate for changing that."
        ),
        evidence=(
            # Names the capability, not a filename. An earlier wording pointed at
            # a file no plan ever proposed writing, so the claim would have kept
            # reading as true even after signing was wired through the entrypoint
            # that actually exists — an absence check aimed at the wrong absence.
            "packages/misquote/agents/warden/__main__.py — does not import ChainExecutor"
        ),
    ),
    NotBuilt(
        name="TermiX authenticated API",
        category="Registry",
        what=(
            "Listing our agents on TermiX's own platform, and any authenticated "
            "read of their order book — the half of their API that is not public."
        ),
        why=(
            "Blocked on a wallet-signed nonce exchanged for a session JWT, which "
            "is the same signing path the 24h burn-in needs and which does not "
            "exist yet. Deliberately not half-built: an auth module that cannot "
            "complete the exchange would look present on this page while doing "
            "nothing. The public half does work and carries the finding that "
            "matters — `/api/v1/explorer/jobs` needs no credentials and is what "
            "let a real order be read back and decoded (P-18)."
        ),
        evidence="packages/misquote/registry/ — no authenticate.py",
    ),
    NotBuilt(
        name="ERC-8183 hire flow",
        category="Registry",
        what=(
            "A Hire button that escrows a job against a deployed ERC-8183 "
            "contract, in the seven transactions `erc8183.steps()` prices."
        ),
        why=(
            "The blocker moved, and it is worth being exact about which half "
            "closed. It used to be that **no verified deployment existed** — the "
            "EIP is Draft and publishes no reference addresses, and TermiX's "
            "`TermixEscrow` was carried as one and removed because its bytecode "
            "implements none of the calls (P-18). That is no longer the "
            "situation: `scripts/verify_erc8183.py` checked Altana's published "
            "AgenticCommerce kernel three ways on both BSC networks and every "
            "check passed — 56,632 jobs on mainnet, 581 on chapel, and a "
            "registry field byte-identical to the one this repository verified "
            "independently from the PancakeSwap side. `JOB_ESCROW` now carries "
            "both addresses with their readings (P-24). "
            "What is still missing is the **button**: escrowing a job means "
            "signing five client transactions and moving real USDT, and nothing "
            "here can sign. That is the same gate that keeps `make warden` on "
            "the recording executor, and it has not moved."
        ),
        evidence="packages/misquote/registry/ — no signer.py",
    ),
    NotBuilt(
        name="Ops surface",
        category="Operations",
        what="Prometheus metrics and Telegram alerting for the live agent loop.",
        why=(
            "Declared as an optional dependency group and never wired. The Warden "
            "loop writes a JSONL journal instead, which is what the tearsheet reads."
        ),
        evidence="packages/misquote/ops/__init__.py — docstring only",
    ),
)


def to_dicts() -> list[dict[str, Any]]:
    return [asdict(item) for item in NOT_BUILT]


def names() -> frozenset[str]:
    return frozenset(item.name for item in NOT_BUILT)
