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
OPAQUE = frozenset(
    {
        "activity.held_by_gate",
        # 8004scan's readings, whose keys are data the index chose rather than
        # schema this repository declares. `by_agent` is keyed by token id and
        # holds one entry per rated agent; the histograms are keyed by whatever
        # tag, method, parse code or failure string came back. Declaring those
        # keys would contract *the registry's current contents* as an interface,
        # which is a test that fails when somebody else mints an agent.
        "third_party.feedback_graph.by_agent",
        "third_party.feedback_graph.tags",
        "third_party.feedback_graph.methods",
        "third_party.feedback_graph.decode_failures",
        "third_party.feedback_graph.parse_status",
        "third_party.feedback_graph.failure_reasons",
        "third_party.census.protocols",
        "third_party.census.failure_reasons",
        "third_party.name_collisions.names",
        # A proof's `params` are keyed by the parameter the filter sends, which
        # is the filter's own business — `FILTERS` is where that is declared and
        # `tests/registry/test_scan8004.py` is what holds it honest.
        "third_party.counts.filters.x402_supported.params",
        "third_party.counts.filters.with_feedback.params",
        "third_party.counts_testnet.filters.x402_supported.params",
        "third_party.counts_testnet.filters.with_feedback.params",
        "third_party.ours_as_indexed.filter_proof.params",
        # Keyed by chain id, by Solidity signature, and by contract name
        # respectively — data in all three cases. `aacp.escrow_interface`'s keys
        # are literally `acceptOrder(bytes32)`; contracting those would make
        # this test a snapshot of somebody else's ABI.
        "hire_flow_contracts.56",
        "hire_flow_contracts.97",
        "aacp.contracts",
        "aacp.escrow_interface",
        "identity.identity_registry",
        "identity.reputation_registry",
        # Keyed by search needle, which is our schema — but four categories
        # times four needles is sixteen paths saying one thing, and the needles
        # are held against `index.json` by
        # `tests/registry/test_scan8004.py::test_the_needles_cover_the_categories_the_index_publishes`
        # rather than here.
        "third_party.categories.Rebalancing.searched",
        "third_party.categories.Market making.searched",
        "third_party.categories.Health.searched",
        "third_party.categories.Yield.searched",
    }
)


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
    "source": "",  # recorded in the artifact; not rendered
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
    # Recorded by the emitter and read by `scripts/go_no_go.py`; no view
    # renders it. The site states what the numbers are, not how the run that
    # produced them was bookkept.
    "provenance.journal": "",
    "provenance.journal_rows": "",
    "provenance.hours_covered": "",
    "provenance.every_number_derived": "",
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
    "source": "",  # recorded in the artifact; not rendered
    "counterfactual": "",
    "badge": "RouterCard.tsx",
    "quote_symbol": "RouterDetail.tsx",
    "capital_quote": "",
    "finding": "RouterCard.tsx",
    "pool_finding": "RouterDetail.tsx",
    # The second replay, at a notional the ranges can absorb. Every key is
    # declared: the block is a fixed shape, not a data-keyed container, and
    # `flatten` recurses into it exactly as it does into `quote`.
    "at_pool_scale.capital_quote": "RouterDetail.tsx",
    "at_pool_scale.derived_from": "RouterDetail.tsx",
    "at_pool_scale.entries": "RouterDetail.tsx",
    "at_pool_scale.switches": "RouterDetail.tsx",
    "at_pool_scale.exits": "",
    "at_pool_scale.invested_fraction": "RouterDetail.tsx",
    "at_pool_scale.net_quote": "RouterDetail.tsx",
    "at_pool_scale.best_apr_seen": "RouterDetail.tsx",
    "at_pool_scale.venues_held": "RouterDetail.tsx",
    "at_pool_scale.pool_held_samples": "RouterDetail.tsx",
    "at_pool_scale.samples": "RouterDetail.tsx",
    "at_pool_scale.quote.p25": "RouterDetail.tsx",
    "at_pool_scale.quote.p50": "RouterDetail.tsx",
    "at_pool_scale.quote.p75": "RouterDetail.tsx",
    "at_pool_scale.quote.samples": "RouterDetail.tsx",
    "at_pool_scale.quote.windows": "RouterDetail.tsx",
    "at_pool_scale.quote.sufficient": "RouterDetail.tsx",
    "at_pool_scale.quote.note": "RouterDetail.tsx",
    # Emitted for a machine consumer and not rendered: `basis` states the same
    # fact in the words a reader needs — "over 125h — too short to annualise
    # honestly" — and a boolean beside that sentence would be the sentence twice.
    "at_pool_scale.quote.annualised": "",
    "at_pool_scale.quote.basis": "RouterDetail.tsx",
    "at_pool_scale.quote.hours_per_window": "RouterDetail.tsx",
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
    # Where the numbers came from. `make router` writes a journal; no view
    # renders it. Contracted so the emitter cannot quietly stop writing it.
    "provenance.journal": "",
    "provenance.journal_rows": "",
    "provenance.hours_covered": "",
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
    return strip_image_metadata(source)


