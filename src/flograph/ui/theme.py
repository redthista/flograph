"""All colors and the application-wide theme live here — the single place
where core's hex strings become QColors.

Everything here follows a light/dark/system preference through
`apply_theme`: the chrome (docks, panels, dialogs, menus, tables, the title
bar and toolbar) *and* the canvas. The canvas constants below are module
state — `apply_theme` rewrites them in place — so painting code must read
them as `theme.NODE_BODY` at paint time, never copy them at import.
"""
from __future__ import annotations

import re
import weakref

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QApplication

from flograph.core import WIRE_COLORS, PortType
from flograph.core.node import NodeStatus

# ------------------------------------------------------------------ canvas
#
# Dark by default; `apply_theme` swaps these for the light set (see
# `_CANVAS_LIGHT` below) and back. Read them at paint time.

CANVAS_BG = QColor("#1b1c20")
GRID_FINE = QColor("#232429")
GRID_COARSE = QColor("#2c2d34")

NODE_BODY = QColor("#2a2c33")
NODE_HEADER = QColor("#363943")
NODE_HEADER_BROKEN = QColor("#4c2626")
NODE_BORDER = QColor("#17181c")
NODE_BORDER_BROKEN = QColor("#7f1d1d")
NODE_TEXT = QColor("#e5e7eb")
NODE_SUBTEXT = QColor("#9ca3af")
SELECTION_OUTLINE = QColor("#60a5fa")
# A frozen node whose inputs have moved since it was pinned: the amber says
# "this is deliberate but no longer true", which is exactly the state.
PIN_STALE = QColor("#eab308")
# A healthy pin. Ice, and deliberately not near any status colour — green
# done, red error, blue running, amber queued — because in the minimap this
# has to be told apart from all four at four pixels across.
PIN_HELD = QColor("#22d3ee")
# A bypassed node, and the line drawn through it from the input it hands on
# to the output it feeds. Fuchsia because it has to sit apart from the four
# status colours and from both pin colours, on the card and in the minimap.
BYPASS = QColor("#e879f9")

# Status-bar memory bar, brightest first: the project's own cached outputs,
# the rest of the flograph process, everything else the machine is using.
# One hue stepping down in brightness rather than three colours, so the bar
# reads as "how much of this is mine" at a glance instead of asking to be
# decoded against a key.
MEM_CACHE = QColor("#60a5fa")
MEM_APP = QColor("#3b6299")
MEM_OTHER = QColor("#4b4e58")

FRAME_TITLE = QColor("#d1d5db")
BUTTON_ACCENT = QColor("#7c6cf6")

# ------------------------------------------------------------------- tinting
#
# User-picked colours are never painted flat. A colour straight from the
# picker is fully saturated and fights the dark theme; laid over the themed
# surface at low alpha it keeps its hue but takes the theme's value, which is
# why frames have always looked calm. These are the canonical strengths —
# SOFT for large surfaces (a card body, an unselected tab), STRONG for the
# smaller strip that has to stand out from it (a header, the selected tab).
#
# How muted is a matter of taste, so Settings > Canvas can retune both. The
# current values are module state that painting code must read at paint time
# (theme.TINT_SOFT, never a module-level copy taken at import) — otherwise a
# settings change won't reach it until restart.

DEFAULT_TINT_SOFT = 0.30
DEFAULT_TINT_STRONG = 0.55

TINT_SOFT = DEFAULT_TINT_SOFT
TINT_STRONG = DEFAULT_TINT_STRONG


def set_tints(soft: float, strong: float) -> None:
    """Retune the muting. Callers repaint; this only moves the numbers."""
    global TINT_SOFT, TINT_STRONG
    TINT_SOFT = max(0.0, min(1.0, soft))
    TINT_STRONG = max(0.0, min(1.0, strong))


def tint(base: QColor, color, alpha: float) -> QColor:
    """`color` laid over `base` at `alpha`, as an opaque colour.

    Composited here rather than by painting translucently so callers get a
    concrete colour they can hand to a brush, gradient or stylesheet.
    """
    over = QColor(color)
    return QColor(
        round(over.red() * alpha + base.red() * (1 - alpha)),
        round(over.green() * alpha + base.green() * (1 - alpha)),
        round(over.blue() * alpha + base.blue() * (1 - alpha)),
    )

