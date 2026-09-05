"""Public definitions nothing ever uses.

`apps/web` has had this check for TypeScript for a while. Python did not, and the
gap cost something: `replay/driver.py:passive_result` sat there building a
`ReplayResult` that nothing called — not the showcase, not the advantage report,
not one test — while `tearsheet/advantage.py` cited it by name as built
machinery. Being named in prose is most of why it survived.

That one mattered because it answered a **live** question by a different rule:
`in_range_samples` per swap event, where the driver counts per decision sample.
InRange% is on every card and gates G-3's floor. Dead code is tolerable; dead
code with a plausible name that answers a live question differently is a trap.

**Identifiers, not text.** A regex would have counted that docstring mention as a
use, which is exactly how it hid. This walks the AST and collects names actually
loaded, called, imported or accessed as attributes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "packages" / "misquote"
SEARCHED = (REPO / "packages", REPO / "scripts", REPO / "tests")

#: Names that are allowed to have no call site, each with the reason. A `Protocol`
#: is a real exception — it constrains by being *annotated*, and annotations are
#: strings under `from __future__ import annotations`, so the AST cannot see them.
#: Anything else here should be viewed with suspicion.
ALLOWED: dict[str, str] = {
    "SUBMIT_NEEDS_EXPIRY_BEYOND_DISPUTE_WINDOW": (
        "A measurement, not a value. `submit` reverts SubmissionTooLate() unless "
        "expiredAt outlives the policy's dispute window — established across eight "
        "fork runs varying only the expiry, and later corroborated by the vendor's "
        "own SDK guarding the identical inequality. The constant exists so the "
        "finding is greppable from the module whose FLOW_ERRORS it explains. "
        "Nothing reads it because the chain enforces it, not us."
    ),
    "MASTERCHEF_V3_IS_A_NON_GOAL": (
        "A declaration, not a value. `docs/ASSUMPTIONS.md` records that Warden "
        "deliberately does not stake into MasterChefV3 — staking transfers NFT "
        "ownership and would contaminate the fee-APR metric with emissions. The "
        "constant exists so the decision is greppable from the address module "
        "it constrains. Nothing reads it because nothing may."
    ),
    "ERC8004_SCHEMA": (
        "The registration schema URL the EIP publishes. Carried beside the "
        "registry addresses so a reader can check what a resolvable agent is "
        "supposed to contain; the survey reads `tokenURI` payloads rather than "
        "validating against it, and validating would be a claim this project "
        "has not earned."
    ),
    "ORDER_WORD_WINDOW": (
        "How many 32-byte words TermiX's `orders(bytes32)` returns, recorded "
        "from the bytecode during P-18. Kept as the reading that identified the "
        "escrow as order-keyed rather than job-keyed; nothing decodes an order "
        "because nothing signs."
    ),
    "Tape": (
        "Protocol describing the tape interface. Currently annotates nothing — "
        "`ReplayDriver.run(self, tape, ...)` is untyped — so it documents rather "
        "than constrains. Kept because the description is worth having; noted "
        "because a Protocol nobody annotates with enforces nothing."
    ),
}


def _python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in str(p)]


def _public_definitions() -> dict[str, tuple[Path, int]]:
    """Module-level `def`/`class`/CONSTANT in the package, excluding `_private`.

    Constants were not surveyed at all, and that omission had a cost: three
    verified ERC-8183 addresses — `EVALUATOR_ROUTER`, `OPTIMISTIC_POLICY`,
    `PAYMENT_TOKEN` — shipped with no callers and a green suite, under a
    docstring claiming they were load-bearing, while `steps()` priced the flow
    against string literals instead.

    Only SCREAMING_CASE names are collected. Module-level lowercase bindings are
    usually configured instances rather than published facts, and sweeping them
    in would produce noise that trains people to add exemptions.
    """
    found: dict[str, tuple[Path, int]] = {}
    for path in _python_files(PACKAGE):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                if not node.name.startswith("_"):
                    found[node.name] = (path.relative_to(REPO), node.lineno)
            elif isinstance(node, ast.Assign | ast.AnnAssign):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    name = target.id
                    if name.startswith("_") or not name.isupper():
                        continue
                    found[name] = (path.relative_to(REPO), node.lineno)
    return found


def _used_identifiers() -> set[str]:
    used: set[str] = set()
    for root in SEARCHED:
        for path in _python_files(root):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Name):
                    # **Load context only.** An assignment's target is an
                    # `ast.Name` too, so counting every `Name` made each
                    # constant a user of itself and the constant survey below
                    # vacuous — it passed against a tree where three verified
                    # addresses had no callers at all. Functions and classes
                    # were never affected: they are `FunctionDef`/`ClassDef`,
                    # not `Name`.
                    if isinstance(node.ctx, ast.Load):
                        used.add(node.id)
                elif isinstance(node, ast.Attribute):
                    used.add(node.attr)
                elif isinstance(node, ast.ImportFrom):
                    used.update(alias.name for alias in node.names)
                elif isinstance(node, ast.Import):
                    used.update(alias.name.split(".")[-1] for alias in node.names)
    return used


DEFINITIONS = _public_definitions()
USED = _used_identifiers()


def test_the_survey_found_something_to_check() -> None:
    """A survey that collects nothing passes every assertion built on it.

    Ported in spirit from the TypeScript version, which carries the same guard
    for the same reason.
    """
    assert len(DEFINITIONS) > 150, f"only {len(DEFINITIONS)} definitions — the walk is broken"
    assert len(USED) > 500, f"only {len(USED)} identifiers — the corpus is not being read"
    assert "quote" in USED and "ReplayDriver" in USED


@pytest.mark.parametrize("name", sorted(DEFINITIONS))
def test_every_public_definition_is_used_somewhere(name: str) -> None:
    if name in ALLOWED:
        pytest.skip(ALLOWED[name])
    path, lineno = DEFINITIONS[name]
    assert name in USED, (
        f"{path}:{lineno} defines {name!r} and nothing loads, calls, imports or "
        "accesses it anywhere in packages/, scripts/ or tests/. Delete it, wire "
        "it up, or add it to ALLOWED with the reason."
    )


def test_the_allowance_list_does_not_outlive_its_entries() -> None:
    """An exemption for a name that no longer exists is a claim about nothing,
    and it will quietly cover the next definition to take that name."""
    stale = [name for name in ALLOWED if name not in DEFINITIONS]
    assert stale == [], f"ALLOWED covers names that are gone: {stale}"
