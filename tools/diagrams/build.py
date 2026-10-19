# =================== AIPass ====================
# Name: build.py
# Description: Diagram kit command - JSON spec to SVG and PNG under assets/diagrams/
# Version: 1.0.0
# Created: 2026-10-19
# Modified: 2026-10-19
# =============================================

"""Build AIPass architecture pictures from JSON specs.

    python tools/diagrams/build.py <name>     render specs/<name>.json
    python tools/diagrams/build.py --all      render every spec
    python tools/diagrams/build.py --check    render every spec, then verify each PNG's size

Output: assets/diagrams/<name>.png and assets/diagrams/src/<name>.svg at the repo root.
A spec that breaks a rule (unknown name, overlapping tiles, colliding text, a line
through a tile or a label) is refused with the names involved; nothing is written.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

import icons
import render
import theme

KIT = Path(__file__).resolve().parent
ROOT = KIT.parents[1]
SPECS = KIT / "specs"
OUT = ROOT / "assets" / "diagrams"
OUT_SRC = OUT / "src"

Point = tuple[float, float]

KINDS = ("tile", "hub")
SIDES = ("top", "bottom", "left", "right")
OUTWARD = {"top": (0.0, -1.0), "bottom": (0.0, 1.0), "left": (-1.0, 0.0), "right": (1.0, 0.0)}
STYLES = ("solid", "dashed")
ROUTES = ("bottom", "top")
LABEL_AT = ("under", "start", "end")
SPEC_KEYS = {"title", "subtitle", "canvas", "nodes", "edges", "footers", "decor"}
NODE_KEYS = {"id", "kind", "icon", "label", "caption", "x", "y", "w", "h", "accent"}
EDGE_KEYS = {"from", "to", "style", "accent", "route", "label", "label_at", "labels", "from_side", "to_side", "faint"}
DECOR_KEYS = {"traces", "pulse", "grid"}
MARGIN = 80
TITLE_Y = 96
SUBTITLE_Y = 128
FOOTER_SEP = "   ·   "


class SpecError(ValueError):
    """The spec breaks a kit rule; the message names what and where."""


# Geometry ------------------------------------------------------------------


@dataclass(frozen=True)
class Box:
    """An axis-aligned rectangle."""

    x0: float
    y0: float
    x1: float
    y1: float

    def intersects(self, other: Box) -> bool:
        """True when the two boxes share any area."""
        return self.x0 < other.x1 and other.x0 < self.x1 and self.y0 < other.y1 and other.y0 < self.y1

    def contains(self, p: Point) -> bool:
        """True when the point lies strictly inside."""
        return self.x0 < p[0] < self.x1 and self.y0 < p[1] < self.y1

    def union(self, other: Box) -> Box:
        """The smallest box holding both."""
        return Box(min(self.x0, other.x0), min(self.y0, other.y0), max(self.x1, other.x1), max(self.y1, other.y1))

    def shrink(self, d: float) -> Box:
        """The box pulled in by d on every side."""
        return Box(self.x0 + d, self.y0 + d, self.x1 - d, self.y1 - d)


@dataclass
class Text:
    """One block of text (one or more lines) with its owner, for drawing and collision checks."""

    owner: str
    lines: list[str]
    x: float
    y: float  # first baseline
    size: float
    fill: str
    anchor: str = "middle"
    bold: bool = False
    spacing: float = 0.0
    backing: bool = False

    @property
    def width(self) -> float:
        """Widest line, estimated."""
        return max(theme.text_width(s, self.size, self.bold, self.spacing) for s in self.lines)

    @property
    def box(self) -> Box:
        """Estimated ink box of the whole block."""
        w = self.width
        x0 = {"middle": self.x - w / 2, "start": self.x, "end": self.x - w}[self.anchor]
        last = self.y + theme.line_step(self.size) * (len(self.lines) - 1)
        return Box(x0, self.y - 0.8 * self.size, x0 + w, last + 0.25 * self.size)


@dataclass
class Node:
    """A tile or hub placed on the canvas."""

    id: str
    kind: str
    icon: str
    label: list[str]
    caption: list[str]
    x: float
    y: float
    w: float
    h: float
    accent: str

    @property
    def body(self) -> Box:
        """The tile or hub rectangle."""
        return Box(self.x, self.y, self.x + self.w, self.y + self.h)

    @property
    def centre(self) -> Point:
        """Centre of the body."""
        return (self.x + self.w / 2, self.y + self.h / 2)

    def label_text(self) -> Text | None:
        """A tile's label under it; hubs carry their label inside."""
        if self.kind != "tile" or not self.label:
            return None
        size = theme.TILE_LABEL_SIZE
        return Text(
            self.id, self.label, self.x + self.w / 2, self.y + self.h + 30, size, theme.TILE_LABEL_FILL, bold=True
        )

    @property
    def occupied(self) -> Box:
        """Body plus the label under a tile."""
        lt = self.label_text()
        return self.body.union(lt.box) if lt else self.body


