"""The address checks, against a chain that answers however the test says.

`survey()` takes a `Reader` protocol rather than a `Web3` precisely so this can
exist: every judgement is exercised without a node, including the ones that only
happen when a contract lies.

Named `test_address_checks` rather than `test_addresses`, which is the obvious
name and is already taken by `tests/chain/test_addresses.py`. `tests/` is not a
package, so pytest derives a module name from the basename alone: two files
called `test_addresses.py` produce one module name, and the second to be
collected fails — taking **the whole suite's collection** with it, not just
those two files. A package marker in this directory also resolves it, but it
depends on package semantics that shift with `--import-mode` and it leaves the
trap armed for the next person. A distinct basename does not.
"""

from __future__ import annotations

from typing import Any

import pytest

from misquote.chain.addresses import DEPLOYMENTS, POOLS
from misquote.vetting import addresses
from misquote.vetting.badge import FAIL, PASS, UNKNOWN

CHAIN = 56
POOL = POOLS[CHAIN]
DEPLOYMENT = DEPLOYMENTS[CHAIN]


class FakeChain:
    """A chain that agrees with `chain/addresses.py` unless told otherwise."""

    def __init__(self, **overrides: Any) -> None:
        self.overrides = overrides
        self.empty: set[str] = set()
        self.reverts: set[str] = set()

    def code_size(self, address: str) -> int:
        if address in self.reverts:
            raise RuntimeError("connection reset")
        return 0 if address in self.empty else 4_413

    def call(self, address: str, signature: str, *args: Any) -> Any:
        name = signature.split("(")[0]
        if name in self.overrides:
            value = self.overrides[name]
            if isinstance(value, Exception):
                raise value
            return value
        return {
            "getPool": POOL.address,
            "token0": POOL.token0,
            "token1": POOL.token1,
            "factory": DEPLOYMENT.factory,
            "fee": POOL.fee_pips,
            "tickSpacing": POOL.tick_spacing,
        }[name]


def status_of(report: addresses.AddressReport, fragment: str) -> str:
    match = [c for c in report.checks if fragment in c.name]
    assert match, f"no check named like {fragment!r} in {[c.name for c in report.checks]}"
    return match[0].status


def test_a_chain_that_agrees_with_the_config_passes_every_check() -> None:
    report = addresses.survey(FakeChain(), CHAIN)
    assert report.verdict == PASS
    assert report.checks, "no checks ran"
    assert all(c.status == PASS for c in report.checks)


def test_the_addresses_come_from_the_module_the_signer_imports() -> None:
    """Not from a second table typed beside the script.

    `scripts/verify_addresses.py` carried its own `CANDIDATES` copy of these
    addresses with nothing comparing the two, so it could report every check
    green while `chain/addresses.py` — the module the signer actually imports —
    pointed somewhere else. That is the exact failure "verify the addresses"
    exists to catch, committed by the verifier itself.
    """
    report = addresses.survey(FakeChain(), CHAIN)
    detail = " ".join(c.detail for c in report.checks)

    for address in (DEPLOYMENT.factory, DEPLOYMENT.position_manager, POOL.address):
        assert address in detail, f"{address} is in the config but was never checked"


def test_a_factory_naming_a_different_pool_fails() -> None:
    """The check that catches a real mistake rather than a typo.

    P-6: Pancake deploys pools from its own `PancakeV3PoolDeployer` with a
    different init-code hash, so Uniswap's `computeAddress` constants return
    addresses that are perfectly well-formed and wrong.
    """
    report = addresses.survey(
        FakeChain(getPool="0x0000000000000000000000000000000000000bad"), CHAIN
    )
    assert status_of(report, "factory names this pool") == FAIL
    assert report.verdict == FAIL


@pytest.mark.parametrize(
    "override,fragment",
    [
        ({"token0": "0x0000000000000000000000000000000000000bad"}, "names these tokens"),
        ({"factory": "0x0000000000000000000000000000000000000bad"}, "manager names this factory"),
        ({"fee": 3000}, "fee tier"),
        ({"tickSpacing": 60}, "tick spacing"),
    ],
)
def test_each_disagreement_is_caught_on_its_own(override: dict, fragment: str) -> None:
    """One at a time, so a failure names which reading disagreed.

    `fee: 3000` and `tickSpacing: 60` are the Uniswap pair that does not exist
    on Pancake at all — the mismatch V-10 and P-6 are both about.
    """
    report = addresses.survey(FakeChain(**override), CHAIN)
    assert status_of(report, fragment) == FAIL