def page_tint(color, alpha: float = None) -> QColor:
    """A page's own colour as it is laid **over** its tab, or None when
    the page has no colour.

    Translucent, unlike `tint` above: the themed tab shows through, so
    whatever the colour picker returned comes out muted rather than
    garish. Read at paint time, so Settings ▸ Canvas reaches it without a
    restart — hence the default resolved here rather than in a signature
    that is bound at import.

    One definition because three places have to agree on it: the tab bar,
    the second row of pages, and the pixmap Qt makes of a tab being
    dragged (`dashboard.page_bar.DraggedTabStyle`).
    """
    if not color:
        return None
    over = QColor(color)
    over.setAlphaF(TINT_STRONG if alpha is None else alpha)
    return over


STATUS_COLORS: dict[NodeStatus, QColor] = {
    NodeStatus.IDLE: QColor("#6b7280"),
    NodeStatus.QUEUED: QColor("#eab308"),
    NodeStatus.RUNNING: QColor("#3b82f6"),
    NodeStatus.DONE: QColor("#22c55e"),
    NodeStatus.ERROR: QColor("#ef4444"),
}

WIRE_VALID = QColor("#4ade80")
WIRE_INVALID = QColor("#ef4444")
WIRE_PENDING = QColor("#93c5fd")


# The wire hues in core are chosen for a dark canvas. On a light one the
# pale ones (ANY, SERIES, the flow grey) all but vanish, so the light mode
# keeps each hue and drops its lightness.
_WIRE_LIGHT = {
    PortType.ANY: "#374151",
    PortType.DATAFRAME: "#0b6b63",
    PortType.SERIES: "#0f766e",
    PortType.NUMBER: "#166534",
    PortType.STRING: "#92400e",
    PortType.BOOL: "#b91c1c",
    PortType.OBJECT: "#374151",
    PortType.FIGURE: "#6d28d9",
    PortType.FLOW: "#334155",
}


def wire_color(port_type: PortType) -> QColor:
    if APP_MODE == "light":
        return QColor(_WIRE_LIGHT[port_type])
    return QColor(WIRE_COLORS[port_type])


def status_color(status: NodeStatus) -> QColor:
    return STATUS_COLORS[status]


# ------------------------------------------------------------ canvas sets
#
# The two looks of the canvas. `_apply_canvas` copies one of them onto the
# module constants above. Light is built around one idea: the canvas is a
# *tinted* grey and a node is the brightest thing on it, with an edge dark
# enough to see — the contrast a user of the dark theme asked for, which a
# node of near-canvas colour could not give.

_CANVAS_DARK = {
    "CANVAS_BG": "#1b1c20", "GRID_FINE": "#232429", "GRID_COARSE": "#2c2d34",
    "NODE_BODY": "#2a2c33", "NODE_HEADER": "#363943",
    "NODE_HEADER_BROKEN": "#4c2626", "NODE_BORDER": "#17181c",
    "NODE_BORDER_BROKEN": "#7f1d1d", "NODE_TEXT": "#e5e7eb",
    "NODE_SUBTEXT": "#9ca3af", "SELECTION_OUTLINE": "#60a5fa",
    "PIN_STALE": "#eab308", "PIN_HELD": "#22d3ee", "BYPASS": "#e879f9",
    "MEM_CACHE": "#60a5fa", "MEM_APP": "#3b6299", "MEM_OTHER": "#4b4e58",
    "FRAME_TITLE": "#d1d5db", "BUTTON_ACCENT": "#7c6cf6",
    "WIRE_VALID": "#4ade80", "WIRE_INVALID": "#ef4444",
    "WIRE_PENDING": "#93c5fd",
}

