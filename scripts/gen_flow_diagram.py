"""The whole system on one canvas, generated rather than drawn.

    uv run python scripts/gen_flow_diagram.py
    make diagram

Misquote is eleven thousand lines across nine sub-packages, a static front end
that reads fourteen precomputed JSON files, a Foundry differential-test lab, and
a test suite whose main job is to forbid things. The architecture is legible
only by reading module docstrings: the three-layer purity split, the `policy=`
seam that lets one engine run four agents, the difference between the indexer's
cursor and its coverage table, and the dozen separate places the system refuses
to answer. None of that was drawn anywhere.

This writes that map to `MISQUOTE_FLOW.excalidraw`, in nine bands read top to
bottom.

## Why a generator and not a drawing

A drawing is a claim about the code made once. Every number and every list here
is either authored prose or read out of the repository at run time — the route
list from `apps/web/src/lib/routes.ts`, the not-built ledger from
`packages/misquote/tearsheet/ledger.py`, the layer names and the banned-import
set from `tests/test_layering.py`, the artifact order from the Makefile, and
every refusal floor from the module that enforces it. So the diagram cannot
quietly drift from the thing it describes, which is the same posture
`scripts/venue_report.py` takes with prose.

The output is deterministic: fixed seeds, a fixed timestamp, counter-derived
ids. Re-running with nothing changed rewrites a byte-identical file, so
`make diagram` never shows up as diff noise. That is the discipline
`packages/misquote/indexer/store.py` is built on, applied to a drawing.

## Layout

Standalone text rather than container-bound text. Bound text auto-wraps, but
its geometry is recomputed by the application and is easy to get subtly wrong
from outside; standalone text with computed widths places deterministically and
cannot end up clipped by a box drawn too small for it. Every node's rectangle
and its text share a group id, so a node drags as one object — the file is meant
to be edited, not only read.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))

DEFAULT_OUT = REPO / "MISQUOTE_FLOW.excalidraw"

# Fixed, so re-running produces the same bytes. Excalidraw only uses `seed` for
# the hand-drawn jitter and `updated` for conflict resolution; neither carries
# meaning we need, and both would otherwise churn the file on every run.
SEED_BASE = 20260818
STAMP = 1786531955200

# ---------------------------------------------------------------- palette --
#
# Excalidraw's own default swatches, so a node edited by hand in the app picks
# the same colours out of the palette rather than something adjacent to them.

INK = "#1e1e1e"
GREY = "#495057"

PURE = ("#1971c2", "#e7f5ff")  # core, estimators, lvr, replay
DATA = ("#2f9e44", "#ebfbee")  # chain, indexer, sqlite, artifacts on disk
DRIVE = ("#9c36b5", "#f8f0fc")  # agents, ops, registry, tearsheet, scripts
WEB = ("#f08c00", "#fff9db")  # apps/web
STOP = ("#e03131", "#fff5f5")  # every guard, floor, refusal, kill switch
TEST = ("#495057", "#f1f3f5")  # tests, the frozen spec, enforcement edges
BAND = ("#adb5bd", "#ffffff")

KINDS = {
    "pure": PURE,
    "data": DATA,
    "drive": DRIVE,
    "web": WEB,
    "stop": STOP,
    "test": TEST,
}

# ------------------------------------------------------------- text metry --
#
# Advance width as a fraction of font size, measured against Excalidraw's own
# rendering rather than guessed: family 3 is Cascadia (monospace) and family 2
# is the sans it uses for normal text. These are what make a computed box
# height correct, which is what keeps text off the edges.

CHAR_W = {1: 0.55, 2: 0.52, 3: 0.60}
LINE_H = 1.25

TITLE_SIZE = 15
PATH_SIZE = 11
BODY_SIZE = 12
PAD_X = 14
PAD_Y = 12


def text_width(text: str, size: int, family: int) -> float:
    longest = max((len(line) for line in text.split("\n")), default=0)
    return longest * size * CHAR_W[family]


def text_height(text: str, size: int) -> float:
    return len(text.split("\n")) * size * LINE_H


def wrap(text: str, width_px: float, size: int, family: int) -> str:
    """Greedy wrap to a pixel width. Explicit newlines are kept as breaks."""
    limit = max(8, int(width_px / (size * CHAR_W[family])))
    out: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}".strip()
            if len(candidate) > limit and line:
                out.append(line)
                line = word
            else:
                line = candidate
        out.append(line)
    return "\n".join(out)


# ------------------------------------------------------------- the canvas --


@dataclass
class Box:
    """A placed node, and the rectangle an arrow may bind to."""

    id: str
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0


@dataclass
class Canvas:
    """Accumulates elements and hands out deterministic ids."""

    elements: list[dict[str, Any]] = field(default_factory=list)
    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Node rectangles only, so the overlap check has something to check. Band
    # plates and legend swatches are deliberately absent from it.
    boxes: list[Box] = field(default_factory=list)
    # (tail box, head box, evidence) for every structural edge. Kept here rather
    # than on the element so the written file stays exactly what Excalidraw
    # expects — the claim is the generator's, not the drawing's.
    edges: list[tuple[str, str, str]] = field(default_factory=list)
    # Deferred arrow labels: (text, midpoint x, midpoint y, colour, tail, head).
    labels: list[tuple[str, float, float, str, Box, Box]] = field(default_factory=list)
    _n: int = 0
    _bands: int = 0

    def next_id(self) -> str:
        self._n += 1
        return f"mq{self._n:04d}"

    def add(self, element: dict[str, Any]) -> dict[str, Any]:
        self.elements.append(element)
        self.by_id[element["id"]] = element
        return element

    def seed(self) -> int:
        # Derived from the element index, not from a PRNG: same file, same
        # seeds, and no hidden global state to get out of step.
        return (SEED_BASE * 7919 + self._n * 104729) % 2_147_483_647


def _base(canvas: Canvas, kind: str, **over: Any) -> dict[str, Any]:
    element = {
        "id": canvas.next_id(),
        "type": kind,
        "x": 0,
        "y": 0,
        "width": 0,
        "height": 0,
        "angle": 0,
        "strokeColor": INK,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "seed": canvas.seed(),
        "version": 1,
        "versionNonce": canvas.seed(),
        "isDeleted": False,
        "boundElements": [],
        "updated": STAMP,
        "link": None,
        "locked": False,
    }
    element.update(over)
    return element


def text(
    canvas: Canvas,
    x: float,
    y: float,
    body: str,
    *,
    size: int = BODY_SIZE,
    family: int = 2,
    color: str = INK,
    group: str | None = None,
    align: str = "left",
    width: float | None = None,
) -> dict[str, Any]:
    return canvas.add(
        _base(
            canvas,
            "text",
            x=x,
            y=y,
            width=width if width is not None else text_width(body, size, family),
            height=text_height(body, size),
            strokeColor=color,
            groupIds=[group] if group else [],
            text=body,
            originalText=body,
            fontSize=size,
            fontFamily=family,
            textAlign=align,
            verticalAlign="top",
            containerId=None,
            lineHeight=LINE_H,
        )
    )


def rect(
    canvas: Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    stroke: str = INK,
    fill: str = "transparent",
    group: str | None = None,
    dashed: bool = False,
    rounded: bool = True,
    stroke_width: int = 1,
) -> dict[str, Any]:
    return canvas.add(
        _base(
            canvas,
            "rectangle",
            x=x,
            y=y,
            width=w,
            height=h,
            strokeColor=stroke,
            backgroundColor=fill,
            fillStyle="solid",
            strokeStyle="dashed" if dashed else "solid",
            strokeWidth=stroke_width,
            groupIds=[group] if group else [],
            roundness={"type": 3} if rounded else None,
        )
    )


def node(
    canvas: Canvas,
    x: float,
    y: float,
    w: float,
    *,
    title: str,
    kind: str = "pure",
    path: str = "",
    body: str = "",
    tag: str = "",
) -> Box:
    """One box: a title, an optional source path, wrapped prose, an optional tag.

    Height is computed from the wrapped text rather than assumed, which is the
    only reason a box in this file is never too small for what is inside it.
    """
    stroke, fill = KINDS[kind]
    group = canvas.next_id()
    inner = w - 2 * PAD_X

    title_text = wrap(title, inner, TITLE_SIZE, 2)
    path_text = wrap(path, inner, PATH_SIZE, 3) if path else ""
    body_text = wrap(body, inner, BODY_SIZE, 2) if body else ""
    tag_text = wrap(tag, inner, PATH_SIZE, 3) if tag else ""

    h = PAD_Y + text_height(title_text, TITLE_SIZE)
    if path_text:
        h += 4 + text_height(path_text, PATH_SIZE)
    if body_text:
        h += 8 + text_height(body_text, BODY_SIZE)
    if tag_text:
        h += 6 + text_height(tag_text, PATH_SIZE)
    h += PAD_Y

    box_element = rect(canvas, x, y, w, h, stroke=stroke, fill=fill, group=group)

    cursor = y + PAD_Y
    text(
        canvas, x + PAD_X, cursor, title_text, size=TITLE_SIZE, family=2, color=stroke, group=group
    )
    cursor += text_height(title_text, TITLE_SIZE)
    if path_text:
        cursor += 4
        text(
            canvas, x + PAD_X, cursor, path_text, size=PATH_SIZE, family=3, color=GREY, group=group
        )
        cursor += text_height(path_text, PATH_SIZE)
    if body_text:
        cursor += 8
        text(canvas, x + PAD_X, cursor, body_text, size=BODY_SIZE, family=2, color=INK, group=group)
        cursor += text_height(body_text, BODY_SIZE)
    if tag_text:
        cursor += 6
        text(
            canvas, x + PAD_X, cursor, tag_text, size=PATH_SIZE, family=3, color=stroke, group=group
        )

    box = Box(box_element["id"], x, y, w, h)
    canvas.boxes.append(box)
    return box


def arrow(
    canvas: Canvas,
    a: Box,
    b: Box,
    *,
    label: str = "",
    color: str = GREY,
    dashed: bool = False,
    gap: int = 6,
    evidence: str = "",
    kind: str = "",
) -> dict[str, Any]:
    """Bind an edge between two boxes, elbowed along the dominant axis.

    Bound at both ends, so the edge re-routes when either node is dragged. A
    diagram whose arrows come loose the first time it is rearranged is a
    diagram nobody rearranges.

    ## `evidence`, and why an arrow needs any

    The layout guards check that the drawing is well-formed. They cannot check
    that it is **true**, and the first version of this file was not: it drew
    `WardenLive -> WardenLoop -> ChainExecutor` when the loop calls the agent and
    the agent calls the executor, and it drew the tape reaching the engine, which
    nothing does. Both are the kind of wrong that survives every review, because
    a plausible arrow looks exactly like a correct one.

    So a structural edge declares what makes it true — `"module.path:Symbol"`,
    the reference that has to exist in the source for this edge to exist — and
    `validate()` resolves it with `ast`. Which end holds the reference depends on
    the edge: for a call it is the caller, and for a data-flow edge it is the
    consumer that names the producer. Rename the symbol and the diagram stops
    building instead of quietly pointing at a file that no longer does that.

    Python only. TypeScript edges in the front-end band, and edges between things
    that are not modules at all, are `kind="concept"`.

    `kind="concept"` is the escape hatch for edges that are not calls: a
    sequence, a guard, a claim. It is deliberately explicit, so an undeclared
    call edge is a failure rather than an omission.
    """
    if not evidence and not kind:
        raise ValueError(
            f"arrow {a.id} -> {b.id} declares neither `evidence` nor `kind`. "
            "A structural edge must name the symbol that makes it true; a "
            "conceptual one must say that it is conceptual."
        )
    if b.x >= a.right - 1:  # left to right
        sx, sy, ex, ey = a.right, a.cy, b.x, b.cy
    elif a.x >= b.right - 1:  # right to left
        sx, sy, ex, ey = a.x, a.cy, b.right, b.cy
    elif b.y >= a.bottom - 1:  # downward
        sx, sy, ex, ey = a.cx, a.bottom, b.cx, b.y
    else:  # upward
        sx, sy, ex, ey = a.cx, a.y, b.cx, b.bottom

    dx, dy = ex - sx, ey - sy
    if abs(dy) < 2 or abs(dx) < 2:
        points = [[0, 0], [dx, dy]]
    elif abs(dx) >= abs(dy):
        points = [[0, 0], [dx / 2, 0], [dx / 2, dy], [dx, dy]]
    else:
        points = [[0, 0], [0, dy / 2], [dx, dy / 2], [dx, dy]]

    element = canvas.add(
        _base(
            canvas,
            "arrow",
            x=sx,
            y=sy,
            width=abs(dx),
            height=abs(dy),
            strokeColor=color,
            strokeStyle="dashed" if dashed else "solid",
            points=points,
            lastCommittedPoint=None,
            startBinding={"elementId": a.id, "focus": 0.0, "gap": gap},
            endBinding={"elementId": b.id, "focus": 0.0, "gap": gap},
            startArrowhead=None,
            endArrowhead="arrow",
            elbowed=False,
            roundness={"type": 2},
        )
    )
    canvas.by_id[a.id]["boundElements"].append({"id": element["id"], "type": "arrow"})
    canvas.by_id[b.id]["boundElements"].append({"id": element["id"], "type": "arrow"})
    if evidence:
        canvas.edges.append((a.id, b.id, evidence))

    if label:
        canvas.labels.append((label, sx + dx / 2, sy + dy / 2, color, a, b))
    return element


def place_labels(canvas: Canvas) -> None:
    """Put every arrow label somewhere it does not land on a node.

    Deferred to the end deliberately. A label dropped at its edge's midpoint
    lands inside a box about a third of the time — the midpoint of a short edge
    is often *behind* something — and worse, placing it while its own band is
    still being drawn checks it against boxes that do not exist yet. So the
    search runs once, against the finished canvas.
    """
    placed: list[tuple[float, float, float, float]] = []
    for label, mid_x, mid_y, color, a, b in canvas.labels:
        width = text_width(label, PATH_SIZE, 3)
        height = text_height(label, PATH_SIZE)
        left, top = mid_x - width / 2, mid_y

        candidates = [
            (left + dx_, top + dy_)
            for dy_, dx_ in (
                (-20, 0),
                (-36, 0),
                (10, 0),
                (26, 0),
                (-20, 40),
                (-20, -40),
                (-52, 0),
                (42, 0),
                (10, 60),
                (10, -60),
                (0, 100),
                (0, -100),
            )
        ]
        # These two clear both endpoints outright, which is the only thing that
        # works for boxes side by side with a 40px gap: no offset from the
        # midpoint can fit a label into that gap.
        candidates.append((left, min(a.y, b.y) - height - 10))
        candidates.append((left, max(a.bottom, b.bottom) + 10))
        candidates += [
            (left + shift, top - 20 - step * 16)
            for step in range(1, 24)
            for shift in (0, -90, 90, -180, 180)
        ]

        for x_, y_ in candidates:
            hits_box = any(
                x_ < box.right and box.x < x_ + width and y_ < box.bottom and box.y < y_ + height
                for box in canvas.boxes
            )
            # Labels also have to clear each other. Two edges leaving the same
            # node put their midpoints in the same place, so this is not a
            # theoretical collision — it happened on the first run.
            hits_label = any(
                x_ < lx + lw and lx < x_ + width and y_ < ly + lh and ly < y_ + height
                for lx, ly, lw, lh in placed
            )
            if not hits_box and not hits_label:
                left, top = x_, y_
                break
        else:
            raise SystemExit(
                f"no clear position for the arrow label {label!r} near "
                f"({mid_x:.0f}, {mid_y:.0f}) — the band is too dense to label there"
            )
        placed.append((left, top, width, height))
        text(canvas, left, top, label, size=PATH_SIZE, family=3, color=color)


def begin_band(canvas: Canvas) -> int:
    """Remember where a band's elements start, so its plate can be slid behind."""
    return len(canvas.elements)


