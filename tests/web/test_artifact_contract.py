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
    # The unit of every `*_quote` figure below. Added to the emitter without
    # being added here, which this test's own docstring is about: the omission
    # was invisible because the artifacts on disk predated the field, so the
    # `undeclared` direction had nothing to catch and the `undelivered`
    # direction was satisfied by both sides being silent. The first
    # regeneration would have failed for a reason unrelated to whoever ran it.
    "quote_symbol": "AgentCard.tsx",
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
    # Was `""` — emitted and rendered nowhere, which is how `/methods` came to
    # say "The four floors" over a block of five. It is the only floor that
    # calls a verdict rather than withholding a number, and it decides the
    # in-range PASS/FAIL on every card.
    "floors.in_range_floor": "methods/view.tsx",
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
    "activity.executed": "AgentDetail.tsx",
    "activity.failed": "AgentDetail.tsx",
    "activity.dropped": "AgentDetail.tsx",
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
    # Per-card provenance. Not rendered by any view — it is read by
    # `scripts/go_no_go.py`'s `check_artifact_freshness`, which asks whether a
    # published card still describes the engine that exists and answers
    # UNVERIFIED for any artifact recording no commit. Every card recorded none
    # until this block was added: they were stamped by proxy through
    # `build.json`, so the gate could not go green and its own stated remedy —
    # regenerate them — could not clear it either.
    "build.command": "",
    "build.source": "",
    "build.generated_at": "",
    "build.git_sha": "",
    "build.git_dirty": "",
}


@pytest.fixture(scope="module")
def router_artifact() -> dict:
    path = ARTIFACTS / "router.json"
    if not path.exists():
        pytest.skip("no router card; run `make router-card`")
    return json.loads(path.read_text())


