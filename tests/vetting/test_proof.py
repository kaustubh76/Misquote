"""The proving half of "they flag, we prove", and the honesty it needs.

The risk with a proof-of-concept layer is not that it fails — a failure is the
finding working. It is that it looks like it covers more than it does. Three
green ticks beside nine checks reads as six failures unless the six say why they
are absent, so most of what is asserted here is about that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from misquote.vetting import proof as vp
from misquote.vetting.badge import CHECK_IDS

REPO = Path(__file__).resolve().parents[2]


def test_every_check_is_either_provable_or_explained() -> None:
    """No check may be silently absent from the proof layer.

    This is the assertion the whole module is shaped around. A page showing
    proofs for three of nine checks, with nothing said about the other six,
    invites the reader to conclude the six failed.
    """
    accounted = set(vp.PROVEN) | set(vp.UNPROVEN)
    assert accounted == set(CHECK_IDS.values()), (
        f"checks with no proof and no reason: {set(CHECK_IDS.values()) - accounted}"
    )
    assert not (set(vp.PROVEN) & set(vp.UNPROVEN)), "a check cannot be both"


def test_the_reasons_are_reasons_and_not_placeholders() -> None:
    """ "not implemented" is not an explanation.

    Each entry has to say *why the consequence is not executable*, which is a
    different claim from "we did not get to it" — and if it ever is the second,
    it belongs on the not-built ledger rather than here.
    """
    for check_id, why in vp.UNPROVEN.items():
        assert len(why) > 40, f"{check_id}'s reason is too short to be one"
        assert "todo" not in why.lower() and "not implemented" not in why.lower(), check_id


def test_the_proof_ids_are_the_badge_s_ids() -> None:
    """A proof joins to a finding on `CHECK_IDS`, or it joins to nothing."""
    for check_id in vp.PROVEN:
        assert check_id in CHECK_IDS.values(), check_id


def test_coverage_needs_no_chain_and_no_toolchain() -> None:
    """It is computed from the badge on disk, so it can go into every build.

    The executed half needs anvil, foundry and a fork url. The *statement of what
    is provable* needs none of them, and separating the two is what lets the
    artifact carry the coverage on a machine with no toolchain rather than
    omitting the section entirely.
    """
    badges = sorted((REPO / "vetting" / "badges").glob("*.json"))
    if not badges:
        pytest.skip("no badge recorded; run `make vet`")

    badge = json.loads(badges[0].read_text())
    cover = vp.coverage(badge)

    assert cover["checks"] == 9
    assert sorted(cover["provable"]) == sorted(vp.PROVEN)
    assert set(cover["not_provable"]) == set(vp.UNPROVEN)


def test_a_missing_badge_refuses_rather_than_proving_nothing() -> None:
    """A proof-of-concept with no finding to prove is a test looking for a
    subject, and returning an empty list would publish as "nothing failed"."""
    with pytest.raises(FileNotFoundError, match="no finding to prove"):
        vp.badge_for("0x" + "ab" * 20)


def test_the_forge_script_exists_and_names_the_ids_it_proves() -> None:
    """The join, checked from the Solidity side.

    `Badge.s.sol` emits `Proved(id, held, detail)` and the ids it emits must be
    the badge's. A script emitting `"factory-check"` against a badge recording
    `"factory"` would run green and join to nothing.
    """
    source = (REPO / "vetting" / "forge" / "script" / "Badge.s.sol").read_text()
    for check_id in vp.PROVEN:
        assert f'"{check_id}"' in source, (
            f"{check_id} is listed as provable and Badge.s.sol never emits it"
        )


def test_the_prover_can_receive_the_position_it_mints() -> None:
    """A v3 position is an ERC-721, and the prover is its recipient.

    Without `onERC721Received` the mint reverts — and reverts with **empty return
    data**, so `catch Error(string)` never fires and the proof reports "no reason
    given". Identical parameters minted from an EOA with `status: 1`; the only
    difference was who was being handed the token.

    Asserted from the source because the failure is silent: the proof does not
    crash, it publishes `held: false` and looks like a finding that did not hold.
    """
    source = (REPO / "vetting" / "forge" / "script" / "Badge.s.sol").read_text()
    assert "onERC721Received" in source
    assert "0x150b7a02" in source, "the ERC-721 magic value is what makes it an acceptance"


def test_the_mint_prover_is_sent_with_an_explicit_gas_limit() -> None:
    """`estimate_gas` measures the caught path of a `try/catch`.

    Estimating a function that catches a failing inner call measures the cheap,
    caught path; sending with that estimate gives the inner call 63/64 of almost
    nothing, so it runs out of gas, so the catch fires. The failure is
    self-fulfilling, perfectly stable, and produces empty revert data that is
    indistinguishable from a bare `revert()`.

    So the gas is explicit, and this asserts it stays that way — the symptom of
    losing it is a finding quietly reporting `held: false`.
    """
    harness = (REPO / "scripts" / "vetting_proof.py").read_text()
    assert "MINT_GAS" in harness
    assert "gas=MINT_GAS" in harness, "the mint must not be sent on an estimate"


def test_the_recorded_run_holds_if_one_exists() -> None:
    """Every proof in a recorded run held, or the badge that shipped is wrong.

    Skipped when nothing has been run, because "no proof has been executed" and
    "a proof failed" are different facts — the same distinction the badge draws
    between UNKNOWN and FAIL.
    """
    runs = sorted((REPO / "vetting" / "runs").glob("proof-*.json"))
    if not runs:
        pytest.skip("no proof run recorded; `make vet-prove` writes one")

    for path in runs:
        record = json.loads(path.read_text())
        assert record["proofs"], f"{path.name} recorded a run with no proofs"
        for entry in record["proofs"]:
            assert entry["held"], (
                f"{path.name}: {entry['check_id']} did not hold on the fork — "
                f"{entry['detail']}. The published badge says otherwise."
            )
            assert entry["check_id"] in CHECK_IDS.values()
            assert entry["block"] > 0, "a proof with no block cannot be reproduced"