def strip_image_metadata(source: str) -> str:
    """Remove Next's `export const size = {width, height}`, which is a format.

    Third in the same family as `strip_comments` and the class stripper above,
    and added for a collision that shows why the family is the right shape:
    `opengraph-image.tsx` declares `size = { width: 1200, height: 630 }` because
    that is the OpenGraph card dimension every scraper expects, and a live
    8004scan reading came back with 1,200 testnet agents lacking x402 support.
    Two unrelated numbers, one value, and the guard could not tell them apart.

    The fix is structural rather than numeric on purpose. This test's own
    docstring argues against an allowlist — "a guard people edit to silence is a
    guard people stop reading" — and adding `1200` to `UNDISTINCTIVE` would
    blind it to a real 1,200 anywhere on any page, permanently, to fix one
    collision that will disappear the next time BSC testnet mints an agent.
    Removing an image dimension declaration blinds it to nothing a reader sees.

    Deliberately narrow: it matches the `size` export by name, in the files
    Next reserves that name in. A component that renders `1200` as text still
    fails, which is the case worth catching.
    """
    return re.sub(r"export const size\s*=\s*\{[^}]*\}", "", source, flags=re.DOTALL)


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


# ── third_party: what 8004scan's readings are contracted to carry ────────────
#
# `registry.json` had no contract at all before this — `AGENT_FIELDS` and
# `ROUTER_FIELDS` cover the agent cards and nothing covered the registry page,
# so its fields could be added, renamed or dropped without any test noticing.
# This closes that for the block this feature triples in size; `REGISTRY_FIELDS`
# below covers the rest.
#
# ## Declared by shape rather than by path
#
# Four categories carry one shape and two filters carry another, so a literal
# map would be the same fifteen lines four times over. `categories.ts` makes the
# argument in the other direction — a taxonomy is derived, never re-declared —
# and the same reasoning applies to a repeated *shape*: writing it once means a
# field added to a category is added to all four or to none, which is what the
# emitter actually does.

#: One category's fields. `searched` is OPAQUE — its keys are the needles.
_CATEGORY_SHAPE = {
    "available": "ScanAgents.tsx",
    "agents": "ScanAgents.tsx",
    "category": "ScanAgents.tsx",
    "matched": "ScanAgents.tsx",
    "dropped_not_matching": "ScanAgents.tsx",
    "crowded_out_by_owner_cap": "ScanAgents.tsx",
    "distinct_owners_matched": "ScanAgents.tsx",
    "max_per_owner": "ScanAgents.tsx",
    "needles": "ScanAgents.tsx",
    "attributed_to": "ScanAgents.tsx",
    "note": "ScanAgents.tsx",
    # Machine-readable, with a reason. `tier` and `chain_id` say which API
    # answered and about what; `read_at` is rendered as an age by the section
    # header rather than as a field on every card, and `searched` is the
    # per-needle detail the summary counts already carry.
    "tier": "",
    "chain_id": "",
    "read_at": "",
    "searched": "",
}