# Router's card, and the file expected to render each field.
#
# It shipped unguarded: `AGENT_FIELDS` above covers `warden.json` only, so the
# newest emitter and the newest views could drift apart in either direction with
# nothing to notice. This closes that, and it is a separate map rather than an
# extension of `AGENT_FIELDS` because the two artifacts are deliberately
# different shapes — see `RouterArtifact` in `lib/artifacts.ts`.
ROUTER_FIELDS: dict[str, str] = {
    "agent": "RouterDetail.tsx",
    "kind": "app/view.tsx",  # the discriminator both surfaces dispatch on
    "category": "RouterCard.tsx",
    "venue": "RouterDetail.tsx",
    "venues": "RouterDetail.tsx",
    "source": "RouterDetail.tsx",  # the SourceBanner names the tape it read
    "counterfactual": "",
    "badge": "RouterCard.tsx",
    "quote_symbol": "RouterDetail.tsx",
    "capital_quote": "",
    "finding": "RouterCard.tsx",
    "pool_finding": "RouterDetail.tsx",
    "caveats": "RouterDetail.tsx",
    "quote.p25": "RouterCard.tsx",
    "quote.p50": "RouterCard.tsx",
    "quote.p75": "RouterCard.tsx",
    "quote.samples": "RouterDetail.tsx",
    "quote.windows": "RouterDetail.tsx",
    "quote.perturbations": "RouterDetail.tsx",
    "quote.best_venue_p50": "",
    "quote.switches_p50": "",
    "quote.hours_per_window": "RouterDetail.tsx",
    "quote.sufficient": "RouterCard.tsx",
    "quote.note": "RouterCard.tsx",
    "quote.annualised": "",
    "quote.basis": "RouterCard.tsx",
    "quote.net_positive": "RouterDetail.tsx",
    "quote.returns": "RouterDetail.tsx",
    "quote.max_edge_apr": "",
    "quote.hurdle_apr": "",
    "replay.samples": "RouterDetail.tsx",
    "replay.hours": "RouterDetail.tsx",
    "replay.entries": "RouterCard.tsx",
    "replay.exits": "RouterCard.tsx",
    "replay.switches": "RouterCard.tsx",
    "replay.invested_fraction": "RouterDetail.tsx",
    "replay.best_venue_fraction": "RouterDetail.tsx",
    "replay.gross_yield_quote": "RouterDetail.tsx",
    "replay.costs_quote": "RouterDetail.tsx",
    "replay.net_quote": "RouterDetail.tsx",
    "replay.max_edge_apr": "RouterDetail.tsx",
    "replay.hurdle_apr_p50": "RouterCard.tsx",
    "replay.best_apr_seen": "RouterCard.tsx",
    "replay.breakeven_horizon_hours": "RouterDetail.tsx",
    # `params` renders whole, as `Object.entries(data.params)` in
    # RouterDetail.tsx, so no individual leaf name appears in the source and the
    # check below cannot see one. Empty is the honest entry: the block is read,
    # these names are not written anywhere a grep would find them.
    "params.horizon_hours": "",
    "params.switch_cost_margin": "",
    "params.persistence_samples": "",
    "params.cooldown_s": "",
    "params.max_switches_per_day": "",
    "params.min_apr_samples": "",
    "params.eps_market_share": "",
    # The cost model, published because it decides the hurdle and therefore
    # every other figure on this card. `basis` names each input's source and
    # `derived` says whether any of them fell back — the distinction P-25 is
    # about.
    "cost_model.gas_quote": "RouterDetail.tsx",
    "cost_model.slippage_bps": "RouterDetail.tsx",
    "cost_model.derived": "RouterDetail.tsx",
    "cost_model.basis": "RouterDetail.tsx",
    # The comparison, in the same shape the LP cards carry it.
    "advantage.delta_pp": "RouterCard.tsx",
    "advantage.verdict": "RouterCard.tsx",
    "advantage.material": "RouterDetail.tsx",
    "advantage.ranges_overlap": "RouterDetail.tsx",
    "advantage.separated": "RouterDetail.tsx",
    "advantage.quotable": "RouterDetail.tsx",
    "advantage.source": "",
    "advantage.without_agent": "RouterDetail.tsx",
    "advantage.baseline.p25": "RouterDetail.tsx",
    "advantage.baseline.p50": "RouterDetail.tsx",
    "advantage.baseline.p75": "RouterDetail.tsx",
    "advantage.baseline.entries": "RouterDetail.tsx",
    "advantage.baseline.switches": "RouterDetail.tsx",
    "advantage.baseline.invested_fraction": "",
    "advantage.baseline.gross_yield_quote": "RouterDetail.tsx",
    "advantage.baseline.costs_quote": "RouterDetail.tsx",
    "advantage.baseline.net_quote": "RouterDetail.tsx",
    # Where the numbers came from. `make router` writes a journal and nothing
    # read it, so Router was the only card with no provenance at all — in a repo
    # where the Warden entrypoint argues that producing that journal is the
    # point of having an entrypoint.
    "provenance.journal": "RouterDetail.tsx",
    "provenance.journal_rows": "RouterDetail.tsx",
    "provenance.hours_covered": "RouterDetail.tsx",
    "provenance.every_number_derived": "",
    # Per-card provenance, read by `go_no_go.check_artifact_freshness`.
    "build.command": "",
    "build.source": "",
    "build.generated_at": "",
    "build.git_sha": "",
    "build.git_dirty": "",
}


def test_the_router_emitter_writes_exactly_the_contracted_fields(router_artifact: dict) -> None:
    """Both directions, for the fourth card as for the first."""
    actual = flatten(router_artifact)
    declared = set(ROUTER_FIELDS)

    undeclared = actual - declared
    undelivered = declared - actual

    assert not undeclared, (
        "the router emitter writes fields the contract does not declare — add "
        f"them to ROUTER_FIELDS and render them, or stop emitting them: {sorted(undeclared)}"
    )
    assert not undelivered, (
        "the contract declares router fields the emitter no longer writes; a "
        f"view is reading something that will be undefined: {sorted(undelivered)}"
    )


