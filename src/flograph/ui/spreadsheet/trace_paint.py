"""Drawing Trace Precedents / Dependents over the grid: Excel's blue
arrows — a dot where an arrow starts, a head on the formula it points
into — and a box round each range a formula reads. What to draw is
core/sheet/trace.py's; this only turns cells into viewport pixels."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

ARROW = QColor("#60a5fa")


def _first_shown(view, start: int, end: int, rows: bool):
    hidden = view.isRowHidden if rows else view.isColumnHidden
    step = 1 if end >= start else -1
    for i in range(start, end + step, step):
        if not hidden(i):
            return i
    return None


def cell_rect(view, cell) -> QRect | None:
    r, c = cell
    if view.isRowHidden(r) or view.isColumnHidden(c):
        return None
    rect = view.visualRect(view.model().index(r, c))
    return rect if rect.isValid() else None


def box_rect(view, box) -> QRect | None:
    """The viewport rectangle round a range, its hidden edges skipped."""
    r1, c1, r2, c2 = box
    top = _first_shown(view, r1, r2, True)
    bottom = _first_shown(view, r2, r1, True)
    left = _first_shown(view, c1, c2, False)
    right = _first_shown(view, c2, c1, False)
    if None in (top, bottom, left, right):
        return None
    a, b = cell_rect(view, (top, left)), cell_rect(view, (bottom, right))
    if a is None or b is None:
        return None
    return a.united(b)


def _head(painter: QPainter, tip: QPointF, angle: float) -> None:
    size, spread = 7.0, math.radians(24)
    left = QPointF(tip.x() - size * math.cos(angle - spread),
                   tip.y() - size * math.sin(angle - spread))
    right = QPointF(tip.x() - size * math.cos(angle + spread),
                    tip.y() - size * math.sin(angle + spread))
    painter.drawPolygon(QPolygonF([tip, left, right]))


def paint_trace(view, trace) -> None:
    painter = QPainter(view.viewport())
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(ARROW, 1.5)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    for box in trace.boxes:
        rect = box_rect(view, box)
        if rect is not None:
            painter.drawRect(QRectF(rect).adjusted(1, 1, -1, -1))
    painter.setBrush(ARROW)
    for arrow in trace.arrows:
        if arrow.source == arrow.target:
            continue
        target = cell_rect(view, arrow.target)
        if arrow.box is not None:
            from_rect = box_rect(view, arrow.box)
        else:
            from_rect = cell_rect(view, arrow.source)
        if target is None or from_rect is None:
            continue
        start = QPointF(from_rect.center())
        end = QPointF(target.center())
        if arrow.box is not None:
            # from the box's edge nearest the formula, not from inside it
            start = QPointF(
                min(max(end.x(), from_rect.left()), from_rect.right()),
                min(max(end.y(), from_rect.top()), from_rect.bottom()))
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        painter.drawLine(start, end)
        painter.drawEllipse(start, 2.5, 2.5)
        _head(painter, end, angle)
    painter.end()