#: One `proven_count`. The three checks are contracted individually because the
#: page renders the proof, not just its verdict — a share published without
#: showing what was checked is the assertion this whole mechanism replaced.
_PROVEN_COUNT_SHAPE = {
    "applied": "registry/view.tsx",
    "total": "registry/view.tsx",
    "share": "registry/view.tsx",
    "baseline": "registry/view.tsx",
    "reason": "registry/view.tsx",
    "rows_checked": "registry/view.tsx",
    "rows_satisfying": "registry/view.tsx",
    "differs_from_baseline": "registry/view.tsx",
    "name": "",
    "available": "",
    "tier": "",
    "params": "",
}

#: The three keys a complement adds, and only a filter that has one carries them.
#:
#: Not a conditional field being tolerated — a different shape, declared. A
#: complement is what turns "this total is not the population" into "this total
#: and its opposite add back to the population", and `FILTERS` says which filters
#: have one: `x402_supported=false` is a set, `max_feedbacks` is not implemented.
#: Declaring these on `with_feedback` would contract a check that filter cannot
#: run, and the test would demand the emitter invent it.
_COMPLEMENT_SHAPE = {
    "complement_total": "registry/view.tsx",
    "sum_vs_baseline": "registry/view.tsx",
    "within_tolerance": "registry/view.tsx",
    "growth_tolerance": "registry/view.tsx",
}

#: Which filters have a complement, mirroring `scan8004.FILTERS`.
_FILTERS_WITH_COMPLEMENT = ("x402_supported",)

#: One proven ordering.
_PROVEN_SORT_SHAPE = {
    "sorted": "ScanAgents.tsx",
    "rows": "ScanAgents.tsx",
    "reason": "ScanAgents.tsx",
    "monotone": "ScanAgents.tsx",
    "differs_from_unsorted_head": "ScanAgents.tsx",
    "key": "",
    "head_values": "",
}

_CATEGORIES = ("Rebalancing", "Market making", "Health", "Yield")
_FILTERS = ("x402_supported", "with_feedback")
_SORTS = ("total_score", "total_feedbacks")