def end_band(canvas: Canvas, mark: int, top: float, title: str, blurb: str) -> float:
    """Draw the backing plate for the band that began at `mark`, behind its nodes.

    The plate is sized from what the band actually contains rather than from a
    guessed height, and is then moved to the front of the band's slice — z-order
    in this format is list order, and a plate appended after its nodes would
    paint over them.
    """
    number = canvas._bands
    canvas._bands += 1
    contents = canvas.elements[mark:]
    bottom = max((e["y"] + e["height"] for e in contents), default=top + 160) + 46

    plate_mark = len(canvas.elements)
    rect(canvas, 30, top, CANVAS_W - 60, bottom - top, stroke=BAND[0], fill=BAND[1], dashed=True)
    text(canvas, 58, top + 20, f"BAND {number}", size=13, family=3, color="#adb5bd")
    text(canvas, 58, top + 40, title, size=23, family=2, color=INK)
    text(canvas, 58, top + 74, blurb, size=13, family=2, color=GREY)

    plate = canvas.elements[plate_mark:]
    del canvas.elements[plate_mark:]
    canvas.elements[mark:mark] = plate
    return bottom


def chain(
    canvas: Canvas,
    x: float,
    y: float,
    specs: list[dict[str, Any]],
    *,
    w: float = 330,
    gap: float = 66,
    connect: bool = True,
    labels: list[str] | None = None,
    link: dict[str, Any] | None = None,
    links: list[dict[str, Any]] | None = None,
) -> list[Box]:
    """A left-to-right run of nodes, connected in order.

    `link` declares what every connecting edge is; `links` overrides it per gap.
    One of them must say — see `arrow`, which refuses an edge that claims
    neither evidence nor concept.
    """
    boxes: list[Box] = []
    cursor = x
    for spec in specs:
        width = spec.pop("w", w)
        boxes.append(node(canvas, cursor, y, width, **spec))
        cursor += width + gap
    if connect:
        for i, (left, right) in enumerate(zip(boxes, boxes[1:], strict=False)):
            edge = (links[i] if links and i < len(links) else link) or {}
            arrow(
                canvas,
                left,
                right,
                label=(labels[i] if labels and i < len(labels) else ""),
                **edge,
            )
    return boxes


def stack(
    canvas: Canvas,
    x: float,
    y: float,
    specs: list[dict[str, Any]],
    *,
    w: float = 330,
    gap: float = 22,
    connect: bool = False,
    link: dict[str, Any] | None = None,
) -> list[Box]:
    """A top-to-bottom column of nodes."""
    boxes: list[Box] = []
    cursor = y
    for spec in specs:
        width = spec.pop("w", w)
        box = node(canvas, x, cursor, width, **spec)
        boxes.append(box)
        cursor = box.bottom + gap
    if connect:
        for left, right in zip(boxes, boxes[1:], strict=False):
            arrow(canvas, left, right, **(link or {}))
    return boxes


# ------------------------------------------------------- facts, not typed --
#
# Everything below is read out of the repository. A number that appears on the
# canvas and also appears in the code appears here exactly once, and it is read
# from the code.

CANVAS_W = 5240


@dataclass(frozen=True)
class Facts:
    layers: dict[str, tuple[str, ...]]
    banned: dict[str, int]
    routes: list[tuple[str, str]]
    artifact_order: list[str]
    target_commands: dict[str, str]
    artifact_files: list[str]
    not_built: list[dict[str, Any]]
    params: Any
    costs: Any
    pool: Any
    equity_pool: Any
    floors: dict[str, Any]
    badge_checks: int
    fee_tiers: dict[int, int]
    tests: dict[str, int]
    capital: float
    gas_quote: float
    # Router's half. Read for the same reason everything else here is: a number
    # on the canvas that also appears in the code appears once, in the code.
    router_params: Any
    switch_cost: Any
    venus_markets: tuple[Any, ...]
    swap_venue: Any
    venus_gas_units: int
    allocation_floors: dict[str, Any]


def _literal(node_: ast.AST) -> Any:
    """`frozenset({...})` and `("a", "b")` alike, without importing the module."""
    if isinstance(node_, ast.Call) and getattr(node_.func, "id", "") == "frozenset":
        return ast.literal_eval(node_.args[0])
    return ast.literal_eval(node_)


def read_layering() -> tuple[dict[str, tuple[str, ...]], dict[str, int]]:
    tree = ast.parse((REPO / "tests" / "test_layering.py").read_text())
    layers: dict[str, tuple[str, ...]] = {}
    banned: dict[str, int] = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id in ("PURE_LAYERS", "IO_LAYERS", "DRIVER_LAYERS"):
            layers[target.id] = tuple(_literal(statement.value))
        elif target.id in ("BANNED_STDLIB", "BANNED_THIRD_PARTY"):
            banned[target.id] = len(_literal(statement.value))
    missing = {"PURE_LAYERS", "IO_LAYERS", "DRIVER_LAYERS"} - layers.keys()
    if missing:
        raise SystemExit(f"tests/test_layering.py no longer defines {sorted(missing)}")
    return layers, banned


def read_routes() -> list[tuple[str, str]]:
    source = (REPO / "apps" / "web" / "src" / "lib" / "routes.ts").read_text()
    block = re.search(r"ROUTES[^=]*=\s*\[(.*?)\]\s*as const", source, re.S)
    if not block:
        raise SystemExit("could not find the ROUTES array in apps/web/src/lib/routes.ts")
    found = re.findall(r'href:\s*"([^"]+)",\s*label:\s*"([^"]+)"', block.group(1))
    if not found:
        raise SystemExit("the ROUTES array parsed to nothing — has its shape changed?")
    return found


def read_artifact_order() -> list[str]:
    line = re.search(r"^artifacts:([^\n#]*)", (REPO / "Makefile").read_text(), re.M)
    if not line:
        raise SystemExit("the Makefile has no `artifacts:` rule")
    return line.group(1).split()


def read_target_commands() -> dict[str, str]:
    """The command each Makefile target actually runs, minus the runner prefix.

    Read rather than restated, so a target renamed or repointed shows up on the
    canvas instead of quietly leaving a stale label behind. Make variables are
    resolved from their own `?=` defaults, because `--synthetic $(ADV_N)` on a
    diagram tells a reader nothing and 9,000 tells them why the floor matters.
    """
    text_ = (REPO / "Makefile").read_text()
    variables = dict(re.findall(r"^([A-Z_]+)\s*\?=\s*(\S*)", text_, re.M))

    def expand(command: str) -> str:
        return re.sub(r"\$\((\w+)\)", lambda m: variables.get(m.group(1), m.group(0)), command)

    out: dict[str, str] = {}
    target = ""
    for line in text_.splitlines():
        rule = re.match(r"^([a-z][a-z0-9-]*):", line)
        if rule:
            target = rule.group(1)
            continue
        if not line.startswith("\t") or not target or target in out:
            continue
        command = line.strip().lstrip("-").strip().rstrip("\\").strip()
        if command.startswith("#") or command.startswith("@"):
            continue
        out[target] = expand(re.sub(r"^\$\(UV\)\s+run\s+(python\s+)?(-u\s+)?", "", command))
    return out


def read_artifact_files() -> list[str]:
    directory = REPO / "apps" / "web" / "public" / "artifacts"
    return sorted(p.name for p in directory.glob("*.json")) if directory.is_dir() else []


def read_badge_checks() -> int:
    """How many checks `evaluate` actually runs, counted from its body."""
    tree = ast.parse((REPO / "packages" / "misquote" / "vetting" / "badge.py").read_text())
    for statement in ast.walk(tree):
        if isinstance(statement, ast.FunctionDef) and statement.name == "evaluate":
            return sum(
                1
                for call in ast.walk(statement)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id.startswith("_check_")
            )
    raise SystemExit("packages/misquote/vetting/badge.py no longer defines evaluate()")


def count_tests() -> dict[str, int]:
    """Test files per area. Files, not cases — the case count has its own guard."""
    root = REPO / "tests"
    counts: dict[str, int] = {}
    for path in sorted(root.rglob("test_*.py")):
        area = path.parent.name if path.parent != root else "root"
        counts[area] = counts.get(area, 0) + 1
    return counts


def gather() -> Facts:
    from misquote.agents.router.policy import RouterParams
    from misquote.chain.addresses import EQUITY_POOL, TARGET_POOL
    from misquote.chain.venus import (
        STABLE_SWAP_VENUE,
        VENUS_SWITCH_GAS_UNITS,
        markets_on,
    )
    from misquote.core.types import DEFAULT_CAPITAL_QUOTE, DEFAULT_GAS_QUOTE, Params
    from misquote.replay import allocation as allocation_mod
    from misquote.replay import ranges
    from misquote.replay.allocation import FALLBACK_GAS_QUOTE, SwitchCost
    from misquote.replay.driver import CostModel
    from misquote.replay.engine import MIN_SWAPS_FOR_TOXICITY_VERDICT
    from misquote.tearsheet.advantage import MATERIAL_PP
    from misquote.tearsheet.generate import MIN_OBSERVATIONS
    from misquote.tearsheet.ledger import to_dicts
    from misquote.vetting.badge import FEE_TIER_SPACING

    layers, banned = read_layering()
    return Facts(
        layers=layers,
        banned=banned,
        routes=read_routes(),
        artifact_order=read_artifact_order(),
        target_commands=read_target_commands(),
        artifact_files=read_artifact_files(),
        not_built=to_dicts(),
        params=Params(),
        costs=CostModel(),
        pool=TARGET_POOL,
        equity_pool=EQUITY_POOL,
        floors={
            "MIN_SAMPLES": ranges.MIN_SAMPLES,
            "MIN_WINDOW_HOURS": ranges.MIN_WINDOW_HOURS,
            "MIN_HOURS_TO_ANNUALISE": ranges.MIN_HOURS_TO_ANNUALISE,
            "MIN_OBSERVATIONS": MIN_OBSERVATIONS,
            "MIN_SWAPS_FOR_TOXICITY_VERDICT": MIN_SWAPS_FOR_TOXICITY_VERDICT,
            "MATERIAL_PP": MATERIAL_PP,
        },
        router_params=RouterParams(),
        # The offline shape of the cost model. `chain/costs.py` derives the live
        # one; this canvas reads no chain, so it draws the fallback and says so
        # — which is the distinction `derived` exists to carry.
        switch_cost=SwitchCost.from_venue(
            STABLE_SWAP_VENUE,
            gas_units=VENUS_SWITCH_GAS_UNITS,
            gas_price_wei=None,
            native_price_quote=None,
        ),
        venus_markets=tuple(markets_on(56)),
        swap_venue=STABLE_SWAP_VENUE,
        venus_gas_units=VENUS_SWITCH_GAS_UNITS,
        allocation_floors={
            "MIN_SAMPLES": allocation_mod.MIN_SAMPLES,
            "MIN_WINDOW_HOURS": allocation_mod.MIN_WINDOW_HOURS,
            "MIN_HOURS_TO_ANNUALISE": allocation_mod.MIN_HOURS_TO_ANNUALISE,
            "FALLBACK_GAS_QUOTE": FALLBACK_GAS_QUOTE,
        },
        badge_checks=read_badge_checks(),
        fee_tiers=dict(FEE_TIER_SPACING),
        tests=count_tests(),
        capital=DEFAULT_CAPITAL_QUOTE,
        gas_quote=DEFAULT_GAS_QUOTE,
    )


# ------------------------------------------------------------- the bands --
#
# Read top to bottom. Each function takes the y its band starts at and returns
# the y the next one may start at.

GAP = 44

# The reading order, and the only place a band number exists. `BAND_NO` turns a key
# into the numeral the plate will show, so a cross-reference in prose cannot
# drift from the band it points at — which is exactly what happened when the
# vocabulary band was inserted and nine typed numerals silently became wrong.
BAND_ORDER = (
    "map",
    "vocabulary",
    "spine",
    "tape",
    "decision",
    "quote",
    "router",
    "publish",
    "web",
    "proof",
    "refusals",
    "next",
)
BAND_NO = {key: number for number, key in enumerate(BAND_ORDER)}


def band_map(canvas: Canvas, f: Facts, top: float) -> float:
    mark = begin_band(canvas)
    y = top + 116

    text(
        canvas,
        58,
        y,
        "MISQUOTE — the whole system, end to end",
        size=38,
        family=2,
        color=INK,
    )
    text(
        canvas,
        58,
        y + 54,
        "Agent marketplace for BNB Chain. One engine replays four policies on real pool history and quotes a\n"
        "P25-P75 range instead of a number. The interesting part of the architecture is everything it refuses to say.",
        size=15,
        family=2,
        color=GREY,
    )

    legend_y = y + 118
    text(canvas, 58, legend_y, "COLOUR = LAYER CLASS", size=12, family=3, color=GREY)
    swatches = [
        ("pure", "pure layers", "core · estimators · lvr · replay"),
        ("data", "i/o and data", "chain · indexer · sqlite · json"),
        ("drive", "drivers", "agents · ops · registry · tearsheet"),
        ("web", "front end", "apps/web, static export"),
        ("stop", "refusals and gates", "the thing that says no"),
        ("test", "tests and spec", "what forbids the rest"),
    ]
    x = 58
    for kind, label, detail in swatches:
        stroke, fill = KINDS[kind]
        rect(canvas, x, legend_y + 22, 20, 20, stroke=stroke, fill=fill)
        text(canvas, x + 30, legend_y + 22, label, size=13, family=2, color=stroke)
        text(canvas, x + 30, legend_y + 40, detail, size=11, family=3, color=GREY)
        x += 300

    text(canvas, 58, legend_y + 82, "ARROWS", size=12, family=3, color=GREY)
    text(
        canvas,
        58,
        legend_y + 102,
        "solid = data or control flows this way        dashed = this forbids, proves or guards that",
        size=13,
        family=2,
        color=GREY,
    )

    facts_y = legend_y + 148
    tests_total = sum(f.tests.values())
    node(
        canvas,
        58,
        facts_y,
        1180,
        title="What is on this canvas",
        kind="test",
        body=(
            f"{len(BAND_ORDER)} bands. {BAND_NO['vocabulary']} the vocabulary, if a term below is new · "
            f"{BAND_NO['spine']} the spine · {BAND_NO['tape']} chain to tape · "
            f"{BAND_NO['decision']} inside one decision · {BAND_NO['quote']} replay to quote · "
            f"{BAND_NO['publish']} the artifact pipeline · {BAND_NO['web']} the front end · "
            f"{BAND_NO['proof']} proof and gates · {BAND_NO['refusals']} every refusal in one place · "
            f"{BAND_NO['next']} what is not built, and where to work next."
        ),
        tag="read top to bottom · every node drags as one object · jargon is band 1",
    )
    node(
        canvas,
        1278,
        facts_y,
        1180,
        title="Generated, not drawn",
        kind="drive",
        path="make diagram  ->  scripts/gen_flow_diagram.py",
        body=(
            "Layout is authored once. Every list and every threshold below is read out of the "
            "repository at generation time, so this cannot drift from the code the way a drawing does. "
            "Re-running with nothing changed rewrites the same bytes."
        ),
        tag="derived here: routes · ledger · layers · floors · artifact order · pool",
    )
    node(
        canvas,
        2498,
        facts_y,
        1180,
        title="The repository, counted",
        kind="data",
        body=(
            f"{len(f.layers['PURE_LAYERS'])} pure layers, {len(f.layers['IO_LAYERS'])} i/o layers, "
            f"{len(f.layers['DRIVER_LAYERS'])} driver layers · "
            f"{tests_total} test files across {len(f.tests)} areas · "
            f"{len(f.artifact_files)} published artifacts feeding {len(f.routes)} routes · "
            f"{len(f.not_built)} capabilities advertised and not built."
        ),
        tag=f"target pool: {f.pool.label}",
    )
    node(
        canvas,
        3718,
        facts_y,
        1440,
        title="The one claim everything else serves",
        kind="stop",
        body=(
            "A quote is a range with its assumptions attached, and where the evidence is thin the "
            f"system publishes nothing rather than a number. Band {BAND_NO['refusals']} collects every place "
            "that happens; each one is a floor in code, not a paragraph in a doc."
        ),
        tag="if a number cannot be traced, it does not render",
    )
    return end_band(
        canvas,
        mark,
        top,
        "THE MAP",
        "what this canvas is, what the colours mean, and where the numbers on it come from",
    )