_CANVAS_LIGHT = {
    "CANVAS_BG": "#c9ced7", "GRID_FINE": "#c0c6d0", "GRID_COARSE": "#b0b7c3",
    "NODE_BODY": "#f8f9fb", "NODE_HEADER": "#e4e7ed",
    "NODE_HEADER_BROKEN": "#fbd5d5", "NODE_BORDER": "#7b8494",
    "NODE_BORDER_BROKEN": "#dc2626", "NODE_TEXT": "#161a22",
    "NODE_SUBTEXT": "#4b5563", "SELECTION_OUTLINE": "#3b6cf6",
    "PIN_STALE": "#b7791f", "PIN_HELD": "#0891b2", "BYPASS": "#c026d3",
    "MEM_CACHE": "#2563eb", "MEM_APP": "#7ea1dd", "MEM_OTHER": "#aab1be",
    "FRAME_TITLE": "#374151", "BUTTON_ACCENT": "#7c6cf6",
    "WIRE_VALID": "#15803d", "WIRE_INVALID": "#b91c1c",
    "WIRE_PENDING": "#1d4ed8",
}

_STATUS_DARK = {
    NodeStatus.IDLE: "#6b7280", NodeStatus.QUEUED: "#eab308",
    NodeStatus.RUNNING: "#3b82f6", NodeStatus.DONE: "#22c55e",
    NodeStatus.ERROR: "#ef4444",
}
_STATUS_LIGHT = {
    NodeStatus.IDLE: "#8a91a0", NodeStatus.QUEUED: "#b7791f",
    NodeStatus.RUNNING: "#2563eb", NodeStatus.DONE: "#16a34a",
    NodeStatus.ERROR: "#dc2626",
}


# How much of a frame's own colour shows, as alpha over the canvas: body,
# title bar, a collapsed frame's body, and the run chip (rest / hover). A
# colour that tints a dark canvas gently is a heavy slab on a light one, and
# the title text sits on it — so light mode lays it on much thinner.
_FRAME_DARK = {"FRAME_FILL": 0.18, "FRAME_TITLE_BAR": 0.45,
               "FRAME_FOLDED": 0.45, "FRAME_CHIP": 0.40,
               "FRAME_CHIP_HOVER": 0.65}
_FRAME_LIGHT = {"FRAME_FILL": 0.16, "FRAME_TITLE_BAR": 0.16,
                "FRAME_FOLDED": 0.22, "FRAME_CHIP": 0.18,
                "FRAME_CHIP_HOVER": 0.40}
FRAME_FILL = _FRAME_DARK["FRAME_FILL"]
FRAME_TITLE_BAR = _FRAME_DARK["FRAME_TITLE_BAR"]
FRAME_FOLDED = _FRAME_DARK["FRAME_FOLDED"]
FRAME_CHIP = _FRAME_DARK["FRAME_CHIP"]
FRAME_CHIP_HOVER = _FRAME_DARK["FRAME_CHIP_HOVER"]


def _apply_canvas(mode: str) -> None:
    """Point the canvas constants at the `mode` set, in place."""
    g = globals()
    g.update(_FRAME_LIGHT if mode == "light" else _FRAME_DARK)
    for name, hexcode in (_CANVAS_LIGHT if mode == "light"
                          else _CANVAS_DARK).items():
        g[name] = QColor(hexcode)
    for status, hexcode in (_STATUS_LIGHT if mode == "light"
                            else _STATUS_DARK).items():
        STATUS_COLORS[status] = QColor(hexcode)


# ------------------------------------------------------------ window chrome
#
# The custom title bar, the toolbar and the start screen draw themselves
# from QSS strings and painted icons rather than the palette, so they ask
# here. `chrome()` is read when a widget (re)styles itself; widgets that
# must follow a live switch register with `on_change`.

_CHROME_DARK = {
    "bar_bg": "#17181c", "bar_border": "#14151a", "fg": "#c8cbd2",
    "fg_strong": "#f3f4f6", "fg_dim": "#8b8f99", "fg_disabled": "#5f636d",
    "hover": "#34363f", "pressed": "#3d404a", "outline": "#3c3f49",
    "sep": "#2c2d34", "panel": "#2b2d36", "panel_line": "#3a3d47",
    "star_off": "#7f838d", "track": "#1c1d23", "unselected": "#4b5563",
    "frozen": "#5b8def", "run": "#22c55e", "reset": "#eab308",
    "close_hover": "#e5484d",
}
_CHROME_LIGHT = {
    "bar_bg": "#3a3f48", "bar_border": "#2a2d33", "fg": "#d9dce3",
    "fg_strong": "#ffffff", "fg_dim": "#a3a9b5", "fg_disabled": "#7a808b",
    "hover": "#4a505b", "pressed": "#575e6a", "outline": "#5a606c",
    "sep": "#505662", "panel": "#454a54", "panel_line": "#5a606c",
    "star_off": "#8b909c", "track": "#2a2d33", "unselected": "#7b8494",
    "frozen": "#7aa2f7", "run": "#4ade80", "reset": "#facc15",
    "close_hover": "#e5484d",
}