def test_every_contracted_router_field_is_read_by_the_named_view() -> None:
    sources = _sources()
    missing: list[str] = []
    for path, renderer in ROUTER_FIELDS.items():
        if not renderer:
            continue
        source = sources.get(renderer)
        assert source is not None, f"{renderer} does not exist"
        leaf = path.split(".")[-1]
        if leaf not in strip_comments(source):
            missing.append(f"{path} -> {renderer}")
    assert not missing, (
        f"contracted router fields are not read by the view named against them: {missing}"
    )


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


def strip_styling(source: str) -> str:
    """Remove class strings, which are full of numbers that mean nothing here.

    `max-w-[68ch]`, `text-[0.85em]`, `sm:grid-cols-2`, `mt-10` — Tailwind
    encodes layout as digits, and none of it is a claim to a reader. Scanning it
    made `68`, `24` and `0.85` look like smuggled artifact values in nearly
    every file.

    What is left is the text and the expressions, which is where a hardcoded
    figure would actually reach someone.
    """
    source = re.sub(r'className="[^"]*"', "", source)
    source = re.sub(r"className=\{[^}]*\}", "", source, flags=re.DOTALL)
    return source


def test_no_artifact_number_is_hardcoded_in_the_ui() -> None:
    """`Readme.md` rule 6, enforced mechanically.

    Every displayed number must trace to the artifact. A literal copied into a
    component looks identical to a rendered one and stops updating silently.

    ## What this used to miss

    It opened three artifacts of thirteen — `warden`, `grid`, `sentinel` — and
    within those took floats only at |x| >= 10 and ints only at |x| >= 1000. An
    audit of the nine pages found a dozen hardcoded values, and **not one of
    them was reachable by that rule**:

    * `index.json`, `build.json`, `advantage*.json`, `registry.json`,
      `vetting.json`, `addresses.json`, `vectors.json`, `status.json` were never
      opened at all.
    * `min_windows: 20`, `min_observations: 30`, `windows: 20`,
      `perturbations: 3`, `in_range_floor: 0.7` fell under both thresholds — and
      those are precisely the floors the pages restated.
    * `24.0` and `168.0` entered the set as `"24.00"` and `"168.00"`, so no page
      writing `24h` or `168h` could ever match.

    Every artifact is read now, and a value qualifies on being *distinctive*
    rather than large. Both forms of a float are checked, so `24.0` catches a
    page that writes `24`.

    ## Spelled-out numerals

    "twenty", "thirty", "three" evaded it completely, and that is how the worst
    findings hid: `/methods` restating its own window floor as "Twenty of them",
    `/advantage` claiming a "thirty-observation floor" and "twenty sub-windows
    times three perturbations". Only words for values in a `floors` block are
    checked — every floor is a number a page has a motive to restate, and the
    set is small enough that a false positive is a real finding.
    """
    if not (ARTIFACTS / "warden.json").exists():
        pytest.skip("no artifacts; run `make showcase-demo`")

    literals: set[str] = set()
    spelled: dict[str, str] = {}

    #: What a bare integer cannot be distinguished from.
    #:
    #: A one- or two-digit integer is a Tailwind scale step, a grid span, a
    #: z-index or a pixel threshold as often as it is an artifact value.
    #: Scanning for them flagged `pad = 32` in the nav's scroll maths, `zero >
    #: 14` in the band's axis, and the "83% win rate" hypothetical on /methods —
    #: three constants that belong exactly where they are.
    #:
    #: So this rule does not cover them, and that hole is stated rather than
    #: allowlisted: an allowlist would grow every time layout code moved, and a
    #: guard people edit to silence is a guard people stop reading. What covers
    #: the small values that matter is the spelled-out scan below — every floor
    #: is two digits, and every floor is a number a page has a motive to
    #: restate.
    def _too_ambiguous(text: str) -> bool:
        return text.isdigit() and len(text) <= 2

    #: Small integers and round decimals appear legitimately in layout code —
    #: grid spans, opacities, durations — so they are never treated as
    #: artifact values. Anything outside this is distinctive enough to matter.
    UNDISTINCTIVE = {"0", "1", "2", "3", "4", "5", "6", "8", "10", "12", "100"}

    WORDS = {
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
        6: "six",
        7: "seven",
        8: "eight",
        9: "nine",
        10: "ten",
        12: "twelve",
        20: "twenty",
        24: "twenty-four",
        30: "thirty",
        168: "one hundred and sixty-eight",
    }

    def add(value: object) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, float):
            # Both renderings: `24.0` is written `24` by a page and `24.00` by
            # a formatter, and the old rule only ever built the second.
            #
            # The two-decimal form is only added when it is **lossless**. It was
            # added unconditionally, so `0.0829` — a Router window return —
            # entered the set as `"0.08"` and matched `Band.tsx`'s
            # `pad = (hi - lo) * 0.08`, a layout constant that has nothing to do
            # with any artifact. A *rounded* rendering is not the artifact's
            # value: no page restates 0.0829 by writing 0.08, and treating a
            # two-digit truncation as the thing itself produces a false
            # accusation for every small decimal a card publishes.
            #
            # `24.0` still works, because `24.00` round-trips exactly.
            renderings = [f"{value:g}"]
            two_dp = f"{value:.2f}"
            if float(two_dp) == value:
                renderings.append(two_dp)
            for text in renderings:
                if text not in UNDISTINCTIVE and not _too_ambiguous(text):
                    literals.add(text)
        elif isinstance(value, int):
            text = str(value)
            # `UNDISTINCTIVE` applies here too. It did not, and the asymmetry
            # was unintentional: 100 was declared undistinctive for floats and
            # distinctive for ints, so the moment an artifact carried a bare
            # `100` — `venue.json`'s 0.01% fee tier — six components doing
            # `* 100` to make a percentage were flagged as smuggling it.
            if text not in UNDISTINCTIVE and not _too_ambiguous(text):
                literals.add(text)

    def walk(o: object) -> None:
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        else:
            add(o)

    for path in sorted(ARTIFACTS.glob("*.json")):
        data = json.loads(path.read_text())
        walk(data)
        # Floors get their words checked too — see the docstring.
        for block in ("floors",):
            for value in (data.get(block) or {}).values():
                word = WORDS.get(int(value)) if isinstance(value, int | float) else None
                if word:
                    spelled[word] = f"{block} value {value}"

    offenders: list[str] = []
    for path in [*WEB_SRC.rglob("*.tsx"), *WEB_SRC.rglob("*.ts")]:
        if path.name.endswith(".test.ts") or path.name.endswith(".test.tsx"):
            continue
        # `src/test/` is the harness the component tests run against — stubbed
        # fetches, fixture loaders. Nothing in it renders, so a number there is
        # never a figure a reader sees; `harness.tsx` was flagged for the `200`
        # in an HTTP status. The rule is about what reaches a page.
        if "test" in path.relative_to(WEB_SRC).parts:
            continue
        # Comments are stripped first. The rule is about numbers that reach a
        # reader, and these files quote real figures when explaining which bug
        # they exist to prevent — that prose is the opposite of a smuggled
        # literal, and flagging it would train the next person to delete the
        # explanation rather than the hardcoding.
        text = strip_styling(strip_comments(path.read_text()))
        where = path.relative_to(REPO)
        for literal in literals:
            # Bounded, so `68` does not match `ERC-8183` or `max-w-[68ch]` and
            # `56` does not match a chain id inside an identifier. A bare
            # substring scan was survivable only while the thresholds kept every
            # literal long; dropping them made almost every file a false
            # positive, which is worse than the hole it closed.
            if re.search(rf"(?<![\w.-]){re.escape(literal)}(?![\w.-])", text):
                offenders.append(f"{where} contains {literal!r}")
        for word, why in spelled.items():
            if re.search(rf"\b{word}\b", text, re.IGNORECASE):
                offenders.append(f"{where} spells out {word!r} ({why})")

    assert not offenders, (
        "hardcoded artifact values in the UI — read them from the artifact "
        f"instead: {sorted(offenders)}"
    )