def band_vocabulary(canvas: Canvas, f: Facts, top: float) -> float:
    """Every term the rest of the canvas uses without stopping to explain.

    Three vocabularies meet in this repository — concentrated-liquidity AMMs,
    market-making theory, and backtesting discipline — and a sentence like
    "realized LVR net of the protocol cut, winsorised, over the trailing window"
    is four of them at once. The definitions are deliberately blunt and one line
    each; the precise version is always the code the term links to.

    Numbers here are read from the same place the rest of the canvas reads them,
    so a default that changes cannot leave a stale definition behind.
    """
    mark = begin_band(canvas)
    y = top + 118
    p_ = f.params
    pool = f.pool

    cards = [
        (
            "Concentrated liquidity — the venue",
            "data",
            "PancakeSwap v3 (Uniswap v3 math)",
            [
                "pool — one token pair at one fee tier. A different tier is a different pool with its own price and depth.",
                "tick — one 1.0001x step in price. v3 speaks in ticks, not prices; 100 ticks is about 1%.",
                f"tick spacing — only every Nth tick may be used as a bound. {pool.tick_spacing} on the target pool; it is fixed by the fee tier.",
                "sqrtPriceX96 / Q96 — the price as its square root, times 2^96, as an integer. Fixed-point, because Solidity has no floats.",
                "range position — liquidity supplied between a lower and an upper tick. Outside that band it earns nothing.",
                "liquidity (L) — the size of a position in v3's own units. Not a token amount: what it is worth depends on where price sits.",
                "in range — price is between the bounds, so the position is earning fees. Out of range it is one token, idle.",
                "mint / burn / collect — open a position, close it, sweep the fees it accrued. A recentre is all three plus a new mint.",
                "NFPM — NonfungiblePositionManager, the contract that holds v3 positions as NFTs and the one this agent transacts against.",
                f"fee tier / pips — the swap fee, in millionths. {pool.fee_pips} pips is {pool.fee_pips / 10_000:.2f}%.",
                f"feeProtocol — the share of that fee the protocol keeps before LPs see any. {pool.fee_protocol} here, so LPs keep {100 - pool.fee_protocol / 100:.0f}%. Uniswap's is off; Pancake's is not.",
                "slot0 — the pool's current price, tick and fee configuration, in one call.",
                "LP — liquidity provider. The role this whole system is automating.",
            ],
        ),
        (
            "Market making — the theory",
            "pure",
            "Avellaneda-Stoikov, mapped onto ranges",
            [
                "Avellaneda-Stoikov — the standard model for where a market maker should quote given inventory, volatility and time left. Equations (1) and (2).",
                "reservation price — the centre a maker quotes around, pushed away from mid by the inventory it is stuck with.",
                "half-spread — how far from the centre to quote. Here it becomes the half-width of the range.",
                "inventory (q) — how lopsided the position is, from -1 (all token1) to +1 (all token0). It skews the centre.",
                "fill intensity (kappa) — how quickly the chance of being traded against falls off with distance from mid. Large kappa means flow is concentrated at the mid, so the range tightens.",
                "adverse selection — losing to someone who knows more than you. For an AMM the informed trader is the arbitrageur.",
                "informed flow / toxicity — trades that carry information. The right response is to stop quoting, which here means withdrawing the range.",
                "LVR — loss-versus-rebalancing: what the position gave up by trading at the pool's stale price instead of the market's. The cost of being an AMM.",
                "MEV — value extracted by whoever orders the transactions. Charged here as a haircut on whatever a move has to swap.",
                "slippage — the gap between the price you expect and the price you get.",
                "notional — the amount actually being swapped. Not the position's value: a recentre trades the imbalance, not the whole thing.",
                "bps — basis points, hundredths of a percent. 10 bps is 0.1%.",
                "CEX-DEX gap — how far a centralised exchange has moved ahead of the pool. Wider than the round-trip arbitrage cost means the next trade is an arbitrageur.",
            ],
        ),
        (
            "Statistics — how the numbers are made",
            "pure",
            "and where each one refuses",
            [
                "EWMA — exponentially weighted moving average: recent observations count more, older ones fade.",
                "half-life — how long until an observation counts half as much. Six hours for the volatility estimator.",
                "winsorising — clipping extreme observations before averaging, so one outlier cannot dominate. Clip too aggressively and you are reshaping the distribution, not containing it.",
                "z-score — how many standard deviations from normal. Used here to say flow is running one way unusually hard.",
                "percentile / P25-P75 — order statistics. A quarter of outcomes fell below P25, a quarter above P75, so the band is the middle half.",
                "annualising — scaling a short result up to a year. Legitimate only if the period is long enough to survive the multiplication.",
                f"sample floor — the count below which a result is withheld instead of reported. {f.floors['MIN_SAMPLES']} replays for a quote, {f.floors['MIN_OBSERVATIONS']} observations for a verdict.",
                "r-squared — how much of the data a fit actually explains. A poor one means the parameter came from a default, and the card has to say so.",
                "ablation — rerunning the same thing with one behaviour switched off, to isolate what that behaviour was worth.",
                f"materiality — the size below which a difference is noise rather than a finding. {f.floors['MATERIAL_PP']}pp here.",
                "power law vs exponential — two different shapes of decay. Fitting one to data generated by the other is assumption A8's admitted approximation.",
            ],
        ),
        (
            "Backtesting — and its ways of lying",
            "test",
            "what the replay engine is defending against",
            [
                "replay — running a policy over recorded history to see what it would have done. Never what it did.",
                "tape — that recorded history, as a file. One pool's swaps in order.",
                "frontier — how far through the tape the replay has been allowed to see. It only moves forward.",
                "look-ahead bias — letting the policy see data from after the moment it is deciding. The classic way a backtest flatters itself; T1 and T3 exist for it.",
                "counterfactual — a result for a position nobody actually held. Every card here is one, and says so.",
                "baseline / DIY — what you would have done instead. Here: mint once at the same width and never touch it.",
                "perturbation — rerunning with a parameter nudged, to see whether the answer survives. Assumption A5 nudges gamma by a quarter.",
                "rolling window — cutting history into overlapping slices and replaying each, so the answer is not a statement about one lucky fortnight.",
                "determinism — same input, same bits out. Required, because T1 and L1 compare decision sequences bitwise.",
                "differential test — asking two independent implementations the same question and demanding they agree exactly. Here: our tick math against the deployed Solidity.",
                "vectors — the recorded answers from such a run, replayed offline on every commit.",
                "fork / anvil — a local copy of the real chain at a real block, so a transaction can be run against real contracts without spending anything.",
            ],
        ),
        (
            "Chain and standards — the plumbing",
            "data",
            "reading BSC, and the agent registries",
            [
                "eth_getLogs — the RPC call that fetches past events. Expensive, rationed, and the constraint the whole indexer is shaped around.",
                "block range — how many blocks one such call may cover. 5,000 is what the endpoints that answer at all will serve.",
                "backfill vs follow — fetching history backwards versus keeping up with the head. One can recover the past; the other only accumulates.",
                "cursor vs coverage — a single high-water mark versus the set of ranges actually read. Only the second can describe a tape with a hole in it.",
                "WAL — SQLite's write-ahead log, which lets the agent read while the indexer writes.",
                "uint256 as TEXT — chain integers exceed SQLite's signed 64-bit INTEGER and would truncate silently, so they are stored as strings.",
                "dry run — the default posture: build the transaction, refuse to broadcast it.",
                "kill switch — a file on disk whose presence stops the agent. Checked by the loop and again inside the signer.",
                "session keys — a scoped, revocable permission to act on someone's behalf, with a spend cap and an expiry. Advertised here and not built.",
                "ERC-8004 — an identity registry for agents, as NFTs whose token URI is the agent's card.",
                "ERC-8183 — a job-escrow interface: hire an agent, hold payment, release on completion.",
                "AACP — TermiX's commerce protocol, which builds on both of the above and, it turns out, on the same deployed registry we already read.",
                "tokenURI — where an NFT's metadata lives. On-chain base64 always resolves; an https one may not, and conflating them reports a card as readable when nothing was fetched.",
            ],
        ),
    ]

    boxes = []
    cursor = 58.0
    for title, kind, subtitle, terms in cards:
        boxes.append(
            node(
                canvas,
                cursor,
                y,
                1000,
                title=title,
                kind=kind,
                path=subtitle,
                body="\n".join(terms),
            )
        )
        cursor += 1036

    y2 = max(box.bottom for box in boxes) + 40
    node(
        canvas,
        58,
        y2,
        2036,
        title="Notation, and where each symbol is consumed",
        kind="pure",
        path="core/types.py :: Params · core/policy.py",
        body=(
            f"gamma {p_.gamma} — risk aversion. Bigger means a wider, more defensive range. A user preference, published with three settings.\n"
            f"sigma — volatility per square-root hour, from the EWMA estimator. Sets how wide the range has to be.\n"
            f"kappa — fill intensity, fitted from how far swaps travel. Sets how tight it can afford to be.\n"
            f"q — inventory imbalance in [-1, +1]. Skews the centre so the position sells down whatever it holds too much of.\n"
            f"delta* — the optimal half-width in log-price, from equation (2), before it is turned into ticks.\n"
            f"T - t — how much of the rolling window is left. Constant at {p_.window_hours:.0f}h here, not decaying.\n"
            f"theta {p_.theta} — how far the range must have drifted, as a fraction of its own width, before moving is considered.\n"
            f"delta_s {p_.sample_interval_s}s — the sampling interval. Decisions are taken on this grid, not per trade.\n"
            f"m_toxic {p_.m_toxic} / m_clear {p_.m_clear} — consecutive samples a condition must hold before withdrawing, and before returning.\n"
            f"z_pull {p_.z_pull} — the imbalance z-score that triggers a withdrawal on its own.\n"
            f"epsilon {p_.eps_liquidity_share:.0%} — the largest share of a pool a replayed position may be. Breaching it refuses the quote."
        ),
    )
    node(
        canvas,
        2130,
        y2,
        1500,
        title="Two ids that are not what they look like",
        kind="stop",
        body=(
            "A1..A12 are published assumptions, in docs/ASSUMPTIONS.md — things taken on faith, each one "
            "chosen to make the headline number worse rather than better.\n"
            "P-n, V-n, D-n, G-n are entries in docs/REQUIREMENTS_MATRIX.md — P for problems found in "
            "review, V for defects the build found in itself, D for deliberate deviations from the frozen "
            "spec, G for values that had to be measured before they could be published.\n"
            "T1-T4 and L1 are tests. Both series render on the site, one click from any figure citing them."
        ),
        tag="a citation that does not resolve is a defect the assumption sheet catches",
    )
    node(
        canvas,
        3666,
        y2,
        1492,
        title="The one sentence the vocabulary is in service of",
        kind="stop",
        body=(
            "A liquidity position earns fees while price sits inside its range and loses to arbitrage "
            "whenever price moves. An agent that manages the range is betting the first exceeds the second, "
            "net of what moving costs. Everything on this canvas is machinery for measuring that bet "
            "honestly on history nobody can retroactively choose."
        ),
    )
    return end_band(
        canvas,
        mark,
        top,
        "THE VOCABULARY",
        "three trades' worth of jargon meet in this repo — this is all of it, one line each",
    )