@dataclass
class Edge:
    """A connector with its resolved sides, attachment points, path and labels."""

    index: int
    src: Node
    dst: Node
    spec: dict
    from_side: str = ""
    to_side: str = ""
    p0: Point = (0.0, 0.0)
    p1: Point = (0.0, 0.0)
    d: str = ""
    samples: list[Point] = field(default_factory=list)
    straights: list[tuple[Point, Point]] = field(default_factory=list)
    texts: list[Text] = field(default_factory=list)

    @property
    def name(self) -> str:
        """How the edge is named in refusals."""
        return f"edge {self.src.id}->{self.dst.id}"

    @property
    def accent(self) -> str:
        """Accent colour name."""
        return self.spec.get("accent", "blue")


def _fmt(p: Point) -> str:
    return f"{p[0]:.1f} {p[1]:.1f}"


def _add(p: Point, v: Point, k: float = 1.0) -> Point:
    return (p[0] + v[0] * k, p[1] + v[1] * k)


def _unit(a: Point, b: Point) -> Point:
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1.0
    return (dx / n, dy / n)


def _cubic(p0: Point, c1: Point, c2: Point, p1: Point, n: int = 48) -> list[Point]:
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        pts.append(
            (
                u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p1[0],
                u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p1[1],
            )
        )
    return pts


def _line(a: Point, b: Point, step: float = 4.0) -> list[Point]:
    n = max(1, int(math.dist(a, b) / step))
    return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]


def rounded_polyline(points: list[Point], radius: float) -> tuple[str, list[Point], list[tuple[Point, Point]]]:
    """Orthogonal waypoints joined by straight runs and cubic rounded corners."""
    pts = [p for i, p in enumerate(points) if i == 0 or math.dist(p, points[i - 1]) > 0.5]
    cur = pts[0]
    d = [f"M{_fmt(cur)}"]
    samples: list[Point] = [cur]
    straights: list[tuple[Point, Point]] = []
    for i in range(1, len(pts) - 1):
        prev, corner, nxt = pts[i - 1], pts[i], pts[i + 1]
        din, dout = _unit(prev, corner), _unit(corner, nxt)
        before = math.dist(prev, corner) / (2 if i > 1 else 1)
        after = math.dist(corner, nxt) / (2 if i < len(pts) - 2 else 1)
        r = min(radius, before, after)
        a, b = _add(corner, din, -r), _add(corner, dout, r)
        if math.dist(cur, a) > 0.5:
            d.append(f"L{_fmt(a)}")
            samples += _line(cur, a)
            straights.append((cur, a))
        c1, c2 = _add(a, din, r * 0.552), _add(b, dout, -r * 0.552)
        d.append(f"C{_fmt(c1)} {_fmt(c2)} {_fmt(b)}")
        samples += _cubic(a, c1, c2, b)
        cur = b
    end = pts[-1]
    if math.dist(cur, end) > 0.5:
        d.append(f"L{_fmt(end)}")
        samples += _line(cur, end)
        straights.append((cur, end))
    return " ".join(d), samples, straights


