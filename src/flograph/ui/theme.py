"""All colors and the application-wide theme live here — the single place
where core's hex strings become QColors.

The *canvas* is always dark: it is a Blueprints-style workspace and every
constant in the "canvas" block below is fixed, whatever the app theme. The
switchable part is the chrome around it — docks, panels, dialogs, menus,
tables — which follows a light/dark/system preference through `apply_theme`.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QApplication

from flograph.core import WIRE_COLORS, PortType
from flograph.core.node import NodeStatus

# ------------------------------------------------------------------ canvas
#
# Fixed. The canvas never changes with the app theme — see module docstring.

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


def wire_color(port_type: PortType) -> QColor:
    return QColor(WIRE_COLORS[port_type])


def status_color(status: NodeStatus) -> QColor:
    return STATUS_COLORS[status]


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
    "statusbar": "#202226",
}

_LIGHT = {
    "window": "#f3f4f6", "window_text": "#111827",
    "base": "#ffffff", "alt_base": "#eef0f2",
    "text": "#111827", "button": "#e8eaed", "button_text": "#111827",
    "bright_text": "#b91c1c",
    "light": "#ffffff", "midlight": "#f6f7f8", "dark": "#b4b9c1",
    "mid": "#616a77", "shadow": "#9aa0aa",
    "placeholder": "#8a909c",
    "tooltip_bg": "#111827", "tooltip_text": "#f3f4f6",
    "tooltip_border": "#111827",
    "highlight": "#3b82f6", "highlighted_text": "#ffffff",
    "link": "#2563eb", "link_visited": "#7c3aed", "accent": "#2563eb",
    "disabled_text": "#a3a8b2", "disabled_base": "#f0f1f3",
    "disabled_button": "#e8eaed",
    "dock_title": "#e4e6ea", "tab": "#e4e6ea", "tab_selected": "#ffffff",
    "statusbar": "#e4e6ea",
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

    app.setStyle("Fusion")
    app.setPalette(_make_palette(colors))
    app.setStyleSheet(_app_stylesheet(colors))


class _BackgroundFiller(QObject):
    """Paints a scroll area's background just before the widget paints it.

    Exists so that WA_OpaquePaintEvent can stay switched on -- see
    style_scroll_area for why that matters. The filter runs ahead of the
    widget's own paint handler and returns False, so everything is drawn on
    top of the fill exactly as before; the only difference is that no pixel
    is left untouched, which is the promise the attribute makes.
    """

    def __init__(self, area, color: QColor) -> None:
        super().__init__(area)
        self._color = QColor(color)
        viewport = area.viewport()
        viewport.installEventFilter(self)
        viewport.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Paint:
            painter = QPainter(obj)
            painter.fillRect(event.rect(), self._color)
            painter.end()
        return False


def grid_stylesheet() -> str:
    """The dark table look shared by canvas cards, dashboard tiles and the
    dashboard's maximized pages — one definition so a grid reads the same
    wherever it appears. Apply it with style_scroll_area, not setStyleSheet.
    """
    return (f"QTableView {{ background: {NODE_BODY.name()};"
            f" color: {NODE_TEXT.name()}; border: none;"
            f" gridline-color: {NODE_BORDER.name()}; font-size: 8.5pt; }}"
            f"QHeaderView::section {{ background: {NODE_HEADER.name()};"
            f" color: {NODE_SUBTEXT.name()};"
            f" border: 1px solid {NODE_BORDER.name()}; padding: 2px; }}")


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
    area.setStyleSheet(stylesheet)
    existing = getattr(area, "_flograph_bg_filler", None)
    if existing is not None:
        existing.setParent(None)
    area._flograph_bg_filler = _BackgroundFiller(
        area, background if background is not None else NODE_BODY)