# ------------------------------------------------------------------ skin
#
# Most of flograph's widgets were drawn in the dark theme first, with their
# colours written into a stylesheet or a QColor as hex. `skin` is the one
# translation table that turns those into their light-mode counterparts, so
# a widget keeps writing the dark value it always has and asks here. Only
# neutrals and the few "bright on dark" text accents are mapped; a
# status/brand colour (green, red, the purple accent) means the same in both
# modes and is left alone, as is white.

_SKIN = {
    # canvas / surfaces
    "#1b1c20": "#e3e6ec", "#17181c": "#9aa2b1", "#14151a": "#c3c8d1",
    "#111318": "#c3c8d1", "#0c0d0f": "#9aa0aa",
    "#1e2024": "#ffffff", "#1f2026": "#ffffff", "#1f2024": "#ffffff",
    "#202127": "#ffffff", "#202226": "#eceef2", "#23252c": "#eef0f4",
    "#24262c": "#eef0f4", "#24262d": "#eef0f4", "#25272e": "#eef0f4",
    "#2a2c33": "#ffffff", "#2c2d34": "#cfd3db", "#2f323b": "#e4e7ed",
    "#363943": "#dde2ec",
    # hover / pressed / borders
    "#34363f": "#dcdfe6", "#3e414c": "#d3d7de", "#3a3d47": "#cfd3db",
    "#3d404a": "#ccd0d9", "#3c3f49": "#c3c8d1", "#3a3d46": "#c3c8d1",
    "#3b3d46": "#c3c8d1", "#3a3e47": "#c3c8d1", "#44475a": "#b4bac4",
    "#4b4e58": "#c3c8d1", "#4b4f5c": "#b4bac4", "#4b5563": "#9aa2b1",
    "#5b5f68": "#9aa2b1",
    # disabled
    "#5d616c": "#a3a8b2", "#5f636d": "#a3a8b2", "#6b7080": "#a3a8b2",
    # text
    "#e5e7eb": "#111827", "#f3f4f6": "#111827", "#f4f5f7": "#111827",
    "#d6d8de": "#374151", "#d1d5db": "#374151", "#c8cbd2": "#374151",
    "#c9ccd3": "#374151", "#d7dae0": "#374151", "#aeb2bc": "#4b5563",
    "#9ca3af": "#6b7280", "#8b909c": "#6b7280", "#8b8f99": "#6b7280",
    "#9aa0ab": "#6b7280", "#9aa0a6": "#6b7280", "#9da5b4": "#6b7280",
    # selection fills
    "#3b4a7a": "#cfe0fd", "#264f78": "#bcd7fb", "#1e3a5f": "#d6e4fb",
    "#2b3550": "#dbe6fb", "#33415c": "#dbe6fb",
    # tinted warning fills
    "#4b1d24": "#fde4e4", "#3b4a2a": "#e3f4dc", "#6b5a1a": "#fdf0c4",
    # bright-on-dark accents that need to deepen on light
    "#60a5fa": "#2563eb", "#93c5fd": "#2563eb", "#f87171": "#dc2626",
    "#ef4444": "#dc2626", "#fde68a": "#92400e", "#fbbf24": "#b45309",
    "#eab308": "#a16207", "#86efac": "#15803d",
}

# The canvas constants are written *into* stylesheets as `dark_hex(NAME)` —
# always the dark value — so what a widget stores is dark-theme source for
# both modes, and this map (built from the two canvas sets, so it cannot
# drift from them) is the one thing that makes it light.
for _name in ("CANVAS_BG", "GRID_FINE", "GRID_COARSE", "NODE_BODY",
              "NODE_HEADER", "NODE_BORDER", "NODE_TEXT", "NODE_SUBTEXT",
              "SELECTION_OUTLINE", "FRAME_TITLE"):
    _SKIN[_CANVAS_DARK[_name].lower()] = _CANVAS_LIGHT[_name]