THIRD_PARTY_FIELDS: dict[str, str] = {
    "third_party.source": "",
    "third_party.tier": "",
    "third_party.rate_limit_per_minute": "",
    "third_party.rate_limit_per_day": "",
    # The population, and the two counts of it that will not be reconciled.
    "third_party.population.available": "",
    "third_party.population.tier": "",
    "third_party.population.chain_id": "",
    "third_party.population.population": "",
    "third_party.population.contract_address": "",
    "third_party.reconciliation.ours": "registry/view.tsx",
    "third_party.reconciliation.ours_method": "registry/view.tsx",
    "third_party.reconciliation.theirs": "registry/view.tsx",
    "third_party.reconciliation.theirs_method": "registry/view.tsx",
    "third_party.reconciliation.difference": "registry/view.tsx",
    "third_party.reconciliation.difference_pct": "registry/view.tsx",
    "third_party.reconciliation.same_contract": "registry/view.tsx",
    "third_party.reconciliation.note": "registry/view.tsx",
    # Cross-chain context. Explicitly not comparable to the BSC figures, which
    # is why nothing renders them beside a BSC number.
    "third_party.stats.available": "",
    "third_party.stats.total_agents_all_chains": "",
    "third_party.stats.total_feedbacks_all_chains": "",
    "third_party.stats.daily_new_agents_all_chains": "",
    "third_party.stats.average_feedback_score": "",
    # The walk. Kept, demoted, and carried forward between runs rather than
    # overwritten — `carried_forward` and `read_at` are what stop a two-hour
    # reading from being republished as though it were taken this morning.
    "third_party.census.available": "registry/view.tsx",
    "third_party.census.reason": "registry/view.tsx",
    "third_party.census.carried_forward": "registry/view.tsx",
    "third_party.census.read_at": "registry/view.tsx",
    "third_party.census.counted": "registry/view.tsx",
    "third_party.census.complete": "registry/view.tsx",
    "third_party.census.distinct_owners": "registry/view.tsx",
    "third_party.census.distinct_descriptions": "registry/view.tsx",
    "third_party.census.tier": "",
    "third_party.census.chain_id": "",
    "third_party.census.described": "",
    "third_party.census.verified": "",
    "third_party.census.starred": "",
    "third_party.census.with_score": "",
    "third_party.census.with_feedback": "",
    "third_party.census.x402_supported": "",
    "third_party.census.feedbacks_claimed": "",
    "third_party.census.protocols": "",
    "third_party.census.pages_failed": "",
    "third_party.census.agents_missed": "",
    "third_party.census.failed_offsets": "",
    "third_party.census.failure_reasons": "",
    "third_party.census.population_at_start": "",
    "third_party.census.population_at_end": "",
    "third_party.census.minted_during_the_walk": "",
    "third_party.census.ordering": "",
    "third_party.census.note": "",
    # The counts, and the same walk-versus-ask comparison the page draws.
    "third_party.counts.available": "registry/view.tsx",
    "third_party.counts.baseline": "registry/view.tsx",
    "third_party.counts.requests": "registry/view.tsx",
    "third_party.counts.refused": "registry/view.tsx",
    "third_party.counts.note": "registry/view.tsx",
    "third_party.counts.read_at": "",
    "third_party.counts.tier": "",
    "third_party.counts.chain_id": "",
    "third_party.counts_cross_check.available": "registry/view.tsx",
    "third_party.counts_cross_check.rows": "registry/view.tsx",
    "third_party.counts_cross_check.hours_apart": "registry/view.tsx",
    "third_party.counts_cross_check.note": "registry/view.tsx",
    # Testnet, carried because our own four agents' zeros are zeros out of it.
    "third_party.counts_testnet.available": "IndexedAgreement.tsx",
    "third_party.counts_testnet.baseline": "IndexedAgreement.tsx",
    "third_party.counts_testnet.refused": "",
    "third_party.counts_testnet.requests": "",
    "third_party.counts_testnet.note": "",
    "third_party.counts_testnet.read_at": "",
    "third_party.counts_testnet.tier": "",
    "third_party.counts_testnet.chain_id": "",
    # Who does the rating.
    "third_party.feedback_graph.available": "registry/view.tsx",
    "third_party.feedback_graph.rows": "registry/view.tsx",
    "third_party.feedback_graph.total_reported": "registry/view.tsx",
    "third_party.feedback_graph.complete": "registry/view.tsx",
    "third_party.feedback_graph.distinct_raters": "registry/view.tsx",
    "third_party.feedback_graph.distinct_rated_agents": "registry/view.tsx",
    "third_party.feedback_graph.top_rater_share": "registry/view.tsx",
    "third_party.feedback_graph.top_five_rater_share": "registry/view.tsx",
    "third_party.feedback_graph.anchored": "registry/view.tsx",
    "third_party.feedback_graph.with_comment": "registry/view.tsx",
    "third_party.feedback_graph.declaring_a_method": "registry/view.tsx",
    "third_party.feedback_graph.declaring_known_defects": "registry/view.tsx",
    "third_party.feedback_graph.uris_decoded": "registry/view.tsx",
    "third_party.feedback_graph.revoked": "registry/view.tsx",
    "third_party.feedback_graph.note": "registry/view.tsx",
    "third_party.feedback_graph.by_agent": "ScanAgents.tsx",
    "third_party.feedback_graph.top_rater_rows": "",
    "third_party.feedback_graph.tags": "",
    "third_party.feedback_graph.methods": "",
    "third_party.feedback_graph.decode_failures": "",
    "third_party.feedback_graph.parse_status": "",
    "third_party.feedback_graph.pages_failed": "",
    "third_party.feedback_graph.failure_reasons": "",
    "third_party.feedback_graph.by_agent_held": "",
    "third_party.feedback_graph.by_agent_published": "",
    "third_party.feedback_graph.by_agent_note": "",
    "third_party.feedback_graph.read_at": "",
    "third_party.feedback_graph.tier": "",
    "third_party.feedback_graph.chain_id": "",
    # The feedback table's own total, and the two comparisons it feeds.
    "third_party.feedback_reach.available": "",
    "third_party.feedback_reach.feedbacks": "",
    "third_party.feedback_reach.anchored": "",
    "third_party.feedback_reach.example_transaction_hash": "",
    "third_party.feedback_reach.example_block_number": "",
    "third_party.feedback_reach.chain_id": "",
    "third_party.feedback_reach.tier": "",
    "third_party.feedback_reach.note": "",
    "third_party.feedback_cross_check.available": "registry/view.tsx",
    "third_party.feedback_cross_check.summed_over_agents": "registry/view.tsx",
    "third_party.feedback_cross_check.counted_in_feedback_table": "registry/view.tsx",
    "third_party.feedback_cross_check.difference": "registry/view.tsx",
    "third_party.feedback_cross_check.agree": "registry/view.tsx",
    "third_party.feedback_cross_check.note": "registry/view.tsx",
    "third_party.agents_with_feedback_three_ways.available": "registry/view.tsx",
    "third_party.agents_with_feedback_three_ways.readings": "registry/view.tsx",
    "third_party.agents_with_feedback_three_ways.low": "registry/view.tsx",
    "third_party.agents_with_feedback_three_ways.high": "registry/view.tsx",
    "third_party.agents_with_feedback_three_ways.spread": "registry/view.tsx",
    "third_party.agents_with_feedback_three_ways.agree": "registry/view.tsx",
    "third_party.agents_with_feedback_three_ways.note": "registry/view.tsx",
    # The chain-wide ranking.
    "third_party.leaderboard.available": "ScanAgents.tsx",
    "third_party.leaderboard.note": "ScanAgents.tsx",
    "third_party.leaderboard.read_at": "",
    "third_party.leaderboard.tier": "",
    "third_party.leaderboard.chain_id": "",
    # A name is not an identity.
    "third_party.name_collisions.available": "ScanAgents.tsx",
    "third_party.name_collisions.names": "ScanAgents.tsx",
    "third_party.name_collisions.note": "ScanAgents.tsx",
    "third_party.name_collisions.read_at": "",
    "third_party.name_collisions.tier": "",
    "third_party.name_collisions.chain_id": "",
    # Our own four, read back from an index we do not run.
    "third_party.ours_as_indexed.available": "IndexedAgreement.tsx",
    "third_party.ours_as_indexed.agents": "IndexedAgreement.tsx",
    "third_party.ours_as_indexed.owner": "IndexedAgreement.tsx",
    "third_party.ours_as_indexed.population": "IndexedAgreement.tsx",
    "third_party.ours_as_indexed.indexed_contract": "IndexedAgreement.tsx",
    "third_party.ours_as_indexed.note": "IndexedAgreement.tsx",
    "third_party.ours_as_indexed.read_at": "",
    "third_party.ours_as_indexed.tier": "",
    "third_party.ours_as_indexed.chain_id": "",
    "third_party.ours_cross_check.available": "IndexedAgreement.tsx",
    "third_party.ours_cross_check.matched": "IndexedAgreement.tsx",
    "third_party.ours_cross_check.recorded": "IndexedAgreement.tsx",
    "third_party.ours_cross_check.indexed": "IndexedAgreement.tsx",
    "third_party.ours_cross_check.recorded_only": "IndexedAgreement.tsx",
    "third_party.ours_cross_check.indexed_only": "IndexedAgreement.tsx",
    "third_party.ours_cross_check.same_contract": "IndexedAgreement.tsx",
    "third_party.ours_cross_check.agreements": "IndexedAgreement.tsx",
    "third_party.ours_cross_check.disagreements": "IndexedAgreement.tsx",
    "third_party.ours_cross_check.honest_negatives": "IndexedAgreement.tsx",
    "third_party.ours_cross_check.note": "IndexedAgreement.tsx",
    "third_party.ours_cross_check.owner": "",
    "third_party.ours_cross_check.chain_id": "",
}

