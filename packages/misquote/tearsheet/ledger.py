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
            "The agent is built and replays on a chain tape; the Studio deployment "
            "is not. **The funding half of this blocker has closed**: all four "
            "agents now hold ERC-8004 identities on chapel — ids 1927-1930, owned "
            "by the operator, recorded in `vetting/identity/97.json` and "
            "re-derivable with `make identity-verify` — so 'this repository will "
            "not register from an unfunded posture' is no longer the reason. What "
            "remains is the Studio itself and x402 self-funding. Two of the "
            "vendor's own links are dead: `studio.bnbchain.org` does not resolve, "
            "and the npm package's declared repository, "
            "github.com/bnb-chain/bnbagent-studio, returns 404. The artifact is "
            "real and signed; its source is not readable, which is not a blocker "
            "a funded wallet can clear. Nor would registering harder help: "
            "TermiX's production config returns chainId 56 and their own module "
            "here records that there is no testnet, so the chapel identities are "
            "invisible to them by construction rather than by omission."
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
            "**The blocker moved, and the half that closed is the bigger half.** "
            "This entry used to say no Altana session-key module had been verified "
            "on either network, so there was nowhere to send a grant. That was a "
            "statement about `vetting/addresses/`, not about the world: "
            "`@altananetwork/sdk@0.8.0` publishes `keyStore` and "
            "`keyStoreController` for both BSC networks in `dist/config.js` — the "
            "same package, at the same version, that `JOB_ESCROW` was verified "
            "from — and nobody here had opened it. That is P-24 repeating one "
            "module over, and it is written up as **P-27**.\n\n"
            "`scripts/verify_session_keys.py` ran the same three-way check on both "
            "chains and every check passed, so `make session-keys` then granted a "
            "key on chapel, read it back live, revoked it, and read it back dead — "
            "three mined transactions in `vetting/identity/session-keys-97.json`. "
            "Grant, visible, revoke, gone is `Readme.md` §5's definition of done "
            "for activation, and it is met for expiry and revocation.\n\n"
            "**What is not built is the caps.** The keystore enforces the expiry "
            "and nothing else. An allowlist and a spend cap would live in a "
            "`validator` module's `metadata`, and every grant observed on this "
            "deployment — ours and other people's — carries `validator = 0x0` and "
            "empty metadata. So no validator module has been read, and "
            "`SessionKeyWriter.grant` refuses to send a capped-looking grant "
            "unless the caller passes `allow_unenforced_caps=True`. A page "
            "rendering four caps over a key the chain bounds by one would be the "
            "misquote this project is named after, committed by us, on the "
            "activation page."
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
            "**The mint is built, and finding out why it did not work is the "
            "useful part.** `Badge.s.sol` now sends a real mint through the "
            "verified NonfungiblePositionManager at the badge's **own published "
            "bounds**, funded by whale impersonation for USDT and wrapping for "
            "WBNB. Four of four findings held on a BSC fork.\n\n"
            "It failed twice first, and both failures were **silent** — the proof "
            "did not crash, it published `held: false` and read exactly like a "
            "finding that did not hold.\n\n"
            "1. **A v3 position is an ERC-721 and the prover is its recipient.** "
            "Without `onERC721Received` the transfer rejects it, so the mint "
            "reverts — with **empty return data**, so `catch Error(string)` never "
            "fires and the honest report is 'no reason given'. Identical "
            "parameters minted from an EOA with `status: 1`.\n"
            "2. **`estimate_gas` measures the caught path of a `try/catch`.** "
            "Estimating a function that catches a failing inner call measures the "
            "cheap branch; sending on that estimate gives the inner call 63/64 of "
            "almost nothing, it runs out of gas, and the catch fires. "
            "Self-fulfilling, perfectly stable, and it produces the same empty "
            "revert data as a bare `revert()`. Written up as **P-30**.\n\n"
            "That also retires a dangling promise: `initialised`'s reason says "
            "its consequence *is proven by `mintable-range` instead* — a forward "
            "reference which, until now, pointed at a check that was itself "
            "unproven.\n\n"
            "**The remaining five are readings, and that is the honest ceiling.** "
            "`decimals()` returns 18 or it does not; `slot0.feeProtocol` is a "
            "number. There is no transaction that demonstrates a reading, and "
            "wrapping one in a fork call would be theatre. `vetting/proof.py`'s "
            "`UNPROVEN` names each with its reason, and a test asserts every "
            "check is either proven or explained — because four green ticks "
            "beside nine checks otherwise reads as five failures."
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
            "**Chapel is wired; mainnet is the gate.** This entry read "
            "*'`make warden` is still wired to the recording executor'*, and the "
            "evidence was that `__main__.py` does not import `ChainExecutor`. "
            "Both were true, and the reason underneath was narrower than either: "
            "`main` had no `Web3` in scope at all — `build_source` returns a "
            "`BscReader` built from a list of endpoints and never exposed one — "
            "so this was a plumbing gap wearing a capability's clothes, the same "
            "shape as the hire flow's *'nothing here can sign'* (P-28).\n\n"
            "`build_executor` now constructs `BscSigner` -> `PositionManager` -> "
            "`ChainExecutor` behind **three gates whose default is refuse**: "
            "`--broadcast` must be passed, the chain must be chapel (mainnet is "
            "refused in code, not by convention), and `MISQUOTE_DRY_RUN` must be "
            "`0`, which also triggers `assert_signs_for_operator`. Everything "
            "downstream was already wired — `reconcile()` adopts the real "
            "position the moment it is handed an executor with `observe()`.\n\n"
            "What is not built is the decision to point it at chain 56 and a "
            "funded wallet there. `check_burn_in`, `check_signer_configured` and "
            "`check_position_cap` all report UNVERIFIED, and `make go-no-go` is "
            "the gate for changing that — not a flag.\n\n"
            "**Nor has anything run unattended for 24 hours**, which is the other "
            "half and used to be a ledger entry of its own. That entry is gone "
            "because everything it named — Prometheus metrics, an agent "
            "heartbeat, Telegram alerting, and `ops/RUNBOOK.md` with the eight "
            "procedures they imply — is built. What is left is wall clock, and "
            "duplicating a gate as a ledger entry only made two things point at "
            "the same constant.\n\n"
            "`check_burn_in` is the place that says it, and it says it properly "
            "now: it measures the **longest unbroken run** in each agent's "
            "journal rather than the span of an append-only file (which counted "
            "two ten-minute runs a day apart as 25 hours), it reads every agent's "
            "journal rather than one hardcoded filename, and it refuses a journal "
            "recording chain 56 in a gate named *testnet* burn-in — which the "
            "only journal on disk does."
        ),
        evidence="packages/misquote/agents/warden/__main__.py — BROADCAST_CHAIN is 97",
    ),
    NotBuilt(
        name="ERC-8183 escrow",
        category="Registry",
        what=(
            "A Hire button that **escrows** a job. Creating, budgeting and reading "
            "one back is done and on chain; moving money into it is not."
        ),
        why=(
            "**This entry has now been wrong in three ways, each less wrong than "
            "the last.** It said no verified deployment existed (P-18 removed "
            "`TermixEscrow`; P-24 found Altana's kernel and `JOB_ESCROW` carries "
            "both chains). It then said the blocker was that *nothing here can "
            "sign* — which was false when written: `chain/signer.py` signs, and "
            "`registry/identity.py` broadcast six chapel transactions whose "
            "hashes are in `vetting/identity/97.json`. What was actually missing "
            "was an **ABI**, and the difference matters: 'we cannot sign' invites "
            "waiting, 'we have no ABI' invites reading a dispatch table.\n\n"
            "`registry/erc8183_abi.py` is that table, recovered from deployed "
            "bytecode rather than copied — which immediately caught `submit`, "
            "whose real signature is `submit(uint256,bytes32,bytes)` against the "
            "EIP's two arguments. `make hire` then ran the flow on chapel: "
            "`approve`, `createJob` and `setBudget` **mined**, and job 746 reads "
            "back with our client, provider, evaluator and budget "
            "(`vetting/identity/hire-97.json`).\n\n"
            "**Two steps did not.** `fund()` moves the deployment's payment "
            "token, and that token is owner-minted — `mint` reverts `Ownable: "
            "caller is not the owner`, there is no faucet among its 59 "
            "selectors, and the signer holds none. So the escrow cannot be "
            "exercised from here at any price, and no amount of code closes it. "
            "`registerJob` reverts for every policy argument tried, consistent "
            "with the hook having registered the job already — an inference from "
            "a revert, recorded as one.\n\n"
            "Four permissioning surprises came out of it, none in any ABI and all "
            "found by varying one argument at a time: the **hook is mandatory** "
            "(`address(0)` reverts `HookRequired()`, and only the EvaluatorRouter "
            "is accepted, against an EIP that calls it an optional extension), "
            "`expiredAt` is an absolute timestamp with a ceiling, and the "
            "evaluator may not be zero. `Readme.md` §8's D1 box asked for this "
            "call invoked from an external script *with no permissioning "
            "surprises*; there were seven errors, three named and four counted."
        ),
        evidence="packages/misquote/registry/hire.py — no escrow.py",
    ),
)


def to_dicts() -> list[dict[str, Any]]:
    return [asdict(item) for item in NOT_BUILT]


def names() -> frozenset[str]:
    return frozenset(item.name for item in NOT_BUILT)
