"""One forked BSC, funded, shared by every test in this directory.

`test_position_lifecycle.py` grew this fixture first. `test_executor.py` needs
exactly the same thing — a `PositionManager` on a fork with real balances and
real allowances — and copying sixty lines of anvil boot, whale impersonation and
allowance setup into a second file is how the two come to disagree about what a
funded wallet means.

Module-scoped rather than session-scoped: these tests mint, burn and withdraw,
and a shared fork would let one module's leftovers decide another's starting
state.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time

import pytest
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from misquote.chain.addresses import MAINNET, TARGET_POOL, USDT_MAINNET, WBNB_MAINNET
from misquote.chain.nfpm import PositionManager
from misquote.chain.signer import BscSigner
from misquote.core.types import PoolMeta

# anvil's first deterministic account. Public, empty, and only ever used here.
ANVIL_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
USDT_WHALE = "0xF977814e90dA44bFA03b6295A0616a897441aceC"

# The agent's own ERC20 ABI has no `transfer` — it never needs one. Funding a
# test wallet does, so it lives here rather than widening the production surface.
FUNDING_ABI = json.loads("""[
 {"name":"balanceOf","type":"function","stateMutability":"view",
  "inputs":[{"type":"address"}],"outputs":[{"type":"uint256"}]},
 {"name":"transfer","type":"function","stateMutability":"nonpayable",
  "inputs":[{"type":"address"},{"type":"uint256"}],"outputs":[{"type":"bool"}]},
 {"name":"deposit","type":"function","stateMutability":"payable","inputs":[],"outputs":[]}
]""")

META = PoolMeta(
    address=TARGET_POOL.address,
    chain_id=56,
    token0=TARGET_POOL.token0,
    token1=TARGET_POOL.token1,
    dec0=TARGET_POOL.dec0,
    dec1=TARGET_POOL.dec1,
    fee_pips=TARGET_POOL.fee_pips,
    tick_spacing=TARGET_POOL.tick_spacing,
    fee_protocol=TARGET_POOL.fee_protocol,
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def manager(tmp_path_factory):
    """A funded `PositionManager` pointed at a forked BSC, broadcasting for real."""
    if not shutil.which("anvil"):
        pytest.skip("anvil not installed")

    rpc = os.environ.get("BSC_ARCHIVE_RPC_URL") or "https://bsc-dataseed.bnbchain.org"
    port = _free_port()
    proc = subprocess.Popen(
        ["anvil", "--fork-url", rpc, "--port", str(port), "--no-rate-limit"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    w3 = Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}", request_kwargs={"timeout": 180}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    for _ in range(45):
        if proc.poll() is not None:
            pytest.skip("anvil exited (free endpoints prune; set BSC_ARCHIVE_RPC_URL)")
        try:
            if w3.is_connected() and w3.eth.block_number > 0:
                break
        except Exception:  # noqa: BLE001 — still booting
            pass
        time.sleep(1)
    else:
        proc.terminate()
        pytest.skip("anvil did not come up")

    account = Web3().eth.account.from_key(ANVIL_KEY).address
    w3.provider.make_request("anvil_setBalance", [account, hex(20_000 * 10**18)])

    # WBNB by wrapping, USDT by impersonation. Neither depends on the pool's own
    # balance, which we are about to trade against.
    wbnb = w3.eth.contract(address=Web3.to_checksum_address(WBNB_MAINNET), abi=FUNDING_ABI)
    wbnb.functions.deposit().transact({"from": account, "value": 5_000 * 10**18})

    whale = Web3.to_checksum_address(USDT_WHALE)
    w3.provider.make_request("anvil_impersonateAccount", [whale])
    w3.provider.make_request("anvil_setBalance", [whale, hex(10**18)])
    usdt = w3.eth.contract(address=Web3.to_checksum_address(USDT_MAINNET), abi=FUNDING_ABI)
    usdt.functions.transfer(account, 1_000_000 * 10**18).transact({"from": whale})
    w3.provider.make_request("anvil_stopImpersonatingAccount", [whale])

    os.environ["MISQUOTE_DRY_RUN"] = "0"  # this fixture broadcasts, on a fork
    kill_file = tmp_path_factory.mktemp("ops") / "KILL"
    signer = BscSigner(w3, ANVIL_KEY, kill_file=kill_file)
    pm = PositionManager(signer, META, MAINNET)

    pm.ensure_allowance(WBNB_MAINNET, 2**200)
    pm.ensure_allowance(USDT_MAINNET, 2**200)

    try:
        yield pm
    finally:
        # Found a two-day-old anvil from an earlier run still holding its port.
        # The teardown used to sit bare after the `yield`, so anything that threw
        # on the way out — including `wait` timing out — left the process behind,
        # and a forked anvil looks completely idle while it does. Nothing in the
        # suite would ever mention it.
        os.environ["MISQUOTE_DRY_RUN"] = "1"
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def range_around(manager: PositionManager, half_width_ticks: int) -> tuple[int, int]:
    import json

    pool_abi = json.loads(
        '[{"name":"slot0","type":"function","stateMutability":"view","inputs":[],'
        '"outputs":[{"type":"uint160"},{"type":"int24"},{"type":"uint16"},'
        '{"type":"uint16"},{"type":"uint16"},{"type":"uint32"},{"type":"bool"}]}]'
    )
    pool = manager.w3.eth.contract(
        address=Web3.to_checksum_address(manager.resolve_pool()), abi=pool_abi
    )
    tick = pool.functions.slot0().call()[1]
    spacing = manager.meta.tick_spacing
    centre = (tick // spacing) * spacing
    return centre - half_width_ticks, centre + half_width_ticks


# --- the whole cycle -------------------------------------------------------


# --- pruned forks are an absence of infrastructure, not a defect -------------

PRUNED = ("missing trie node", "required historical state unavailable", "state not available")


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Turn a pruned-state RPC error into a skip that names the cause.

    anvil forks from a public endpoint, which serves only recent state. A run
    that takes a minute can outlive the window: the node prunes the block the
    fork is pinned to and every later `eth_call` fails with `missing trie node`.
    Nothing in this repository can prevent that, and `BSC_ARCHIVE_RPC_URL` is
    exactly the knob that does.

    Reporting it as a failure would make the chain suite intermittently red for
    a reason nobody can fix, and a suite that is sometimes red for no reason
    teaches people to ignore it being red for a real one. So it is reported as
    what it is: a test that could not run.

    Deliberately narrow. Only these three phrases, all of them the node saying
    it no longer has the data — never a revert, never a gas estimate, never a
    wrong number.
    """
    outcome = yield
    report = outcome.get_result()
    # Every phase, not just `call`. A fixture that closes leftover positions
    # touches the chain too, and a pruned node fails it during *setup* — which
    # reports as an ERROR rather than a failure and slipped past the first
    # version of this hook entirely.
    if not (report.failed or report.outcome == "failed"):
        return
    text = str(getattr(call, "excinfo", "") or "")
    if any(phrase in text for phrase in PRUNED):
        report.outcome = "skipped"
        # pytest reads a skip's longrepr as (path, lineno, reason). Setting a
        # bare string here — and, worse, setting `wasxfail` — made it render as
        # XFAIL, which is a different claim: "expected to fail" says we knew the
        # code was wrong, where the truth is that the test could not run.
        reason = (
            f"{item.nodeid}: the forked node pruned the state this test needed "
            f"(during {report.when}). Set BSC_ARCHIVE_RPC_URL to a node that "
            "serves archive state and re-run.\n\n"
            "Measured: the executor module alone passes 13 of 13 in under a "
            "minute. The whole chain suite takes nine, spins up one anvil per "
            "module, and every one of them proxies its state reads to the same "
            "free endpoints — so the later modules outlive the window."
        )
        report.longrepr = (str(item.fspath), item.location[1] or 0, f"Skipped: {reason}")