# Spec loading and validation ----------------------------------------------------


def _refuse_unknown(keys: set, allowed: set, where: str) -> None:
    extra = sorted(set(keys) - allowed)
    if extra:
        raise SpecError(f"{where}: unknown key(s) {', '.join(extra)}")


def _lines(value: object) -> list[str]:
    return str(value).split("\n") if value else []


def load_nodes(spec: dict) -> dict[str, Node]:
    """Validate and place every node; refuse unknown kinds, icons, accents and overlapping bodies."""
    nodes: dict[str, Node] = {}
    for raw in spec.get("nodes", []):
        nid = raw.get("id")
        if not nid:
            raise SpecError(f"node without an id: {raw}")
        _refuse_unknown(set(raw), NODE_KEYS, f"node {nid}")
        if nid in nodes:
            raise SpecError(f"duplicate node id: {nid}")
        kind = raw.get("kind", "tile")
        if kind not in KINDS:
            raise SpecError(f"node {nid}: unknown kind {kind!r} (known: {', '.join(KINDS)})")
        icon = raw.get("icon", "")
        if icon not in icons.ICONS:
            raise SpecError(f"node {nid}: unknown icon {icon!r} (known: {', '.join(icons.ICONS)})")
        accent = raw.get("accent", "blue")
        if accent not in theme.ACCENTS:
            raise SpecError(f"node {nid}: unknown accent {accent!r} (known: {', '.join(theme.ACCENTS)})")
        if kind == "tile":
            w = h = theme.TILE_SIZE
        else:
            w, h = raw.get("w", theme.HUB_DEFAULT_W), raw.get("h", theme.HUB_DEFAULT_H)
        nodes[nid] = Node(
            nid, kind, icon, _lines(raw.get("label")), _lines(raw.get("caption")), raw["x"], raw["y"], w, h, accent
        )
    ids = list(nodes)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if nodes[a].body.intersects(nodes[b].body):
                raise SpecError(f"overlapping tiles: {a} and {b}")
    return nodes


def load_edges(spec: dict, nodes: dict[str, Node]) -> list[Edge]:
    """Validate every edge's names and options."""
    edges = []
    for i, raw in enumerate(spec.get("edges", [])):
        where = f"edge #{i + 1} ({raw.get('from')}->{raw.get('to')})"
        _refuse_unknown(set(raw), EDGE_KEYS, where)
        for end in ("from", "to"):
            if raw.get(end) not in nodes:
                raise SpecError(f"{where}: unknown node id {raw.get(end)!r}")
        checks = (
            ("style", STYLES, "solid"),
            ("accent", tuple(theme.ACCENTS), "blue"),
            ("route", (None, *ROUTES), None),
            ("label_at", LABEL_AT, "under"),
            ("from_side", ("", *SIDES), ""),
            ("to_side", ("", *SIDES), ""),
        )
        for key, allowed, default in checks:
            if raw.get(key, default) not in allowed:
                raise SpecError(f"{where}: unknown {key} {raw.get(key)!r}")
        for extra in raw.get("labels", []):
            if set(extra) - {"text", "at"} or extra.get("at", "under") not in LABEL_AT:
                raise SpecError(f"{where}: labels entries take text and at ({', '.join(LABEL_AT)})")
        edges.append(Edge(i, nodes[raw["from"]], nodes[raw["to"]], raw))
    return edges


# Edge layout --------------------------------------------------------------------


def _auto_sides(a: Node, b: Node) -> tuple[str, str]:
    """Facing sides: the axis with the larger gap between the two bodies wins."""
    ab, bb = a.body, b.body
    gx = max(bb.x0 - ab.x1, ab.x0 - bb.x1)
    gy = max(bb.y0 - ab.y1, ab.y0 - bb.y1)
    (ax, ay), (bx, by) = a.centre, b.centre
    if gx >= gy:
        return ("right", "left") if bx >= ax else ("left", "right")
    return ("bottom", "top") if by >= ay else ("top", "bottom")