def band_spine(canvas: Canvas, f: Facts, top: float) -> float:
    """The call graph, drawn as the call graph.

    The first version of this band drew `WardenLive -> WardenLoop ->
    ChainExecutor`, and read left to right as though history flowed into the
    engine. Both are wrong, and the shape of the mistake is worth keeping in
    mind while reading the rest of the canvas: **layer 3 owns the loop and calls
    layer 2**, so the picture is a round trip rather than a pipeline. The engine
    never fetches anything and never acts on anything; a driver hands it a window
    of events and a market state, and gets a Decision back.
    """
    mark = begin_band(canvas)
    y = top + 152

    text(
        canvas,
        58,
        y - 30,
        "LAYER 1 · history, from a file or from a node",
        size=13,
        family=2,
        color=GREY,
    )
    sources = chain(
        canvas,
        58,
        y,
        [
            dict(
                title="MemoryTape · SqliteTape",
                kind="pure",
                path="replay/tape.py · indexer/tape_source.py",
                body="advance_to(t) yields (frontier, t] and nothing else. The frontier only moves forward; asking it to rewind raises.",
                tag="no next-N, no events-near-t, no last-before-t",
            ),
            dict(
                title="the ChainSource protocol",
                kind="data",
                path="chain/source.py :: TapeChainSource · chain/live_source.py :: LiveChainSource",
                body=(
                    "One interface, two implementations, and the agent cannot tell them apart. "
                    "**TapeChainSource** serves recorded history — which is the only reason test L1 can "
                    "exist. **LiveChainSource** reads a node, and runs two clocks deliberately: the "
                    f"decision clock ticks at delta_s = {f.params.sample_interval_s}s, the poll clock is "
                    "however often a free endpoint will answer. Between polls it returns nothing rather "
                    "than pretending to be fresh."
                ),
                tag="deviation D-9: m consecutive samples spans m x poll_seconds",
                w=802,
            ),
        ],
        w=380,
        gap=42,
        connect=False,
    )

    y2 = max(box.bottom for box in sources) + 80
    text(
        canvas,
        58,
        y2 - 32,
        "LAYER 3 · the drivers. These own the loop, and they are the only things that read history or act on a decision.",
        size=13,
        family=2,
        color=GREY,
    )
    replay_driver = node(
        canvas,
        58,
        y2,
        380,
        title="ReplayDriver.run(tape)",
        kind="drive",
        path="replay/driver.py",
        body="Pulls the next window off the tape, calls the engine, applies what comes back to a hypothetical position and charges a cost model for it.",
        tag=f"-> band {BAND_NO['quote']}",
    )
    loop = node(
        canvas,
        900,
        y2,
        380,
        title="WardenLoop",
        kind="drive",
        path="agents/warden/loop.py",
        body=(
            "Four asyncio tasks and one kill switch. It calls decide(), journals the result, and offers "
            "any action to a one-slot queue that replaces on full — a rebalance computed ninety seconds "
            "ago is worse than none. Execution runs on a worker thread so the kill-file check never blocks."
        ),
        tag="the loop drives the agent, not the other way round",
    )
    warden_live = node(
        canvas,
        1322,
        y2,
        380,
        title="WardenLive",
        kind="drive",
        path="agents/warden/live.py",
        body=(
            "decide(t) reads the source and calls the engine; perform(d) acts and only then tells the "
            "engine what position resulted — so if the executor raises, the agent's idea of its position "
            "stays equal to the chain's."
        ),
    )
    arrow(canvas, sources[0], replay_driver, evidence="misquote.replay.driver:tape", label="tape")
    arrow(canvas, sources[1], warden_live, evidence="misquote.agents.warden.live:ChainSource")
    arrow(
        canvas,
        loop,
        warden_live,
        label="decide(t) · perform(d)",
        evidence="misquote.agents.warden.loop:warden",
    )

    y3 = max(replay_driver.bottom, loop.bottom, warden_live.bottom) + 86
    text(
        canvas,
        58,
        y3 - 32,
        "LAYER 2 · the shared decision. Called by both drivers, with no way to tell which one is calling.",
        size=13,
        family=2,
        color=GREY,
    )
    engine = node(
        canvas,
        480,
        y3,
        800,
        title="Engine.step(events, market) -> Decision",
        kind="pure",
        path="replay/engine.py",
        body=(
            "Ingest the window, update the estimators, assemble an Observation, call the policy, return "
            "a Decision. It holds no capability to act, cannot read a clock or a socket, and cannot tell "
            f"which driver is calling it. Opened up in band {BAND_NO['decision']}."
        ),
        tag="there is no `if replay:` here, and there cannot be",
    )
    arrow(
        canvas,
        replay_driver,
        engine,
        label="events + MarketState",
        evidence="misquote.replay.driver:Engine",
    )
    arrow(
        canvas,
        warden_live,
        engine,
        label="events + MarketState",
        evidence="misquote.agents.warden.live:Engine",
    )

    y4 = engine.bottom + 76
    applied = node(
        canvas,
        58,
        y4,
        380,
        title="_apply -> ReplayResult",
        kind="drive",
        path="replay/driver.py",
        body="Settle what the closing position earned, open the new range, charge for the move. Nothing is signed and nothing exists.",
        tag=f"-> band {BAND_NO['quote']}",
    )
    executor = node(
        canvas,
        900,
        y4,
        802,
        title="the Executor protocol — and the one nothing constructs",
        kind="stop",
        path="agents/warden/live.py :: Executor",
        body=(
            "WardenLive.perform calls executor.mint / rebalance / pull. Three implementations exist: "
            "SimulatedExecutor (tests), RecordingExecutor (what `make warden` actually runs — it journals "
            "instead of signing), and ChainExecutor, which broadcasts. **Nothing constructs the third.** "
            "agents/warden/__main__.py does not import it, the not-built ledger says so, and a test holds "
            "that claim to the file. So the live lane below this box is built and unwired."
        ),
        tag=f"-> band {BAND_NO['next']}, 'Signing on a live chain'",
    )
    arrow(canvas, engine, applied, label="Decision", evidence="misquote.replay.driver:Decision")
    arrow(
        canvas,
        engine,
        warden_live,
        label="Decision",
        evidence="misquote.agents.warden.live:Decision",
        dashed=True,
    )
    arrow(
        canvas,
        warden_live,
        executor,
        label="perform",
        evidence="misquote.agents.warden.live:executor",
    )

    signer = node(
        canvas,
        1764,
        y4,
        380,
        title="PositionManager · BscSigner",
        kind="data",
        path="chain/nfpm.py · chain/signer.py",
        body=(
            "decreaseLiquidity, collect, burn, mint — closing first, so a crash in the middle leaves the "
            "agent flat and solvent rather than stranded. The signer asserts the chain id, refuses unless "
            "explicitly taken out of dry run, checks for a revert, and reads the kill file immediately "
            "before broadcast."
        ),
        tag="dry run is the default, not a flag",
    )
    arrow(canvas, executor, signer, evidence="misquote.chain.executor:PositionManager")

    y5 = max(applied.bottom, executor.bottom, signer.bottom) + 76
    firewall = node(
        canvas,
        58,
        y3,
        396,
        title="The purity firewall",
        kind="test",
        path="tests/test_layering.py",
        body=(
            f"{', '.join(f.layers['PURE_LAYERS'])} may not import "
            f"{f.banned['BANNED_STDLIB']} stdlib modules or "
            f"{f.banned['BANNED_THIRD_PARTY']} third-party ones — including time, socket, sqlite3, "
            "random and web3. A layer that cannot read a clock cannot read the future."
        ),
        tag="EXEMPTIONS is empty, and adding one is the trade",
    )
    l1 = node(
        canvas,
        1764,
        y2,
        396,
        title="L1 · the two drivers are one policy",
        kind="test",
        path="tests/replay/test_l1_equivalence.py",
        body=(
            "WardenLive is pointed at a tape-backed source and its decision sequence is compared byte for "
            "byte with ReplayDriver's over the same tape. T1 proves the replay could not cheat; L1 proves "
            "the thing that cheated is the thing that will trade."
        ),
    )
    arrow(canvas, firewall, engine, dashed=True, color=TEST[0], kind="concept")
    arrow(canvas, l1, warden_live, dashed=True, color=TEST[0], kind="concept")

    node(
        canvas,
        58,
        y5,
        420,
        title="What layer 2 may not do",
        kind="stop",
        body=(
            "It cannot read a clock, a socket or a database, so it cannot read the future. Reading market "
            "state is the one capability that genuinely differs between live and replay, so the driver "
            "supplies it as a MarketState argument and it lives in exactly one place."
        ),
        tag="the guarantee is structural, not reviewed",
    )
    node(
        canvas,
        522,
        y5,
        420,
        title="Why this is worth the trouble",
        kind="stop",
        body=(
            "The usual architecture has a replay harness that resembles the live loop and drifts from it "
            "quietly. Here the resemblance is a test. Every claim on the site is about the policy that "
            "would actually trade, not about a simulator of it."
        ),
    )

    node(
        canvas,
        2270,
        y,
        1420,
        title="How to read this band",
        kind="test",
        body=(
            "Top to bottom is one turn of the loop, not a pipeline. A driver (layer 3) pulls a window of "
            "events off layer 1, hands it down to layer 2, and gets a Decision back — which is why the "
            "engine sits *below* the things that call it. Follow the left column for a replay and the "
            "right one for the live agent; they meet in the middle, and that meeting is the product claim."
        ),
        tag="the two lanes share exactly one implementation of the policy",
    )
    node(
        canvas,
        2270,
        y + 250,
        1420,
        title="Where a change lands",
        kind="test",
        body=(
            f"New strategy -> a Policy function, band {BAND_NO['decision']}. New market signal -> an "
            f"estimator plus one Observation field, band {BAND_NO['decision']}. New cost -> CostModel and "
            f"the assumption sheet, band {BAND_NO['quote']}. New published number -> an emitter, a "
            f"TypeScript interface and a contract test, bands {BAND_NO['publish']} and {BAND_NO['web']}. "
            f"New chain read -> chain/ or indexer/, band {BAND_NO['tape']} — never core/."
        ),
        tag="if the change wants a clock inside a pure layer, the design is wrong",
    )
    node(
        canvas,
        2270,
        y + 500,
        1420,
        title="The layers, as the test enforces them",
        kind="test",
        body=(
            f"pure: {', '.join(f.layers['PURE_LAYERS'])}   |   "
            f"i/o: {', '.join(f.layers['IO_LAYERS'])}   |   "
            f"drivers: {', '.join(f.layers['DRIVER_LAYERS'])}"
            "\ncore/ is the base of the tower and depends on nothing of ours; pure layers may not import "
            "i/o or driver layers even transitively."
        ),
    )
    node(
        canvas,
        3738,
        y,
        1420,
        title="Every arrow on this canvas is checked",
        kind="stop",
        path="scripts/gen_flow_diagram.py :: check_evidence",
        body=(
            "A structural edge declares the symbol that makes it true — 'the module at the tail "
            "references this' — and the generator resolves that against the parsed source before it will "
            "write the file. Conceptual edges (a guard, a sequence, a claim) must say so explicitly, so "
            "an undeclared call edge fails rather than passing quietly."
        ),
        tag="this band is the reason the check exists — see the docstring",
    )
    node(
        canvas,
        3738,
        y + 300,
        1420,
        title="What the first version of this band got wrong",
        kind="stop",
        body=(
            "It drew WardenLive -> WardenLoop -> ChainExecutor, when the loop calls the agent and the "
            "agent calls the executor. It drew the tape reaching the engine, which nothing does. And it "
            "drew ChainExecutor in the same style as the wired components, which is the failure this "
            "project is named after — a plausible arrow looks exactly like a correct one."
        ),
    )
    return end_band(
        canvas,
        mark,
        top,
        "THE SPINE — ONE ENGINE, TWO DRIVERS",
        "the real call graph: layer 3 owns the loop and calls layer 2, and the tests that stop the two lanes becoming two programs",
    )


def band_tape(canvas: Canvas, f: Facts, top: float) -> float:
    mark = begin_band(canvas)
    y = top + 118

    rpc = node(
        canvas,
        58,
        y,
        346,
        title="BSC RPC endpoints",
        kind="data",
        path="indexer/reader.py :: connect_all",
        body=(
            "Twenty-two public endpoints were probed; three serve eth_getLogs at all. The rest answer "
            "for chain 56 and refuse every log query, so the health check probes the capability rather "
            "than the chain id."
        ),
        tag="no key needed — measured, not assumed",
    )
    reader = node(
        canvas,
        470,
        y,
        346,
        title="BscReader",
        kind="data",
        path="indexer/reader.py",
        body=(
            "5,000-block windows, the ceiling both log-serving endpoints declare. A refusal halves the "
            "chunk and retries; 'exceed maximum block range' is classified as a range error rather "
            "than a transient one, so a tighter cap corrects itself."
        ),
    )
    backfill = node(
        canvas,
        882,
        y,
        346,
        title="backfill",
        kind="drive",
        path="indexer/backfill.py",
        body=(
            "Resumes from the ranges nobody has read, not from the cursor — a cursor is one high-water "
            "mark, so once the tail has run it is the head. Block time is measured at runtime; BSC has "
            "changed it three times."
        ),
        tag="30 days ~ 1,151 chunks, ~62 minutes, no key",
    )
    follow = node(
        canvas,
        882,
        y + 250,
        346,
        title="follow",
        kind="drive",
        path="indexer/follow.py",
        body="One chunk per poll, ahead of a chain that produces a 5,000-block chunk every ~37 minutes. It can accumulate history going forward and close its own gaps; it cannot recover the past.",
    )
    store = node(
        canvas,
        1294,
        y + 100,
        346,
        title="store",
        kind="data",
        path="indexer/store.py",
        body="INSERT OR IGNORE on (tx, log_index) — the chain's own identity for a log. The cursor and the coverage range advance inside the same transaction as the rows they cover.",
        tag="re-running a backfill is a no-op",
    )
    db = node(
        canvas,
        1706,
        y + 100,
        346,
        title="data/misquote.db",
        kind="data",
        path="indexer/schema.sql",
        body="pool · block · swap · mint · burn · pool_state · cursor · covered. WAL, so the agent reads while the indexer writes.",
    )
    tape = node(
        canvas,
        2118,
        y + 100,
        346,
        title="the tape",
        kind="pure",
        path="indexer/tape_source.py",
        body="A cursor over the swap table, bounded by a SQL parameter rather than by a list in memory — so there is no in-memory future to leak. Same protocol as MemoryTape.",
        tag=f"-> band {BAND_NO['decision']}",
    )
    arrow(canvas, rpc, reader, evidence="misquote.indexer.reader:connect_all")
    arrow(canvas, reader, backfill, evidence="misquote.indexer.backfill:BscReader")
    arrow(canvas, reader, follow, evidence="misquote.indexer.follow:BscReader")
    arrow(canvas, backfill, store, evidence="misquote.indexer.backfill:store")
    arrow(canvas, follow, store, evidence="misquote.indexer.follow:store")
    arrow(canvas, store, db, evidence="misquote.indexer.store:SCHEMA_PATH")
    # The tape holds its own connection rather than going through `store`: the
    # frontier has to be a SQL parameter, not a slice of a list in memory.
    arrow(canvas, db, tape, evidence="misquote.indexer.tape_source:sqlite3")

    node(
        canvas,
        2530,
        y,
        420,
        title="Three load-bearing schema decisions",
        kind="stop",
        path="indexer/schema.sql",
        body=(
            "Every uint256 is TEXT: SQLite's INTEGER is signed 64-bit and would truncate sqrtPriceX96 "
            "and liquidity silently. Every event table is keyed on (tx, log_index). Amounts are stored "
            "gross of the fee, because deriving net here would make the fee unrecoverable — P-2."
        ),
    )
    node(
        canvas,
        2530,
        y + 280,
        420,
        title="covered is not cursor",
        kind="stop",
        body=(
            "A quiet 5,000-block window and one nobody fetched both hold zero swaps, and no query over "
            "the swap table can tell them apart. So the ranges actually read are recorded separately. "
            "A database predating that table reports no coverage, never full coverage."
        ),
        tag="unknown does not become pass",
    )
    node(
        canvas,
        3000,
        y,
        420,
        title="The gap count travels with the card",
        kind="stop",
        path="scripts/showcase.py :: tape_coverage_gaps",
        body=(
            "None and [] are different claims: [] says we checked and there are no holes, None says "
            "nobody can now say. The build stamp carries both, so a card stamped 'chain' over a tape "
            "with a hole in it is visible rather than plausible."
        ),
    )
    node(
        canvas,
        3000,
        y + 280,
        420,
        title="What the live path reads instead",
        kind="data",
        path="chain/live_source.py",
        body=(
            "slot0, liquidity, and eth_gasPrice turned into the cost of one recentre — 600,000 gas at "
            "the prevailing price, in token1. That is the number CostModel.gas_quote stands in for "
            "during a replay."
        ),
    )
    node(
        canvas,
        3470,
        y,
        1690,
        title="The pool everything is measured on",
        kind="data",
        body=(
            f"{f.pool.label}\n{f.pool.address}   fee {f.pool.fee_pips} pips · tick spacing "
            f"{f.pool.tick_spacing} · feeProtocol {f.pool.fee_protocol} (LPs keep "
            f"{100 - f.pool.fee_protocol / 100:.0f}%) · quote unit {f.pool.quote_symbol}\n"
            f"Second venue, priced with no code changes: {f.equity_pool.label} — different fee tier, "
            f"different spacing, feeProtocol {f.equity_pool.fee_protocol}."
        ),
        tag="every address verified against chain, never copied from docs",
    )
    node(
        canvas,
        3470,
        y + 200,
        1690,
        title="What the indexer is tested for",
        kind="test",
        path="tests/indexer/",
        body=(
            f"{f.tests.get('indexer', 0)} files: the reader's chunk adaptation, coverage arithmetic and "
            "gap detection, the tape's frontier discipline, and that following forward cannot "
            "manufacture history it never read."
        ),
    )
    return end_band(
        canvas,
        mark,
        top,
        "CHAIN -> TAPE",
        "how real pool history gets onto disk, and why the coverage table matters more than the cursor",
    )


