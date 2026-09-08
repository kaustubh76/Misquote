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
        # Which agents have ever written a journal, which is data: an agent
        # that runs tomorrow appears, and one that never ran is absent rather
        # than present-and-empty. The *shape* of each entry is schema and is
        # asserted separately by
        # `test_every_journal_entry_carries_the_summary_the_page_reads`.
        "agents",
        # Keyed by chain id, by Solidity signature, and by contract name
        # respectively — data in all three cases. `aacp.escrow_interface`'s keys
        # are literally `acceptOrder(bytes32)`; contracting those would make
        # this test a snapshot of somebody else's ABI.
        "hire_flow_contracts.56",
        "hire_flow_contracts.97",
        # Keyed by four-byte revert selector, which is the chain's vocabulary
        # rather than ours — contracting these would make this test a snapshot
        # of somebody else's custom errors, and a deployment that adds one would
        # fail a test about our schema.
        "hire_flow.errors",
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
    "source": "AgentCard.tsx",  # `provenance.build_stamp` calls this required: "chain" and
    # "synthetic" are not two qualities of one result, they are two claims,
    # "and the UI is required to say which one it is showing". It stopped
    # saying when `SourceBanner` was deleted.
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
    # Declared the day it was predicted. The note that stood here said a card
    # is a four-hour replay and regenerating one to add a field is a compute
    # budget rather than a rendering decision — and that the test would fail
    # the day anyone ran `make showcase`. Somebody did.
    "quote_detail.perturbation_fraction": "methods/view.tsx",
    "quote_detail.perturbations": "AgentDetail.tsx",
    "quote_detail.net_positive": "AgentDetail.tsx",
    "quote_detail.returns": "AgentCard.tsx",
    "quote_detail.in_range_p50": "methods/view.tsx",
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
    "activity.decisions": "AgentDetail.tsx",
    "activity.hours": "AgentDetail.tsx",
    "activity.mints": "AgentDetail.tsx",
    "activity.rebalances": "AgentDetail.tsx",
    "activity.pulls": "AgentDetail.tsx",
    "activity.executed": "AgentDetail.tsx",
    "activity.failed": "AgentDetail.tsx",
    "activity.dropped": "AgentDetail.tsx",
    "activity.read_errors": "AgentDetail.tsx",
    "activity.held_by_gate": "GateHistogram.tsx",
    # Where the live loop's numbers came from, and whether there are any.
    #
    # Both were unrendered on the reasoning that the site states what the
    # numbers are rather than how the run was bookkept. That held until it
    # turned out two of the three agents have no run at all: `journal_rows` is
    # the only field that separates a loop which held on every decision from a
    # loop that never started, and the card was rendering the second as the
    # first. It is the discriminator now, and `journal` is the path the refusal
    # names so the absence is checkable rather than asserted.
    "provenance.journal": "AgentDetail.tsx",
    "provenance.journal_rows": "AgentDetail.tsx",
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
    "advantage.material": "AgentDetail.tsx",
    "advantage.ranges_overlap": "AgentCard.tsx",
    "advantage.separated": "AgentDetail.tsx",
    "advantage.quotable": "AgentCard.tsx",
    "advantage.verdict": "AgentCard.tsx",
    "advantage.without_agent": "AgentDetail.tsx",
    "advantage.baseline.p25": "AgentCard.tsx",
    "advantage.baseline.p50": "AgentCard.tsx",
    "advantage.baseline.p75": "AgentCard.tsx",
    "advantage.baseline.in_range_fraction": "AgentDetail.tsx",
    "advantage.baseline.fees_quote": "AgentDetail.tsx",
    "advantage.baseline.lvr_quote_upper_bound": "AgentDetail.tsx",
    "advantage.baseline.costs_quote": "AgentDetail.tsx",
    "advantage.baseline.moves": "AgentDetail.tsx",
    # Per-card provenance. Read by `scripts/go_no_go.py`'s
    # `check_artifact_freshness`, which asks whether a published card still
    # describes the engine that exists and answers UNVERIFIED for any artifact
    # recording no commit. Every card recorded none until this block was added:
    # they were stamped by proxy through `build.json`, so the gate could not go
    # green and its own stated remedy — regenerate them — could not clear it.
    #
    # None of them renders. The contradiction they were surfaced for — this card
    # and `/advantage` scoring the same replay from runs nine engine commits
    # apart, one saying Warden beats DIY by 17.21pp and the other that it loses
    # by 64.29pp — is still caught by `tests/web/test_artifact_agreement.py`,
    # which fails on the state itself rather than printing a sha at a reader.
    # Which tape a number came from is still answered where a reader asks it, by
    # `TapeSource` beside the number.
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
    "source": "RouterCard.tsx",
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
    # Per-card provenance, read by `go_no_go.check_artifact_freshness` and now
    # by the page. Router's card and the advantage report publish the same
    # comparison from separate runs — `make router-card` against `make
    # advantage` — so the two can drift apart with nothing on either saying so.
    # See the longer note in `AGENT_FIELDS`.
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
    """Both directions. Neither side may move without the other noticing.

    ## If this is failing on fields you have never seen

    The emitters gained five on 8 Sep and the artifacts they write are a
    multi-hour rebuild, so the two halves land at different times. After
    `make artifacts` this will report them as undeclared; they are all real and
    all rendered, and the map wants:

        "quote_detail.worst_return":     "AgentCard.tsx"
        "quote_detail.best_return":      "AgentCard.tsx"
        "quote_detail.distinct_returns": "AgentCard.tsx"
        "replay.first_ts":               "AgentCard.tsx"
        "replay.last_ts":                "AgentCard.tsx"
        "advantage.beat_rate.*":         "AgentCard.tsx"

    They are not declared here yet on purpose: this assertion fails just as
    loudly for a field declared and *not* delivered, and pre-declaring them
    would have left the suite red for everyone until somebody found eleven
    hours."""
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
    """Every module a field could be read by, keyed by name and by parent/name.

    `.ts` as well as `.tsx`. This globbed only `.tsx`, which was fine while
    every artifact field was consumed in a component — and stopped being fine
    when the escrow flow's chain logic moved into `useEscrowFlow.ts` so that the
    guided hire and the raw console could share one implementation. A renderer
    named against a `.ts` module resolved to `None` and the check asserted the
    file did not exist, which was the guard being blind rather than the field
    being unread.
    """
    files = [*WEB_SRC.rglob("*.tsx"), *WEB_SRC.rglob("*.ts")]
    return {p.name: p.read_text() for p in files} | {
        f"{p.parent.name}/{p.name}": p.read_text() for p in files
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
    return strip_milliseconds(strip_image_metadata(strip_motion_easing(source)))


def strip_milliseconds(source: str) -> str:
    """Remove the seconds-to-milliseconds conversion, which is a unit.

    Fourth in the family, and the collision is the same shape as the OpenGraph
    one. `docs/REQUIREMENTS_MATRIX.md` carries a `±1000 ticks` row, which reaches
    `assumptions.json` and therefore the forbidden set; `lib/stream.ts` declares
    `const SECOND_MS = 1000` and `AgentJournal.tsx` does `new Date(ts * 1000)`
    because a unix timestamp is in seconds and `Date` wants milliseconds. Two
    unrelated meanings, one value.

    Structural rather than numeric, for the reason `strip_image_metadata` gives:
    adding `1000` to `UNDISTINCTIVE` would blind this guard to a real 1,000 —
    a tick width, an agent count, a block span — on every page, permanently, to
    settle one collision with a constant that is not a quantity at all.

    Deliberately narrow. It matches the conversion *idiom*: a `SECOND_MS`-style
    declaration, and `* 1000` / `/ 1000` in an expression. A component that
    renders `1000` as text still fails, which is the case worth catching.
    """
    source = re.sub(r"\b\w*(?:SECOND|SECS?)_MS\w*\s*=\s*1000\b", "", source)
    source = re.sub(r"[*/]\s*1000\b", "", source)
    return source


def strip_motion_easing(source: str) -> str:
    """Remove `ease: [...]`, which is a cubic-bezier curve and not a number.

    Fourth in the family, and it arrived the way the third did. The journal
    summary started publishing a duration rounded to two decimals, sentinel's
    came out `0.16`, and `CompareTray.tsx` animates with
    `ease: [0.16, 1, 0.3, 1]` — the control points of an easing curve, which is
    the same four numbers every Framer Motion codebase has.

    Structural rather than adding `0.16` to `UNDISTINCTIVE`, for the reason
    `strip_image_metadata` gives at length: an allowlist entry blinds this guard
    to a real 0.16 on every page forever, to fix a collision that moves the next
    time any agent runs for a slightly different length of time. A bezier
    coefficient is never rendered to a reader, so removing it blinds nothing.

    Narrow on purpose: the `ease` key and its array, nothing else on the
    transition. A `duration` that matched an artifact value would still fail.
    """
    return re.sub(r"\bease:\s*\[[^\]]*\]", "", source)


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
        # The Open Graph card, for the same reason and a narrower one. It is a
        # build-time image generator: it reads no artifact, its copy is fixed,
        # and every number in it is a pixel dimension or a font size fed to
        # `next/og`. `studio.json` publishing a 900-second quote TTL collided
        # with its `maxWidth: 900`, which is a share card's text column and
        # cannot be a restatement of anything.
        #
        # Excluded here rather than by adding 900 to `UNDISTINCTIVE`, because
        # that set is global: 900 is a plausible figure for an artifact to
        # publish and a page to smuggle, and silencing it everywhere to fix one
        # layout constant is the move this test's own docstring warns about. One
        # file that renders no data is the smaller hole.
        if path.name == "opengraph-image.tsx":
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
    "third_party.feedback_reach.available": "registry/view.tsx",
    # Not missing from the page — it arrives through `feedback_cross_check`,
    # which is where it earns its keep, compared against the sum over agent
    # rows. Drawing it a second time under this block would put one number on
    # the page twice under two names, which is the shape of a disagreement —
    # and there is none here: this route and the walk agree exactly, which is
    # the finding, not a defect to draw.
    "third_party.feedback_reach.feedbacks": "",
    "third_party.feedback_reach.anchored": "registry/view.tsx",
    "third_party.feedback_reach.example_transaction_hash": "registry/view.tsx",
    "third_party.feedback_reach.example_block_number": "registry/view.tsx",
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
    # TermiX's own agent count, and ours read in the same build.
    #
    # Declared unrendered because their consumer is not a page: `sync_docs.py`'s
    # `explorer_block` turns them into the `<!-- derived:explorer -->` table in
    # `FOR_JUDGES.md`. That is the whole reason they are emitted — the document
    # published 304,790 as prose, with no constant and no function behind it, and
    # by the time anyone looked again it read 320,243.
    #
    # `withheld_fields` and `withheld_reason` are the opposite of a gap: the
    # explorer returns `reputationScore` / `passRate` / `onTimeRate`, this
    # repository refuses to publish a reputation score, and naming what was
    # received and declined is a stronger claim than silently not fetching it.
    "aacp.explorer_agents.read": "",
    "aacp.explorer_agents.path": "",
    "aacp.explorer_agents.total": "",
    "aacp.explorer_agents.page_size": "",
    "aacp.explorer_agents.total_pages": "",
    "aacp.explorer_agents.sort_order": "",
    "aacp.explorer_agents.ours": "",
    "aacp.explorer_agents.ours_at_block": "",
    "aacp.explorer_agents.gap": "",
    "aacp.explorer_agents.gap_note": "",
    "aacp.explorer_agents.withheld_fields": "",
    "aacp.explorer_agents.withheld_reason": "",
    "hire_flow.errors": "registry/view.tsx",
    "hire_flow.recourse": "registry/view.tsx",
    "hire_flow.proof.ran": "registry/view.tsx",
    "hire_flow.proof.job_id": "registry/view.tsx",
    "hire_flow.proof.escrowed": "registry/view.tsx",
    "hire_flow.proof.mined": "registry/view.tsx",
    "hire_flow.proof.reverted": "registry/view.tsx",
    "hire_flow.proof.not_escrowed_because": "registry/view.tsx",
    "hire_flow.proof.transactions": "registry/view.tsx",
    # The fork run, which is a different claim and says so in every consumer's
    # reach. `escrowed` on the chapel record is false and on this one is true,
    # and the only thing keeping those apart is that `network` is rendered
    # beside them — so it is contracted to a view rather than left as data.
    "hire_flow.fork_proof.ran": "registry/view.tsx",
    "hire_flow.fork_proof.network": "registry/view.tsx",
    "hire_flow.fork_proof.escrowed": "registry/view.tsx",
    "hire_flow.fork_proof.settled": "registry/view.tsx",
    "hire_flow.fork_proof.job_id": "registry/view.tsx",
    "hire_flow.fork_proof.escrowed_on_mainnet": "registry/view.tsx",
    "hire_flow.fork_proof.why_not_on_mainnet": "registry/view.tsx",
    # The claims these two records used to make, kept beside the ones that
    # replaced them. Both said the payment token could not be obtained; a
    # PancakeSwap swap falsified both, and deleting the sentence would erase
    # the correction along with the error. Carried, not rendered — a reader
    # wanting the history has the record; a page showing both would be showing
    # a retracted claim at the same weight as a true one.
    "hire_flow.fork_proof.why_not_on_mainnet_was": "",
    "hire_flow.proof.not_escrowed_because_was": "",
    "hire_flow.fork_proof.transactions": "registry/view.tsx",
    # ── what stays unrendered under hire_flow, and why ──────────────────────
    #
    # 74 of this block's 145 fields were `""` — half of everything the hire
    # flow emits, including both parties to every hire, on the page a
    # marketplace is judged from. `HireParties.tsx` took 21 of them. What is
    # left is not a backlog; it falls into four groups, each of which is
    # *better* unrendered:
    #
    #   `addresses.*` (16) — the kernel, router, policy and token, repeated on
    #       every proof. `deployments` publishes the same four per chain and the
    #       page renders those. A second copy is a second thing to be wrong, and
    #       the wrong one would be the one people send money to.
    #   `job_words` (4) — the raw 32-byte words `getJob` returned. The reading
    #       is what a reader wants; the ABI encoding behind it is what
    #       `lib/escrow.ts` and its tests are for.
    #   `*_was` (2), `record` (5) — superseded prose kept as history, and paths
    #       to files under `vetting/` that the static export does not serve. A
    #       link a reader cannot follow is worse than no link.
    #   redundant siblings — `expires_at` beside the rendered `expires_at_utc`,
    #       `job_exists` beside the job id it echoes, `dispute_window_s` beside
    #       the settle date computed from it, `balance_before`/`balance_after`
    #       beside the `recovered` difference that is the actual claim.
    #
    # The fork's own bookkeeping, carried and not rendered for the same reason
    # the chapel run's is.
    "hire_flow.fork_proof.forked_from": "",
    "hire_flow.fork_proof.forked_at_block": "",
    "hire_flow.fork_proof.chain_id": "registry/view.tsx",
    "hire_flow.fork_proof.client": "HireParties.tsx",
    "hire_flow.fork_proof.provider": "HireParties.tsx",
    "hire_flow.fork_proof.evaluator": "",
    "hire_flow.fork_proof.token_owner": "",
    "hire_flow.fork_proof.minted_to_client": "",
    "hire_flow.fork_proof.budget": "HireParties.tsx",
    "hire_flow.fork_proof.dispute_window_s": "",
    "hire_flow.fork_proof.gas_spent_wei": "HireParties.tsx",
    "hire_flow.fork_proof.job_words": "",
    "hire_flow.fork_proof.record": "",
    "hire_flow.fork_proof.success_criterion": "HireParties.tsx",
    "hire_flow.fork_proof.addresses.kernel": "",
    "hire_flow.fork_proof.addresses.router": "",
    "hire_flow.fork_proof.addresses.policy": "",
    "hire_flow.fork_proof.addresses.erc20": "",
    # The mainnet run — a third record, and the one that cost money. The four
    # fields a reader needs to tell it from the fork are contracted to the view;
    # the rest is the run's own bookkeeping, carried and not rendered.
    "hire_flow.mainnet_proof.addresses.erc20": "",
    "hire_flow.mainnet_proof.addresses.kernel": "",
    "hire_flow.mainnet_proof.addresses.policy": "",
    "hire_flow.mainnet_proof.addresses.router": "",
    # Seeds the console's budget field, so the page opens on a figure this
    # repository has actually spent rather than a round number in a component.
    "hire_flow.mainnet_proof.budget": "components/EscrowConsole.tsx",
    # Read, though not displayed: `readHireTerms` uses it to pick which
    # deployment's `decimals()` scales the opening escrow, because the budget it
    # formats is the one that hire escrowed. Declared here rather than left at
    # "" — the unrendered check happens to skip `chain_id` because the leaf name
    # is not unique across the maps, and leaning on that blind spot is how a
    # contract stops describing the code.
    "hire_flow.mainnet_proof.chain_id": "lib/build-artifact.ts",
    "hire_flow.mainnet_proof.client": "HireParties.tsx",
    "hire_flow.mainnet_proof.escrowed": "registry/view.tsx",
    "hire_flow.mainnet_proof.escrowed_on_mainnet": "",
    "hire_flow.mainnet_proof.evaluator": "",
    "hire_flow.mainnet_proof.gas_spent_wei": "HireParties.tsx",
    "hire_flow.mainnet_proof.job_exists": "",
    "hire_flow.mainnet_proof.job_id": "registry/view.tsx",
    "hire_flow.mainnet_proof.job_words": "",
    "hire_flow.mainnet_proof.network": "registry/view.tsx",
    "hire_flow.mainnet_proof.provider": "HireParties.tsx",
    "hire_flow.mainnet_proof.ran": "registry/view.tsx",
    "hire_flow.mainnet_proof.record": "",
    "hire_flow.mainnet_proof.settled": "registry/view.tsx",
    "hire_flow.mainnet_proof.success_criterion": "HireParties.tsx",
    #: What `submit`'s 32 bytes commit to, and null on every record so far.
    #: Job 56681's `submit` reverted `SubmissionTooLate()` and never sent any,
    #: which is why `HireParties` is told whether the call mined rather than
    #: guessing from the absence — the same distinction the block draws on
    #: screen.
    "hire_flow.mainnet_proof.deliverable.file": "HireParties.tsx",
    "hire_flow.mainnet_proof.deliverable.bytes": "HireParties.tsx",
    "hire_flow.mainnet_proof.deliverable.keccak256": "HireParties.tsx",
    "hire_flow.mainnet_proof.deliverable.url": "HireParties.tsx",
    #: `hire_mainnet.py`'s own label, contracted so the field cannot appear
    #: undeclared the first time a two-party run writes one. Deliberately
    #: unrendered: `HireParties` decides distinctness from the two addresses,
    #: because `hire-fork-56.json` has had two of them since before this flag
    #: existed and a page reading the label would call that run a self-hire.
    #: `tests/registry/test_two_party_hire.py` is where the label is held to
    #: the addresses, which is the right place for a claim about a fact.
    "hire_flow.mainnet_proof.two_party": "",
    "hire_flow.mainnet_proof.transactions": "registry/view.tsx",
    # The refund. A fourth record and the only one about money coming back,
    # rendered under the fork block because it is one until the mainnet clock
    # passes `expiredAt`. Its hash is carried and deliberately not linked — a
    # fork transaction is not on any explorer, and rendering it as a link would
    # be the misquote in miniature.
    # Why a record is not here, when it is not. An absence carries every key a
    # presence carries — see `_published_record` — so this renders instead of
    # the block vanishing, which is the difference between "not run" and
    # "never existed".
    "hire_flow.proof.reason": "registry/view.tsx",
    "hire_flow.fork_proof.reason": "registry/view.tsx",
    "hire_flow.mainnet_proof.reason": "registry/view.tsx",
    "hire_flow.refund_proof.reason": "registry/view.tsx",
    # The run where `submit` mined. Job 56681 asked for twelve hours and was
    # refused; this one asked for 192 and was not, which is the entire
    # difference and the reason it is published beside rather than instead.
    "hire_flow.submit_proof.ran": "registry/view.tsx",
    "hire_flow.submit_proof.network": "registry/view.tsx",
    "hire_flow.submit_proof.job_id": "registry/view.tsx",
    "hire_flow.submit_proof.submitted": "registry/view.tsx",
    "hire_flow.submit_proof.settled": "registry/view.tsx",
    "hire_flow.submit_proof.escrowed": "registry/view.tsx",
    "hire_flow.submit_proof.expires_at_utc": "registry/view.tsx",
    "hire_flow.submit_proof.settle_earliest_utc": "registry/view.tsx",
    "hire_flow.submit_proof.why_settle_reverted": "registry/view.tsx",
    "hire_flow.submit_proof.what_this_run_changes": "registry/view.tsx",
    "hire_flow.submit_proof.transactions": "registry/view.tsx",
    # Its own bookkeeping, carried for the same reason its siblings' is.
    "hire_flow.submit_proof.reason": "",
    "hire_flow.submit_proof.record": "",
    "hire_flow.submit_proof.budget": "HireParties.tsx",
    "hire_flow.submit_proof.chain_id": "registry/view.tsx",
    "hire_flow.submit_proof.client": "HireParties.tsx",
    "hire_flow.submit_proof.provider": "HireParties.tsx",
    "hire_flow.submit_proof.evaluator": "",
    "hire_flow.submit_proof.expires_at": "",
    "hire_flow.submit_proof.dispute_window_s": "",
    "hire_flow.submit_proof.escrowed_on_mainnet": "",
    "hire_flow.submit_proof.gas_spent_wei": "HireParties.tsx",
    "hire_flow.submit_proof.job_exists": "",
    "hire_flow.submit_proof.job_words": "",
    "hire_flow.submit_proof.success_criterion": "HireParties.tsx",
    #: What `submit`'s 32 bytes commit to. Job 56718 is the one run whose
    #: `submit` mined, and it sent `keccak256("job-56718")` — a hash of the
    #: job's own id, which commits to no file. `--deliverable-file` writes these
    #: fields, and `HireParties` renders the hash beside the file it names so a
    #: reader can fetch and re-derive it.
    "hire_flow.submit_proof.deliverable.file": "HireParties.tsx",
    "hire_flow.submit_proof.deliverable.bytes": "HireParties.tsx",
    "hire_flow.submit_proof.deliverable.keccak256": "HireParties.tsx",
    "hire_flow.submit_proof.deliverable.url": "HireParties.tsx",
    #: `hire_mainnet.py`'s own label, contracted so the field cannot appear
    #: undeclared the first time a two-party run writes one. Deliberately
    #: unrendered: `HireParties` decides distinctness from the two addresses,
    #: because `hire-fork-56.json` has had two of them since before this flag
    #: existed and a page reading the label would call that run a self-hire.
    #: `tests/registry/test_two_party_hire.py` is where the label is held to
    #: the addresses, which is the right place for a claim about a fact.
    "hire_flow.submit_proof.two_party": "",
    "hire_flow.submit_proof.addresses.kernel": "",
    "hire_flow.submit_proof.addresses.router": "",
    "hire_flow.submit_proof.addresses.policy": "",
    "hire_flow.submit_proof.addresses.erc20": "",
    "hire_flow.refund_proof.ran": "registry/view.tsx",
    "hire_flow.refund_proof.network": "registry/view.tsx",
    "hire_flow.refund_proof.job_id": "registry/view.tsx",
    "hire_flow.refund_proof.refunded": "registry/view.tsx",
    "hire_flow.refund_proof.recovered": "registry/view.tsx",
    "hire_flow.refund_proof.expires_at_utc": "registry/view.tsx",
    "hire_flow.refund_proof.status_before": "registry/view.tsx",
    "hire_flow.refund_proof.status_after": "registry/view.tsx",
    "hire_flow.refund_proof.transactions": "registry/view.tsx",
    # Its own bookkeeping, carried for the same reason the other three records
    # carry theirs: a reader who opens the JSON can check the arithmetic.
    "hire_flow.refund_proof.balance_after": "",
    "hire_flow.refund_proof.balance_before": "",
    "hire_flow.refund_proof.budget": "",
    "hire_flow.refund_proof.client": "",
    "hire_flow.refund_proof.expires_at": "",
    "hire_flow.refund_proof.gas_spent_wei": "",
    "hire_flow.refund_proof.record": "",
    # The addresses a browser needs to send any of this itself. Emitted rather
    # than typed into TypeScript because `erc8183.py` is where a deployment is
    # admitted after being read, and a second copy is a second thing to be
    # wrong — the wrong one being the address a reader sends money to.
    "hire_flow.deployments.56.kernel": "components/useEscrowFlow.ts",
    "hire_flow.deployments.56.router": "components/useEscrowFlow.ts",
    "hire_flow.deployments.56.policy": "components/useEscrowFlow.ts",
    "hire_flow.deployments.56.erc20": "components/useEscrowFlow.ts",
    # Read off chain by `verify_erc8183.py` and consumed at build time by
    # `readHireTerms`, which formats the opening escrow on an agent card.
    # It was the literal 18 in that function until the token was asked.
    "hire_flow.deployments.56.decimals": "lib/build-artifact.ts",
    "hire_flow.deployments.56.explorer": "components/EscrowConsole.tsx",
    "hire_flow.deployments.56.name": "components/EscrowConsole.tsx",
    "hire_flow.deployments.97.kernel": "components/useEscrowFlow.ts",
    "hire_flow.deployments.97.router": "components/useEscrowFlow.ts",
    "hire_flow.deployments.97.policy": "components/useEscrowFlow.ts",
    "hire_flow.deployments.97.erc20": "components/useEscrowFlow.ts",
    # Read off chain by `verify_erc8183.py` and consumed at build time by
    # `readHireTerms`, which formats the opening escrow on an agent card.
    # It was the literal 18 in that function until the token was asked.
    "hire_flow.deployments.97.decimals": "lib/build-artifact.ts",
    "hire_flow.deployments.97.explorer": "components/EscrowConsole.tsx",
    "hire_flow.deployments.97.name": "components/EscrowConsole.tsx",
    # The console keys deployments by the wallet's chain id, so the id inside
    # the entry is never read. Carried because a record that does not say which
    # chain it describes is a trap for whoever reads the JSON directly.
    "hire_flow.deployments.56.chain_id": "",
    "hire_flow.deployments.97.chain_id": "",
    # Carried in the artifact and deliberately not rendered.
    #
    # These are the run's own bookkeeping: which addresses it used, what it
    # spent, and the raw words `getJob` returned. A reader who wants them has
    # the record path; putting fifteen undecoded 32-byte words on the page would
    # be publishing bytes as though they were findings, which is the thing
    # `JOB_STRUCT_IS_UNDECODED` exists to refuse.
    "hire_flow.proof.chain_id": "registry/view.tsx",
    "hire_flow.proof.client": "HireParties.tsx",
    "hire_flow.proof.budget": "HireParties.tsx",
    "hire_flow.proof.record": "",
    "hire_flow.proof.gas_spent_wei": "HireParties.tsx",
    "hire_flow.proof.job_exists": "",
    "hire_flow.proof.job_words": "",
    "hire_flow.proof.success_criterion": "HireParties.tsx",
    "hire_flow.proof.addresses.kernel": "",
    "hire_flow.proof.addresses.router": "",
    "hire_flow.proof.addresses.policy": "",
    "hire_flow.proof.addresses.erc20": "",
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
    # Two of the strongest findings in this artifact, and for a long time no
    # view read either: that TermixEscrow implements none of ERC-8183's seven
    # calls across 5,894 candidate signatures, and that `orders(bytes32)`
    # returns 13 words of which exactly one is decoded. Both are prose the
    # emitter writes and the escrow card now prints them under its own rule,
    # beside `escrow_selectors.note`, which had been carrying the surface alone.
    "aacp.not_erc8183": "registry/view.tsx",
    "aacp.order_decode": "registry/view.tsx",
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
    # The level the six intervals are at. Rendered in two places — the CI label
    # on the survey table and `ShareIntervals`' spoken description — both of
    # which used to say "95%" as a literal beside bounds this repository
    # computes.
    "identity.confidence_level": "registry/view.tsx",
    "identity.identity_registry": "registry/view.tsx",
    "identity.reputation_registry": "registry/view.tsx",
    # Reproducibility. `seed` is what regenerates the draw, and rendering it
    # would put a number on the page that means nothing to a reader who is not
    # about to re-run the survey.
    #
    # The other two are rendered, and the correction is worth keeping. This
    # comment used to cover all three and argued that showing them "would be
    # 400 integers on a page" — but `/registry` shows the *count* of ids and the
    # block the sample was read at, which are one figure each and are exactly
    # the two facts that make the draw checkable. The justification was written
    # for the raw list and applied to the summary of it.
    "identity.seed": "",
    "identity.sampled_ids": "registry/view.tsx",
    "identity.sampled_at_block": "registry/view.tsx",
    # Our own registrations, self-reported. Read back from an index in
    # `IndexedAgreement.tsx`; this is the file half.
    "ours.surveyed": "registry/view.tsx",
    "ours.agents": "registry/view.tsx",
    "ours.checks": "registry/view.tsx",
    "ours.verdict": "registry/view.tsx",
    "ours.summary.checked": "registry/view.tsx",
    "ours.summary.registered": "registry/view.tsx",
    # The failing half of the same summary, which for a while did not render
    # while `checked` and `registered` did. Both are zero on the recorded run,
    # which is exactly when an unrendered failure count is hardest to notice and
    # most misleading if it ever stops being zero — so it renders at zero too,
    # rather than appearing only once there is something to report.
    "ours.summary.failed": "registry/view.tsx",
    "ours.summary.unknown": "registry/view.tsx",
    "ours.owner": "registry/view.tsx",
    "ours.registry": "registry/view.tsx",
    "ours.chain_id": "registry/view.tsx",
    "ours.explorer": "registry/view.tsx",
    # How stale the recorded reading is. Computed by the emitter on every build
    # and for several releases drawn nowhere, so the page presented a reading of
    # unknown age as current. It has never been zero on any recorded run, and
    # the card now says how old the reading is beside the verdict.
    "ours.age_hours": "registry/view.tsx",
    "ours.record": "registry/view.tsx",
    # The funding transaction that made the registrations possible, and the
    # block they landed in. Recorded so the record is checkable rather than
    # merely stated; the page names the explorer and lets a reader go there.
    "ours.funding.amount": "",
    "ours.funding.from": "",
    "ours.funding.to": "",
    "ours.funding.tx": "",
    "ours.funding.url": "",
    "ours.implementation": "",
    # Both rendered on the identity card — the block beside the reading and the
    # signer whenever it differs from the owner, which is the case worth seeing.
    "ours.block": "registry/view.tsx",
    "ours.signer": "registry/view.tsx",
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


# ── the other direction: a field declared unrendered must not be rendered ─────


#: Leaves that name a field on more than one shape, so finding one in a view
#: says nothing about which shape it came from.
#:
#: `x402_supported` is the whole list today: it is a `census` figure in
#: `third_party.census.x402_supported` and a per-agent flag in
#: `scan8004.SCAN_LISTING_KEYS`, and `ScanAgents.tsx` renders the second while
#: the contract declares the first unrendered. Both statements are true.
#:
#: Recorded rather than silently skipped, and deliberately not a general
#: allowlist: an entry here is a claim that two different artifact shapes share
#: a field name, which is a fact about the artifacts. It is not a way to quiet a
#: finding — the check below is already restricted to leaves that appear exactly
#: once across all four maps, so anything reaching this list is a collision with
#: a shape the maps do not cover at all.
#: Leaf names that mean more than one thing, so finding one proves nothing.
#:
#: `tx` is `ours.funding.tx` — carried, not rendered — and also the hash on each
#: step inside `hire_flow.refund_proof.transactions`. That second one *is*
#: rendered, and cannot be declared separately: `flatten` stops at a list, so
#: the whole array is one leaf and its members have no paths of their own. The
#: guard was right that a `.tx` is read in `registry/view.tsx`; it was reading
#: the wrong one.
#: `amount` is `ours.funding.amount` — carried, all-null, never rendered — and
#: also `tasks[].hire_cost.amount` in `advantage.json`, which `readHireTerms`
#: reads to put a fee on an agent card. Both statements are true, and it is the
#: third collision in this list to involve `ours.funding.*`.
#:
#: The cause is structural and worth naming, because it will happen again. The
#: check assumes **a renderer file corresponds to one artifact** — reasonable
#: for a component, which draws one card. `lib/build-artifact.ts` is not a view
#: at all; it is the shared build-time reader, and `readHireTerms` joins
#: `registry.json` and `advantage.json` in one function because the two halves
#: of a price live in different files. A leaf found there is not evidence about
#: either artifact on its own.
#:
#: Not fixed by renaming the field: the ambiguity is between two artifacts, not
#: between two things a reader of one file could confuse, so there is nothing to
#: disambiguate at the call site. And not fixed by destructuring around the
#: regex, which would be quieting the guard rather than answering it.
#:
#: There is a second one already, found while arguing about the first:
#: `app/venue/page.tsx` reads `venue.json`, `vetting.json` and `pools.json` and
#: joins all three. It has not fired only because no leaf has collided there
#: yet. So if anyone teaches this check that a multi-artifact reader is not
#: evidence — which is the real fix and is a change to the check rather than to
#: any caller — those two files are its test cases.
LEAF_COLLISIONS = frozenset({"x402_supported", "tx", "amount"})


def _blank_entries_that_look_rendered() -> list[str]:
    """Every `""` entry whose leaf is read, as a property, by its own renderers.

    Restricted three ways, because the leaf name is a weak identifier and a
    guard that cries wolf gets edited until it stops:

    1. **Only leaves that are unique across all four maps.** `tier`, `note`,
       `chain_id` and `read_at` name a field on a dozen shapes each; finding one
       proves nothing about which.
    2. **Only property accesses** — `.leaf` or `["leaf"]`. Unrestricted matching
       flagged `key` on every React list, `from` on every import and `name` on
       every form control. `hours` is the sharpest case: `activity.hours` is a
       field and `hours()` is the formatter imported beside it, and only the dot
       tells them apart.
    3. **Only the files that map already names as renderers**, not all of
       `src/` — a leaf appearing in an unrelated page is not evidence about this
       artifact.

    What survives is narrow and was worth having: it found six entries declared
    unrendered that render, four of them written by the same hand that wrote the
    declaration.
    """
    from collections import Counter

    maps = {
        "AGENT_FIELDS": AGENT_FIELDS,
        "ROUTER_FIELDS": ROUTER_FIELDS,
        "THIRD_PARTY_FIELDS": THIRD_PARTY_FIELDS,
        "REGISTRY_FIELDS": REGISTRY_FIELDS,
    }
    seen: Counter[str] = Counter()
    for table in maps.values():
        for path in table:
            seen[path.split(".")[-1]] += 1

    sources = _sources()
    found: list[str] = []
    for name, table in maps.items():
        renderers = sorted({r for r in table.values() if r})
        for path, renderer in table.items():
            if renderer:
                continue
            leaf = path.split(".")[-1]
            if seen[leaf] != 1 or leaf in LEAF_COLLISIONS:
                continue
            for filename in renderers:
                source = strip_comments(sources.get(filename, ""))
                if re.search(rf"[.\[]\"?{re.escape(leaf)}\b", source):
                    found.append(f"{name}: {path} -> read by {filename}")
                    break
    return found


def test_a_field_declared_unrendered_is_not_rendered() -> None:
    """The half of the contract that had no test, and had rotted.

    `test_every_contracted_*_field_is_read_by_the_named_view` checks that a
    field naming a renderer is read there. The `""` branch is `continue`d in
    every one of them, so the opposite claim — *this field reaches no view* —
    was never checked at all, and an empty string is the easiest thing in these
    maps to write. Six were wrong when this was added, including
    `identity.sampled_ids` and `identity.sampled_at_block`, whose declarations
    carried a written justification for not showing them while
    `registry/view.tsx` showed both.

    That matters beyond tidiness. A `""` is how this file records a **known
    gap**, and the note beside it is the todo list. `ours.age_hours` was the
    clearest one: declared unrendered, with the note that the page "presents a
    reading of unknown age as current". It has since been rendered and the note
    rewritten to say so, which is the discipline this test exists to enforce —
    a map where `""` also means "rendered, nobody updated it" is a todo list
    with entries that are already done, which is a todo list nobody reads.

    Worth saying once, so the remaining count is not read as a backlog: the
    bulk of the surviving `""` entries are decisions, not gaps. Reproducibility
    fields (`identity.seed`); the machine-readable `tier` / `chain_id` /
    `read_at` / `params` repeated on every third-party block, where `AnsweredBy`
    answers the freshness question a reader actually has; `third_party.stats.*`,
    because cross-chain totals are explicitly not comparable to the BSC figures
    beside them; `build.*`, removed deliberately. The reasons are written per
    block rather than per entry, so a lone `""` in the middle of one of those
    runs is covered by the comment that heads it — and a `""` that is genuinely
    a gap should say so in its own comment, on its own line.

    Note what this test does **not** check: the prose. It reads the map, so a
    comment can go on asserting a gap over an entry that names a renderer and
    nothing fails. Three did, in the commit that closed them.

    ## What this cannot see

    Leaves that name a field on more than one path — `ranges_overlap`,
    `lvr_quote_upper_bound`, `hours` — are skipped by construction, and all
    three were also declared unrendered while being rendered. They were found by
    hand and fixed in the same commit; the hole is stated here rather than
    papered over, because the alternative is matching a bare word and flagging
    the `hours()` formatter every time.
    """
    stale = _blank_entries_that_look_rendered()

    assert not stale, (
        "these fields are declared unrendered and a view reads them — either "
        "name the renderer or stop rendering the field:\n  " + "\n  ".join(stale)
    )


# ── build.json, which had no contract at all ─────────────────────────────────
#
# The run stamp for the whole artifact set: which tape, how many events, which
# commit, and whether that commit was dirty. `scripts/showcase.py` writes it on
# every run and **no file under `apps/web/src` mentions it** — so until this map
# existed the file could be renamed, reshaped or dropped and every suite in the
# repository stayed green.
#
# Every renderer is `""`, and that is a statement rather than a placeholder. The
# component that drew these was deleted deliberately, so nothing draws them
# today and nothing is claimed to — it is not named here because
# `tests/web/test_comment_references.py` suffix-matches file names and cannot
# tell a citation from a post-mortem, which it demonstrated by failing on this
# very comment. What the map buys is the *other* direction: the emitter
# can no longer quietly stop writing `git_dirty`, which is the field that makes
# a sha honest — the commit is real and the code that produced these numbers is
# not in it.
#
# `/status` answers the freshness question for now, through
# `go_no_go.check_artifact_freshness`. Whether a build stamp returns to the
# pages themselves is a rendering decision this map takes no position on.
BUILD_FIELDS: dict[str, str] = {
    "command": "",
    "source": "",
    "generated_at": "",
    "git_sha": "",
    "git_dirty": "",
    "events": "",
    "span_hours": "",
    "capital_quote": "",
    "quote_symbol": "",
    # `null` and `0` are different claims here and both occur: null means this
    # DB predates the coverage table and nobody can say, 0 means it was checked
    # and there are no holes. Contracted so the distinction cannot be dropped.
    "tape_gaps": "",
    "tape_blocks_unread": "",
}


@pytest.fixture(scope="module")
def build_artifact() -> dict:
    path = ARTIFACTS / "build.json"
    if not path.exists():
        pytest.skip("no build artifact; run `make showcase-demo`")
    return json.loads(path.read_text())


def test_the_build_emitter_writes_exactly_the_contracted_fields(build_artifact: dict) -> None:
    """The smallest artifact on the site, and the last one with no contract."""
    actual = flatten(build_artifact)
    declared = set(BUILD_FIELDS)

    undeclared = actual - declared
    undelivered = declared - actual

    assert not undeclared, (
        "the build emitter writes fields the contract does not declare — add them "
        f"to BUILD_FIELDS: {sorted(undeclared)}"
    )
    assert not undelivered, (
        f"the contract declares build fields the emitter no longer writes: {sorted(undelivered)}"
    )


# ── journal.json: what the live agents did, so the section survives no API ────
#
# `AgentJournal` renders **nothing** when nothing answers, so on the exported
# site the one section showing what a live agent decided was missing — while
# `/status` reported the burn-in gate against that same journal. This artifact
# is its fallback.
# ── studio.json: the Agent Studio half, which had no contract and no page ────
#
# Added with the route. The lesson `registry.json` taught — "the largest artifact
# this site fetches and it was the largest thing with no contract" — applies to a
# new emitter on the day it is written, not once it has drifted.
#
# `""` means the same thing here as everywhere else: carried for a machine
# reader, rendered by nothing, and that is deliberate rather than an oversight.
# Most of them are values the emitter uses to build a field that *is* rendered —
# `identity.explorer` becomes `owner_url`, `commerce.signer` is `identity.owner`
# under another name — and publishing the input beside the output is what lets a
# reader check the derivation without running the emitter.
STUDIO_FIELDS: dict[str, str] = {
    "agent.url": "app/studio/view.tsx",
    "agent.name": "app/studio/view.tsx",
    "agent.description": "app/studio/view.tsx",
    "agent.protocol_version": "app/studio/view.tsx",
    "agent.preferred_transport": "app/studio/view.tsx",
    "agent.host": "app/studio/view.tsx",
    "agent.health_check": "app/studio/view.tsx",
    # A list is a leaf to `flatten`, so the container is the whole
    # declaration and the shapes inside it are not covered here. What covers
    # those is `test_every_contracted_field_is_read_by_the_named_view`, which
    # matches on the leaf name, plus the per-element assertions the view
    # tests make. Same convention as `JOURNAL_FIELDS.agents`.
    "agent.skills": "app/studio/view.tsx",
    "agent.not_bag_deploy": "app/studio/view.tsx",
    "identity.agent_id": "app/studio/view.tsx",
    "identity.chain_id": "app/studio/view.tsx",
    "identity.owner": "app/studio/view.tsx",
    "identity.owner_url": "app/studio/view.tsx",
    "identity.endpoint": "app/studio/view.tsx",
    "identity.registered_by": "app/studio/view.tsx",
    "identity.verified": "app/studio/view.tsx",
    # The input `owner_url` is built from. Both are published so the derivation
    # is checkable without running the emitter.
    "identity.explorer": "",
    "identity.audit": "app/studio/view.tsx",
    "cli.package": "app/studio/view.tsx",
    "cli.version": "app/studio/view.tsx",
    "cli.versions": "app/studio/view.tsx",
    "cli.read_at": "app/studio/view.tsx",
    "cli.install_page_reachable": "app/studio/view.tsx",
    "cli.commands": "app/studio/view.tsx",
    "cli.record": "app/studio/view.tsx",
    # True whenever the probe ran at all, so it distinguishes nothing a reader
    # can see. The version and the count next to it are the claim.
    "cli.published": "",
    "commerce.available": "app/studio/view.tsx",
    "commerce.protocols": "app/studio/view.tsx",
    "commerce.runtime": "app/studio/view.tsx",
    "commerce.network": "app/studio/view.tsx",
    "commerce.wallet_kind": "app/studio/view.tsx",
    "commerce.price_wei": "app/studio/view.tsx",
    "commerce.min_price_wei": "app/studio/view.tsx",
    "commerce.max_price_wei": "app/studio/view.tsx",
    "commerce.quote_ttl_seconds": "app/studio/view.tsx",
    "commerce.note": "app/studio/view.tsx",
    # `identity.owner` under another name — `studio.toml`'s declared signer,
    # which the negotiation independently proves holds the key. Published
    # because the two agreeing is the finding; rendered once, as the owner.
    "commerce.signer": "",
    # The same address `negotiation.currency` carries, from configuration rather
    # than from the signed envelope. The envelope's copy is the one that matters
    # and is the one shown.
    "commerce.currency": "",
    # Off, and it stays off: an agent settling its own jobs unattended is a
    # decision about money this deployment has not made. Carried so the setting
    # is greppable from the artifact rather than only from the TOML.
    "commerce.auto_settle": "",
    "negotiation.available": "app/studio/view.tsx",
    "negotiation.verdict": "app/studio/view.tsx",
    "negotiation.checks": "app/studio/view.tsx",
    "negotiation.task_description": "app/studio/view.tsx",
    "negotiation.negotiation_hash": "app/studio/view.tsx",
    "negotiation.provider_sig": "app/studio/view.tsx",
    "negotiation.chain_id": "app/studio/view.tsx",
    "negotiation.verifying_contract": "app/studio/view.tsx",
    "negotiation.price_wei": "app/studio/view.tsx",
    "negotiation.currency": "app/studio/view.tsx",
    "negotiation.evaluator_type": "app/studio/view.tsx",
    "negotiation.quote_expires_at": "app/studio/view.tsx",
    "negotiation.estimated_completion_seconds": "app/studio/view.tsx",
    "negotiation.recovered_signer": "app/studio/view.tsx",
    "negotiation.signed_over": "app/studio/view.tsx",
    "negotiation.not_covered": "app/studio/view.tsx",
    "negotiation.read_at": "app/studio/view.tsx",
    "negotiation.record": "app/studio/view.tsx",
    # `available` is what the page branches on, and the two cannot disagree: a
    # record exists only if the agent answered. Carried because the *record*
    # distinguishes "asked and got nothing" from "never asked", and a reader
    # reaching for the file should find that distinction in it.
    "negotiation.answered": "",
    "not_done": "app/studio/view.tsx",
    "doctor.pass": "app/studio/view.tsx",
    "doctor.warn": "app/studio/view.tsx",
    "doctor.fail": "app/studio/view.tsx",
    "build.command": "",
    "build.generated_at": "",
    "build.git_sha": "",
    "build.git_dirty": "",
    "build.source": "",
}


@pytest.fixture(scope="module")
def studio_artifact() -> dict:
    path = ARTIFACTS / "studio.json"
    if not path.exists():
        pytest.skip("no studio artifact; run `make studio`")
    return json.loads(path.read_text())


def test_the_studio_emitter_writes_exactly_the_contracted_fields(studio_artifact: dict) -> None:
    """Both directions, as everywhere else.

    The Agent Studio record spent its whole existence on disk with nothing
    reading it, which is how the ledger came to describe an interface that had
    been deployed for days. A contract does not prevent that on its own — the
    route does — but it is what stops the emitter and the page drifting apart
    once both exist.
    """
    actual = flatten(studio_artifact)
    declared = set(STUDIO_FIELDS)

    undeclared = actual - declared
    undelivered = declared - actual

    assert not undeclared, (
        "the studio emitter writes fields the contract does not declare — render "
        f"them and add them to STUDIO_FIELDS, or stop emitting them: {sorted(undeclared)}"
    )
    assert not undelivered, (
        f"the contract declares studio fields the emitter no longer writes: {sorted(undelivered)}"
    )


JOURNAL_FIELDS: dict[str, str] = {
    # Opaque: the keys are agent names. See the OPAQUE entry above.
    "agents": "AgentJournal.tsx",
    "note": "",
    "build.command": "",
    "build.source": "",
    "build.generated_at": "",
    "build.git_sha": "",
    "build.git_dirty": "",
}

#: What `AgentJournal` reads out of one agent's entry.
#:
#: Every one of these is rendered — the figures row, the parse warning, and the
#: share `holds / decisions`, which the component's own comment insists on
#: because "168 holds" and "168 of 169 decisions were holds" are different
#: claims and only the second is about the policy.
#:
#: `gate_blocks` is not here: it is `GateHistogram`'s input on the card, keyed
#: by gate name, and the summary carries it for the same reason the API does.
JOURNAL_ENTRY_FIELDS = frozenset(
    {
        "total_rows",
        "unparsed_rows",
        "summary",
    }
)

JOURNAL_SUMMARY_FIELDS = frozenset(
    {
        "rows",
        "decisions",
        "holds",
        "mints",
        "rebalances",
        "pulls",
        "errors",
        "executed",
        "failed",
        "dropped",
        "first_ts",
        "last_ts",
        "gate_blocks",
        "fallback_samples",
        "kappa_fallback_samples",
        # The duration, which this artifact did not carry at all — so
        # `AgentJournal` derived it from `first_ts` and `last_ts` and rendered
        # 555h for a 24-hour run. Three numbers rather than one, because a
        # journal is appended to: the longest run, the distance between the two
        # ends, and how many runs are in there.
        "hours",
        "span_hours",
        "runs",
    }
)


@pytest.fixture(scope="module")
def journal_artifact() -> dict:
    path = ARTIFACTS / "journal.json"
    if not path.exists():
        pytest.skip("no journal artifact; run `make journal`")
    return json.loads(path.read_text())


def test_the_journal_emitter_writes_exactly_the_contracted_fields(journal_artifact: dict) -> None:
    """Both directions, with the agent set treated as data."""
    actual = flatten(journal_artifact)
    declared = set(JOURNAL_FIELDS)

    undeclared = actual - declared
    undelivered = declared - actual

    assert not undeclared, f"the journal emitter writes undeclared fields: {sorted(undeclared)}"
    assert not undelivered, (
        f"the contract declares journal fields the emitter no longer writes: {sorted(undelivered)}"
    )


def test_every_journal_entry_carries_the_summary_the_page_reads(journal_artifact: dict) -> None:
    """The half `agents` being opaque would otherwise lose.

    Which agents have run is data; what an entry holds is not. Without this the
    emitter could stop writing `unparsed_rows` — the field that says a journal's
    totals are short by an unknown amount — and nothing would notice, because
    the container it lives in is not flattened.
    """
    entries = journal_artifact.get("agents") or {}
    assert entries, "no agent has written a journal — run `make warden` or `make router`"

    for name, entry in entries.items():
        assert set(entry) == JOURNAL_ENTRY_FIELDS, (
            f"{name}'s journal entry does not carry the contracted fields: {sorted(entry)}"
        )
        assert set(entry["summary"]) == JOURNAL_SUMMARY_FIELDS, (
            f"{name}'s summary does not match `JournalSummary`: {sorted(entry['summary'])}"
        )


def test_the_journal_artifact_stays_small_enough_to_fetch(journal_artifact: dict) -> None:
    """The lesson `LISTING_LIMIT` records, held here as a number.

    The first version of this artifact carried all 344 decisions and was
    **340KB** — larger than every artifact this page fetches except
    `assumptions.json`. It also made every tick index and float in the file a
    literal no component may write: `-1` among them, which is `indexOf`'s miss
    and `slice`'s last element.

    A summary is 292 bytes per agent. The ceiling is deliberately far above that
    and far below where either problem returns, so adding a field is free and
    adding the rows back is not.
    """
    size = len(json.dumps(journal_artifact))

    assert size < 32_000, (
        f"journal.json is {size:,} bytes. It is fetched by every agent page — if the "
        "decisions are being published again, bound them first."
    )


# ── simulation.json: the position a reader sets up, and what it may claim ─────
#
# The last artifact on the site with no contract, and it showed. An audit found
# ten fields declared in `components/PoolSimulator.tsx` and read by nothing —
# `chain_id`, `path_points`, `capital_ladder`, `pools[].fee_pips`,
# `pools[].badged`, `tape.first_ts`, `tape.last_ts`, and, worst of the set,
# `cells[].fee_apr` and `cells[].convexity_cost_apr`.
#
# That last pair is why this contract exists rather than being tidy.
# `estimators/pool_apr.py` says in as many words that "every caller in this
# repository is expected to render the pair", because a fee APR without its
# adverse-selection cost is the overstatement A10 exists to prevent. The page
# emitted both on all 1,400 cells and rendered neither, showing the net alone —
# the answer to a subtraction with neither of its terms. Nothing caught it,
# because nothing was looking at this file.
#
# Three sets, the shape `JOURNAL_FIELDS` uses: `flatten` stops at a list, so the
# per-pool and per-cell keys need asserting separately or the contract would
# cover eight leaves and miss four hundred.

SIMULATION_FIELDS: dict[str, str] = {
    "capital_quote": "components/PoolSimulator.tsx",
    "width_ladder": "app/simulate/view.tsx",
    "a1_share": "components/PoolSimulator.tsx",
    "summary.pools": "app/simulate/view.tsx",
    "summary.badged": "app/simulate/view.tsx",
    "summary.simulable": "app/simulate/view.tsx",
    "summary.refused": "",
    "summary.cells": "app/simulate/view.tsx",
    "pools": "components/PoolSimulator.tsx",
    # Read by tests rather than by a view, which is a real answer and not an
    # oversight. `capital_ladder` is the emitter's declaration of what it swept
    # and `test_the_capital_ladder_is_offered_and_not_interpolated` holds the
    # page's offered sizes against it; `path_points` is the cap
    # `test_the_price_path_is_thinned_rather_than_published_whole` enforces.
    # Declaring them unrendered is what stops them being quietly rendered as a
    # figure nobody checked.
    "capital_ladder": "",
    "path_points": "",
    "chain_id": "",
    "build.command": "",
    "build.source": "",
    "build.generated_at": "",
    "build.git_sha": "",
    "build.git_dirty": "",
}

#: Every key on a pool row. `fee_pips` is emitted and not rendered on purpose —
#: the tier is already in `label` ("… 0.05%"), and a second copy on the page
#: would be the same number in two places with one emitter behind it.
SIMULATION_POOL_FIELDS = frozenset(
    {
        "address",
        "label",
        "quote_symbol",
        "fee_pips",
        "tick_spacing",
        "lp_fee_share",
        "badged",
        "tape",
        "price_path",
        "cells",
        "bands",
        "best_width_ticks",
        "verdict",
    }
)

#: Every key on a cell. `mintable` and `not_mintable_why` are the pair that
#: stops the page implying a reader could have taken a position PancakeSwap
#: would reject: the estimator snaps the centre to the spacing and not the
#: width, so a rung is on the grid only when `width % spacing == 0`.
SIMULATION_CELL_FIELDS = frozenset(
    {
        "width_ticks",
        "window",
        "capital_quote",
        "a1_ceiling_quote",
        "start_ts",
        "end_ts",
        "hours",
        "swaps",
        "fee_apr",
        "convexity_cost_apr",
        "net_apr",
        "fees_quote",
        "convexity_cost_quote",
        "depth_quote",
        "tick_lower",
        "tick_upper",
        "mintable",
        "not_mintable_why",
    }
)


@pytest.fixture(scope="module")
def simulation_artifact() -> dict:
    path = ARTIFACTS / "simulation.json"
    if not path.exists():
        pytest.skip("no simulation; run `make simulate`")
    return json.loads(path.read_text())


def test_the_simulation_emitter_writes_exactly_the_contracted_fields(
    simulation_artifact: dict,
) -> None:
    actual = flatten(simulation_artifact)
    declared = set(SIMULATION_FIELDS)

    undeclared = actual - declared
    undelivered = declared - actual

    assert not undeclared, (
        "the simulation emitter writes fields the contract does not declare — add "
        f"them to SIMULATION_FIELDS: {sorted(undeclared)}"
    )
    assert not undelivered, (
        f"the contract declares simulation fields the emitter no longer writes: "
        f"{sorted(undelivered)}"
    )


def test_every_pool_and_cell_carries_the_contracted_keys(simulation_artifact: dict) -> None:
    """The four hundred leaves `flatten` cannot see, because it stops at a list."""
    pools = simulation_artifact.get("pools") or []
    assert pools, "no pools in the simulation"

    for pool in pools:
        assert set(pool) == SIMULATION_POOL_FIELDS, (
            f"{pool.get('label')} does not carry the contracted pool keys: {sorted(pool)}"
        )
        for c in pool["cells"]:
            assert set(c) == SIMULATION_CELL_FIELDS, (
                f"{pool.get('label')} +/-{c.get('width_ticks')} does not carry the "
                f"contracted cell keys: {sorted(c)}"
            )


def test_every_contracted_simulation_field_is_read_by_the_named_view() -> None:
    """A field with a renderer named must be read by that file.

    The other half of the audit that produced this contract: a leaf can be
    emitted, declared, typed, and reach no reader at all, which is how the fee
    and convexity-cost rates sat on 1,400 cells while the page showed only their
    difference.
    """
    missing = []
    for field, view in SIMULATION_FIELDS.items():
        if not view:
            continue
        leaf = field.rsplit(".", 1)[-1]
        source = (WEB_SRC / view).read_text()
        if leaf not in source:
            missing.append(f"{field} -> {view}")

    assert not missing, f"contracted simulation fields no view reads: {sorted(missing)}"


# ── pools.json: the width ladder, and the fields the ladder's page reads ──────
#
# The artifact behind `/venue`'s "which pool, and how wide", and the twelfth to
# get a contract. It went without one through the change that added
# `indistinguishable_from` to every band — so for that whole period nothing
# checked that what `pools_report.py` writes is what the page reads, which is
# the hole that let ten fields go dead on `simulation.json`.
#
# Two renderers, not one. `app/venue/view.tsx` draws the pool rows and the
# demand table; `components/WidthLadder.tsx` owns `LadderBand` and draws the
# rungs. Naming them separately is what makes the second test mean anything: a
# band field attributed to the view would pass by being read in the wrong file.

POOLS_FIELDS: dict[str, str] = {
    "chain_id": "app/venue/view.tsx",
    "capital_quote": "app/venue/view.tsx",
    "width_ladder": "app/venue/view.tsx",
    "summary.pools": "app/venue/view.tsx",
    "summary.badged": "app/venue/view.tsx",
    "summary.quotable": "app/venue/view.tsx",
    "summary.refused": "app/venue/view.tsx",
    "pools": "app/venue/view.tsx",
    "build.command": "",
    "build.source": "",
    "build.generated_at": "",
    "build.git_sha": "",
    "build.git_dirty": "",
}

#: Every key on a pool row. `lp_fee_share` and `tick_spacing` are emitted and
#: read on `/venue` from `venue.json` instead — the same two facts arrive from
#: two emitters, and the page reads the one whose artifact it is projecting.
#: Declared here so that stays a decision rather than an accident.
POOLS_POOL_FIELDS = frozenset(
    {
        "address",
        "label",
        "fee_pips",
        "tick_spacing",
        "lp_fee_share",
        "quote_symbol",
        "badged",
        "best_width_ticks",
        "verdict",
        "ladder",
        "demand",
    }
)

#: A rung. `indistinguishable_from` is absent on a refused band and present on
#: every band that cleared — an empty list would read as "separated from
#: everything", which is the inversion `pools.separation()` documents.
POOLS_BAND_FIELDS = frozenset(
    {
        "width_ticks",
        "p25",
        "p50",
        "p75",
        "observations",
        "sufficient",
        "note",
    }
)

POOLS_DEMAND_FIELDS = frozenset(
    {
        "swaps",
        "volume_quote",
        "tick_crossings",
        "median_liquidity",
        "fee_per_unit_liquidity",
    }
)


@pytest.fixture(scope="module")
def pools_artifact() -> dict:
    path = ARTIFACTS / "pools.json"
    if not path.exists():
        pytest.skip("no pool report; run `make pools`")
    return json.loads(path.read_text())


def test_the_pools_emitter_writes_exactly_the_contracted_fields(pools_artifact: dict) -> None:
    actual = flatten(pools_artifact)
    declared = set(POOLS_FIELDS)

    undeclared = actual - declared
    undelivered = declared - actual

    assert not undeclared, (
        "the pools emitter writes fields the contract does not declare — add them "
        f"to POOLS_FIELDS: {sorted(undeclared)}"
    )
    assert not undelivered, (
        f"the contract declares pools fields the emitter no longer writes: {sorted(undelivered)}"
    )


def test_every_pool_row_band_and_demand_carries_the_contracted_keys(
    pools_artifact: dict,
) -> None:
    """The leaves `flatten` cannot see, because it stops at a list."""
    rows = pools_artifact.get("pools") or []
    assert rows, "no pools in the report"

    for row in rows:
        assert set(row) <= POOLS_POOL_FIELDS, (
            f"{row.get('label')} carries undeclared pool keys: "
            f"{sorted(set(row) - POOLS_POOL_FIELDS)}"
        )
        assert set(row["demand"]) == POOLS_DEMAND_FIELDS, (
            f"{row.get('label')} demand block: {sorted(row['demand'])}"
        )
        for band in row["ladder"]:
            extra = set(band) - POOLS_BAND_FIELDS - {"indistinguishable_from"}
            assert not extra, f"{row.get('label')} band carries undeclared keys: {sorted(extra)}"
            assert POOLS_BAND_FIELDS <= set(band), (
                f"{row.get('label')} band is missing contracted keys: "
                f"{sorted(POOLS_BAND_FIELDS - set(band))}"
            )
            # The join `/venue` renders, and the asymmetry that makes it honest.
            assert ("indistinguishable_from" in band) is bool(band["sufficient"]), (
                f"{row.get('label')} +/-{band['width_ticks']}: ties present="
                f"{'indistinguishable_from' in band} but sufficient={band['sufficient']}"
            )


def test_every_contracted_pools_field_is_read_by_the_named_view() -> None:
    missing = []
    for field, view in POOLS_FIELDS.items():
        if not view:
            continue
        leaf = field.rsplit(".", 1)[-1]
        if leaf not in (WEB_SRC / view).read_text():
            missing.append(f"{field} -> {view}")

    assert not missing, f"contracted pools fields no view reads: {sorted(missing)}"


def test_the_band_keys_are_read_where_the_ladder_is_drawn() -> None:
    """`LadderBand` lives in the component, not the view.

    Attributing these to `app/venue/view.tsx` would pass — the view imports the
    type — while the rungs are actually drawn one file over. This asserts the
    file that reads them.
    """
    source = (WEB_SRC / "components/WidthLadder.tsx").read_text()
    unread = sorted(f for f in POOLS_BAND_FIELDS | {"indistinguishable_from"} if f not in source)

    assert not unread, f"band fields WidthLadder.tsx does not read: {unread}"
