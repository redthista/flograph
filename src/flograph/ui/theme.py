"""All colors and the application-wide dark theme live here — the single
place where core's hex strings become QColors."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QApplication

from flograph.core import WIRE_COLORS, PortType
from flograph.core.node import NodeStatus

# ------------------------------------------------------------------ canvas

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

def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    window = QColor("#24262b")
    base = QColor("#1e2024")
    text = QColor("#e5e7eb")
    disabled = QColor("#6b7280")
    highlight = QColor("#3b82f6")

    palette.setColor(QPalette.Window, window)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Base, base)
    palette.setColor(QPalette.AlternateBase, window)
    palette.setColor(QPalette.ToolTipBase, base)
    palette.setColor(QPalette.ToolTipText, text)
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.Button, window)
    palette.setColor(QPalette.ButtonText, text)
    palette.setColor(QPalette.BrightText, QColor("#f87171"))
    palette.setColor(QPalette.Link, highlight)
    palette.setColor(QPalette.Highlight, highlight)
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, disabled)
    app.setPalette(palette)

    app.setStyleSheet("""
        QToolTip { background: #1e2024; color: #e5e7eb; border: 1px solid #3a3d46; }
        QDockWidget::title { background: #2a2c33; padding: 4px 8px; }
        QTabBar::tab { background: #24262b; padding: 5px 12px; border: none; }
        QTabBar::tab:selected { background: #33363e; }
        QStatusBar { background: #202226; }
    """)


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