def _side_point(node: Node, side: str, along: float) -> Point:
    """The attachment point on a side; under a tile, below its label so lines never cross it."""
    b = node.body
    if side == "top":
        return (along, b.y0)
    if side == "bottom":
        lt = node.label_text()
        return (along, lt.box.y1 + 8 if lt else b.y1)
    if side == "left":
        return (b.x0, along)
    return (b.x1, along)


def resolve_attachments(edges: list[Edge]) -> None:
    """Pick sides for every edge, then spread several edges that share a long side."""
    groups: dict[tuple[str, str], list[tuple[Edge, str]]] = {}
    for e in edges:
        route = e.spec.get("route")
        if route:
            fs = ts = route
        else:
            fs, ts = _auto_sides(e.src, e.dst)
        e.from_side = e.spec.get("from_side") or fs
        e.to_side = e.spec.get("to_side") or ts
        groups.setdefault((e.src.id, e.from_side), []).append((e, "from"))
        groups.setdefault((e.dst.id, e.to_side), []).append((e, "to"))
    for (_, side), members in groups.items():
        node = members[0][0].src if members[0][1] == "from" else members[0][0].dst
        horizontal_side = side in ("top", "bottom")
        axis = 0 if horizontal_side else 1
        length = node.w if horizontal_side else node.h
        centre = node.centre[axis]

        def other_coord(item: tuple[Edge, str], axis: int = axis) -> float:
            """Where the far end sits along this side's axis, to order attachments without crossings."""
            e, end = item
            return (e.dst if end == "from" else e.src).centre[axis]

        members.sort(key=other_coord)
        n = len(members)
        step = 0.0
        if n > 1 and length >= theme.SPREAD_MIN_SIDE:
            step = min(length * theme.HUB_SPREAD / (n - 1), 60.0)
        for i, (e, end) in enumerate(members):
            along = centre + (i - (n - 1) / 2) * step
            point = _side_point(node, side, along)
            if end == "from":
                e.p0 = point
            else:
                e.p1 = point


def _lane(nodes: dict[str, Node], route: str) -> float:
    """Y of a routed return path: outside every node and tile label on the canvas."""
    span = [n.occupied for n in nodes.values()]
    if route == "bottom":
        return max(b.y1 for b in span) + theme.LANE_GAP
    return min(b.y0 for b in span) - theme.LANE_GAP


def build_path(e: Edge, nodes: dict[str, Node]) -> None:
    """Compute the SVG path, sample points and straight runs for one edge."""
    p0, p1 = e.p0, e.p1
    route = e.spec.get("route")
    r = theme.CORNER_RADIUS
    if route:
        lane = _lane(nodes, route)
        e.d, e.samples, e.straights = rounded_polyline([p0, (p0[0], lane), (p1[0], lane), p1], r)
        return
    h0, h1 = e.from_side in ("left", "right"), e.to_side in ("left", "right")
    if h0 != h1:
        corner = (p1[0], p0[1]) if h0 else (p0[0], p1[1])
        e.d, e.samples, e.straights = rounded_polyline([p0, corner, p1], r)
        return
    across = abs(p1[1] - p0[1]) if h0 else abs(p1[0] - p0[0])
    if across < 0.5:
        e.d, e.samples, e.straights = rounded_polyline([p0, p1], r)
        return
    along = abs(p1[0] - p0[0]) if h0 else abs(p1[1] - p0[1])
    k = max(along / 2, 30.0)
    c1, c2 = _add(p0, OUTWARD[e.from_side], k), _add(p1, OUTWARD[e.to_side], k)
    e.d = f"M{_fmt(p0)} C{_fmt(c1)} {_fmt(c2)} {_fmt(p1)}"
    e.samples = _cubic(p0, c1, c2, p1)
    e.straights = []


