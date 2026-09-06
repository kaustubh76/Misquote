"""Prose written in markdown must reach a renderer that renders markdown.

Every emitter in this repository writes its prose the same way: bold for the
sentence that carries the finding, backticks for a path or a call, the
occasional link. `/assumptions` has rendered that since it was written, through
`Blocks`. Nothing else did — `Prose` was private to that one file — so six other
surfaces printed the source characters at the reader.

The one that prompted this: the Agent Studio ledger card, on `/` and `/status`,
read

    **The funding half of this blocker has closed**: all four agents now hold
    ERC-8004 identities on chapel ... recorded in `vetting/identity/97.json`

with the asterisks and the backticks on the screen, in the middle of the one
card on this site whose whole job is to be read carefully.

This is the guard against the seventh. It sweeps every artifact for prose
carrying balanced inline markdown, and requires each field to be accounted for:
rendered by a file that uses `Prose`, or listed as deliberately plain with the
reason. A field nobody thought of fails rather than passing quietly, which is
the same shape as `test_artifact_contract`'s maps and for the same reason.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO / "apps" / "web" / "public" / "artifacts"
WEB = REPO / "apps" / "web" / "src"

#: Balanced pairs only. A lone asterisk or a single backtick is prose, not
#: markup, and `Prose` leaves it alone — its split matches pairs. Matching
#: singletons here would report every apostrophe-adjacent star on the site.
MARKDOWN = re.compile(r"\*\*[^*]+\*\*|`[^`]+`|(?<![\w*])\*[^*\s][^*]*\*(?![\w*])")

#: The four `index.json` category names appear as object keys in the registry
#: artifact, so a raw walk would emit four paths for one field.
CATEGORIES = {"Health", "Market making", "Rebalancing", "Yield"}

#: Every markdown-bearing prose field, and the file that must render it with
#: `Prose`. Keyed by `artifact:path`, with list indices collapsed to `[]` and
#: category names to `*`.
RENDERED_AS_MARKDOWN: dict[str, str] = {
    "assumptions.json:entries[].title": "app/assumptions/view.tsx",
    "assumptions.json:entries[].blocks[].text": "components/Blocks.tsx",
    "assumptions.json:entries[].blocks[].items[]": "components/Blocks.tsx",
    "assumptions.json:entries[].blocks[].head[]": "components/Blocks.tsx",
    "assumptions.json:entries[].blocks[].rows[][]": "components/Blocks.tsx",
    "assumptions.json:sections.estimator_fits[].text": "components/Blocks.tsx",
    "assumptions.json:sections.parameters[].text": "components/Blocks.tsx",
    "assumptions.json:sections.parameters[].rows[][]": "components/Blocks.tsx",
    "assumptions.json:sections.protocol_fee[].text": "components/Blocks.tsx",
    "assumptions.json:sections.protocol_fee[].rows[][]": "components/Blocks.tsx",
    "assumptions.json:sections.settled_vs_displayed[].text": "components/Blocks.tsx",
    "assumptions.json:sections.target_pool[].text": "components/Blocks.tsx",
    "assumptions.json:sections.target_pool[].head[]": "components/Blocks.tsx",
    "assumptions.json:sections.target_pool[].rows[][]": "components/Blocks.tsx",
    "index.json:not_built[].what": "components/Ledger.tsx",
    "index.json:not_built[].why": "components/Ledger.tsx",
    # Keyed by chain id rather than collapsed: `*` is reserved for the four
    # agent categories, and a wildcard here would hide a third chain appearing.
    "addresses.json:session_keys.56.not_verified[]": "app/activate/view.tsx",
    "addresses.json:session_keys.97.not_verified[]": "app/activate/view.tsx",
    # Keyed by check id — six paths saying one thing, listed individually
    # because `*` is reserved for the four agent categories and a wildcard here
    # would hide a seventh unprovable check appearing.
    "vetting.json:pools[].proof.reason": "app/vetting/view.tsx",
    "vetting.json:pools[].proof.coverage.not_provable.protocol-fee": "app/vetting/view.tsx",
    "vetting.json:pools[].proof.coverage.not_provable.decimals": "app/vetting/view.tsx",
    "vetting.json:pools[].proof.coverage.not_provable.initialised": "app/vetting/view.tsx",
    "vetting.json:pools[].proof.coverage.not_provable.tokens-are-contracts": "app/vetting/view.tsx",
    "vetting.json:pools[].proof.coverage.not_provable.recorded-matches-chain": "app/vetting/view.tsx",
    "registry.json:hire_flow.escrow.evidence[]": "app/registry/view.tsx",
    # `not_escrowed_because` itself is no longer here and that is not an
    # oversight: the correction that replaced it — nothing had been spent to buy
    # the payment token, and then something was — is written in plain sentences.
    # It is still rendered through `Prose`; it just has nothing for `Prose` to
    # do. The superseded original keeps the backticks and is listed below.
    "registry.json:hire_flow.submit_proof.what_this_run_changes": "app/registry/view.tsx",
    "status.json:checks[].detail": "app/status/view.tsx",
    "status.json:checks[].remedy": "app/status/view.tsx",
    "venue.json:divergences[].what": "app/venue/view.tsx",
}

#: Fields whose markdown comes and goes with the run rather than with the code.
#:
#: `status.json` is the go/no-go gate's own output: a check's `detail` is the
#: last line the tool printed and its `remedy` is only written when the check is
#: not passing. So whether either carries a backtick depends on which gates were
#: red when `make status` last ran — `checks[].remedy` had markdown in every
#: artifact until the run where the three failing checks all had bare-command
#: remedies, and `checks[].detail` gained it the same day, from vitest printing
#: a node warning.
#:
#: Dropping them when they go quiet and re-adding them when they come back is a
#: gate that flaps for no reason, so the staleness sweep skips them. They stay
#: in the map above, which is what matters: if the markdown does appear, it is
#: accounted for and its renderer is held to using `Prose`.
VOLATILE = frozenset(
    {
        "status.json:checks[].detail",
        "status.json:checks[].remedy",
    }
)

#: Markdown that must stay on the page as characters, and why.
PLAIN_BY_DESIGN: dict[str, str] = {
    # The one string on the site a stranger wrote. `Prose` would let whoever
    # minted a registry card choose the emphasis — and, through `[label](href)`,
    # place a link — on our pages. Guarded on its own in
    # `test_third_party_listings.py`; listed here so the sweep does not report
    # it as an oversight.
    "registry.json:third_party.categories.*.agents[].description": (
        "third-party text: theirs to write, ours to print verbatim"
    ),
    # Declared unrendered in `test_artifact_contract.REGISTRY_FIELDS`. A field
    # no view reads cannot be rendered wrong.
    "registry.json:third_party.census.note": "not rendered by any view",
    # The claim `hire-97.json` used to make, kept beside the one that replaced
    # it because a PancakeSwap swap falsified it and deleting the sentence would
    # erase the correction along with the error. Declared unrendered in
    # `REGISTRY_FIELDS` on purpose: showing a retracted claim at the same weight
    # as a true one is the failure this whole site is named after.
    "registry.json:hire_flow.proof.not_escrowed_because_was": (
        "a superseded claim, carried in the record and rendered by no view"
    ),
}


def _prose_fields() -> dict[str, int]:
    """Every `artifact:path` whose value carries balanced inline markdown."""
    found: dict[str, int] = {}

    def walk(node: object, path: str, artifact: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                name = "*" if key in CATEGORIES else key
                walk(value, f"{path}.{name}" if path else name, artifact)
        elif isinstance(node, list):
            for value in node:
                walk(value, f"{path}[]", artifact)
        elif isinstance(node, str) and MARKDOWN.search(node):
            found[f"{artifact}:{path}"] = found.get(f"{artifact}:{path}", 0) + 1

    for file in sorted(ARTIFACTS.glob("*.json")):
        walk(json.loads(file.read_text()), "", file.name)
    return found


@pytest.fixture(scope="module")
def prose() -> dict[str, int]:
    fields = _prose_fields()
    if not fields:
        pytest.skip("no artifacts have been generated")
    return fields


def test_every_markdown_field_is_accounted_for(prose: dict[str, int]) -> None:
    """A new one fails here rather than reaching a reader as asterisks."""
    known = set(RENDERED_AS_MARKDOWN) | set(PLAIN_BY_DESIGN)
    unaccounted = sorted(set(prose) - known)

    assert not unaccounted, (
        "these artifact fields carry inline markdown and no entry in this file "
        "says what happens to it — render them with `Prose` and list them, or "
        "list them as plain by design:\n  "
        + "\n  ".join(f"{f} ({prose[f]} value(s))" for f in unaccounted)
    )


def test_every_field_declared_rendered_still_carries_markdown(prose: dict[str, int]) -> None:
    """The other direction, so this file does not accumulate dead entries.

    The same failure `test_artifact_contract` guards for its own maps: a claim
    about a field that no longer looks like that is a claim nobody is checking.
    """
    stale = sorted(f for f in RENDERED_AS_MARKDOWN if f not in prose and f not in VOLATILE)

    assert not stale, (
        "these fields are listed as carrying markdown and no longer do — the "
        "emitter changed, so drop them from this file:\n  " + "\n  ".join(stale)
    )


@pytest.mark.parametrize("field,renderer", sorted(RENDERED_AS_MARKDOWN.items()))
def test_the_named_renderer_uses_prose(field: str, renderer: str) -> None:
    """Named rather than inferred, so moving the render moves this line too."""
    path = WEB / renderer
    assert path.exists(), f"{field} names {renderer}, which does not exist"

    source = path.read_text()
    assert "Prose" in source, (
        f"{field} carries inline markdown and {renderer} renders it without "
        f"`Prose`, so its asterisks and backticks reach the reader"
    )


def test_volatile_entries_are_declared_rendered() -> None:
    """`VOLATILE` waives the staleness sweep, not the rendering claim.

    An entry here that is not in `RENDERED_AS_MARKDOWN` would be a field
    exempted from both checks at once, which is the exemption this file exists
    to make impossible.
    """
    unclaimed = sorted(VOLATILE - set(RENDERED_AS_MARKDOWN))
    assert not unclaimed, (
        f"these are waived from the staleness sweep and named by no renderer: {unclaimed}"
    )


def test_plain_by_design_entries_give_a_reason() -> None:
    """An exemption with no reason beside it is an exemption nobody can review."""
    silent = sorted(k for k, why in PLAIN_BY_DESIGN.items() if len(why.strip()) < 20)
    assert not silent, f"these exemptions do not say why: {silent}"
