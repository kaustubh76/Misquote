"""The browser's copy of the ERC-8183 ABI, held against the verified one.

There are two copies of one truth. `registry/erc8183_abi.py` carries the
signatures recovered from deployed bytecode — `test_erc8183_abi.py:92` walks the
PUSH4 opcodes of the chapel implementations and asserts every selector is really
there. `apps/web/src/lib/escrow.ts` carries the same calls again, because a
browser cannot import a Python module, and **nothing compared them**.

That gap is not hypothetical. The browser passed `address(0)` as `createJob`'s
hook for the whole life of the console, while `hire.py:352` had defaulted it to
the router and refused to build the call otherwise since the day
`0x55c45de1 HookRequired()` was isolated. Every `createJob` sent from the site
reverted, and the console decoded its own bug out of `hire_flow.errors` and
printed it as though the chain had surprised it.

So this reads the TypeScript as text. Parsing it properly would mean a JS
runtime in a Python suite; the shapes here are flat literals and a regex over
them is enough to catch the thing that actually went wrong — a name, an argument
list, or an argument order drifting apart.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from misquote.registry import erc8183_abi

ESCROW_TS = Path(__file__).resolve().parents[2] / "apps/web/src/lib/escrow.ts"


def _ts_abi(name: str) -> dict[str, list[str]]:
    """`{function name: [input types]}` out of a `const NAME = [...] as const`."""
    source = ESCROW_TS.read_text(encoding="utf-8")
    start = source.index(f"export const {name} = [")
    end = source.index("] as const;", start)
    block = source[start:end]
    out: dict[str, list[str]] = {}
    for entry in re.finditer(
        r'name:\s*"(\w+)",\s*type:\s*"function".*?inputs:\s*\[(.*?)\]',
        block,
        re.S,
    ):
        out[entry.group(1)] = re.findall(r'type:\s*"(\w+)"', entry.group(2))
    return out


def _py_abi(abi: list[dict]) -> dict[str, list[str]]:
    return {
        item["name"]: [arg["type"] for arg in item["inputs"]]
        for item in abi
        if item.get("type") == "function"
    }


def test_the_escrow_module_is_where_it_is_said_to_be() -> None:
    # A parity test that cannot find one of its two sides passes vacuously, and
    # this suite has been burned by exactly that shape before.
    assert ESCROW_TS.exists(), f"{ESCROW_TS} — the browser's ABI has moved"


@pytest.mark.parametrize("name", ["KERNEL_ABI", "ROUTER_ABI"])
def test_the_browser_declares_the_same_arguments_as_the_verified_abi(name: str) -> None:
    browser = _ts_abi(name)
    verified = _py_abi(getattr(erc8183_abi, name))
    assert browser, f"{name} parsed to nothing out of {ESCROW_TS.name}"
    # The browser is allowed to carry fewer calls than Python — it has no reason
    # to declare `paymentToken()`. It is not allowed to declare one differently.
    for call, types in browser.items():
        assert call in verified, f"{name}.{call} exists in the browser and not in the verified ABI"
        assert types == verified[call], (
            f"{name}.{call} takes {types} in the browser and "
            f"{verified[call]} in the ABI read off deployed bytecode"
        )


def test_submit_takes_three_arguments_in_the_browser_too() -> None:
    # The EIP describes two. A client written from the standard encodes two
    # words, hits a selector that does not exist, and reverts with no reason.
    assert _ts_abi("KERNEL_ABI")["submit"] == ["uint256", "bytes32", "bytes"]


def test_get_job_is_the_selector_the_repository_confirmed() -> None:
    source = ESCROW_TS.read_text(encoding="utf-8")
    declared = re.search(r'GET_JOB_SELECTOR = "(0x[0-9a-f]{8})"', source)
    assert declared, "GET_JOB_SELECTOR is no longer a literal in escrow.ts"
    assert declared.group(1) == erc8183_abi.KERNEL_INTERFACE["getJob(uint256)"]


def test_the_browser_never_sends_a_zero_hook() -> None:
    """The regression that motivated this file.

    `createJobArgs` is the only place the browser builds those five arguments,
    and the hook is the last of them. A zero address anywhere in that function
    is the bug coming back.
    """
    source = ESCROW_TS.read_text(encoding="utf-8")
    start = source.index("export function createJobArgs")
    # Not `source.index("\n}", start)` — the inline parameter type closes with a
    # brace of its own, so that lands inside the signature.
    opened = source.index("return [", start)
    body = source[start : source.index("] as const;", opened)]
    assert "0x0000000000000000000000000000000000000000" not in body, (
        "createJobArgs is passing a zero address again — on this deployment the "
        "hook may not be zero and createJob reverts 0x55c45de1 HookRequired(); "
        "see REQUIRED_HOOK_IS_THE_ROUTER in registry/hire.py"
    )
    # Positionally: provider, evaluator, expiredAt, description, hook. The two
    # router slots are what the EIP will lead a reader to get wrong.
    returned = body[body.index("return [") :]
    assert returned.count("router") == 2, (
        "createJobArgs should name the router twice — as the evaluator and as "
        f"the hook — and names it {returned.count('router')} time(s)"
    )


def test_the_verified_abi_is_json_the_browser_test_could_be_read_against() -> None:
    # Cheap guard that `_py_abi` is looking at what it thinks it is.
    assert json.dumps(erc8183_abi.KERNEL_ABI)
    assert len(_py_abi(erc8183_abi.KERNEL_ABI)) >= 6
