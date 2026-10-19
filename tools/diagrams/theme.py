# =================== AIPass ====================
# Name: theme.py
# Description: Diagram kit house style - colours, gradients, filters, geometry, fonts
# Version: 1.0.0
# Created: 2026-10-19
# Modified: 2026-10-19
# =============================================

"""The house style for AIPass diagrams: colours, gradients, filters, geometry, fonts.

Everything visual that is not an icon or a spec coordinate lives here, so every
picture the kit renders shares one look: navy background, glowing rounded tiles,
white line icons, curved glowing connectors, faint circuit traces.
"""

from __future__ import annotations

FONT_FAMILY = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"

# Colours -----------------------------------------------------------------

BG_TOP = "#040a16"
BG_MID = "#071a33"
BG_BOTTOM = "#03070f"
BACKING = "#061630"  # label backing rects (the background's mid tone), drawn at BACKING_OPACITY
BACKING_OPACITY = 0.85
GRID_STROKE = "#0e2a4e"
TRACE_STROKE = "#1d4f8f"
TRACE_DOT = "#3d8bff"
PULSE_STROKE = "#2f7fe6"
CENTRE_GLOW = "#1d6cff"

ICON_STROKE = "#dbeeff"
HUB_ICON_STROKE = "#e6f3ff"
TITLE_FILL = "#e6f3ff"
SUBTITLE_FILL = "#9cc6f5"
HUB_LABEL_FILL = "#ffffff"
CAPTION_FILL = "#bfe0ff"
TILE_LABEL_FILL = "#dbeeff"
FOOTER_FILL = "#7fb2e8"
BRAND_FILL = "#4d7fb8"

# accent name -> (node stroke, edge stroke, arrow fill, edge label fill)
ACCENTS = {
    "blue": {"node": "#4d9dff", "hub": "#6db3ff", "edge": "#9ccbff", "arrow": "#8fc4ff", "label": "#bfe0ff"},
    "green": {"node": "#5fd9a8", "hub": "#5fd9a8", "edge": "#5fd9a8", "arrow": "#5fd9a8", "label": "#8fe0c0"},
}

# Geometry ----------------------------------------------------------------

TILE_SIZE = 88
TILE_RADIUS = 16
HUB_RADIUS = 22
HUB_DEFAULT_W = 330
HUB_DEFAULT_H = 120
HUB_ICON_X = 18  # left inset of the hub's icon box
HUB_ICON_SCALE = 0.8  # the 88x88 icon drawn at 70x70 inside a hub
HUB_TEXT_X = 100  # left inset where hub label and caption start
HUB_TEXT_PAD_R = 20

CORNER_RADIUS = 44  # rounded corners on elbows and routed return paths
LANE_GAP = 44  # distance from the lowest/highest content to a routed lane
LABEL_GAP = 10  # distance from a line to the edge of its label text
HUB_SPREAD = 0.7  # share of a long side used to spread several attachments
SPREAD_MIN_SIDE = 200  # sides shorter than this keep one shared attachment point

# Fonts -------------------------------------------------------------------

TITLE_SIZE = 32
SUBTITLE_SIZE = 19
HUB_LABEL_SIZE = 22
CAPTION_SIZE = 18
TILE_LABEL_SIZE = 19
EDGE_LABEL_SIZE = 18
FOOTER_SIZE = 18
LINE_HEIGHT = 1.3  # multiple of font size between stacked lines

# Width metrics: Arial/Liberation advance widths per 1000 em, which is what the
# PNG renderer falls back to when Inter is absent. WIDTH_SAFETY widens every
# estimate so a wider face (Inter, Segoe UI) still fits its backing rect.
WIDTH_SAFETY = 1.08
_REGULAR = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191,
    "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278,
    ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015, "[": 278,
    "\\": 278, "]": 278, "^": 469, "_": 556, "`": 333, "{": 334, "|": 260, "}": 334,
    "~": 584, "·": 278,
    "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778, "H": 722,
    "I": 278, "J": 500, "K": 667, "L": 556, "M": 833, "N": 722, "O": 778, "P": 667,
    "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944, "X": 667,
    "Y": 667, "Z": 611,
    "a": 556, "b": 556, "c": 500, "d": 556, "e": 556, "f": 278, "g": 556, "h": 556,
    "i": 222, "j": 222, "k": 500, "l": 222, "m": 833, "n": 556, "o": 556, "p": 556,
    "q": 556, "r": 333, "s": 500, "t": 278, "u": 556, "v": 500, "w": 722, "x": 500,
    "y": 500, "z": 500,
}  # fmt: skip
_BOLD_DIFF = {
    "A": 722, "B": 722, "J": 556, "K": 722, "L": 611, "@": 975, "?": 611,
    "b": 611, "c": 556, "d": 611, "f": 333, "g": 611, "h": 611, "i": 278, "j": 278,
    "k": 556, "l": 278, "m": 889, "n": 611, "o": 611, "p": 611, "q": 611, "r": 389,
    "s": 556, "t": 333, "u": 611, "v": 556, "w": 778, "x": 556, "y": 556,
}  # fmt: skip


