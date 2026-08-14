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
        name="Vetting badges",
        category="Due diligence",
        what=(
            "A due-diligence badge on every pool a listed agent touches, with each "
            "finding shipping a proof-of-concept that executes on a mainnet fork."
        ),
        why=(
            "The fork lab under vetting/forge exists and runs; the badge generator "
            "that would turn its output into a rendered claim does not."
        ),
        evidence="vetting/badges/ — empty directory",
    ),
    NotBuilt(
        name="Live agent entrypoint",
        category="Operations",
        what=(
            "`make warden ENV=testnet` — the Warden loop running unattended against "
            "a live chain, writing the decision journal every tearsheet verdict "
            "is computed from."
        ),
        why=(
            "`agents/warden/loop.py` implements the loop, the action queue, the "
            "journal and the kill file, but nothing wires it to a command. The "
            "Makefile advertised the target for weeks against a module that does "
            "not exist. This is why every journal in the repo has zero rows, and "
            "why every card says its provenance journal is empty."
        ),
        evidence="packages/misquote/agents/warden/ — no __main__.py",
    ),
    NotBuilt(
        name="Live indexer tail",
        category="Data",
        what=(
            "`misquote.indexer.follow` — following the pool forward from the "
            "backfill cursor, so the tape stays current without a re-run."
        ),
        why=(
            "Only the backfill exists. `make indexer` used to invoke both and "
            "failed on the second line."
        ),
        evidence="packages/misquote/indexer/ — no follow.py",
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