THIRD_PARTY_FIELDS.update(
    {
        f"third_party.categories.{category}.{field}": renderer
        for category in _CATEGORIES
        for field, renderer in _CATEGORY_SHAPE.items()
    }
)
THIRD_PARTY_FIELDS.update(
    {
        f"third_party.{block}.filters.{name}.{field}": renderer
        for block in ("counts", "counts_testnet")
        for name in _FILTERS
        for field, renderer in _PROVEN_COUNT_SHAPE.items()
    }
)
THIRD_PARTY_FIELDS.update(
    {
        f"third_party.{block}.filters.{name}.{field}": renderer
        for block in ("counts", "counts_testnet")
        for name in _FILTERS_WITH_COMPLEMENT
        for field, renderer in _COMPLEMENT_SHAPE.items()
    }
)
THIRD_PARTY_FIELDS.update(
    {
        f"third_party.leaderboard.by.{key}.{field}": renderer
        for key in _SORTS
        for field, renderer in _PROVEN_SORT_SHAPE.items()
    }
)
THIRD_PARTY_FIELDS.update(
    {
        f"third_party.ours_as_indexed.filter_proof.{field}": renderer
        for field, renderer in _PROVEN_COUNT_SHAPE.items()
        if field not in {"available", "tier"}
    }
)