def text_width(text: str, size: float, bold: bool = False, letter_spacing: float = 0.0) -> float:
    """Estimated rendered width of one line of text, with WIDTH_SAFETY applied."""
    units = 0
    for ch in text:
        if bold and ch in _BOLD_DIFF:
            units += _BOLD_DIFF[ch]
        else:
            units += _REGULAR.get(ch, 600)
    return (units / 1000.0 * size + letter_spacing * len(text)) * WIDTH_SAFETY


def line_step(size: float) -> float:
    """Baseline-to-baseline distance for stacked lines of one font size."""
    return round(size * LINE_HEIGHT, 1)


# SVG building blocks -------------------------------------------------------


def defs(width: int, height: int) -> str:
    """Gradients, glow filters, grid pattern and arrow markers every picture uses."""
    markers = "".join(
        f'<marker id="arrow-{name}" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" '
        f'markerWidth="13" markerHeight="13" orient="auto-start-reverse">'
        f'<path d="M0 0L10 5L0 10z" fill="{c["arrow"]}"/></marker>'
        for name, c in ACCENTS.items()
    )
    return f"""<defs>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="{BG_TOP}"/>
<stop offset="0.55" stop-color="{BG_MID}"/>
<stop offset="1" stop-color="{BG_BOTTOM}"/>
</linearGradient>
<linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#1b4a8a"/><stop offset="1" stop-color="#0b2550"/>
</linearGradient>
<linearGradient id="hub" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#1f5aa8"/><stop offset="1" stop-color="#0b2a5c"/>
</linearGradient>
<filter id="glow" x="-40%" y="-40%" width="180%" height="180%">
<feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
</filter>
<filter id="softglow" x="-40%" y="-40%" width="180%" height="180%">
<feGaussianBlur stdDeviation="10" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
</filter>
<filter id="lineglow" x="0" y="0" width="{width}" height="{height}" filterUnits="userSpaceOnUse">
<feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
</filter>
<pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
<path d="M40 0H0V40" fill="none" stroke="{GRID_STROKE}" stroke-width="0.6"/>
</pattern>
{markers}
</defs>"""


def background(width: int, height: int, decor: dict) -> str:
    """Background gradient plus the optional grid, centre glow, circuit traces and pulse line."""
    w, h = width, height
    parts = [f'<rect width="{w}" height="{h}" fill="url(#bg)"/>']
    if decor.get("grid", True):
        parts.append(f'<rect width="{w}" height="{h}" fill="url(#grid)" opacity="0.55"/>')
    parts.append(
        f'<ellipse cx="{w / 2:g}" cy="{h * 0.49:g}" rx="{w * 0.33:g}" ry="{h * 0.29:g}" '
        f'fill="{CENTRE_GLOW}" opacity="0.07" filter="url(#softglow)"/>'
    )
    if decor.get("traces", False):
        # Faint traces hug the top band and the bottom-right corner, where titles and
        # footers leave room; coordinates scale with the canvas.
        def p(fx: float, fy: float) -> str:
            """A canvas point given as fractions of width and height."""
            return f"{w * fx:g} {h * fy:g}"

        paths = [
            f"M{p(0.62, 0.075)}H{w * 0.79:g}V{h * 0.14:g}H{w * 0.88:g}V{h * 0.066:g}H{w * 0.975:g}",
            f"M{p(0.40, 0.045)}H{w * 0.55:g}V{h * 0.11:g}",
            f"M{p(0.975, 0.93)}H{w * 0.87:g}V{h * 0.89:g}H{w * 0.80:g}",
        ]
        dots = [p(0.79, 0.075), p(0.88, 0.14), p(0.975, 0.066), p(0.55, 0.11), p(0.87, 0.93), p(0.80, 0.89)]
        parts.append(
            f'<g fill="none" stroke="{TRACE_STROKE}" stroke-width="1.4" opacity="0.5">'
            + "".join(f'<path d="{d}"/>' for d in paths)
            + "</g>"
        )
        parts.append(
            f'<g fill="{TRACE_DOT}" opacity="0.8">'
            + "".join(f'<circle cx="{d.split()[0]}" cy="{d.split()[1]}" r="3"/>' for d in dots)
            + "</g>"
        )
    if decor.get("pulse", False):
        y = h * 0.945
        x0 = w * 0.04
        parts.append(
            f'<path d="M{x0:g} {y:g} c 70 0, 90 -50, 150 -30 s 90 60, 160 20 s 80 -50, 140 -10" '
            f'fill="none" stroke="{PULSE_STROKE}" stroke-width="2" opacity="0.6" filter="url(#lineglow)"/>'
        )
    return "\n".join(parts)


def tile_rect(accent: str) -> str:
    """The rounded glowing tile body, drawn at the group origin."""
    stroke = ACCENTS[accent]["node"]
    return (
        f'<rect width="{TILE_SIZE}" height="{TILE_SIZE}" rx="{TILE_RADIUS}" fill="url(#tile)" '
        f'stroke="{stroke}" stroke-width="2" filter="url(#glow)"/>'
    )


def hub_rect(w: float, h: float, accent: str) -> str:
    """The wide hub body, drawn at the group origin."""
    stroke = ACCENTS[accent]["hub"]
    return (
        f'<rect width="{w:g}" height="{h:g}" rx="{HUB_RADIUS}" fill="url(#hub)" '
        f'stroke="{stroke}" stroke-width="2.5" filter="url(#softglow)"/>'
    )


# =================== END AIPass ====================
