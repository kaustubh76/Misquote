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
            "Two of the three now exist: the agent is deployed at "
            "misquote-agent.onrender.com, and `bag erc8004 register` gave it "
            "identity 2102 on chapel, whose published endpoint resolves to it. "
            "The ERC-8183 interface and x402 self-funding do not, and `bag deploy` "
            "has not run — it takes bnb, aws or azure, and hosting the agent "
            "ourselves is not the same claim as the CLI deploying it."
        ),
        evidence="packages/misquote/agents/router/ — no studio.py",
    ),
    NotBuilt(
        name="Altana session keys: the caps",
        category="Activation",
        what=(
            "The half of the caps subset this deployment does not enforce: the "
            "allowlist and the spend cap. Expiry and one-transaction revoke are "
            "built and proven on chain; these two are not."
        ),
        why=(
            "Expiry and revoke are enforced by the keystore and proven on chain. "
            "The allowlist and spend cap would need a validator module, and no grant "
            "on this deployment carries one."
        ),
        evidence="packages/misquote/sessions/keys.py — VALIDATOR_MODULE is empty",
    ),
    NotBuilt(
        name="Vetting proof-of-concepts: the five readings",
        category="Due diligence",
        what=(
            "An executable demonstration for the five badge checks that do not "
            "have one. Four of the nine now do, including the mint."
        ),
        why=(
            "Four of the nine can be demonstrated by a transaction, and are — "
            "including a real mint. The other five are readings: a token either "
            "reports 18 decimals or it does not, and no transaction demonstrates "
            "a reading."
        ),
        evidence="packages/misquote/vetting/proof.py — no Prover.sol",
    ),
    NotBuilt(
        name="Signing on mainnet",
        category="Operations",
        what=(
            "`make warden` broadcasting the decisions it already makes correctly "
            "against **BSC mainnet**, with capital at risk."
        ),
        why=(
            "Chapel broadcasts behind three gates that each default to refuse. "
            "Pointing the same path at mainnet is a decision about capital, not a "
            "line of code — and three readiness gates report UNVERIFIED until it is "
            "made."
        ),
        evidence="packages/misquote/agents/warden/__main__.py — BROADCAST_CHAIN is 97",
    ),
    NotBuilt(
        name="ERC-8183 escrow",
        category="Registry",
        what=(
            "A Hire button that **escrows** a job and releases it. Escrowing is "
            "done, on mainnet, with real money; releasing is not."
        ),
        why=(
            "`fund` moved 0.1 of the payment token into job 56681 on BSC mainnet and "
            "`claimRefund` moved it back, both mined. `submit` has since mined too, on "
            "job 56718 — the same flow with a 192-hour expiry instead of twelve, which "
            "is the whole difference. What is left is `settle`, which reverts "
            "`NotDecided()` until the 7-day dispute window runs and is due 13 Sep: a "
            "wait rather than a gap, and the only part still unproven on chain."
        ),
        evidence="packages/misquote/registry/hire.py — no escrow.py",
    ),
)


def to_dicts() -> list[dict[str, Any]]:
    return [asdict(item) for item in NOT_BUILT]


def names() -> frozenset[str]:
    return frozenset(item.name for item in NOT_BUILT)