@pytest.fixture(scope="module")
def registry_artifact() -> dict:
    path = ARTIFACTS / "registry.json"
    if not path.exists():
        pytest.skip("no registry artifact; run `make registry`")
    return json.loads(path.read_text())


def test_the_scan_emitter_writes_exactly_the_contracted_third_party_fields(
    registry_artifact: dict,
) -> None:
    """Both directions, for the block the pro key tripled in size.

    An emitter field with no entry here is a number reaching an artifact nobody
    decided to publish; an entry with no field is a view reading `undefined`.
    """
    actual = {p for p in flatten(registry_artifact) if p.startswith("third_party.")}
    declared = set(THIRD_PARTY_FIELDS)

    undeclared = actual - declared
    undelivered = declared - actual

    assert not undeclared, (
        "the 8004scan emitter writes fields the contract does not declare — add them "
        f"to THIRD_PARTY_FIELDS and render them, or stop emitting them: {sorted(undeclared)}"
    )
    assert not undelivered, (
        "the contract declares third-party fields the emitter no longer writes; a view "
        f"is reading something that will be undefined: {sorted(undelivered)}"
    )


def test_every_contracted_third_party_field_is_read_by_the_named_view() -> None:
    """A renderer named against a field must actually mention it."""
    sources = _sources()
    missing: list[str] = []
    for path, renderer in THIRD_PARTY_FIELDS.items():
        if not renderer:
            continue
        source = sources.get(renderer)
        assert source is not None, f"{renderer} does not exist"
        leaf = path.split(".")[-1]
        if leaf not in strip_comments(source):
            missing.append(f"{path} -> {renderer}")
    assert not missing, (
        f"contracted third-party fields are not read by the view named against them: {missing}"
    )


# ── the rest of registry.json, which had no contract at all ──────────────────
#
# `THIRD_PARTY_FIELDS` above covers the block the pro key tripled in size. This
# covers everything else on the page — the hire flow, the AACP snapshot, the
# ERC-8004 survey and our own registrations — none of which was contracted
# before, so any of it could be renamed or dropped and no test would notice.
#
# Six containers are OPAQUE because their keys are data: chain ids, Solidity
# signatures, contract names. The rest is declared, and the empty strings are
# the interesting entries — each one is a field the emitter writes deliberately
# and no view draws, with the reason on the line above it.

