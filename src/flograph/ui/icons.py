"""Painted glyph icons for the node library and node headers.

No asset files: every icon is drawn with QPainter into a small pixmap on
first use and cached. One consistent colour (the theme's subtext grey) so
a glyph reads the same on the dark library tree, the palette popup and a
canvas node header.

Which glyph a node gets: the most specific thing about it wins. A rich-card
node (`spec.card`) shows the shape of that card (table, chart, kpi...); an
ordinary node falls back to its category. The mapping is keyed by string so
a new card kind needs no code change beyond a painter in this module.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from flograph.core.node import NodeSpec

# logical icon size; the pixmap is drawn at 2x for HiDPI and Qt down-samples
ICON_SIZE = 14
_DPR = 2.0

_COLOR = QColor("#aab0bd")


def _pixmap(paint: Callable[[QPainter], None]) -> QIcon:
    pm = QPixmap(int(ICON_SIZE * _DPR), int(ICON_SIZE * _DPR))
    pm.setDevicePixelRatio(_DPR)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.scale(_DPR, _DPR)
    painter.setRenderHint(QPainter.Antialiasing, True)
    paint(painter)
    painter.end()
    return QIcon(pm)


def _pen(painter: QPainter, width: float = 1.3) -> None:
    painter.setPen(QPen(_COLOR, width))
    painter.setBrush(Qt.NoBrush)


def _fill(painter: QPainter) -> None:
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(_COLOR))


# ---------------------------------------------------------------- card glyphs

def _paint_table(p: QPainter) -> None:
    _pen(p)
    p.drawRect(QRectF(2, 2, 10, 10))
    p.drawLine(QPointF(2, 5.5), QPointF(12, 5.5))
    p.drawLine(QPointF(6.5, 2), QPointF(6.5, 12))


def _paint_grid(p: QPainter) -> None:
    _pen(p)
    p.drawRect(QRectF(2, 2, 10, 10))
    p.drawLine(QPointF(2, 6.5), QPointF(12, 6.5))
    p.drawLine(QPointF(6.5, 2), QPointF(6.5, 12))


def _paint_chart(p: QPainter) -> None:
    _pen(p)
    path = QPainterPath(QPointF(2, 10))
    path.lineTo(5, 10)
    path.lineTo(6.5, 6)
    path.lineTo(8.5, 8)
    path.lineTo(12, 3)
    p.drawPath(path)
    _fill(p)
    p.drawEllipse(QPointF(12, 3), 1.2, 1.2)


def _paint_report(p: QPainter) -> None:
    _pen(p)
    p.drawRect(QRectF(2.5, 2, 9, 10))
    p.drawLine(QPointF(4.5, 5), QPointF(9.5, 5))
    p.drawLine(QPointF(4.5, 7), QPointF(9.5, 7))
    p.drawLine(QPointF(4.5, 9), QPointF(7.5, 9))


def _paint_kpi(p: QPainter) -> None:
    _pen(p)
    p.drawRect(QRectF(2, 2, 10, 10))
    for x in (5.0, 7.5, 10.0):
        p.drawLine(QPointF(x - 0.75, 8), QPointF(x + 0.75, 8))
        p.drawLine(QPointF(x, 5.5), QPointF(x, 8))
        p.drawLine(QPointF(x - 0.75, 5.5), QPointF(x, 5.5))


def _paint_slicer(p: QPainter) -> None:
    _pen(p, 2.2)
    p.drawLine(QPointF(2, 9), QPointF(12, 9))
    _fill(p)
    p.drawEllipse(QRectF(6, 6, 3, 3))


def _paint_button(p: QPainter) -> None:
    _pen(p)
    p.drawRoundedRect(QRectF(2, 2, 10, 10), 3, 3)
    _fill(p)
    path = QPainterPath(QPointF(6, 4.5))
    path.lineTo(6, 9.5)
    path.lineTo(9, 7)
    path.closeSubpath()
    p.setPen(Qt.NoPen)
    p.drawPath(path)


def _paint_note(p: QPainter) -> None:
    _pen(p)
    p.drawRect(QRectF(2.5, 2, 9, 10))
    path = QPainterPath(QPointF(8, 2))
    path.lineTo(11.5, 5.5)
    path.lineTo(8, 5.5)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(8, 2), QPointF(8, 5.5))


def _paint_diamond(p: QPainter) -> None:
    _fill(p)
    path = QPainterPath(QPointF(7, 2))
    path.lineTo(12, 7)
    path.lineTo(7, 12)
    path.lineTo(2, 7)
    path.closeSubpath()
    p.drawPath(path)


def _paint_goto(p: QPainter) -> None:
    _pen(p)
    p.drawRect(QRectF(2, 3, 6, 8))
    path = QPainterPath(QPointF(9.5, 4))
    path.lineTo(12, 7)
    path.lineTo(9.5, 10)
    p.drawPath(path)


def _paint_from(p: QPainter) -> None:
    _pen(p)
    p.drawRect(QRectF(6, 3, 6, 8))
    path = QPainterPath(QPointF(4.5, 4))
    path.lineTo(2, 7)
    path.lineTo(4.5, 10)
    p.drawPath(path)


def _paint_toggle(p: QPainter) -> None:
    _pen(p)
    p.drawRoundedRect(QRectF(2, 5, 10, 4), 2, 2)
    _fill(p)
    p.drawEllipse(QRectF(8, 4, 2.5, 2.5))


def _paint_webview(p: QPainter) -> None:
    _pen(p)
    p.drawRect(QRectF(2, 3, 10, 8.5))
    p.drawLine(QPointF(2, 5), QPointF(12, 5))
    p.drawLine(QPointF(4, 3), QPointF(4, 5))


def _paint_arrow_up(p: QPainter) -> None:
    _fill(p)
    path = QPainterPath(QPointF(7, 2.5))
    path.lineTo(12, 7)
    path.lineTo(8.5, 7)
    path.lineTo(8.5, 11)
    path.lineTo(5.5, 11)
    path.lineTo(5.5, 7)
    path.lineTo(2, 7)
    path.closeSubpath()
    p.drawPath(path)


def _paint_arrow_down(p: QPainter) -> None:
    _fill(p)
    path = QPainterPath(QPointF(7, 11.5))
    path.lineTo(12, 7)
    path.lineTo(8.5, 7)
    path.lineTo(8.5, 3)
    path.lineTo(5.5, 3)
    path.lineTo(5.5, 7)
    path.lineTo(2, 7)
    path.closeSubpath()
    p.drawPath(path)


def _paint_io(p: QPainter) -> None:
    _pen(p)
    path = QPainterPath(QPointF(7, 3))
    path.lineTo(11, 7)
    path.lineTo(8, 7)
    path.lineTo(8, 10)
    path.lineTo(6, 10)
    path.lineTo(6, 7)
    path.lineTo(3, 7)
    path.closeSubpath()
    p.drawPath(path)


# ---------------------------------------------------------- category glyphs

def _paint_input(p: QPainter) -> None:
    _pen(p)
    p.drawRoundedRect(QRectF(2, 3, 10, 8), 1.5, 1.5)
    p.drawLine(QPointF(7, 4), QPointF(7, 9))
    p.drawLine(QPointF(5, 7), QPointF(9, 7))


def _paint_transform(p: QPainter) -> None:
    _pen(p)
    path = QPainterPath(QPointF(2, 2))
    path.lineTo(12, 2)
    path.lineTo(8.5, 6.5)
    path.lineTo(8.5, 12)
    path.lineTo(5.5, 12)
    path.lineTo(5.5, 6.5)
    path.closeSubpath()
    p.drawPath(path)


def _paint_viz(p: QPainter) -> None:
    _fill(p)
    p.drawRect(QRectF(2, 8, 2.5, 4))
    p.drawRect(QRectF(5.75, 5, 2.5, 7))
    p.drawRect(QRectF(9.5, 2, 2.5, 10))


def _paint_util(p: QPainter) -> None:
    _pen(p)
    p.drawEllipse(QPointF(7, 7), 4.5, 4.5)
    p.drawEllipse(QPointF(7, 7), 1.2, 1.2)


def _paint_scripting(p: QPainter) -> None:
    _pen(p)
    path = QPainterPath(QPointF(4, 2))
    path.lineTo(2, 7)
    path.lineTo(4, 12)
    p.drawPath(path)
    path = QPainterPath(QPointF(10, 2))
    path.lineTo(12, 7)
    path.lineTo(10, 12)
    p.drawPath(path)
    p.drawLine(QPointF(8, 3.5), QPointF(6, 10.5))


def _paint_folder(p: QPainter) -> None:
    _pen(p)
    path = QPainterPath(QPointF(2, 4))
    path.lineTo(2, 11)
    path.lineTo(12, 11)
    path.lineTo(12, 5.5)
    path.lineTo(6.5, 5.5)
    path.lineTo(5.5, 4)
    path.closeSubpath()
    p.drawPath(path)


# card glyphs override category glyphs; key = spec.card or spec.category
_GLYPHS: dict[str, Callable[[QPainter], None]] = {
    "table_viewer": _paint_table,
    "grid": _paint_grid,
    "figure": _paint_chart,
    "report": _paint_report,
    "kpi": _paint_kpi,
    "slicer": _paint_slicer,
    "button": _paint_button,
    "note": _paint_note,
    "reroute": _paint_diamond,
    "goto": _paint_goto,
    "from": _paint_from,
    "control": _paint_toggle,
    "webview": _paint_webview,
    # category fallbacks
    "input": _paint_input,
    "io": _paint_io,
    "transform": _paint_transform,
    "viz": _paint_viz,
    "util": _paint_util,
    "scripting": _paint_scripting,
    "user": _paint_folder,
}

_cache: dict[str, QIcon] = {}


def glyph_icon(key: str) -> QIcon:
    """Icon for a card kind, category, or 'user'. Painted once, cached forever."""
    painter = _GLYPHS.get(key)
    if painter is None:
        painter = _paint_util
    icon = _cache.get(key)
    if icon is None:
        icon = _pixmap(painter)
        _cache[key] = icon
    return icon


def spec_icon(spec: NodeSpec) -> QIcon:
    """The most specific glyph for a node: its card kind if it has one,
    else its category. User-authored nodes get the folder regardless."""
    if not spec.builtin:
        return glyph_icon("user")
    if spec.card:
        return glyph_icon(spec.card)
    return glyph_icon(spec.category)