def _place_label(e: Edge, text: str, at: str) -> Text:
    """Put a label beside a straight run (under a horizontal one, right of a vertical one)."""
    size = theme.EDGE_LABEL_SIZE
    lines = _lines(text)
    fill = theme.ACCENTS[e.accent]["label"]
    probe = Text(e.name, lines, 0, 0, size, fill)
    w, hgt = probe.width, probe.box.y1 - probe.box.y0
    gap = theme.LABEL_GAP
    if not e.straights:
        mid = e.samples[len(e.samples) // 2]
        return Text(e.name, lines, mid[0], mid[1] - hgt / 2 + 0.8 * size, size, fill, backing=True)
    if at == "under":
        seg = max(e.straights, key=lambda s: math.dist(*s))
        frac = 0.5
    else:
        seg = e.straights[0] if at == "start" else (e.straights[-1][1], e.straights[-1][0])
        frac = None
    a, b = seg
    horizontal = abs(a[1] - b[1]) < 0.5
    extent = w if horizontal else hgt
    if frac is None:
        dist = min(math.dist(a, b) / 2, 2 * gap + extent / 2)
        frac = dist / (math.dist(a, b) or 1.0)
    pt = (a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac)
    if horizontal:
        return Text(e.name, lines, pt[0], pt[1] + gap + 0.8 * size, size, fill, backing=True)
    return Text(e.name, lines, pt[0] + gap + 4, pt[1] - hgt / 2 + 0.8 * size, size, fill, "start", backing=True)


def layout_edges(edges: list[Edge], nodes: dict[str, Node]) -> None:
    """Attach, route and label every edge."""
    resolve_attachments(edges)
    for e in edges:
        build_path(e, nodes)
        if e.spec.get("label"):
            e.texts.append(_place_label(e, e.spec["label"], e.spec.get("label_at", "under")))
        for extra in e.spec.get("labels", []):
            e.texts.append(_place_label(e, extra["text"], extra.get("at", "under")))


# Text and collision checks -----------------------------------------------------------


def frame_texts(spec: dict, width: int, height: int) -> list[Text]:
    """Title, subtitle, footers and the brand mark."""
    out = [Text("title", [spec.get("title", "")], MARGIN, TITLE_Y, theme.TITLE_SIZE, theme.TITLE_FILL, "start")]
    out[0].bold, out[0].spacing = True, 1.0
    if spec.get("subtitle"):
        sub = Text("subtitle", [spec["subtitle"]], MARGIN, SUBTITLE_Y, theme.SUBTITLE_SIZE, theme.SUBTITLE_FILL)
        sub.anchor = "start"
        out.append(sub)
    if spec.get("footers"):
        line = FOOTER_SEP.join(spec["footers"])
        out.append(Text("footers", [line], width / 2, height - 30, theme.FOOTER_SIZE, theme.FOOTER_FILL))
    brand = Text("brand", ["AIPASS"], width - MARGIN, height - 30, 14, theme.BRAND_FILL, "end", spacing=2.0)
    out.append(brand)
    return out


def hub_texts(node: Node) -> list[Text]:
    """A hub's label and caption lines, vertically centred beside its icon."""
    step = theme.line_step(theme.CAPTION_SIZE)
    content = 30 + step * len(node.caption)
    top = node.y + (node.h - content) / 2
    x = node.x + theme.HUB_TEXT_X
    label = Text(node.id, [" ".join(node.label)], x, top + 20, theme.HUB_LABEL_SIZE, theme.HUB_LABEL_FILL, "start")
    label.bold, label.spacing = True, 1.0
    out = [label]
    if node.caption:
        cap = Text(node.id, node.caption, x, top + 25 + step, theme.CAPTION_SIZE, theme.CAPTION_FILL, "start")
        out.append(cap)
    return out


def check_layout(nodes: dict[str, Node], edges: list[Edge], texts: list[Text], width: int, height: int) -> None:
    """Refuse text that collides, leaves the canvas or overflows a hub, and lines through tiles or labels."""
    canvas = Box(0, 0, width, height)
    for n in nodes.values():
        if n.kind == "hub":
            need = theme.HUB_TEXT_X + max(t.width for t in hub_texts(n)) + theme.HUB_TEXT_PAD_R
            if need > n.w:
                raise SpecError(f"hub {n.id}: text needs w >= {math.ceil(need)}, spec has {n.w:g}")
        if not (canvas.x0 <= n.body.x0 and n.body.x1 <= canvas.x1 and n.body.y1 <= canvas.y1 and n.body.y0 >= 0):
            raise SpecError(f"node {n.id} leaves the {width}x{height} canvas")
    loose = [t for t in texts if not (t.owner in nodes and nodes[t.owner].kind == "hub")]
    for t in loose:
        b = t.box
        if b.x0 < 0 or b.y0 < 0 or b.x1 > width or b.y1 > height:
            raise SpecError(f"text {t.lines[0]!r} ({t.owner}) leaves the canvas")
        for n in nodes.values():
            if n.id != t.owner and b.intersects(n.body):
                raise SpecError(f"text {t.lines[0]!r} ({t.owner}) collides with node {n.id}")
    for i, t in enumerate(loose):
        for u in loose[i + 1 :]:
            if t.box.intersects(u.box):
                raise SpecError(f"text {t.lines[0]!r} ({t.owner}) collides with text {u.lines[0]!r} ({u.owner})")
    for e in edges:
        for n in nodes.values():
            if n.id in (e.src.id, e.dst.id):
                continue
            inner = n.body.shrink(2)
            if any(inner.contains(p) for p in e.samples):
                raise SpecError(f"{e.name} runs through node {n.id}")
        for t in loose:
            tb = t.box
            if any(tb.contains(p) for p in e.samples):
                raise SpecError(f"{e.name} runs through text {t.lines[0]!r} ({t.owner})")


# SVG assembly ---------------------------------------------------------------------


def _text_svg(t: Text) -> str:
    parts = []
    if t.backing:
        b = t.box
        parts.append(
            f'<rect x="{b.x0 - 6:.1f}" y="{b.y0 - 3:.1f}" width="{b.x1 - b.x0 + 12:.1f}" '
            f'height="{b.y1 - b.y0 + 6:.1f}" rx="6" fill="{theme.BACKING}" opacity="{theme.BACKING_OPACITY}"/>'
        )
    weight = ' font-weight="700"' if t.bold else ""
    spacing = f' letter-spacing="{t.spacing:g}"' if t.spacing else ""
    step = theme.line_step(t.size)
    for i, line in enumerate(t.lines):
        parts.append(
            f'<text x="{t.x:.1f}" y="{t.y + i * step:.1f}" fill="{t.fill}" font-size="{t.size:g}" '
            f'text-anchor="{t.anchor}"{weight}{spacing}>{escape(line)}</text>'
        )
    return "".join(parts)


def _edge_svg(e: Edge) -> str:
    c = theme.ACCENTS[e.accent]
    dashed = e.spec.get("style", "solid") == "dashed"
    width = 2.5 if dashed else 3
    dash = ' stroke-dasharray="7 8"' if dashed else ""
    look = ' opacity="0.45"' if e.spec.get("faint") else ' filter="url(#lineglow)"'
    return (
        f'<path d="{e.d}" fill="none" stroke="{c["edge"]}" stroke-width="{width}" stroke-linecap="round"'
        f'{dash}{look} marker-end="url(#arrow-{e.accent})"/>'
    )


def _node_svg(n: Node) -> str:
    if n.kind == "tile":
        body = theme.tile_rect(n.accent) + icons.icon_markup(n.icon, theme.ICON_STROKE)
        return f'<g transform="translate({n.x:g} {n.y:g})">{body}</g>'
    s = theme.HUB_ICON_SCALE
    icon_y = (n.h - theme.TILE_SIZE * s) / 2
    icon = (
        f'<g transform="translate({theme.HUB_ICON_X} {icon_y:.1f}) scale({s:g})">'
        f"{icons.icon_markup(n.icon, theme.HUB_ICON_STROKE)}</g>"
    )
    return f'<g transform="translate({n.x:g} {n.y:g})">{theme.hub_rect(n.w, n.h, n.accent)}{icon}</g>'


def build_svg(spec: dict) -> str:
    """Validate a spec, lay it out, check it, and return the SVG document."""
    _refuse_unknown(set(spec), SPEC_KEYS, "spec")
    width, height = spec.get("canvas", [1600, 900])
    decor = spec.get("decor", {})
    _refuse_unknown(set(decor), DECOR_KEYS, "decor")
    nodes = load_nodes(spec)
    edges = load_edges(spec, nodes)
    layout_edges(edges, nodes)
    texts = frame_texts(spec, width, height)
    for n in nodes.values():
        lt = n.label_text()
        if lt:
            lt.backing = True
            texts.append(lt)
        if n.kind == "hub":
            texts += hub_texts(n)
    for e in edges:
        texts += e.texts
    check_layout(nodes, edges, texts, width, height)
    body = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{theme.FONT_FAMILY}">',
        theme.defs(width, height),
        theme.background(width, height, decor),
        "<g>" + "".join(_edge_svg(e) for e in edges) + "</g>",
        "<g>" + "".join(_node_svg(n) for n in nodes.values()) + "</g>",
        "<g>" + "".join(_text_svg(t) for t in texts) + "</g>",
        "</svg>",
    ]
    return "\n".join(body) + "\n"