def band_decision(canvas: Canvas, f: Facts, top: float) -> float:
    mark = begin_band(canvas)
    y = top + 118
    p = f.params

    guard = node(
        canvas,
        454,
        y,
        330,
        title="T3 · the look-ahead guard",
        kind="stop",
        path="estimators/base.py :: set_decision_time",
        body="An event after the decision time raises LookAheadError; one out of chain order raises OutOfOrderError. Unconditional, in both drivers, with no flag to disable.",
    )
    column = stack(
        canvas,
        850,
        y,
        [
            dict(
                title="sigma",
                kind="pure",
                path="estimators/sigma.py",
                body=(
                    "EWMA of one-minute log returns, six-hour half-life, scaled to per sqrt-hour — the "
                    "unit equations (1) and (2) expect. Its outlier clip — winsorising, band 1 — was "
                    "ported from a codebase that "
                    "winsorises logit returns of probabilities, and here it discarded 27.8% of the "
                    "sample: ranges were built on volatility about 3.6x too low. P-15."
                ),
                tag="a statistic calibrated on one distribution, applied to another",
            ),
            dict(
                title="kappa",
                kind="pure",
                path="estimators/kappa.py",
                body="Least squares on ln(rate) against tick depth over a trailing seven days. A poor fit falls back to a default and the card must say so — A8.",
            ),
            dict(
                title="imbalance z",
                kind="pure",
                path="estimators/imbalance.py",
                body=f"Signed swap volume over a {p.imbalance_window}-swap window. Passed as a hardcoded 0.0 until Sentinel leaned on it, which made half of section 3.4 decoration — V-11.",
            ),
        ],
        w=330,
        gap=18,
    )
    lvr = node(
        canvas,
        850,
        column[-1].bottom + 18,
        330,
        title="LvrAccountant.absorb",
        kind="pure",
        path="lvr/accountant.py — LVR: what the position lost by trading at the pool's stale price",
        body=(
            "Equation (3), per swap, from the price path rather than the event amounts. The *holdings* "
            "stop at the range edge (P-3, worth up to 53x); the *valuation* does not — it is the "
            "post-swap market price, which on a swap that leaves the range is beyond that edge, and "
            "clamping both understated the arbitrageur's edge (P-16). Fee stripped before the deltas "
            "(P-2), the protocol's cut read off the event (P-1)."
        ),
        tag="an upper bound on LVR, and labelled as one — A10",
    )
    fees = node(
        canvas,
        850,
        lvr.bottom + 18,
        330,
        title="_absorb_fee_flow",
        kind="pure",
        path="replay/engine.py",
        body=f"Trailing pool-wide LP fee rate per unit of liquidity over {p.window_hours:.0f}h, kept as a running total rather than re-summed per decision.",
    )
    events = node(
        canvas,
        58,
        (y + fees.bottom) / 2 - 60,
        330,
        title="events in (previous t, t]",
        kind="pure",
        body="Everything in the window and nothing else. The driver hands them over; the engine never fetches.",
        tag="the same window reaches all five",
    )
    observation = node(
        canvas,
        1246,
        y + 190,
        380,
        title="Observation",
        kind="pure",
        path="core/types.py",
        body=(
            "Scalars only: y, q, sigma, kappa, T_t, gas and slippage in quote units, both fee rates, "
            "the imbalance z, the toxic and clear streaks, and the position. Nothing here can be "
            "queried for more."
        ),
    )
    policy_socket = node(
        canvas,
        1692,
        y + 190,
        380,
        title="policy(obs, params, meta)",
        kind="pure",
        path="core/types.py :: Policy",
        body="One call. Which function is on the other end is the seam the whole marketplace rests on — see below right.",
    )
    node(
        canvas,
        2790,
        y + 330,
        1180,
        title="Params — every number the policy is tuned by",
        kind="pure",
        path="core/types.py :: Params",
        body="   ".join(f"{item.name} {getattr(p, item.name)}" for item in fields(p)),
        tag="G-1, G-2 and G-3 are published; kappa's default is still provisional (G-4)",
    )
    journal_note = node(
        canvas,
        3990,
        y + 330,
        1168,
        title="What a Decision carries out with it",
        kind="drive",
        path="agents/warden/loop.py :: Journal",
        body=(
            "Every gate's value, every toxicity term, the centre, the half-width, r and delta* — "
            "written as one JSONL row per decision and again per outcome. That is why the tearsheet "
            "can say which gate held the position still and how often, rather than only that nothing "
            "happened. Outcomes are counted separately from decisions; folding them together is what "
            "once rendered a single mint as three."
        ),
    )
    seam = node(
        canvas,
        1692,
        policy_socket.bottom + 54,
        1010,
        title="THE SEAM · four policies, one engine",
        kind="drive",
        body=(
            "Warden  core/policy.py :: decide — Avellaneda-Stoikov mapped onto v3 ranges. Everything to "
            "the left is this one.\n"
            "Grid  agents/grid/policy.py :: decide_grid — a fixed ladder; no sigma, no kappa, no toxicity.\n"
            "Sentinel  agents/sentinel/policy.py :: sentinel_policy — threshold de-risk; its whole active "
            "behaviour is leaving and coming back.\n"
            "DIY  core/policy.py :: passive_policy — mint once at the same width and never move. The "
            "baseline every card is measured against."
        ),
        tag="passed as policy=, never installed over a module global",
    )
    # The seam plugs *into* the socket. It was drawn the other way round, out of
    # the Decision, which reads as though the Decision chooses the policy.
    arrow(canvas, seam, policy_socket, evidence="misquote.core.types:Policy", dashed=True)

    node(
        canvas,
        2790,
        y,
        1180,
        title="The heuristic, stated as a heuristic",
        kind="stop",
        path="core/policy.py",
        body=(
            "A concentrated position behaves like a pair of limit orders: reservation price maps to "
            "range centre, optimal half-spread to half-width, inventory penalty to the recentre "
            "trigger, adverse selection to LVR, quote pull to range withdrawal. It is a mapping that "
            "motivates the design and produces sane ranges — not an isomorphism. Uniswap's own docs "
            "say range orders approximate limit orders, there is no queue and no declining a fill, "
            "and equation (2) prices no adverse selection at all. Recorded as P-5 and A9, which is "
            "why sections 3.4 and 4 exist at all."
        ),
    )
    node(
        canvas,
        3990,
        y,
        1168,
        title="A note on notation that already cost a bug",
        kind="test",
        body=(
            "kappa here is the Avellaneda-Stoikov order-arrival parameter: fill intensity decays as "
            "exp(-kappa·delta). PolyLambda, which this was re-derived from, calls that k and uses "
            "kappa for an unrelated jump premium. Ported code carrying the other meaning is matrix "
            "item D-3."
        ),
    )
    # The guard sits on the estimator path and nowhere else, which is what the
    # code does: `step` calls `set_decision_time` on the three estimators, then
    # feeds the same window to the accountant and the fee tracker, which are not
    # guarded by it. Drawing it across all five overstated the guarantee.
    arrow(canvas, events, guard, kind="concept")
    for estimator in column:
        arrow(canvas, guard, estimator, evidence="misquote.replay.engine:set_decision_time")
    arrow(canvas, events, lvr, evidence="misquote.replay.engine:absorb")
    arrow(canvas, events, fees, evidence="misquote.replay.engine:_absorb_fee_flow")
    for consumer in [*column, lvr, fees]:
        arrow(canvas, consumer, observation, evidence="misquote.replay.engine:Observation")
    arrow(canvas, observation, policy_socket, evidence="misquote.replay.engine:policy")

    y2 = max(fees.bottom, seam.bottom, journal_note.bottom) + 86
    text(
        canvas,
        58,
        y2 - 46,
        "INSIDE policy(...) — the order decide() actually runs them in, ending in a branch whose three "
        "outcomes are mutually exclusive",
        size=14,
        family=2,
        color=GREY,
    )

    # The real order, and it is not the order this was first drawn in.
    #
    # `decide()` runs toxicity **first** — a position losing to arbitrage faster
    # than it earns should leave, and should not be talked out of leaving by a
    # cooldown or a gas calculation. Only then does it compute where the range
    # would go. Then it branches, and the three outcomes below are mutually
    # exclusive: an out-of-market position never reaches R1-R4 at all.
    internals = chain(
        canvas,
        58,
        y2,
        [
            dict(
                title="1 · toxicity, first",
                kind="pure",
                path="core/policy.py :: toxicity",
                body=(
                    f"CEX-DEX gap above fee + {p.arb_cost_bps:.0f} bps for m_toxic = {p.m_toxic} "
                    f"consecutive samples, OR |imbalance z| > {p.z_pull}. With no feed, fall back to "
                    "realized LVR running above realized fees — which reacts after the damage rather "
                    "than before it, and the card records which arm fired."
                ),
                tag="toxicity outranks every other rule here",
            ),
            dict(
                title="2 · equation (1) — where the centre goes",
                kind="pure",
                path="core/policy.py :: reservation_logprice — Avellaneda-Stoikov, band 1",
                body=(
                    f"r = y - q·gamma·sigma²·(T-t). Holding too much token0 (q > 0) pushes the range "
                    f"*down*, which makes the position a keener seller of the excess. gamma = {p.gamma}."
                ),
            ),
            dict(
                title="3 · equation (2) — how wide",
                kind="pure",
                path="core/policy.py :: half_width_logprice",
                body=(
                    "delta* = ½[gamma·sigma²(T-t) + (2/gamma)·ln(1+gamma/kappa)]. More volatility, wider; "
                    "richer flow at the mid, tighter. The one-half is already applied — halving it again "
                    "is the ported-code bug D-3 exists to prevent."
                ),
            ),
            dict(
                title="4 · into ticks, rounded once",
                kind="pure",
                path="core/policy.py :: target_range",
                body=(
                    f"Round to the spacing grid exactly once — rounding to an integer tick first "
                    f"disagrees on 4.95% of inputs, by a whole spacing each time. Floor at w_min = "
                    f"{p.w_min_mult} × spacing, which on this pool is the floor that actually binds (P-17)."
                ),
                tag="no mintable range at w_min -> AssumptionViolated",
            ),
            dict(
                title="5 · is the position in the market?",
                kind="stop",
                path="core/policy.py :: decide",
                body=(
                    "The branch, and the three paths below it are mutually exclusive. This is where the "
                    "first version of this band was wrong: it drew the gates as one straight sequence, "
                    "so an out-of-market position appeared to pass through R1-R4. It never sees them."
                ),
            ),
        ],
        w=330,
        gap=66,
        connect=False,
        link=dict(kind="concept"),
    )
    for left, right in zip(internals, internals[1:], strict=False):
        arrow(canvas, left, right, kind="concept")

    branch = internals[-1]
    outcomes = stack(
        canvas,
        2098,
        y2,
        [
            dict(
                title="out of market -> may it come back?",
                kind="pure",
                path="core/policy.py :: reentry_affordable",
                body=(
                    f"Clear for m_clear = {p.m_clear} consecutive samples, and under the day's budget of "
                    f"{p.max_rebalances_per_day}. Without that budget the agent pulled and returned 2,585 "
                    "times on a 30-day tape (P-12). Deliberately asymmetric: it gates coming back, never "
                    "leaving, because an agent forbidden to exit is held inside the flow the rule exists "
                    "to escape."
                ),
                tag="-> MINT · REENTER · or HOLD",
            ),
            dict(
                title="in market and toxic -> leave now",
                kind="stop",
                body=(
                    "Returns PULL immediately. No gate is consulted, because every one of them would be "
                    "an argument for staying inside informed flow."
                ),
                tag="-> PULL",
            ),
            dict(
                title="in market and clear -> R1-R4",
                kind="pure",
                path="core/policy.py :: recenter_gates",
                body=(
                    f"R1 drift ≥ theta·width (theta = {p.theta}) · R2 the expected fee *gain* clears gas "
                    f"+ slippage + MEV · R3 cooled for {p.tau_cool_s // 3600}h and under "
                    f"{p.max_rebalances_per_day} moves today · R4 not toxic. All four are always evaluated, "
                    "even once one has failed, so the tearsheet can say which one held the position still."
                ),
                tag="-> RECENTER · or HOLD",
            ),
        ],
        w=560,
        gap=20,
    )
    for outcome in outcomes:
        arrow(canvas, branch, outcome, kind="concept")

    decision = node(
        canvas,
        2724,
        y2 + 120,
        330,
        title="Decision",
        kind="pure",
        path="core/types.py",
        body=(
            "Frozen and hashable, so T1 can compare two runs bitwise. Carries every gate's value in "
            "`reasons`, which is what lets a tearsheet say why nothing happened."
        ),
        tag="MINT · REENTER · RECENTER · PULL · HOLD",
    )
    for outcome in outcomes:
        arrow(canvas, outcome, decision, evidence="misquote.core.policy:Decision")

    return end_band(
        canvas,
        mark,
        top,
        "INSIDE ONE DECISION",
        "Engine.step() at full magnification: estimators, the accountant, the observation, and the policy socket",
    )


