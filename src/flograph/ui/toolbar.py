"""The main window's top toolbar — its look, and the glyphs on its buttons.

Split out of ``mainwindow`` so the styling lives in one place and the icons
can be unit-tested without standing up a whole window.

The glyphs are drawn, not loaded — the same reasoning ``canvas/marks.py``
records: a shipped .svg has to survive the one-file build and Qt's
stylesheet parser rejects an inline data URI, so a dozen ``QPainterPath``
lines that always draw and stay crisp at any DPI is the smaller machinery.
The colours are the canvas status language on purpose (green run, red
stop, amber reset), so the toolbar reads the same way the nodes do.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import theme

# Module state, like the canvas colours: `apply_mode` re-points them, so
# read them as `toolbar.RUN` when drawing, never copy them at import.
RUN = QColor("#22c55e")
STOP = QColor("#ef4444")
RESET = QColor("#eab308")


def apply_mode() -> None:
    """Green / red / amber, in the lightness the current theme can read."""
    global RUN, STOP, RESET
    RUN = QColor(theme.chrome("run"))
    STOP = QColor(theme.chrome("stop"))
    RESET = QColor(theme.chrome("reset"))
    _GLYPHS["run_all"] = (_play, RUN)
    _GLYPHS["run_selected"] = (_play_boxed, RUN)
    _GLYPHS["cancel"] = (_stop, STOP)
    _GLYPHS["reset_caches"] = (_reset, RESET)

_ICON_PT = 18  # logical size the glyphs are drawn at; the toolbar shows them at 16


def _pt(x: float, y: float) -> QPointF:
    return QPointF(x, y)


def _pen(color: QColor, rect: QRectF, weight: float = 0.12) -> QPen:
    pen = QPen(color, max(1.1, rect.width() * weight))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _play(painter: QPainter, rect: QRectF, color: QColor) -> None:
    w, h = rect.width(), rect.height()
    path = QPainterPath(rect.topLeft() + _pt(w * 0.26, h * 0.16))
    path.lineTo(rect.topLeft() + _pt(w * 0.26, h * 0.84))
    path.lineTo(rect.topLeft() + _pt(w * 0.84, h * 0.50))
    path.closeSubpath()
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawPath(path)


def _play_boxed(painter: QPainter, rect: QRectF, color: QColor) -> None:
    w, h = rect.width(), rect.height()
    box = QRectF(rect.left() + w * 0.10, rect.top() + h * 0.10,
                 w * 0.80, h * 0.80)
    painter.setPen(_pen(color, rect, 0.10))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(box, w * 0.14, h * 0.14)
    path = QPainterPath(rect.topLeft() + _pt(w * 0.40, h * 0.30))
    path.lineTo(rect.topLeft() + _pt(w * 0.40, h * 0.70))
    path.lineTo(rect.topLeft() + _pt(w * 0.70, h * 0.50))
    path.closeSubpath()
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawPath(path)


def _stop(painter: QPainter, rect: QRectF, color: QColor) -> None:
    w, h = rect.width(), rect.height()
    box = QRectF(rect.left() + w * 0.22, rect.top() + h * 0.22,
                 w * 0.56, h * 0.56)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(box, w * 0.10, h * 0.10)


def _reset(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """A circular arrow — the universal "start over"."""
    w, h = rect.width(), rect.height()
    inset = QRectF(rect.left() + w * 0.20, rect.top() + h * 0.20,
                   w * 0.60, h * 0.60)
    painter.setPen(_pen(color, rect, 0.13))
    painter.setBrush(Qt.NoBrush)
    # an open ring: leave a gap at the top-right for the arrowhead to sit in
    painter.drawArc(inset, 70 * 16, 300 * 16)
    head = QPainterPath(rect.topLeft() + _pt(w * 0.62, h * 0.10))
    head.lineTo(rect.topLeft() + _pt(w * 0.80, h * 0.22))
    head.lineTo(rect.topLeft() + _pt(w * 0.58, h * 0.34))
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawPath(head)


_GLYPHS = {
    "run_all": (_play, RUN),
    "run_selected": (_play_boxed, RUN),
    "cancel": (_stop, STOP),
    "reset_caches": (_reset, RESET),
}


def toolbar_icon(kind: str) -> QIcon:
    """The glyph named ``kind`` as a device-pixel-ratio-aware icon."""
    painter_fn, color = _GLYPHS[kind]
    icon = QIcon()
    for ratio in (1, 2):
        pixels = _ICON_PT * ratio
        pixmap = QPixmap(pixels, pixels)
        pixmap.fill(Qt.transparent)
        pixmap.setDevicePixelRatio(ratio)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing, True)
        painter_fn(p, QRectF(0, 0, _ICON_PT, _ICON_PT), color)
        p.end()
        icon.addPixmap(pixmap)
    return icon


def _stylesheet() -> str:
    c = theme.chrome
    return f"""
QToolBar#toolbar_main {{
    background: {c('bar_bg')};
    border: none;
    border-bottom: 1px solid {c('bar_border')};
    padding: 1px 3px;
    spacing: 1px;
}}
QToolBar#toolbar_main QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 3px 6px;
    color: {c('fg')};
    font-size: 9pt;
}}
QToolBar#toolbar_main QToolButton:hover {{
    background: {c('hover')};
    border-color: {c('outline')};
    color: {c('fg_strong')};
}}
QToolBar#toolbar_main QToolButton:pressed {{
    background: {c('pressed')};
}}
QToolBar#toolbar_main QToolButton:disabled {{
    color: {c('fg_disabled')};
}}
QToolBar#toolbar_main QToolButton::menu-indicator {{ image: none; }}
QToolBar#toolbar_main::separator {{
    background: {c('sep')};
    width: 1px;
    margin: 3px 5px;
}}
"""


def style_toolbar(toolbar) -> None:
    """Give the main toolbar its flat, rounded-button look and icon labels."""
    toolbar.setObjectName("toolbar_main")
    toolbar.setMovable(False)
    toolbar.setFloatable(False)
    toolbar.setIconSize(QSize(16, 16))
    toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    toolbar.setContentsMargins(0, 0, 0, 0)
    toolbar.setStyleSheet(_stylesheet())


# first in the listener order (this module is imported before any window
# exists), so the colours are right by the time a widget redraws from them
apply_mode()
theme.on_change(apply_mode)