#: One Wilson interval. Six shares carry one, and a share published without one
#: is the false precision this project is named against — at n=400 a 35%
#: substantive share spans 30% to 40%, which is a different claim from "35%".
_INTERVAL_SHARES = (
    "resolvable",
    "with_endpoint",
    "placeholders",
    "declared_active",
    "on_chain_cards",
    "substantive",
)

REGISTRY_FIELDS: dict[str, str] = {
    # The hire flow: seven transactions across three contracts, five signed by
    # the client. Entirely offline, so it always renders.
    "hire_flow.steps": "registry/view.tsx",
    "hire_flow.states": "registry/view.tsx",
    "hire_flow.terminal_states": "registry/view.tsx",
    "hire_flow.transaction_count": "registry/view.tsx",
    "hire_flow.client_transaction_count": "registry/view.tsx",
    "hire_flow.escrow.available": "registry/view.tsx",
    "hire_flow.escrow.address": "registry/view.tsx",
    "hire_flow.escrow.evidence": "registry/view.tsx",
    # Both rendered, and neither can be named here. The page looks these up by
    # chain id — `d.hire_flow_contracts?.[chainId]` — so the leaf is `56` and
    # `97`, and this guard matches leaves as literal strings. `"56"` happens to
    # appear in that file for unrelated reasons and `"97"` does not, which would
    # make one pass and one fail for no reason connected to either. Left
    # unnamed, with the limitation stated rather than worked around.
    "hire_flow_contracts.56": "",
    "hire_flow_contracts.97": "",
    # TermiX's published table, recorded to be checked against.
    "aacp.available": "registry/view.tsx",
    "aacp.contracts": "registry/view.tsx",
    # Emitted and not drawn. `escrow_selectors` carries the summary the page
    # does render — 21 of 65 resolved, counted rather than guessed — and the
    # signature-by-signature table underneath it has never had a surface.
    "aacp.escrow_interface": "",
    "aacp.escrow_selectors.resolved": "registry/view.tsx",
    "aacp.escrow_selectors.total": "registry/view.tsx",
    "aacp.escrow_selectors.note": "registry/view.tsx",
    # Two of the strongest findings in this artifact, and no view reads either:
    # that TermixEscrow implements none of ERC-8183's seven calls across 5,894
    # candidate signatures, and that `orders(bytes32)` returns 13 words of which
    # exactly one is decoded. Contracted as unrendered so the gap is recorded
    # rather than merely true.
    "aacp.not_erc8183": "",
    "aacp.order_decode": "",
    "aacp.shares_our_identity_registry": "registry/view.tsx",
    "aacp.note": "registry/view.tsx",
    "aacp.chain_id": "",
    # The on-chain survey: 400 ids, six shares, six intervals.
    "identity.surveyed": "registry/view.tsx",
    "identity.population": "registry/view.tsx",
    "identity.sampled": "registry/view.tsx",
    "identity.agents": "registry/view.tsx",
    "identity.listings_shown": "registry/view.tsx",
    "identity.resolvable": "registry/view.tsx",
    "identity.with_endpoint": "registry/view.tsx",
    "identity.placeholders": "registry/view.tsx",
    "identity.declared_active": "registry/view.tsx",
    "identity.on_chain_cards": "registry/view.tsx",
    "identity.substantive": "registry/view.tsx",
    "identity.substantive_share": "registry/view.tsx",
    "identity.reputation_note": "registry/view.tsx",
    "identity.identity_registry": "registry/view.tsx",
    "identity.reputation_registry": "registry/view.tsx",
    # Reproducibility, not display. `sampled_ids` is 400 integers and `seed` is
    # what regenerates them — together they let a reader re-run the survey and
    # get the same 400 agents, which is the difference between a survey that is
    # reported and one that is reproducible. Rendering them would be 400
    # integers on a page.
    "identity.sampled_ids": "",
    "identity.seed": "",
    "identity.sampled_at_block": "",
    # Our own registrations, self-reported. Read back from an index in
    # `IndexedAgreement.tsx`; this is the file half.
    "ours.surveyed": "registry/view.tsx",
    "ours.agents": "registry/view.tsx",
    "ours.checks": "registry/view.tsx",
    "ours.verdict": "registry/view.tsx",
    "ours.summary.checked": "registry/view.tsx",
    "ours.summary.registered": "registry/view.tsx",
    # `checked` and `registered` render; these two do not. On the recorded run
    # both are zero, which is exactly when an unrendered failure count is
    # hardest to notice and most misleading if it ever stops being zero.
    "ours.summary.failed": "",
    "ours.summary.unknown": "",
    "ours.owner": "registry/view.tsx",
    "ours.registry": "registry/view.tsx",
    "ours.chain_id": "registry/view.tsx",
    "ours.explorer": "registry/view.tsx",
    # How stale the recorded reading is. Computed by the emitter on every build
    # and drawn nowhere, so the page presents a reading of unknown age as
    # current.
    "ours.age_hours": "",
    "ours.record": "registry/view.tsx",
    # The funding transaction that made the registrations possible, and the
    # block they landed in. Recorded so the record is checkable rather than
    # merely stated; the page names the explorer and lets a reader go there.
    "ours.funding.amount": "",
    "ours.funding.from": "",
    "ours.funding.to": "",
    "ours.funding.tx": "",
    "ours.funding.url": "",
    "ours.block": "",
    "ours.implementation": "",
    "ours.signer": "",
    "ours.read_at": "",
    "ours.reason": "",
    # Per-artifact provenance. Read by `go_no_go.check_artifact_freshness` in
    # the terminal, and by nothing on this page — no view in `apps/web/src`
    # mentions `git_sha` or `generated_at` at all. `RegistryArtifact` still
    # declares `build?: Build` with a comment saying the page "showed none of
    # it", which was written as a correction and is currently true again.
    #
    # Contracted as unrendered rather than pointed at a file that does not read
    # it, because a renderer named here and not delivering is the defect this
    # pair of tests exists to catch, and pointing at one to make a map look
    # complete is how that defect gets written down as done.
    "build.command": "",
    "build.source": "",
    "build.generated_at": "",
    "build.git_sha": "",
    "build.git_dirty": "",
}