def dark_hex(name: str) -> str:
    """The dark-theme hex of canvas constant `name`, for a stylesheet that
    will go through `set_qss` / `skin`."""
    return _CANVAS_DARK[name]


_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def skin(text: str) -> str:
    """`text` (a stylesheet, or one hex colour) as the current mode wants
    it. The identity in dark mode."""
    if APP_MODE != "light" or "#" not in text:
        return text
    return _HEX.sub(lambda m: _SKIN.get(m.group(0).lower(), m.group(0)), text)


def skin_color(color) -> QColor:
    """A QColor written for the dark theme, as the current mode wants it."""
    c = QColor(color)
    if APP_MODE != "light":
        return c
    mapped = _SKIN.get(c.name().lower())
    if mapped is None:
        return c
    out = QColor(mapped)
    out.setAlpha(c.alpha())
    return out


# widget -> the dark-theme stylesheet it was given, so a live switch can
# translate it again. Weak: a closed dialog must not be kept alive by this.
_skinned: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def set_qss(widget, qss: str) -> None:
    """`widget.setStyleSheet(qss)` for a stylesheet written in dark-theme
    colours: translated for the mode now, and again on every theme change."""
    try:
        _skinned[widget] = qss
    except TypeError:
        pass                      # not weak-referenceable: no live switch
    widget.setStyleSheet(skin(qss))


def _restyle_skinned() -> None:
    for widget, qss in list(_skinned.items()):
        try:
            widget.setStyleSheet(skin(qss))
        except RuntimeError:
            pass                  # the C++ half is already gone


def card_look(note: bool = False):
    """The look of a dashboard tile that has not been formatted — the
    theme's card. `core.tile_style.CARD_LOOK` is that card in dark-theme
    hex (core is Qt-free and knows no mode), so the colours that follow the
    theme are filled in here."""
    from dataclasses import replace
    from flograph.core.tile_style import CARD_LOOK, NOTE_LOOK
    if note:
        return NOTE_LOOK          # every colour of it is left to the painter
    if APP_MODE != "light":
        return CARD_LOOK
    return replace(
        CARD_LOOK, frame_color=NODE_BORDER.name(),
        background=NODE_BODY.name(), title_color=NODE_TEXT.name(),
        title_background=NODE_HEADER.name(), shadow=True)


# A node's category as a colour: the one splash of identity a light card
# has, since its body is white whatever it does. Used as a thin stripe on
# the header; dark cards do without it.
CATEGORY_COLOURS = {
    "io": "#3b82f6", "input": "#14b8a6", "transform": "#8b5cf6",
    "viz": "#f59e0b", "util": "#64748b", "scripting": "#ec4899",
    "ai": "#6366f1", "ml": "#a855f7", "connect": "#0ea5e9",
    "automation": "#f97316",
}


def category_color(category: str) -> QColor | None:
    """The category stripe colour, or None where cards carry no stripe."""
    if APP_MODE != "light":
        return None
    return QColor(CATEGORY_COLOURS.get(
        (category or "").split("/")[0].strip().lower(), "#94a3b8"))


def category_tint(category: str, alpha: float) -> QColor | None:
    """The category colour laid thinly over a card's white, or None in the
    dark theme. KNIME's habit, and the one most people already read: a
    node's colour says what kind of step it is before its name does."""
    base = category_color(category)
    if base is None:
        return None
    return tint(NODE_BODY, base, alpha)


def category_edge(category: str) -> QColor | None:
    """A node's outline in its category's colour, deepened a little so a
    one-pixel line still reads on white — or None in the dark theme."""
    base = category_color(category)
    if base is None:
        return None
    return tint(QColor("#475569"), base, 0.78)


def chrome(key: str) -> str:
    """A title-bar / toolbar colour (hex string) for the current mode."""
    return (_CHROME_LIGHT if APP_MODE == "light" else _CHROME_DARK)[key]


_listeners: list = []


def on_change(callback) -> None:
    """Call `callback()` after every `apply_theme`. Held strongly, so pass
    a bound method of something that lives as long as the app (the main
    window), not a short-lived widget."""
    if callback not in _listeners:
        _listeners.append(callback)


def off_change(callback) -> None:
    if callback in _listeners:
        _listeners.remove(callback)