def test_a_read_that_failed_is_unknown_and_never_a_pass() -> None:
    """`read.py`'s rule, enforced by the shape of the data rather than the page."""
    report = addresses.survey(FakeChain(fee=RuntimeError("eth_call reverted")), CHAIN)
    assert status_of(report, "fee tier") == UNKNOWN
    # UNKNOWN is blocking. An address nobody could check and an address checked
    # clean must not produce the same verdict.
    assert report.verdict == UNKNOWN


def test_an_address_with_no_code_fails_rather_than_passing_quietly() -> None:
    chain = FakeChain()
    chain.empty.add(DEPLOYMENT.swap_router)
    report = addresses.survey(chain, CHAIN)

    assert status_of(report, "swap_router has code") == FAIL
    assert report.verdict == FAIL


def test_an_unreachable_node_is_unknown_not_absent() -> None:
    chain = FakeChain()
    chain.reverts.add(DEPLOYMENT.factory)
    report = addresses.survey(chain, CHAIN)

    assert status_of(report, "factory has code") == UNKNOWN
    assert report.verdict == UNKNOWN


def test_no_survey_at_all_is_a_sentence_not_an_empty_list() -> None:
    """Zero checks failing and zero checks run render identically otherwise."""
    report = addresses.not_surveyed(CHAIN, "no reachable RPC")

    assert report.verdict == UNKNOWN
    assert report.surveyed is False
    assert report.reason
    assert report.to_dict()["summary"]["checked"] == 0


def test_every_provenance_cites_something_that_resolves() -> None:
    """A citation renders as a link into /assumptions, so it must land.

    `tests/web/test_citations.py` catches this once the artifact exists; failing
    here instead names the check that carries the bad id.
    """
    import json
    from pathlib import Path

    sheet = Path(__file__).resolve().parents[2] / "apps/web/public/artifacts/assumptions.json"
    if not sheet.is_file():
        pytest.skip("no assumptions.json; run `make assumptions`")
    known = {e["id"] for e in json.loads(sheet.read_text())["entries"]}

    for check in addresses.survey(FakeChain(), CHAIN).checks:
        assert check.provenance in known, (
            f"{check.name!r} cites {check.provenance!r}, which is in neither source document"
        )


def test_the_scripts_candidate_table_agrees_with_the_module_it_verifies() -> None:
    """Two copies of the same addresses, with nothing comparing them.

    `scripts/verify_addresses.py` keeps a `CANDIDATES` table — the same
    addresses as `chain/addresses.py`, typed a second time — for its stdout
    report and its `--scan` pool discovery. The structured survey no longer
    reads it, but the copy is still there, and a copy nothing compares is a copy
    that drifts. It would drift in the worst possible direction: the script
    exists to prove the addresses are right, so it reporting every check green
    against a table the signer does not import is the failure it was written to
    prevent, committed by the verifier.

    Checked rather than deleted, because `--scan` genuinely needs candidate
    entries the deployment config does not carry — chapel's busd/usdc/cake are
    discovery inputs, not facts the signer is pointed at. So the rule is
    one-directional: everything the signer uses must appear in the script's
    table with the same value; extra candidates are fine.
    """
    import importlib.util
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "misquote_verify_addresses", repo / "scripts" / "verify_addresses.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    for chain_id, deployment in DEPLOYMENTS.items():
        candidates = {k: v.lower() for k, v in module.CANDIDATES[chain_id].items()}
        expected = {
            "factory": deployment.factory.lower(),
            "position_manager": deployment.position_manager.lower(),
            "swap_router": deployment.swap_router.lower(),
        }
        for role, address in expected.items():
            assert candidates.get(role) == address, (
                f"chain {chain_id}: scripts/verify_addresses.py has {role} = "
                f"{candidates.get(role)}, chain/addresses.py has {address}. "
                "The signer imports the second."
            )