# Commands ---------------------------------------------------------------------------


def png_size(path: Path) -> tuple[int, int]:
    """Width and height from a PNG's IHDR chunk."""
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise SpecError(f"{path} is not a PNG")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def build(name: str) -> tuple[Path, str]:
    """Render specs/<name>.json to assets/diagrams/. Returns the PNG path and the renderer used."""
    spec_path = SPECS / f"{name}.json"
    if not spec_path.is_file():
        known = ", ".join(sorted(p.stem for p in SPECS.glob("*.json")))
        raise SpecError(f"unknown diagram {name!r} (specs: {known})")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    svg = build_svg(spec)
    OUT_SRC.mkdir(parents=True, exist_ok=True)
    svg_path = OUT_SRC / f"{name}.svg"
    svg_path.write_text(svg, encoding="utf-8")
    width, height = spec.get("canvas", [1600, 900])
    png_path = OUT / f"{name}.png"
    used = render.render(svg_path, png_path, width, height)
    return png_path, used


def main(argv: list[str] | None = None) -> int:
    """CLI entry: build one spec, every spec, or every spec plus a size check."""
    parser = argparse.ArgumentParser(description="Render AIPass diagrams from tools/diagrams/specs/*.json")
    parser.add_argument("name", nargs="?", help="spec name (file stem under specs/)")
    parser.add_argument("--all", action="store_true", help="render every spec")
    parser.add_argument("--check", action="store_true", help="render every spec and verify each PNG's size")
    args = parser.parse_args(argv)
    if not (args.name or args.all or args.check):
        parser.error("give a spec name, --all or --check")
    names = sorted(p.stem for p in SPECS.glob("*.json")) if (args.all or args.check) else [args.name]
    failures = 0
    for name in names:
        try:
            png, used = build(name)
        except (SpecError, render.RenderError) as exc:
            sys.stderr.write(f"REFUSED {name}: {exc}\n")
            failures += 1
            continue
        rel = png.relative_to(ROOT).as_posix()
        if args.check:
            spec = json.loads((SPECS / f"{name}.json").read_text(encoding="utf-8"))
            want = tuple(spec.get("canvas", [1600, 900]))
            got = png_size(png)
            status = "ok" if got == want else f"FAIL want {want[0]}x{want[1]}"
            failures += status != "ok"
            sys.stdout.write(f"{status:>4}  {rel}  {got[0]}x{got[1]}  ({used})\n")
        else:
            svg_rel = (OUT_SRC / f"{name}.svg").relative_to(ROOT).as_posix()
            sys.stdout.write(f"built {rel} and {svg_rel}  ({used})\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())


# =================== END AIPass ====================