# ------------------------------------------------------------------- app
#
# The chrome theme: light, dark, or "system" (follow the OS). The canvas
# above is untouched by any of this. Painting code that wants the chrome
# colour of something must read `theme.APP_MODE` (or a `palette(...)` role
# in a stylesheet) at paint time, never a copy taken at import — a live
# switch moves this module state and re-polishes, it does not restart.

#: Allowed values for the stored preference.
THEME_PREFS = ("system", "light", "dark")

#: The *resolved* mode currently in force — "light" or "dark", never
#: "system". Set by `apply_theme`; defaults to dark so a module imported
#: before the app is themed still gets sane colours.
APP_MODE = "dark"


def is_dark() -> bool:
    return APP_MODE != "light"


# Every visual role, spelled out. An unset QPalette role is resolved from
# the *system* palette, which is how a light desktop leaked pale text into
# flograph's dark theme — some colours flograph's, some the OS's. Nothing
# below is left unset, and Active / Inactive / Disabled are all filled, so
# the theme looks the same on a light desktop, a dark one, and an
# unfocused window.
_DARK = {
    "window": "#24262b", "window_text": "#e5e7eb",
    "base": "#1e2024", "alt_base": "#202226",
    "text": "#e5e7eb", "button": "#24262b", "button_text": "#e5e7eb",
    "bright_text": "#f87171",
    "light": "#3a3d47", "midlight": "#2f323b", "dark": "#141517",
    # `mid` is Fusion's bevel-shadow colour *and*, by long convention, the
    # "secondary text" colour dim labels pull with `color: palette(mid)`.
    # Kept light enough to read on `base`, dark enough not to glow as a bevel.
    "mid": "#8b929e", "shadow": "#0c0d0f",
    "placeholder": "#7f8694",
    "tooltip_bg": "#1e2024", "tooltip_text": "#e5e7eb",
    "tooltip_border": "#3a3d46",
    "highlight": "#3b82f6", "highlighted_text": "#ffffff",
    "link": "#60a5fa", "link_visited": "#a78bfa", "accent": "#60a5fa",
    "disabled_text": "#6b7280", "disabled_base": "#1b1d21",
    "disabled_button": "#24262b",
    "dock_title": "#2a2c33", "tab": "#24262b", "tab_selected": "#33363e",
    "statusbar": "#202226", "line": "#24262b", "accent_line": "#60a5fa",
}

_LIGHT = {
    "window": "#e2e5ea", "window_text": "#111827",
    "base": "#fafbfc", "alt_base": "#eef0f3",
    "text": "#111827", "button": "#d6dae1", "button_text": "#111827",
    "bright_text": "#b91c1c",
    "light": "#ffffff", "midlight": "#f6f7f8", "dark": "#b4b9c1",
    "mid": "#616a77", "shadow": "#9aa0aa",
    "placeholder": "#8a909c",
    "tooltip_bg": "#111827", "tooltip_text": "#f3f4f6",
    "tooltip_border": "#111827",
    "highlight": "#3b82f6", "highlighted_text": "#ffffff",
    "link": "#2563eb", "link_visited": "#7c3aed", "accent": "#2563eb",
    "disabled_text": "#a3a8b2", "disabled_base": "#f0f1f3",
    "disabled_button": "#d6dae1",
    "dock_title": "#d3d7de", "tab": "#d3d7de", "tab_selected": "#e9ebef",
    "statusbar": "#d3d7de", "line": "#b9bfc9", "accent_line": "#3b6cf6",
}

#: (QPalette role, key in the colour dict) for every role we set in all
#: three state groups. `mid` doubles as the "secondary text" colour that
#: dim labels pull with `color: palette(mid)`.
_PALETTE_ROLES = (
    (QPalette.Window, "window"), (QPalette.WindowText, "window_text"),
    (QPalette.Base, "base"), (QPalette.AlternateBase, "alt_base"),
    (QPalette.ToolTipBase, "tooltip_bg"), (QPalette.ToolTipText, "tooltip_text"),
    (QPalette.PlaceholderText, "placeholder"),
    (QPalette.Text, "text"), (QPalette.Button, "button"),
    (QPalette.ButtonText, "button_text"), (QPalette.BrightText, "bright_text"),
    (QPalette.Light, "light"), (QPalette.Midlight, "midlight"),
    (QPalette.Dark, "dark"), (QPalette.Mid, "mid"),
    (QPalette.Shadow, "shadow"),
    (QPalette.Highlight, "highlight"),
    (QPalette.HighlightedText, "highlighted_text"),
    (QPalette.Link, "link"), (QPalette.LinkVisited, "link_visited"),
)

