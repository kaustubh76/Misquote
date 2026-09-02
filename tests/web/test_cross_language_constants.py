"""Constants that exist twice, once in Python and once in TypeScript.

Every check in this file guards the same failure: two copies of one fact, each
internally consistent, disagreeing only with each other. Nothing else in the
suite can see it. `test_artifact_contract.py` checks that a *name* appears in a
renderer; it cannot check that `DEPLOYMENTS[56].keyStore` is the address
`sessions/keys.py` verified. The vitest side pins TypeScript to *artifacts*,
which is the better direction and only available where the value is emitted —
the session-key addresses for chain 56 are not, and the ABIs are not emitted at
all.

The four duplications, and why each one is dangerous:

  * **Session-key addresses.** Four contract addresses typed into
    `sessionKeys.ts` by hand. The wrong one is an address a visitor sends a
    registration fee to.
  * **`getJob`'s selector.** Python computes it from the signature; the browser
    has the answer written down. A wrong four bytes reads a different function.
  * **Kernel and router signatures.** `erc8183_abi.py` resolved these against
    deployed bytecode over 21,060 candidates — `submit` takes three arguments
    where the EIP says two. A TypeScript copy that drifts back toward the EIP
    encodes a call that does not exist.
  * **Job word offsets.** `hire.py` names one offset and refuses to name the
    rest; `escrow.ts` names seven. Two of those seven are named nowhere else.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WEB = REPO / "apps" / "web" / "src"
ARTIFACTS = REPO / "apps" / "web" / "public" / "artifacts"


def strip_comments(source: str) -> str:
    """Same crude strip `test_artifact_contract.py` uses, and safe for the same reason."""
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", " ", source)


def ts(name: str) -> str:
    return strip_comments((WEB / name).read_text())


def test_the_session_key_addresses_are_the_ones_python_verified() -> None:
    """Four addresses, typed into TypeScript by hand, verified only in Python."""
    from misquote.sessions.keys import SESSION_KEY_CONTROLLER, SESSION_KEY_MODULE

    source = ts("lib/sessionKeys.ts")
    for label, table in (
        ("SESSION_KEY_MODULE", SESSION_KEY_MODULE),
        ("SESSION_KEY_CONTROLLER", SESSION_KEY_CONTROLLER),
    ):
        for chain, address in table.items():
            assert address in source, (
                f"{label}[{chain}] is {address} in sessions/keys.py and does not appear "
                f"in lib/sessionKeys.ts — the TypeScript copy has drifted, and the copy "
                f"a visitor's wallet is pointed at is the TypeScript one"
            )


def test_no_other_contract_address_hides_in_the_typescript() -> None:
    """The other direction, which is the one that catches a stale address.

    Presence alone passes while an old address sits beside the new one, which is
    exactly what a careless edit leaves behind.
    """
    from misquote.sessions.keys import SESSION_KEY_CONTROLLER, SESSION_KEY_MODULE

    known = {a.lower() for a in (*SESSION_KEY_MODULE.values(), *SESSION_KEY_CONTROLLER.values())}
    # The zero address is `NO_VALIDATOR`, and is a documented absence.
    known.add("0x" + "00" * 20)

    found = {m.lower() for m in re.findall(r"0x[0-9a-fA-F]{40}", ts("lib/sessionKeys.ts"))}
    assert found <= known, (
        f"lib/sessionKeys.ts carries addresses Python does not know: {sorted(found - known)}"
    )


def test_the_browsers_getjob_selector_is_the_computed_one() -> None:
    """Python derives it; the browser wrote it down."""
    from misquote.registry.erc8183_abi import KERNEL_INTERFACE

    expected = KERNEL_INTERFACE["getJob(uint256)"]
    source = ts("lib/escrow.ts")
    declared = re.search(r'GET_JOB_SELECTOR\s*=\s*"(0x[0-9a-f]{8})"', source)
    assert declared, "GET_JOB_SELECTOR is not a plain literal in lib/escrow.ts any more"
    assert declared.group(1) == expected, (
        f"lib/escrow.ts encodes {declared.group(1)} for getJob and the deployment answers "
        f"{expected} — four wrong bytes read a different function and return plausible words"
    )


def _ts_signatures(source: str, table: str) -> set[str]:
    """Every `name(type,type)` the named TypeScript ABI declares."""
    start = source.index(f"export const {table}")
    body = source[start : source.index("] as const;", start)]
    out: set[str] = set()
    for entry in re.finditer(r'name:\s*"(\w+)"[\s\S]*?inputs:\s*\[([\s\S]*?)\]', body):
        name, inputs = entry.group(1), entry.group(2)
        types = re.findall(r'type:\s*"(\w+)"', inputs)
        out.add(f"{name}({','.join(types)})")
    return out


@pytest.mark.parametrize(
    ("table", "interface"),
    [("KERNEL_ABI", "KERNEL_INTERFACE"), ("ROUTER_ABI", "ROUTER_INTERFACE")],
)
def test_every_typescript_signature_was_resolved_against_bytecode(
    table: str, interface: str
) -> None:
    """The 21,060-candidate search, not re-run in TypeScript by hand.

    `submit` is the one that matters: the EIP describes two arguments and this
    deployment takes three. A TypeScript ABI that drifts back to the EIP's shape
    encodes a selector that does not exist and reverts with no reason string.
    """
    from misquote.registry import erc8183_abi

    known = set(getattr(erc8183_abi, interface))
    for signature in _ts_signatures(ts("lib/escrow.ts"), table):
        assert signature in known, (
            f"lib/escrow.ts declares {signature}, which is not in {interface}. Either the "
            f"deployment has a function this repository never resolved, or the TypeScript "
            f"copy has drifted from the one that was"
        )


def test_the_word_offsets_agree_across_the_boundary() -> None:
    """`escrow.ts` names seven offsets; Python names them in two places."""
    import importlib.util
    import sys

    from misquote.registry.hire import JOB_WORD_ID

    spec = importlib.util.spec_from_file_location(
        "claim_refund", REPO / "scripts" / "claim_refund.py"
    )
    assert spec and spec.loader
    claim_refund = importlib.util.module_from_spec(spec)
    sys.modules["claim_refund"] = claim_refund
    spec.loader.exec_module(claim_refund)

    source = ts("lib/escrow.ts")
    block = source[source.index("export const JOB_WORD") : source.index("} as const;")]
    offsets = {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", block)}

    for name, expected in (
        ("id", JOB_WORD_ID),
        ("budget", claim_refund.WORD_BUDGET),
        ("expiredAt", claim_refund.WORD_EXPIRES),
        ("status", claim_refund.WORD_STATUS),
    ):
        assert offsets.get(name) == expected, (
            f"lib/escrow.ts reads {name} from word {offsets.get(name)} and Python reads it "
            f"from word {expected}. Both decode the same bytes; one of them is naming the "
            f"wrong field, and neither would raise"
        )


def test_the_consoles_revert_vocabulary_is_the_published_one() -> None:
    """`hire_flow.errors` is the table the console looks a revert up in.

    It is in the contract's `OPAQUE` set — deliberately, because contracting a
    chain's custom errors would make our schema test a snapshot of someone
    else's — so nothing checked the keys until now. The console lowercases what
    it scrapes out of a revert and indexes straight into this.
    """
    from misquote.registry import hire

    published = json.loads((ARTIFACTS / "registry.json").read_text())["hire_flow"]["errors"]
    source = {**hire.CREATE_JOB_ERRORS, **hire.FLOW_ERRORS}

    assert published == source, (
        "the published error table and hire.py disagree — run `make registry`. "
        f"only published: {sorted(set(published) - set(source))}, "
        f"only in hire.py: {sorted(set(source) - set(published))}"
    )
    for selector in published:
        assert re.fullmatch(r"0x[0-9a-f]{8}", selector), (
            f"{selector} is not a lowercase four-byte selector, and lib/escrow.ts "
            f"lowercases before looking it up — this key could never be found"
        )