def band_quote(canvas: Canvas, f: Facts, top: float) -> float:
    mark = begin_band(canvas)
    y = top + 118
    p, c, fl = f.params, f.costs, f.floors

    row = chain(
        canvas,
        58,
        y,
        [
            dict(
                title="ReplayDriver.run(tape)",
                kind="drive",
                path="replay/driver.py",
                body=f"Walks the tape on a fixed delta_s = {p.sample_interval_s}s grid rather than per event, which is what makes 'm consecutive samples' mean a duration instead of a trade count.",
            ),
            dict(
                title="_apply · settle, move, charge",
                kind="drive",
                body=(
                    "Settle what the closing position earned and lost, open the new range, charge for "
                    "the move. A HOLD does nothing at all. A PULL settles, records what it is left "
                    "holding, and pays gas — leaving used to be free, an undercharge that fell on the "
                    "agent and never on the never-withdraw baseline it is compared against."
                ),
            ),
            dict(
                title="CostModel",
                kind="drive",
                path="replay/driver.py :: CostModel — notional: what a move actually swaps",
                body=(
                    f"gas {c.gas_quote:g} in token1 (600k gas at the prevailing BSC price) · slippage "
                    f"{c.slippage_bps:g} bps · MEV haircut {c.mev_haircut_bps:g} bps (A4). Both bps are "
                    "charged on what a move actually swaps, and that is three different quantities: a "
                    "**recentre** swaps only the imbalance; **opening** from one asset swaps half the "
                    "capital; **returning after a pull** swaps only the gap between what the burn paid "
                    "out — a v3 position pays out *both* tokens — and what the new range wants."
                ),
                tag="pricing a return as an opening was the whole of Warden's reported loss",
            ),
            dict(
                title="ReplayResult",
                kind="drive",
                body="fees, LVR upper bound, costs, net, samples, in-range samples, mints, recentres, pulls, and how many times A1's ceiling bound the position.",
            ),
            dict(
                title="ranges.quote()",
                kind="pure",
                path="replay/ranges.py",
                body=(
                    f"{p.replay_windows} overlapping sub-windows, each half the span, times "
                    "3 gamma perturbations at ±25% — 60 independent replays. Overlapping because "
                    "disjoint windows over 30 days are a day and a half each, too short for a "
                    f"{p.window_hours:.0f}h horizon to mean anything."
                ),
            ),
            dict(
                title="fork_map",
                kind="drive",
                path="ops/parallel.py",
                body="Fork, not spawn: every policy and every tape factory in this repo is a closure and cannot be pickled. Only a pair of integers crosses the pipe, so the arithmetic is unchanged.",
                tag="lives in ops/ because replay/ may not import multiprocessing",
            ),
            dict(
                title="quote_from_results",
                kind="pure",
                path="P25-P75: a quarter of outcomes fell below, a quarter above",
                body="Turns 60 replays into a return distribution: net token1 over the capital that earned it, annualised only when the window is long enough to survive the multiplication.",
            ),
            dict(
                title="Quote",
                kind="pure",
                body=(
                    "p25 · p50 · p75 · every window return · how many finished in profit · median "
                    "in-range fraction · median recentres · the basis sentence · and, when it refuses, "
                    "why. Plus `distinct_returns`, which is the honest qualifier on all of it — see the "
                    "refusal register."
                ),
                tag=f"-> band {BAND_NO['publish']}",
            ),
        ],
        w=300,
        gap=42,
        links=[
            dict(evidence="misquote.replay.driver:_apply"),
            dict(evidence="misquote.replay.driver:CostModel"),
            dict(evidence="misquote.replay.driver:ReplayResult"),
            dict(evidence="misquote.replay.ranges:ReplayResult"),
            dict(evidence="scripts.showcase:fork_map"),
            dict(evidence="misquote.replay.ranges:quote_from_results"),
            dict(evidence="misquote.replay.ranges:Quote"),
        ],
    )
    # The relationship the first version left out entirely, and it is the whole
    # cost of a quote: `_replay_one` builds a *fresh* driver over a fresh tape
    # for every window x perturbation pair, so the row above is not a pipeline
    # that runs once — the first box is re-entered sixty times from the sixth.
    recursion = node(
        canvas,
        58,
        max(box.bottom for box in row) + 30,
        300,
        title="…and this row runs 60 times",
        kind="stop",
        path="replay/ranges.py :: _replay_one",
        body="Each replay builds its own driver over its own tape and shares no state, which is what makes running them on eight cores change no arithmetic.",
    )
    arrow(
        canvas,
        recursion,
        row[0],
        evidence="misquote.replay.ranges:ReplayDriver",
        dashed=True,
    )

    y2 = max(recursion.bottom, max(box.bottom for box in row)) + 70
    ladder = chain(
        canvas,
        58,
        y2,
        [
            dict(
                title="refuse · A1 breached",
                kind="stop",
                body=f"A position larger than {p.eps_liquidity_share:.0%} of the pool would have moved the price it is being replayed against. A1 says such a quote is refused, not clamped and published anyway — P-14.",
            ),
            dict(
                title=f"refuse · fewer than {fl['MIN_SAMPLES']} usable",
                kind="stop",
                body="Below assumption A5's floor the spread describes the sample rather than the strategy. The note says how many were usable and how many were too short.",
            ),
            dict(
                title=f"exclude · window under {fl['MIN_WINDOW_HOURS']:.0f}h",
                kind="stop",
                body="Shorter than the policy's own horizon, so the replay measures startup rather than strategy. Twenty such windows are still twenty measurements of nothing.",
            ),
            dict(
                title=f"decline to annualise under {fl['MIN_HOURS_TO_ANNUALISE'] / 24:.0f}d",
                kind="stop",
                body="Multiplying an eight-hour result by a thousand makes a fixed rebalance cost look like a catastrophe. The quote states the period it actually covers instead.",
            ),
            dict(
                title="…and then, in tearsheet/, three more",
                kind="test",
                body=(
                    "The three that follow are not in quote_from_results at all — they are the report's "
                    "own refusals, applied to a pair of quotes it has already been handed. Drawn in one "
                    "run because a reader follows the number, not the module boundary."
                ),
                w=210,
            ),
            dict(
                title="compare() · agent vs DIY",
                kind="drive",
                path="tearsheet/advantage.py",
                body="Both columns are one ReplayDriver with policy= swapped: same tape, same costs, same accountant. The delta is a claim about the policy, not about two differently-rigged programs.",
            ),
            dict(
                title="withhold · not separated",
                kind="stop",
                body=f"Below {fl['MATERIAL_PP']}pp the difference is noise. If the two P25-P75 bands overlap the strategies are indistinguishable at this sample size, however far apart the medians sit — and the report says so.",
            ),
            dict(
                title=f"no verdict · n < {fl['MIN_OBSERVATIONS']}",
                kind="stop",
                path="tearsheet/generate.py :: verdict",
                body="With three tasks the overall call is refused, deliberately. What carries the argument is each task's own quote, where the sample is 60 replays rather than 3.",
            ),
        ],
        w=300,
        gap=42,
        connect=False,
    )
    text(
        canvas,
        58,
        y2 - 46,
        "INSIDE quote_from_results — the four refusals a quote has to survive, in the order they are applied",
        size=14,
        family=2,
        color=GREY,
    )
    for left, right in zip(ladder, ladder[1:], strict=False):
        arrow(canvas, left, right, kind="concept")

    node(
        canvas,
        2716,
        y2,
        1180,
        title="Why a range and not a number",
        kind="stop",
        body=(
            "Two sources of spread, both required by A5. Sampling spread: a strategy that earned well "
            "in one fortnight and badly in the next has a wide band, and that width is the honest "
            "statement about how much the headline depends on when you started. Parameter spread: "
            "gamma is a user preference and kappa is a fitted parameter whose functional form is a "
            "documented approximation, so both are wiggled a quarter. A quote that collapses under "
            "that was never a quote."
        ),
        tag="the whole product is this paragraph, enforced in code",
    )
    node(
        canvas,
        2716,
        y2 + 300,
        1180,
        title="What the replay costs to run",
        kind="test",
        body=(
            "Measured on the 30-day WBNB/USDT tape: 1,839 events/s, 60 replays of ~125,700 events per "
            "agent, 4.6 hours serial for four policies. 86% of that is the sigma estimator recomputing "
            "its window. Parallelism was the right lever precisely because it changes no arithmetic — "
            "making sigma incremental would change summation order and therefore change bits, and T1 "
            "and L1 compare bits."
        ),
    )
    node(
        canvas,
        3916,
        y2,
        1242,
        title="quote() is not re-entrant, and says so",
        kind="stop",
        path="replay/ranges.py :: _FORKED",
        body=(
            "The state the forked workers inherit lives in a module-level dict, so a second concurrent "
            "call would overwrite the spans and policy the first is replaying against and return a "
            "plausible quote of the wrong thing. It raises instead."
        ),
    )
    node(
        canvas,
        3916,
        y2 + 240,
        1242,
        title="What was deleted, and why it matters",
        kind="test",
        body=(
            "replay/driver.py once had a passive_result helper nothing called. It counted in-range "
            "samples per swap event where the live path counts per decision sample — trade-weighted "
            "against time-weighted. Dead code is tolerable; dead code that answers a live question "
            "differently is a trap with a fuse in it. The baseline runs through ReplayDriver now."
        ),
    )
    return end_band(
        canvas,
        mark,
        top,
        "REPLAY -> QUOTE",
        "how a tape becomes a P25-P75 range, and the ladder of refusals it has to survive first",
    )


# One sentence per emitter, keyed by the Makefile target so a renamed target
# loses its note loudly rather than attaching it to the wrong box.
ARTIFACT_NOTES = {
    "showcase-demo": "Replays every agent plus the passive baseline and writes one card each, with the counterfactual badge attached.",
    "advantage-demo": "The three tasks, each done with and without an agent, on a tape long enough to clear the 24h window floor.",
    "advantage-short": "The same three tasks on too little history. Every one is withheld — the refusal, demonstrated.",
    "registry": "ERC-8004 identity, ERC-8183 hire, and what TermiX's AACP turns out to share with both.",
    "venue": "Every place PancakeSwap is not Uniswap, each one a defect this project actually hit.",
    "vetting": "Republishes the pool badges make vet left on disk.",
    "addresses": "Republishes what make vet-addresses recorded, address by address.",
    "vectors-report": "The differential-test corpus, and separately whatever replay of it was actually watched.",
    "assumptions": "ASSUMPTIONS.md and the requirements matrix, parsed into the sheet every citation resolves against.",
    "status": "Runs every readiness gate and publishes the verdict without enforcing it.",
}


def band_router(canvas: Canvas, f: Facts, top: float) -> float:
    """The fourth category: a different venue, not a different policy.

    Warden, Grid and Sentinel are three policies through one engine. Router is
    the one that needed a second venue model, which is why it was cut once and
    why this band exists — everything above it is a v3 position, and none of it
    applies here.
    """
    mark = begin_band(canvas)
    y = top + 118
    rp = f.router_params
    sc = f.switch_cost
    fl = f.allocation_floors
    markets = ", ".join(m.symbol for m in f.venus_markets)

    tape = stack(
        canvas,
        58,
        y,
        [
            dict(
                title="AccrueInterest, not Swap",
                kind="data",
                path="indexer/venus.py",
                body=(
                    f"{markets} on Venus Core Pool. Every input the rate formula needs is inside "
                    f"the log — cashPrior, interestAccumulated, borrowIndex, totalBorrows — so a "
                    f"rate is recomputable from the tape with no chain state re-read."
                ),
            ),
            dict(
                title="venus_covered",
                kind="data",
                path="indexer/schema.sql",
                body=(
                    "Which ranges were **read**, kept apart from which produced rows. It matters "
                    "more here than for swaps: a market that did not accrue and a request nobody "
                    "made are both zero rows, and for a thin market the first is normal."
                ),
            ),
        ],
        w=430,
        connect=True,
        link=dict(kind="concept"),
    )

    est = stack(
        canvas,
        548,
        y,
        [
            dict(
                title="Difference the accumulator",
                kind="pure",
                path="estimators/apr.py",
                body=(
                    "supplyRatePerBlock() needs a blocks-per-year constant that is **not readable "
                    "from chain** — the interest-rate model reverts on every accessor for it — and "
                    "the plausible values span 6.67x. borrowIndex is monotone, so differencing it "
                    "needs no constant at all. P-22."
                ),
            ),
            dict(
                title="Trailing-only, same firewall",
                kind="pure",
                path="estimators/base.py :: Timed",
                body=(
                    "The look-ahead guards are inherited, not re-implemented: `ingest` raises on an "
                    "event newer than the decision. A RateEvent satisfies the same protocol a Swap "
                    "does, which is why there is one firewall and not two."
                ),
            ),
        ],
        w=430,
        connect=True,
        link=dict(kind="concept"),
    )

    boundary = stack(
        canvas,
        1038,
        y,
        [
            dict(
                title="Move only when it pays",
                kind="pure",
                path="agents/router/policy.py",
                body=(
                    f"edge > hurdle, and the edge has held {rp.persistence_samples} samples, and "
                    f"{rp.cooldown_s // 3600}h since the last move, and under "
                    f"{rp.max_switches_per_day} moves today. Myopic break-even widened by a "
                    f"published margin of {rp.switch_cost_margin:g} — A13, not a solved free "
                    f"boundary."
                ),
            ),
            dict(
                title="What a move costs",
                kind="pure",
                path="replay/allocation.py :: SwitchCost",
                body=(
                    f"{sc.slippage_bps:g} bps from {f.swap_venue.label}, plus "
                    f"{f.venus_gas_units:,} gas units priced from the chain. This was two literals "
                    f"— a gas figure forty times BSC's cost and a fee copied from a WBNB/USDT pool "
                    f"— and they decided everything the agent published. P-25."
                ),
            ),
        ],
        w=430,
        connect=True,
        link=dict(kind="concept"),
    )

    quote = stack(
        canvas,
        1528,
        y,
        [
            dict(
                title="Its own quote type",
                kind="pure",
                path="replay/allocation.py",
                body=(
                    f"No in-range fraction and no LVR: a supplied position has no range and cannot "
                    f"be picked off. Zeros in those columns would read as claims. Floors are the "
                    f"same — {fl['MIN_SAMPLES']} windows, {fl['MIN_WINDOW_HOURS']:.0f}h each — and "
                    f"under {fl['MIN_HOURS_TO_ANNUALISE'] / 24:.0f} days it states the period "
                    f"instead of annualising."
                ),
            ),
            dict(
                title="Market size, per sample",
                kind="stop",
                path="replay/allocation.py",
                body=(
                    "Taken from the accrual the estimator has seen, not from the tape's last row. "
                    "The emitters passed `rows[-1]` in as a constant, so a window replayed on day "
                    "one was sized by a market measured on day seven — look-ahead, in the project "
                    "whose claim is that look-ahead is impossible."
                ),
            ),
        ],
        w=430,
        connect=True,
        link=dict(kind="concept"),
    )

    arrow(canvas, tape[0], est[0], evidence="misquote.estimators.apr:RateEvent", label="RateEvent")
    arrow(
        canvas,
        est[0],
        boundary[0],
        evidence="misquote.agents.router.policy:VenueQuote",
        label="VenueQuote",
    )
    arrow(
        canvas,
        boundary[0],
        quote[0],
        evidence="misquote.replay.allocation:allocation_quote_from_results",
    )

    return end_band(
        canvas,
        mark,
        top,
        "Router — the fourth category, on a venue none of the above applies to",
        "A lending allocation, not a liquidity position. Different tape, different driver, "
        "different quote type — and the reason the other three share one engine is that they "
        "genuinely can.",
    )


def band_publish(canvas: Canvas, f: Facts, top: float) -> float:
    mark = begin_band(canvas)
    y = top + 118

    # Every one of these is offline. That is the point of the split: the halves
    # that read a chain are separate targets (make indexer, make vet,
    # make vet-addresses), and `make artifacts` republishes what they left on
    # disk. So the whole site can be rebuilt on a plane.
    boxes = chain(
        canvas,
        58,
        y,
        [
            dict(
                title=target,
                kind="drive",
                path=f.target_commands.get(target, ""),
                body=ARTIFACT_NOTES.get(target, ""),
            )
            for target in f.artifact_order
        ],
        w=300,
        gap=30,
        link=dict(kind="concept"),
        labels=["then"] * (len(f.artifact_order) - 1),
    )

    y2 = max(box.bottom for box in boxes) + 60
    node(
        canvas,
        58,
        y2,
        1000,
        title="The order is load-bearing",
        kind="stop",
        body=(
            "assumptions runs last because its cited_by is built by globbing every other artifact in "
            "the output directory, so an emitter running after it is invisible to it. Listed earlier "
            "it only looked right because the previous run's files were still on disk. status runs "
            "last of all and publishes the gate's verdict without enforcing it — make go-no-go is the "
            "one that enforces, and its exit code has to keep meaning something."
        ),
    )
    node(
        canvas,
        1094,
        y2,
        1000,
        title=f"apps/web/public/artifacts/ — {len(f.artifact_files)} files",
        kind="data",
        body="  ".join(f.artifact_files),
        tag="the front end reads these and nothing else",
    )
    node(
        canvas,
        2130,
        y2,
        1000,
        title="Every artifact carries its provenance",
        kind="data",
        path="tearsheet/provenance.py",
        body=(
            "build.json records the exact command, the git sha, whether the tree was dirty, the event "
            "count, the span in hours, the capital, the quote unit, and how many blocks in the tape "
            "were never read. A card without a build stamp is a card nobody can date."
        ),
    )
    node(
        canvas,
        3166,
        y2,
        1000,
        title="COUNTERFACTUAL is a field, not a footnote",
        kind="stop",
        path="scripts/showcase.py",
        body=(
            "The wallet this was built by has a real BSC record and no liquidity positions in it, so "
            "'here is what I earned' would be a fabrication. Every card says it is a replay, the badge "
            "is asserted by a test, and the front end renders it as prominently as the number it "
            "qualifies — A6."
        ),
    )
    node(
        canvas,
        4202,
        y2,
        956,
        title="advantage-short exists to fail",
        kind="stop",
        path=f.target_commands.get("advantage-short", ""),
        body=(
            "The same three tasks on too little history, where every one of them refuses to quote. "
            "Published alongside the real report as proof that the refusal is live machinery rather "
            "than a story told about it."
        ),
    )
    return end_band(
        canvas,
        mark,
        top,
        "make artifacts — THE PUBLISH PIPELINE",
        "ten targets, in the order the Makefile runs them, each writing the JSON the front end reads",
    )