_GROUPS = (QPalette.Active, QPalette.Inactive, QPalette.Disabled)


def _make_palette(c: dict) -> QPalette:
    palette = QPalette()
    for group in _GROUPS:
        for role, key in _PALETTE_ROLES:
            palette.setColor(group, role, QColor(c[key]))
    accent = getattr(QPalette, "Accent", None)     # Qt 6.6+
    if accent is not None:
        for group in _GROUPS:
            palette.setColor(group, accent, QColor(c["accent"]))
    # Disabled: dimmer text, sunk fills — a real state, not an OS artefact.
    for role, key in (
            (QPalette.WindowText, "disabled_text"),
            (QPalette.Text, "disabled_text"),
            (QPalette.ButtonText, "disabled_text"),
            (QPalette.HighlightedText, "disabled_text"),
            (QPalette.Base, "disabled_base"),
            (QPalette.Button, "disabled_button"),
            (QPalette.Highlight, "disabled_button")):
        palette.setColor(QPalette.Disabled, role, QColor(c[key]))
    return palette


def _light_extras(c: dict) -> str:
    """What a light UI does that a dark one gets for free from its contrast:
    surfaces are told apart by hairlines and one accent, not by value. Only
    added in light mode, so the dark chrome is exactly what it was."""
    return f"""
        QDockWidget::title {{ border-bottom: 1px solid {c['line']};
                              font-weight: 600; }}
        QTabBar::tab {{ border-bottom: 2px solid transparent; color: palette(mid); }}
        QTabBar::tab:selected {{ border-bottom: 2px solid {c['accent_line']};
                                 color: palette(window-text); }}
        QStatusBar {{ border-top: 1px solid {c['line']}; }}
        QToolTip {{ border-radius: 4px; padding: 3px 6px; }}
    """


def _app_stylesheet(c: dict) -> str:
    return f"""
        QToolTip {{ background: {c['tooltip_bg']}; color: {c['tooltip_text']};
                    border: 1px solid {c['tooltip_border']}; }}
        QDockWidget::title {{ background: {c['dock_title']}; padding: 4px 8px; }}
        QTabBar::tab {{ background: {c['tab']}; padding: 5px 12px; border: none; }}
        QTabBar::tab:selected {{ background: {c['tab_selected']}; }}
        QStatusBar {{ background: {c['statusbar']}; }}
    """


def resolve_theme_pref(app: QApplication, pref: str) -> str:
    """Turn a stored preference into the mode to actually apply."""
    if pref in ("light", "dark"):
        return pref
    scheme = app.styleHints().colorScheme()
    return "light" if scheme == Qt.ColorScheme.Light else "dark"


def apply_theme(app: QApplication, pref: str = "dark") -> None:
    """Style the whole application for `pref` ("system" | "light" | "dark").

    Re-callable: a live theme switch just calls this again, and Qt's own
    StyleChange / ApplicationPaletteChange propagation re-polishes every
    open widget. The canvas is unaffected either way.
    """
    global APP_MODE
    if pref not in THEME_PREFS:
        pref = "system"

    # Pin the scheme when the user chose one outright, so a platform theme
    # (GTK on this user's Fedora, say) stops pushing its own palette values
    # back over ours — the cause of dark-on-dark text on a light desktop.
    # In "system" mode we unset it *first*, so the resolve below reads the
    # OS scheme and not a value we pinned on a previous call.
    hints = app.styleHints()
    try:
        if pref == "light":
            hints.setColorScheme(Qt.ColorScheme.Light)
        elif pref == "dark":
            hints.setColorScheme(Qt.ColorScheme.Dark)
        else:
            hints.unsetColorScheme()
    except AttributeError:
        pass                       # Qt < 6.8 — palette alone still applies

    mode = resolve_theme_pref(app, pref)
    APP_MODE = mode
    colors = _LIGHT if mode == "light" else _DARK

    _apply_canvas(mode)
    app.setStyle("Fusion")
    app.setPalette(_make_palette(colors))
    app.setStyleSheet(_app_stylesheet(colors)
                      + (_light_extras(colors) if mode == "light" else ""))
    _restyle_skinned()
    for callback in list(_listeners):
        try:
            callback()
        except RuntimeError:
            _listeners.remove(callback)      # its owner was deleted