REGISTRY_FIELDS.update(
    {
        f"identity.intervals.{share}.{bound}": "ShareIntervals.tsx"
        for share in _INTERVAL_SHARES
        for bound in ("low", "high")
    }
)


def test_the_registry_emitter_writes_exactly_the_contracted_fields(
    registry_artifact: dict,
) -> None:
    """The whole artifact, not just the block this feature touched.

    `registry.json` is the largest artifact this site fetches and it was the
    only one with no contract at all — 97 leaves outside `third_party` that
    could be renamed or dropped with nothing to notice. Both directions, as
    everywhere else.
    """
    actual = {p for p in flatten(registry_artifact) if not p.startswith("third_party")}
    declared = set(REGISTRY_FIELDS)

    undeclared = actual - declared
    undelivered = declared - actual

    assert not undeclared, (
        "the registry emitter writes fields the contract does not declare — add them "
        f"to REGISTRY_FIELDS and render them, or stop emitting them: {sorted(undeclared)}"
    )
    assert not undelivered, (
        "the contract declares registry fields the emitter no longer writes; a view is "
        f"reading something that will be undefined: {sorted(undelivered)}"
    )


def test_every_contracted_registry_field_is_read_by_the_named_view() -> None:
    sources = _sources()
    missing: list[str] = []
    for path, renderer in REGISTRY_FIELDS.items():
        if not renderer:
            continue
        source = sources.get(renderer)
        assert source is not None, f"{renderer} does not exist"
        leaf = path.split(".")[-1]
        if leaf not in strip_comments(source):
            missing.append(f"{path} -> {renderer}")
    assert not missing, (
        f"contracted registry fields are not read by the view named against them: {missing}"
    )