def band_web(canvas: Canvas, f: Facts, top: float) -> float:
    mark = begin_band(canvas)
    y = top + 118

    row = chain(
        canvas,
        58,
        y,
        [
            dict(
                title="/artifacts/*.json",
                kind="data",
                body="Served as static files. There is no API, no database and no backend process, which is why the whole site survives every Python process being down.",
            ),
            dict(
                title="getJSON",
                kind="web",
                path="apps/web/src/lib/artifacts.ts",
                body="Checks res.ok and the content-type before parsing, so a 404's HTML body cannot surface as a SyntaxError about an unexpected '<'. The path is root-absolute: with trailingSlash every route is a directory.",
                tag="four distinct causes, kept distinct",
            ),
            dict(
                title="Loaded<T>",
                kind="web",
                body="{ok: true, value} | {ok: false, error}. Never both, never neither. The throwing half is not exported, so a caller cannot forget the catch.",
            ),
            dict(
                title="loadAgents",
                kind="web",
                body="allSettled, not all: one missing agent artifact costs one card rather than erasing the page and blaming the pipeline for never having run.",
            ),
            dict(
                title="pages",
                kind="web",
                path="apps/web/src/app/",
                body=f"{len(f.routes)} routes, each a client component that fetches its own artifacts and renders a named failure when they are absent.",
            ),
            dict(
                title="components",
                kind="web",
                path="apps/web/src/components/",
                body="Band · CostBars · GateHistogram · ComparisonTable · Refusal · SourceBanner · BuildStamp · Ledger. The Refusal component is the one that renders a withheld quote as a first-class state.",
            ),
        ],
        w=300,
        gap=42,
        link=dict(kind="concept"),
    )

    y2 = max(box.bottom for box in row) + 66
    node(
        canvas,
        58,
        y2,
        1140,
        title="The routes, in nav order",
        kind="web",
        path="apps/web/src/lib/routes.ts",
        body="   ".join(f"{href}  {label}" for href, label in f.routes),
        tag="one list — the 404 page and the nav read the same module",
    )
    node(
        canvas,
        1234,
        y2,
        980,
        title="The TypeScript cannot drift from the Python",
        kind="test",
        path="tests/web/test_artifact_contract.py",
        body="Compares the field names in the artifacts.ts interfaces against the keys the Python emitters actually write. The shapes are a contract with a test behind it rather than a comment.",
    )
    node(
        canvas,
        2250,
        y2,
        980,
        title="The test harness forbids a relative fetch",
        kind="test",
        path="apps/web/src/test/harness.tsx",
        body="Throws on any request that is not root-absolute. The jsdom tests stub fetch and match on the basename, so a wrong prefix was invisible to them — every route but '/' fetched from a page-relative path and rendered an error state while the suite stayed green.",
    )
    node(
        canvas,
        3266,
        y2,
        980,
        title="…and a real browser checks the built export",
        kind="test",
        path="apps/web/scripts/check-pages.mjs",
        body="Loads the static export in Chromium: console errors, failed requests, and horizontal overflow at 390px. The only check here that runs real layout, and it is what caught the relative-path failure.",
    )
    node(
        canvas,
        4282,
        y2,
        876,
        title="Served the way a judge would",
        kind="data",
        path=f.target_commands.get("web-static", ""),
        body="A static export served by python3 -m http.server with every backend process down — the state a demo is most likely to be found in. No wallet library is imported anywhere.",
    )
    return end_band(
        canvas,
        mark,
        top,
        "THE FRONT END",
        "a static export that reads precomputed JSON, and the three guards that keep it honest",
    )


def band_proof(canvas: Canvas, f: Facts, top: float) -> float:
    mark = begin_band(canvas)
    y = top + 118

    vectors = chain(
        canvas,
        58,
        y,
        [
            dict(
                title="gen_vectors",
                kind="drive",
                path=f.target_commands.get("vectors", ""),
                body="Compiles Exposer.sol — a thin wrapper over upstream v3-core and v3-periphery at the commits pinned in ops/forge_deps.txt — deploys it to a bare anvil, and asks it the questions we ask ourselves.",
            ),
            dict(
                title="tests/core/vectors/",
                kind="data",
                body="Recorded answers. Written only if every single one agreed, so their presence establishes exactly one thing: a differential run, at a fixed seed, agreed.",
                tag="exact integer equality — no tolerance anywhere",
            ),
            dict(
                title="test_vectors",
                kind="test",
                path="tests/core/test_vectors.py",
                body="Replays the corpus against today's Python on every commit, with no chain and no network. This is the claim the recorded files cannot make for themselves.",
            ),
            dict(
                title="vectors_verify",
                kind="drive",
                path=f.target_commands.get("vectors-verify", ""),
                body="The only thing allowed to say the vectors were replayed, because it is the only thing that watches the replay. Non-zero exit on failure, so a broken proof is not a quiet file change.",
            ),
        ],
        w=300,
        gap=42,
        link=dict(kind="concept"),
    )

    stack(
        canvas,
        1426,
        y,
        [
            dict(
                title="T1 · the replay cannot see the future",
                kind="test",
                path="tests/replay/test_engine.py",
                body="Run twice; the second run replaces every event after a cut with seeded noise. Decision sequences compared with every float packed to its exact bits — plus a negative control proving tampering does change later decisions.",
            ),
            dict(
                title="T2 · fees cannot exceed what the pool paid",
                kind="test",
                body="Credited fees bounded by the pool fee times our share, with the protocol's cut inside the bound — and a test that the bound is tight enough to be violated if the cut is ignored.",
            ),
            dict(
                title="T3 · estimators refuse future data",
                kind="test",
                body="A runtime guard in both drivers rather than a review item. There is no flag to switch it off.",
            ),
            dict(
                title="T4 · passive agrees with direct computation",
                kind="test",
                body="With the policy replaced by 'never move', the replay must agree with accounting the same position straight off the tape, to 1e-12.",
            ),
        ],
        w=380,
        gap=18,
    )

    stack(
        canvas,
        1848,
        y,
        [
            dict(
                title="the fork lab",
                kind="test",
                path=f.target_commands.get("fork-diff", ""),
                body="Mint through the real NonfungiblePositionManager on a pinned BSC fork and compare amounts and principal to one wei. Excluded from the default run so make test stays offline.",
            ),
            dict(
                title="the kill switch, against a real signer",
                kind="stop",
                path="tests/chain/test_position_lifecycle.py",
                body="Not a stub. And a half-failed recentre is asserted to leave the wallet flat rather than stranded.",
            ),
            dict(
                title="a second venue, no code changes",
                kind="test",
                path="tests/chain/test_equity_pool.py",
                body=f"{f.equity_pool.label}: different fee tier, different spacing, different protocol fee, priced by the same engine.",
            ),
        ],
        w=380,
        gap=18,
    )

    stack(
        canvas,
        2270,
        y,
        [
            dict(
                title=f"the pool badge · {f.badge_checks} checks",
                kind="drive",
                path=f"vetting/badge.py  ({f.target_commands.get('vet', '')})",
                body=(
                    "Factory resolves the address · feeProtocol read not assumed · decimals read (BSC's "
                    f"USDT is 18, not 6) · spacing matches the tier ({', '.join(f'{k}->{v}' for k, v in f.fee_tiers.items())}) · "
                    "initialised and not pinned at an extreme · a mintable range exists at w_min · "
                    "liquidity supports a position without being the pool · both tokens have code."
                ),
                tag="every check exists because something went wrong",
            ),
            dict(
                title="the registry, read honestly",
                kind="drive",
                path="registry/erc8004.py · erc8183.py · aacp.py",
                body="BNB Chain has more registered agents than any other chain and about 4% expose a working endpoint. totalSupply() reverts; tokenURI returns two different shapes and conflating them reports a card as resolvable when nothing was fetched.",
            ),
            dict(
                title="addresses, verified three ways",
                kind="drive",
                path="scripts/verify_addresses.py",
                body="Bytecode present, the interface answers, and the answers agree with the other contracts'. Nothing in chain/addresses.py was taken on trust from documentation.",
            ),
        ],
        w=380,
        gap=18,
    )

    gate = node(
        canvas,
        2692,
        y,
        420,
        title="go_no_go · the gate that runs",
        kind="stop",
        path=f.target_commands.get("go-no-go", ""),
        body=(
            "A checklist in a document gets read carefully once and skimmed thereafter. This one "
            "executes, exits non-zero, and prints the remedy. Anything it cannot verify is UNVERIFIED "
            "— an amber light, never a green one."
        ),
        tag="the standard was written down while it was still cheap to meet",
    )
    status = node(
        canvas,
        2692,
        y + 260,
        420,
        title="status.json -> /status",
        kind="web",
        body="The verdict, published rather than summarised: every gate, its detail, its remedy, and whether it blocks. It currently says NOT YET, and the site says so on its own status page.",
    )
    arrow(canvas, gate, status, kind="concept")
    text(
        canvas,
        2692,
        y - 26,
        "every column to the left terminates here",
        size=13,
        family=2,
        color=GREY,
    )

    node(
        canvas,
        58,
        max(box.bottom for box in vectors) + 40,
        1326,
        title="The suite, by area",
        kind="test",
        body="   ".join(f"{area} {count}" for area, count in sorted(f.tests.items())),
        tag="test files, not cases — the case count has its own drift guard",
    )
    node(
        canvas,
        3162,
        y,
        1000,
        title="Guards on the prose, not only the code",
        kind="test",
        body=(
            "A make target named in backticks anywhere in the repo must exist — this sentence "
            "originally failed that check by quoting one. A file named in a "
            "comment must exist. Every assumption cited by any artifact must resolve in the published "
            "sheet. The counts in the judges' document are re-derived from pytest's own collector. "
            "Each of these was a real defect before it was a test."
        ),
        tag="tests/web/test_make_targets.py and friends",
    )
    node(
        canvas,
        3162,
        y + 280,
        1000,
        title="The three tasks, and why the baselines differ",
        kind="drive",
        path="scripts/advantage.py",
        body=(
            "The weakness to avoid is three tasks that are one task relabelled.\n"
            "Earn — baseline: mint once at the same width and never touch it. Isolates the recentring "
            "decision.\nProtect — baseline: the same agent with its withdrawal disabled. An ablation — the "
            "same program with one behaviour switched off — so the only difference is whether it leaves "
            "when flow turns one-way.\nChoose — baseline: "
            "pick the deepest pool. Two real venues, one fee tier apart, each with its own PoolMeta "
            "because their protocol fees differ — sharing one would credit the second pool's LPs with "
            "a share they do not get. What an LP actually does, and the task exists to test whether "
            "deeper is safer."
        ),
        tag="provenance is per task: one report-level flag let synthetic tapes hide under a chain stamp",
    )
    node(
        canvas,
        4198,
        y,
        960,
        title="What is still unverified",
        kind="stop",
        body=(
            "kappa still falls back to a provisional default pending the 30-day fit (G-4); the advantage "
            "report has been generated on a synthetic tape; the burn-in is short. The gate names all of "
            "them rather than rounding them up to green."
        ),
    )
    node(
        canvas,
        4198,
        y + 260,
        960,
        title="L1 sits outside T1-T4 on purpose",
        kind="test",
        path="tests/replay/test_l1_equivalence.py",
        body=(
            "It is not in the frozen spec and is arguably the most valuable test here. T1 proves the "
            "replay could not cheat; L1 proves the thing that cheated is the thing that will trade. "
            "Everything else in this band is downstream of that pair being true."
        ),
    )
    return end_band(
        canvas,
        mark,
        top,
        "PROOF AND GATES",
        "what is actually checked, by what, and the one program that refuses to call it green",
    )


def grid(
    canvas: Canvas,
    x: float,
    y: float,
    specs: list[dict[str, Any]],
    *,
    columns: int = 5,
    w: float = 980,
    gap_x: float = 36,
    gap_y: float = 26,
) -> list[Box]:
    """A left-to-right, top-to-bottom grid. Rows are top-aligned and self-sizing."""
    boxes: list[Box] = []
    cursor_y = y
    for start in range(0, len(specs), columns):
        row = specs[start : start + columns]
        placed = [
            node(canvas, x + i * (w + gap_x), cursor_y, w, **spec) for i, spec in enumerate(row)
        ]
        boxes.extend(placed)
        cursor_y = max(box.bottom for box in placed) + gap_y
    return boxes