class _BackgroundFiller(QObject):
    """Paints a scroll area's background just before the widget paints it.

    Exists so that WA_OpaquePaintEvent can stay switched on -- see
    style_scroll_area for why that matters. The filter runs ahead of the
    widget's own paint handler and returns False, so everything is drawn on
    top of the fill exactly as before; the only difference is that no pixel
    is left untouched, which is the promise the attribute makes.
    """

    def __init__(self, area, color: QColor | None) -> None:
        super().__init__(area)
        # None = the card body colour *now*, so a theme switch needs no
        # re-wiring of a grid that was filled with the old one
        self._color = QColor(color) if color is not None else None
        viewport = area.viewport()
        viewport.installEventFilter(self)
        viewport.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Paint:
            painter = QPainter(obj)
            painter.fillRect(event.rect(), self._color or NODE_BODY)
            painter.end()
        return False


def grid_stylesheet() -> str:
    """The dark table look shared by canvas cards, dashboard tiles and the
    dashboard's maximized pages — one definition so a grid reads the same
    wherever it appears. Apply it with style_scroll_area, not setStyleSheet.

    The text size is the one from Settings ▸ General when it has been
    set, so a grid on a card shrinks with the inspector's rather than
    keeping a size of its own.
    """
    from .data_table import GRID_FONT_PT, table_text_size
    points = table_text_size() or GRID_FONT_PT
    return (f"QTableView {{ background: {_CANVAS_DARK['NODE_BODY']};"
            f" color: {_CANVAS_DARK['NODE_TEXT']}; border: none;"
            f" gridline-color: {_CANVAS_DARK['NODE_BORDER']};"
            f" font-size: {points:g}pt; }}"
            f"QHeaderView::section {{ background: {_CANVAS_DARK['NODE_HEADER']};"
            f" color: {_CANVAS_DARK['NODE_SUBTEXT']};"
            f" border: 1px solid {_CANVAS_DARK['NODE_BORDER']}; padding: 2px; }}"
            # the corner above the row numbers, and a header's empty stretch
            # past its last section: without these the app palette shows
            # through, which is a light square in light mode
            f"QTableCornerButton::section {{ background: {_CANVAS_DARK['NODE_HEADER']};"
            f" border: 1px solid {_CANVAS_DARK['NODE_BORDER']}; }}"
            f"QHeaderView {{ background: {_CANVAS_DARK['NODE_BODY']}; }}")


def style_scroll_area(area, stylesheet: str, background: QColor = None) -> None:
    """Style a table/list without costing it its scroll-blitting.

    A QAbstractScrollArea carrying a stylesheet has QStyleSheetStyle take
    over its viewport background, and Qt then clears WA_OpaquePaintEvent --
    at which point QWidget::scroll() can no longer shift the pixels it
    already has, so every notch of the wheel re-renders the whole visible
    area instead of the one row that came into view. Measured on a 300-row
    grid: 2,268 cells redrawn per scroll against 168, 8.3 ms against 1.0 ms.
    The cost grows with the widget, so a maximized dashboard page suffered
    worst -- and a maximized page is where data actually gets typed in.

    Setting the attribute back on alone is not enough: the area past the
    last column then paints as black, because the attribute is a promise the
    widget fills every pixel and a stylesheet-styled table does not. So the
    fill is supplied here, by an event filter, and the promise is kept.

    The palette route (QPalette::Base, ::Mid for grid lines) looks like the
    tidier answer and is not: with the app palette applied it neither
    reaches the viewport nor drives the grid line colour, so the grid comes
    out the wrong colour with no lines at all.
    """
    set_qss(area, stylesheet)
    existing = getattr(area, "_flograph_bg_filler", None)
    if existing is not None:
        existing.setParent(None)
    area._flograph_bg_filler = _BackgroundFiller(area, background)
