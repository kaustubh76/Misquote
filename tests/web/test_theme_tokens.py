"""Contrast, asserted rather than asserted-about.

The palette this replaces declared ten tokens for dark and re-declared six of
them for light. `--good`, `--bad` and `--warn` kept their dark values on a
near-white background, so `--good: #5fb87a` on `#fbfbfa` measured **2.35:1** —
below the 4.5:1 the text it coloured needed, and it was the colour carrying
"this position made money". `--faint` failed in *both* themes.

Nothing caught it, because nothing was looking. These tests look.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CSS = REPO / "apps" / "web" / "src" / "app" / "globals.css"

# WCAG 2.1 AA.
AA_TEXT = 4.5
AA_NON_TEXT = 3.0


def relative_luminance(hex_colour: str) -> float:
    raw = hex_colour.lstrip("#")
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    channels = [int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


LIGHT_DARK = re.compile(
    r"--([a-z0-9-]+):\s*light-dark\(\s*(#[0-9a-fA-F]{3,8})\s*,\s*(#[0-9a-fA-F]{3,8})\s*\)"
)


@pytest.fixture(scope="module")
def tokens() -> dict[str, tuple[str, str]]:
    """Every colour token, as (light, dark)."""
    if not CSS.exists():
        pytest.skip("no stylesheet")
    found = {m.group(1): (m.group(2), m.group(3)) for m in LIGHT_DARK.finditer(CSS.read_text())}
    assert found, "no light-dark() tokens found — has the palette been restructured?"
    return found


def test_every_colour_token_defines_both_themes(tokens: dict[str, tuple[str, str]]) -> None:
    """The structural guarantee, restated as a test.

    `light-dark()` makes a one-armed token a syntax error rather than a silent
    contrast failure, which is why the palette is written that way. This asserts
    the property still holds — that nobody has reintroduced a bare `--good: #x`
    outside a `light-dark()` and thereby recreated the original bug.
    """
    text = CSS.read_text()
    root = text[text.index(":root {") : text.index("@theme inline")]

    # Every colour-valued custom property in :root must be a light-dark() pair.
    for match in re.finditer(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;", root):
        pytest.fail(
            f"{match.group(1)} is defined as a bare colour ({match.group(2)}). "
            "Use light-dark(light, dark) so it cannot be defined for one theme "
            "and forgotten in the other."
        )


@pytest.mark.parametrize("theme_index,theme", [(0, "light"), (1, "dark")])
def test_text_tokens_clear_aa_against_both_surfaces(
    tokens: dict[str, tuple[str, str]], theme_index: int, theme: str
) -> None:
    bg = tokens["bg"][theme_index]
    panel = tokens["panel"][theme_index]

    failures: list[str] = []
    for name in ("ink", "dim", "faint", "good", "bad", "warn", "neutral"):
        colour = tokens[name][theme_index]
        for surface_name, surface in (("bg", bg), ("panel", panel)):
            ratio = contrast(colour, surface)
            if ratio < AA_TEXT:
                failures.append(
                    f"--{name} ({colour}) on --{surface_name} ({surface}) "
                    f"is {ratio:.2f}:1 in {theme}, needs {AA_TEXT}"
                )

    assert not failures, "\n".join(failures)


@pytest.mark.parametrize("theme_index,theme", [(0, "light"), (1, "dark")])
def test_pill_text_clears_aa_on_its_own_tint(
    tokens: dict[str, tuple[str, str]], theme_index: int, theme: str
) -> None:
    """A pill's foreground sits on its tint, not on the page background."""
    failures: list[str] = []
    for name in ("good", "bad", "warn", "neutral"):
        fg = tokens[name][theme_index]
        bg = tokens[f"{name}-bg"][theme_index]
        ratio = contrast(fg, bg)
        if ratio < AA_TEXT:
            failures.append(
                f"--{name} ({fg}) on --{name}-bg ({bg}) is {ratio:.2f}:1 in {theme}"
            )
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize("theme_index,theme", [(0, "light"), (1, "dark")])
def test_focus_ring_is_visible(
    tokens: dict[str, tuple[str, str]], theme_index: int, theme: str
) -> None:
    """Non-text, so 3:1 — but it is the only thing a keyboard user has."""
    ratio = contrast(tokens["focus"][theme_index], tokens["bg"][theme_index])
    assert ratio >= AA_NON_TEXT, f"focus ring is {ratio:.2f}:1 in {theme}"


def test_the_original_failure_would_be_caught(tokens: dict[str, tuple[str, str]]) -> None:
    """A regression guard aimed at the specific bug, not just the general rule.

    If someone restores the old light palette — dark `--good` on a near-white
    background — this is the assertion that names it.
    """
    assert contrast("#5fb87a", "#fbfbfa") < AA_TEXT, "sanity: the old pairing did fail AA"
    light_good, _ = tokens["good"]
    assert light_good.lower() != "#5fb87a", (
        "the light theme's --good is the dark theme's value again; that pairing "
        "measures 2.35:1 against the light background"
    )
