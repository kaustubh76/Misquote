"""The contract between the Python emitters and the front end.

The failure this guards against is silent and one-directional: a field is added
to `Tearsheet.to_dict` and no view renders it, or a view reads a field the
emitter stopped writing. Both look fine in isolation. Neither is caught by the
Python tests, which never open the web app, or by the component tests, which run
against fixtures rather than against real output.

That failure has already happened once, at scale. `activity` and `provenance`
were emitted on every artifact from the beginning and the card page rendered
neither — including `held_by_gate`, the histogram that is the entire reason all
four R-gates are journalled on every row. Nothing failed. Nothing said anything.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO / "apps" / "web" / "public" / "artifacts"
WEB_SRC = REPO / "apps" / "web" / "src"


# Containers whose *keys* are data rather than schema, so flattening stops at
# them. Listed explicitly: inferring it from "every value is numeric" also
# swallows `floors` and `replay`, which are ordinary fixed-shape objects that
# happen to hold only numbers.
OPAQUE = frozenset({"activity.held_by_gate"})


def flatten(obj: object, prefix: str = "") -> set[str]:
    """Dotted paths for every leaf in a JSON document."""
    if prefix in OPAQUE:
        return {prefix}

    out: set[str] = set()
    if isinstance(obj, dict):
        if not obj:
            return {prefix} if prefix else set()
        for key, value in obj.items():
            out |= flatten(value, f"{prefix}.{key}" if prefix else key)
    else:
        out.add(prefix)
    return out


@pytest.fixture(scope="module")
def agent_artifact() -> dict:
    path = ARTIFACTS / "warden.json"
    if not path.exists():
        pytest.skip("no artifacts; run `make showcase-demo`")
    return json.loads(path.read_text())


# Every dotted path the agent artifact is contracted to carry, and the file
# expected to render it. Adding a field to the emitter without adding it here
# fails; adding it here without rendering it also fails.
AGENT_FIELDS: dict[str, str] = {
    "agent": "AgentDetail.tsx",
    "pool": "AgentDetail.tsx",
    "badge": "AgentCard.tsx",
    "source": "AgentDetail.tsx",
    "counterfactual": "",  # carried for machine readers; no view renders it
    "caveats": "AgentDetail.tsx",
    "quote": "",  # the rendered string; views use quote_detail instead
    "quote_sufficient": "AgentCard.tsx",
    "quote_detail.p25": "Band.tsx",
    "quote_detail.p50": "Band.tsx",
    "quote_detail.p75": "Band.tsx",
    "quote_detail.samples": "AgentDetail.tsx",
    "quote_detail.windows": "AgentDetail.tsx",
    "quote_detail.perturbations": "AgentDetail.tsx",
    "quote_detail.net_positive": "AgentDetail.tsx",
    "quote_detail.returns": "AgentCard.tsx",
    "quote_detail.in_range_p50": "",
    "quote_detail.rebalances_p50": "",
    "quote_detail.hours_per_window": "AgentDetail.tsx",
    "quote_detail.sufficient": "AgentCard.tsx",
    "quote_detail.annualised": "AgentCard.tsx",
    "quote_detail.basis": "AgentDetail.tsx",
    "quote_detail.note": "AgentCard.tsx",
    "floors.min_windows": "methods/view.tsx",
    "floors.min_window_hours": "methods/view.tsx",
    "floors.min_hours_to_annualise": "methods/view.tsx",
    "floors.min_observations": "methods/view.tsx",
    "floors.in_range_floor": "",
    "estimators.sigma_per_sqrt_hour": "AgentDetail.tsx",
    "estimators.sigma_ready": "AgentDetail.tsx",
    "estimators.kappa_per_tick": "AgentDetail.tsx",
    "estimators.kappa_per_logprice": "AgentDetail.tsx",
    "estimators.kappa_r_squared": "AgentDetail.tsx",
    "estimators.kappa_is_fallback": "AgentDetail.tsx",
    "estimators.kappa_buckets_used": "AgentDetail.tsx",
    "estimators.kappa_swaps_used": "AgentDetail.tsx",
    "estimators.kappa_label": "AgentDetail.tsx",
    "estimators.imbalance_z": "AgentDetail.tsx",
    "estimators.imbalance_ready": "AgentDetail.tsx",
    "verdicts.in_range.called": "Pill.tsx",
    "verdicts.in_range.label": "AgentDetail.tsx",
    "verdicts.in_range.detail": "AgentDetail.tsx",
    "verdicts.in_range.n": "AgentDetail.tsx",
    "verdicts.profitable.called": "Pill.tsx",
    "verdicts.profitable.label": "AgentDetail.tsx",
    "verdicts.profitable.detail": "AgentDetail.tsx",
    "verdicts.profitable.n": "AgentDetail.tsx",
    "activity.decisions": "",
    "activity.hours": "",
    "activity.mints": "",
    "activity.rebalances": "",
    "activity.pulls": "",
    "activity.read_errors": "AgentDetail.tsx",
    "activity.held_by_gate": "GateHistogram.tsx",
    "provenance.journal": "AgentDetail.tsx",
    "provenance.journal_rows": "AgentDetail.tsx",
    "provenance.hours_covered": "AgentDetail.tsx",
    "provenance.every_number_derived": "AgentDetail.tsx",
    "replay.samples": "AgentCard.tsx",
    "replay.hours": "AgentCard.tsx",
    "replay.mints": "AgentCard.tsx",
    "replay.rebalances": "AgentCard.tsx",
    "replay.pulls": "AgentCard.tsx",
    "replay.in_range_fraction": "AgentCard.tsx",
    "replay.fees_quote": "AgentCard.tsx",
    "replay.lvr_quote_upper_bound": "AgentCard.tsx",
    "replay.costs_quote": "AgentCard.tsx",
    "replay.net_quote": "AgentCard.tsx",
    "advantage.delta_pp": "AgentCard.tsx",
    "advantage.material": "",
    "advantage.ranges_overlap": "",
    "advantage.separated": "",
    "advantage.quotable": "AgentCard.tsx",
    "advantage.verdict": "AgentCard.tsx",
    "advantage.without_agent": "AgentDetail.tsx",
    "advantage.baseline.p25": "AgentCard.tsx",
    "advantage.baseline.p50": "AgentCard.tsx",
    "advantage.baseline.p75": "AgentCard.tsx",
    "advantage.baseline.in_range_fraction": "AgentDetail.tsx",
    "advantage.baseline.fees_quote": "AgentDetail.tsx",
    "advantage.baseline.lvr_quote_upper_bound": "",
    "advantage.baseline.costs_quote": "AgentDetail.tsx",
    "advantage.baseline.moves": "AgentDetail.tsx",
}


def test_emitter_writes_exactly_the_contracted_fields(agent_artifact: dict) -> None:
    """Both directions. Neither side may move without the other noticing."""
    actual = flatten(agent_artifact)
    declared = set(AGENT_FIELDS)

    undeclared = actual - declared
    undelivered = declared - actual

    assert not undeclared, (
        "the emitter writes fields the contract does not declare — add them to "
        f"AGENT_FIELDS and render them, or stop emitting them: {sorted(undeclared)}"
    )
    assert not undelivered, (
        "the contract declares fields the emitter no longer writes; a view is "
        f"reading something that will be undefined: {sorted(undelivered)}"
    )


def strip_comments(source: str) -> str:
    """Remove `//` and `/* */` comments. Deliberately crude, and safe to be.

    A `//` inside a string literal would be stripped too, which at worst hides a
    literal from the scan below — the failure mode is a missed offender in a
    string containing a URL, not a false accusation.
    """
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", " ", source)


def _sources() -> dict[str, str]:
    return {p.name: p.read_text() for p in WEB_SRC.rglob("*.tsx")} | {
        f"{p.parent.name}/{p.name}": p.read_text() for p in WEB_SRC.rglob("*.tsx")
    }


def test_every_contracted_field_is_read_by_the_named_view() -> None:
    """A field with a renderer named against it must actually appear there."""
    sources = _sources()
    missing: list[str] = []

    for path, renderer in AGENT_FIELDS.items():
        if not renderer:
            continue
        source = sources.get(renderer)
        assert source is not None, f"{renderer} does not exist"
        leaf = path.rsplit(".", 1)[-1]
        if not re.search(rf"\b{re.escape(leaf)}\b", source):
            missing.append(f"{path} -> {renderer}")

    assert not missing, (
        f"these fields are contracted to a view that never mentions them: {sorted(missing)}"
    )


def test_the_counterfactual_badge_survives() -> None:
    """The badge is a field on the artifact, asserted by a test, and rendered.

    `scripts/showcase.py` is explicit that the badge "is not a disclaimer bolted
    on at the end… the web app renders it as prominently as the number it
    qualifies". The artifact side of that was already asserted; the rendering
    side could be deleted and every suite stayed green.
    """
    sources = _sources()
    assert "badge" in sources["Badge.tsx"]
    for view in ("AgentCard.tsx", "AgentDetail.tsx"):
        assert "Badge" in sources[view], f"{view} stopped rendering the badge"


def test_no_artifact_number_is_hardcoded_in_the_ui() -> None:
    """`Readme.md` rule 6, enforced mechanically.

    Every displayed number must trace to the artifact. A literal copied into a
    component looks identical to a rendered one and stops updating silently.
    """
    if not (ARTIFACTS / "warden.json").exists():
        pytest.skip("no artifacts; run `make showcase-demo`")

    literals: set[str] = set()
    for name in ("warden.json", "grid.json", "sentinel.json"):
        data = json.loads((ARTIFACTS / name).read_text())

        def walk(o: object) -> None:
            if isinstance(o, dict):
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
            elif isinstance(o, float):
                # Distinctive values only: 0.0, 1.0 and small integers appear
                # legitimately in layout code.
                text = f"{o:.2f}"
                if abs(o) >= 10 and text not in {"100.00"}:
                    literals.add(text)
            elif isinstance(o, int) and abs(o) >= 1000:
                literals.add(str(o))

        walk(data)

    offenders: list[str] = []
    for path in [*WEB_SRC.rglob("*.tsx"), *WEB_SRC.rglob("*.ts")]:
        if path.name.endswith(".test.ts") or path.name.endswith(".test.tsx"):
            continue
        # Comments are stripped first. The rule is about numbers that reach a
        # reader, and these files quote real figures when explaining which bug
        # they exist to prevent — that prose is the opposite of a smuggled
        # literal, and flagging it would train the next person to delete the
        # explanation rather than the hardcoding.
        text = strip_comments(path.read_text())
        for literal in literals:
            if literal in text:
                offenders.append(f"{path.relative_to(REPO)} contains {literal!r}")

    assert not offenders, f"hardcoded artifact values in the UI: {sorted(offenders)}"