def band_refusals(canvas: Canvas, f: Facts, top: float) -> float:
    mark = begin_band(canvas)
    y = top + 118
    fl = f.floors
    p = f.params

    grid(
        canvas,
        58,
        y,
        [
            dict(
                title="A quote that would breach the liquidity ceiling",
                kind="stop",
                path="replay/ranges.py",
                body=f"A1 caps a replayed position at {p.eps_liquidity_share:.0%} of the pool. The driver used to clamp and publish anyway, so a request for 1,000 WBNB was quoted on the 3.4 it actually deployed. Refusing is the quote A1 promises — P-14.",
            ),
            dict(
                title="A sample that is smaller than it looks",
                kind="stop",
                path="replay/ranges.py :: distinct_returns",
                body=(
                    "A5 builds half the spread by perturbing gamma, so 20 windows are counted as 60 "
                    "samples — honest only if the perturbation changes anything. Mostly it does not: "
                    "equation (2)'s half-width lands 2.9-4.8 ticks against an anti-dust floor of 40, so "
                    "the floor sets the width. Grid and Sentinel read neither parameter, so their 60 "
                    "samples are 20 results counted three times; Warden keeps 23 distinct of 60. "
                    "Published as a field on the quote rather than left for a reader to notice — P-17."
                ),
            ),
            dict(
                title="A quote from too few windows",
                kind="stop",
                path="replay/ranges.py",
                body=f"Fewer than {fl['MIN_SAMPLES']} usable replays and the spread describes the sample, not the strategy. The note distinguishes 'not enough windows' from 'the windows were too short'.",
            ),
            dict(
                title="Annualising a short window",
                kind="stop",
                path="replay/ranges.py",
                body=f"Under {fl['MIN_HOURS_TO_ANNUALISE'] / 24:.0f} days the quote states the period it covers instead. Multiplying is not the same as measuring for a year.",
            ),
            dict(
                title="A verdict below the sample floor",
                kind="stop",
                path="tearsheet/generate.py :: verdict",
                body=f"Ported unchanged from Mission Control's _verdict(min_n={fl['MIN_OBSERVATIONS']}). 'No verdict yet, 12 observations' is worth more than '83% win rate' on twelve.",
            ),
            dict(
                title="A toxicity call from one swap",
                kind="stop",
                path="replay/engine.py",
                body=f"Rates are reported as zero — no verdict — until {fl['MIN_SWAPS_FOR_TOXICITY_VERDICT']} swaps have been seen. LVR is an upper bound and fees accrue in slivers, so a sample of one almost always reads as toxic and produces a pull-wait-remint loop. A12.",
            ),
            dict(
                title="An advantage that is not separated",
                kind="stop",
                path="tearsheet/advantage.py",
                body=f"Below {fl['MATERIAL_PP']}pp it is noise; if the P25-P75 bands overlap the two strategies are indistinguishable at this sample size. The report says which, and never reorders on sign.",
            ),
            dict(
                title="A range that cannot be minted",
                kind="stop",
                path="core/policy.py :: target_range",
                body="MIN_TICK is not a multiple of any Pancake spacing, so clamping to it produces ticks the pool rejects and the mint reverts having cost gas. Price pinned against the edge raises AssumptionViolated — V-10.",
            ),
            dict(
                title="A pool check that could not be read",
                kind="stop",
                path="vetting/badge.py",
                body="UNKNOWN, never PASS. A badge that downgrades a failed read to a pass launders an absence of evidence into evidence of absence — which is the move this project is named after.",
            ),
            dict(
                title="A tape whose coverage is unknown",
                kind="stop",
                path="indexer/store.py",
                body="A database predating the covered table reports no coverage rather than full coverage. None and [] are different claims and collapsing them lets an unverifiable tape publish as a verified one.",
            ),
            dict(
                title="An event from after the decision time",
                kind="stop",
                path="estimators/base.py · replay/tape.py",
                body="LookAheadError. An out-of-order event raises OutOfOrderError; a tape asked to rewind raises rather than quietly restarting its clock. Unconditional in both drivers.",
            ),
            dict(
                title="Signing, unless explicitly told twice",
                kind="stop",
                path="chain/signer.py",
                body="Dry run is the default rather than a flag. The kill file is checked once a second by the loop and again inside the signer immediately before broadcast — redundant on purpose; the second one is the load-bearing one.",
            ),
            dict(
                title="Coming back into the market too often",
                kind="stop",
                path="core/policy.py :: reentry_affordable",
                body=f"At most {p.max_rebalances_per_day} re-entries a day. Deliberately asymmetric: it gates coming back, never leaving. An agent forbidden to exit would be held inside the flow the rule exists to escape.",
            ),
            dict(
                title="An escrow address nobody verified",
                kind="stop",
                path="registry/erc8183.py",
                body="A table on a vendor's website is a claim, not a verification. verify() goes to chain, checks the escrow has code and that the settlement token matches, and returns evidence rather than a boolean.",
            ),
            dict(
                title="A gate nobody checked, called green",
                kind="stop",
                path="scripts/go_no_go.py",
                body="UNVERIFIED is an amber light and it blocks. The gate exits 1 on NO GO and 2 on NOT YET, and make status carries a leading dash precisely so publishing the verdict cannot be mistaken for enforcing it.",
            ),
            dict(
                title="A missing artifact, blamed on the wrong cause",
                kind="stop",
                path="apps/web/src/lib/artifacts.ts",
                body="Four failure causes kept distinct all the way to the surface: http, parse, network, shape. The page this replaced collapsed all of them into one message that named the wrong remedy for three.",
            ),
        ],
    )
    return end_band(
        canvas,
        mark,
        top,
        "THE REFUSAL REGISTER",
        "every place the system declines to answer, in one view — this is the product, not a caveat list",
    )


def band_next(canvas: Canvas, f: Facts, top: float) -> float:
    mark = begin_band(canvas)
    y = top + 118

    boxes = grid(
        canvas,
        58,
        y,
        [
            dict(
                title=f"{entry['name']} — {entry['category']}",
                kind="stop",
                path=entry["evidence"],
                body=entry["why"],
            )
            for entry in f.not_built
        ],
        columns=len(f.not_built) or 1,
        w=980,
        gap_x=36,
    )

    y2 = (max(box.bottom for box in boxes) if boxes else y) + 66
    node(
        canvas,
        58,
        y2,
        1500,
        title="The gaps are data, not omissions",
        kind="drive",
        path="tearsheet/ledger.py",
        body=(
            f"These {len(f.not_built)} entries are emitted into index.json and rendered on the landing "
            "page under 'Advertised, and not built'. A test asserts that nothing here has quietly been "
            "built and that nothing built has quietly been left out — a marketplace showing three cards "
            "and nothing else was telling the truth about three agents and lying by omission about the fourth. All four are built now."
        ),
    )
    node(
        canvas,
        1594,
        y2,
        1500,
        title="What to do next, in dependency order",
        kind="test",
        body=(
            "1 · Extend the backfill to a full 30 days and fit kappa on it, which clears two blocking "
            "gates at once (G-4 and the tape gate) and lets the cards stop carrying a provisional "
            "constant.\n2 · Re-run make artifacts against that tape so the advantage report stops being "
            "generated on a synthetic one — the third blocking gate.\n3 · Wire ChainExecutor into "
            "agents/warden/__main__.py behind an explicit flag, which is the last thing standing between "
            "the journal and a real burn-in."
        ),
        tag="each one closes a gate that make go-no-go already names",
    )
    node(
        canvas,
        3130,
        y2,
        1000,
        title="Where a new agent goes",
        kind="drive",
        body=(
            f"Band {BAND_NO['decision']}'s seam. A Policy function, a CATEGORIES entry, a run_agent call — "
            "and it inherits "
            "the engine, the tape, the cost model, the accountant, the quote machinery, every refusal "
            "and the card. If a new agent needs a change below the policy, that is a finding about the "
            "engine and worth stopping for."
        ),
    )
    node(
        canvas,
        4166,
        y2,
        992,
        title="The rule the whole repo is built on",
        kind="stop",
        body=(
            "Every displayed number must trace to a chain query or to an entry in the published "
            "assumption sheet. If it cannot, it does not render. Everything in the eight bands above "
            "is machinery for keeping that sentence true under pressure."
        ),
    )
    return end_band(
        canvas,
        mark,
        top,
        "NOT BUILT, AND WHERE TO WORK NEXT",
        "the five capabilities this repository advertises and does not contain, read out of the ledger itself",
    )


# ------------------------------------------------------------- assembling --


def build(f: Facts) -> Canvas:
    canvas = Canvas()
    drawers = {
        "map": band_map,
        "vocabulary": band_vocabulary,
        "spine": band_spine,
        "tape": band_tape,
        "decision": band_decision,
        "quote": band_quote,
        "router": band_router,
        "publish": band_publish,
        "web": band_web,
        "proof": band_proof,
        "refusals": band_refusals,
        "next": band_next,
    }
    if tuple(drawers) != BAND_ORDER:
        raise SystemExit("BAND_ORDER and the drawers disagree about the reading order")

    y = 0.0
    for key in BAND_ORDER:
        y = drawers[key](canvas, f, y) + GAP
    place_labels(canvas)
    return canvas


def _references(module_path: str, symbol: str) -> bool:
    """Does `module_path`'s source actually mention `symbol`?

    Parsed rather than grepped, so a symbol named only inside a docstring or a
    comment does not count as a reference. An import, a call, an attribute, a
    base class, a type annotation — anything the parser turns into a Name or an
    attribute — does.
    """
    parts = module_path.split(".")
    if parts[0] == "scripts":
        file = REPO / "scripts" / Path(*parts[1:]).with_suffix(".py")
    else:
        file = REPO / "packages" / Path(*parts).with_suffix(".py")
    if not file.exists():
        return False
    tree = ast.parse(file.read_text())
    for node_ in ast.walk(tree):
        if isinstance(node_, ast.Name) and node_.id == symbol:
            return True
        if isinstance(node_, ast.Attribute) and node_.attr == symbol:
            return True
        if isinstance(node_, ast.alias) and (node_.asname or node_.name).split(".")[-1] == symbol:
            return True
        if isinstance(node_, ast.ImportFrom) and (node_.module or "").split(".")[-1] == symbol:
            return True
        if isinstance(node_, ast.arg) and node_.arg == symbol:
            return True
        if isinstance(node_, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if node_.name == symbol:
                return True
    return False


def check_evidence(canvas: Canvas) -> list[str]:
    """Every declared edge must be a relationship the source actually has.

    This is the guard the first version of this file needed and did not have. It
    is the same shape as the repo's own prose guards: a claim that can be
    resolved is resolved, and the ones that cannot are failures rather than
    footnotes.
    """
    problems: list[str] = []
    for tail, head, evidence in canvas.edges:
        del head
        if ":" not in evidence:
            problems.append(f"evidence {evidence!r} is not module.path:Symbol")
            continue
        module_path, symbol = evidence.rsplit(":", 1)
        if not _references(module_path, symbol):
            problems.append(
                f"the edge at {tail} claims {module_path} references {symbol!r}, and it does not"
            )
    return problems


def _segment_hits(a: tuple[float, float], b: tuple[float, float], box: Box) -> bool:
    """Does the axis-aligned segment a->b pass through `box`'s interior?

    Every segment this generator emits is horizontal or vertical, so the test is
    an interval overlap rather than a general intersection. A small inset keeps
    an edge that merely grazes a corner from counting.
    """
    inset = 3.0
    left, right = box.x + inset, box.right - inset
    top, bottom = box.y + inset, box.bottom - inset
    (ax, ay), (bx, by) = a, b
    if abs(ay - by) < 0.5:  # horizontal
        return top < ay < bottom and min(ax, bx) < right and max(ax, bx) > left
    if abs(ax - bx) < 0.5:  # vertical
        return left < ax < right and min(ay, by) < bottom and max(ay, by) > top
    return False


def validate(canvas: Canvas) -> list[str]:
    """Check the drawing the way the repo checks everything else: by running it.

    Three failures are possible in a layout engine and all three are silent in
    the JSON: an arrow bound to an element that does not exist, two nodes drawn
    on top of each other, and text drawn outside the box that is supposed to
    contain it. None of them would raise; all of them would ship.
    """
    problems: list[str] = check_evidence(canvas)

    for element in canvas.elements:
        for key in ("startBinding", "endBinding"):
            binding = element.get(key)
            if binding and binding["elementId"] not in canvas.by_id:
                problems.append(f"{element['id']}.{key} points at a missing element")
        for bound in element.get("boundElements") or []:
            if bound["id"] not in canvas.by_id:
                problems.append(f"{element['id']} is bound to a missing {bound['id']}")

    for i, a in enumerate(canvas.boxes):
        for b in canvas.boxes[i + 1 :]:
            if a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom:
                problems.append(
                    f"nodes overlap: ({a.x:.0f},{a.y:.0f},{a.w:.0f}x{a.h:.0f}) "
                    f"and ({b.x:.0f},{b.y:.0f},{b.w:.0f}x{b.h:.0f})"
                )

    for element in canvas.elements:
        if element["type"] != "arrow":
            continue
        bound = {element["startBinding"]["elementId"], element["endBinding"]["elementId"]}
        points = [(element["x"] + px, element["y"] + py) for px, py in element["points"]]
        for box in canvas.boxes:
            if box.id in bound:
                continue
            if any(_segment_hits(a, b, box) for a, b in zip(points, points[1:], strict=False)):
                problems.append(
                    f"an arrow crosses a box it is not bound to, at ({box.x:.0f},{box.y:.0f})"
                )
                break

    for element in canvas.elements:
        if element["type"] != "text" or element["groupIds"]:
            continue
        for box in canvas.boxes:
            if (
                element["x"] < box.right
                and box.x < element["x"] + element["width"]
                and element["y"] < box.bottom
                and box.y < element["y"] + element["height"]
            ):
                problems.append(f"loose text sits on a node: {element['text'][:56]!r}")
                break

    loose = [e for e in canvas.elements if e["type"] == "text" and not e["groupIds"]]
    for i, a in enumerate(loose):
        for b in loose[i + 1 :]:
            if (
                a["x"] < b["x"] + b["width"]
                and b["x"] < a["x"] + a["width"]
                and a["y"] < b["y"] + b["height"]
                and b["y"] < a["y"] + a["height"]
            ):
                problems.append(
                    f"two loose texts overlap: {a['text'][:34]!r} and {b['text'][:34]!r}"
                )

    rects = {
        element["groupIds"][0]: element
        for element in canvas.elements
        if element["type"] == "rectangle" and element["groupIds"]
    }
    for element in canvas.elements:
        if element["type"] != "text" or not element["groupIds"]:
            continue
        container = rects.get(element["groupIds"][0])
        if container is None:
            continue
        if element["x"] + element["width"] > container["x"] + container["width"] - 6:
            problems.append(f"text overflows its box horizontally: {element['text'][:48]!r}")
        if element["y"] + element["height"] > container["y"] + container["height"] - 2:
            problems.append(f"text overflows its box vertically: {element['text'][:48]!r}")

    return problems


def document(canvas: Canvas) -> dict[str, Any]:
    return {
        "type": "excalidraw",
        "version": 2,
        "source": "misquote/scripts/gen_flow_diagram.py",
        "elements": canvas.elements,
        "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
        "files": {},
    }


def report(f: Facts, canvas: Canvas, out: Path) -> None:
    bottom = max(e["y"] + e["height"] for e in canvas.elements)
    print(f"wrote {out.relative_to(REPO) if out.is_relative_to(REPO) else out}")
    arrows = sum(1 for e in canvas.elements if e["type"] == "arrow")
    print(
        f"  {len(canvas.elements):,} elements, {len(canvas.boxes)} nodes, "
        f"canvas {CANVAS_W:,} x {bottom:,.0f}"
    )
    print(
        f"  {arrows} edges — {len(canvas.edges)} resolved against a symbol in the source, "
        f"{arrows - len(canvas.edges)} declared conceptual"
    )
    print("  derived, not typed:")
    print(
        f"    layers          {sum(len(v) for v in f.layers.values())} across 3 classes "
        f"<- tests/test_layering.py"
    )
    print(
        f"    banned imports  {f.banned['BANNED_STDLIB']} stdlib + "
        f"{f.banned['BANNED_THIRD_PARTY']} third-party <- tests/test_layering.py"
    )
    print(f"    routes          {len(f.routes)} <- apps/web/src/lib/routes.ts")
    print(f"    artifact order  {' '.join(f.artifact_order)} <- Makefile")
    print(f"    artifact files  {len(f.artifact_files)} <- apps/web/public/artifacts/")
    print(f"    not built       {len(f.not_built)} <- misquote.tearsheet.ledger")
    print(f"    badge checks    {f.badge_checks} <- misquote.vetting.badge :: evaluate")
    print(f"    test files      {sum(f.tests.values())} across {len(f.tests)} areas <- tests/")
    print(f"    floors          {', '.join(f'{k}={v}' for k, v in f.floors.items())}")
    print(f"    pool            {f.pool.label} <- misquote.chain.addresses")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate MISQUOTE_FLOW.excalidraw")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and report without writing, the CI-shaped form",
    )
    args = parser.parse_args(argv)

    facts = gather()
    canvas = build(facts)

    problems = validate(canvas)
    if problems:
        print(f"{len(problems)} layout problem(s):", file=sys.stderr)
        for problem in problems[:20]:
            print(f"  {problem}", file=sys.stderr)
        return 1

    out = Path(args.out)
    if args.check:
        print(f"layout clean: {len(canvas.elements):,} elements, {len(canvas.boxes)} nodes")
        return 0

    out.write_text(json.dumps(document(canvas), indent=1) + "\n")
    report(facts, canvas, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
