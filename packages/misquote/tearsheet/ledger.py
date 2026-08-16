"""What is not built, named in one place so the UI cannot quietly omit it.

A marketplace page that shows three agent cards and nothing else is telling the
truth about three agents and lying by omission about the fourth. `Readme.md` §1
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
    NotBuilt(
        name="Router",
        category="Yield",
        what=(
            "A whitelist APR router with an optimal-switching boundary — move only "
            "when the yield delta exceeds gas plus slippage — deployed through the "
            "BNB Agent Studio CLI as the native-citizenship proof."
        ),
        why=(
            "Never started. The three agents that exist share one replay engine and "
            "one cost model; Router is the only one of the four that would have "
            "needed a second venue model, and it was cut rather than faked."
        ),
        evidence="agents/router/ — empty directory",
    ),
    NotBuilt(
        name="Altana session keys",
        category="Activation",
        what=(
            "The caps subset: allowlist, spend cap, expiry, Keystore, and one-"
            "transaction revoke, so hiring an agent is bounded and reversible."
        ),
        why=(
            "Unimplemented. Without it there is no activation path, which is why "
            "no page here has a Hire button — the button would not do anything."
        ),
        evidence="packages/misquote/sessions/__init__.py — docstring only",
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
