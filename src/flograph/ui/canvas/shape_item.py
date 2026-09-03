"""Whiteboard shapes on the model canvas — rectangles, ellipses, diamonds,
triangles, lines, arrows and text labels.

A `ShapeItem` draws one `core.graph.Shape`. It is not a node and not a frame:
it has no ports, no run state and the engine never sees it. Frames group the
flow and sit behind it; a shape annotates the canvas and — via the shape's
`behind` flag — can sit either side of the nodes (see `stacking.py`).

Geometry, style and text all commit through `UpdateShapeCommand`, one command
per finished gesture, exactly as `FrameItem` commits through
`UpdateFrameCommand`. `rect` is always a normalised box; for a line or arrow
the two endpoints are that box's diagonal, `flip` choosing which one.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF,
)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QInputDialog

from flograph.core import Shape

from .. import theme
from .stacking import SHAPE_BACK_Z, SHAPE_FRONT_Z, z_for

#: Half-width of a resize / endpoint handle, in scene units.
HANDLE = 5.0
#: Smallest box a resize drag will leave.
MIN_SIZE = 12.0

BOX_KINDS = ("rect", "rounded", "ellipse", "diamond", "triangle", "text")
LINE_KINDS = ("line", "arrow")

#: Human labels, shared by the menus, the tool rail and the Selection pane.
KIND_LABELS = {
    "rect": "Rectangle",
    "rounded": "Rounded Rectangle",
    "ellipse": "Ellipse",
    "diamond": "Diamond",
    "triangle": "Triangle",
    "line": "Line",
    "arrow": "Arrow",
    "text": "Text",
}

#: The eight box handles, as (x, y) in unit coordinates of the box.
_BOX_HANDLES = ((0, 0), (0.5, 0), (1, 0), (1, 0.5),
                (1, 1), (0.5, 1), (0, 1), (0, 0.5))
_BOX_CURSORS = (Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor,
                Qt.SizeHorCursor, Qt.SizeFDiagCursor, Qt.SizeVerCursor,
                Qt.SizeBDiagCursor, Qt.SizeHorCursor)

_ARROW_HEAD = 13.0
_ARROW_HALF = 0.42


class ShapeItem(QGraphicsObject):
    def __init__(self, shape: Shape) -> None:
        super().__init__()
        self.shape_model = shape
        self.setFlags(QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self._dragging = False        # group-drag flag (see scene)
        self._group_starts: Optional[dict] = None
        self._w = float(shape.rect[2])
        self._h = float(shape.rect[3])
        self.setPos(shape.rect[0], shape.rect[1])
        self.apply_stacking()
        self.setVisible(not shape.hidden)
        self._grab: Optional[int] = None      # index of the handle being dragged
        self._press_pos = QPointF()
        self._press_size = (self._w, self._h)
        self._press_scene = QPointF()
        self._press_flip = shape.flip
        self._moved = False

    # ---------------------------------------------------------- model sync

    def sync_from_model(self) -> None:
        s = self.shape_model
        self.prepareGeometryChange()
        self._w, self._h = float(s.rect[2]), float(s.rect[3])
        if (self.pos().x(), self.pos().y()) != (s.rect[0], s.rect[1]):
            self.setPos(s.rect[0], s.rect[1])
        self.apply_stacking()
        self.setVisible(not s.hidden)
        self.update()

    def apply_stacking(self) -> None:
        band = SHAPE_BACK_Z if self.shape_model.behind else SHAPE_FRONT_Z
        self.setZValue(z_for(band, self.shape_model.z))

    # --------------------------------------------------------------- paint

    def _stroke_color(self) -> QColor:
        s = self.shape_model
        return QColor(s.stroke) if s.stroke else QColor(theme.NODE_TEXT)

    def _text_color(self) -> QColor:
        s = self.shape_model
        if s.text_color:
            return QColor(s.text_color)
        if s.stroke and s.kind != "text":
            return QColor(s.stroke)
        return QColor(theme.NODE_TEXT)

    def _fill_brush(self):
        s = self.shape_model
        return QBrush(QColor(s.fill)) if s.fill else Qt.NoBrush

    def _pen(self) -> QPen:
        s = self.shape_model
        pen = QPen(self._stroke_color(),
                   max(0.5, float(s.stroke_width)))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        if s.dashed:
            pen.setStyle(Qt.DashLine)
        return pen

    def _pad(self) -> float:
        return HANDLE + max(2.0, self.shape_model.stroke_width) + 1.0

    def boundingRect(self) -> QRectF:
        pad = self._pad()
        return QRectF(-pad, -pad, self._w + 2 * pad, self._h + 2 * pad)

    def _endpoints(self) -> tuple[QPointF, QPointF]:
        if self.shape_model.flip:
            return QPointF(0, self._h), QPointF(self._w, 0)
        return QPointF(0, 0), QPointF(self._w, self._h)

    def shape(self) -> QPainterPath:  # hit area
        from PySide6.QtGui import QPainterPathStroker
        s = self.shape_model
        if s.kind in LINE_KINDS:
            a, b = self._endpoints()
            seg = QPainterPath(a)
            seg.lineTo(b)
            pen = QPen(Qt.black, max(10.0, s.stroke_width + 8))
            return QPainterPathStroker(pen).createStroke(seg)
        outline = self._box_path()
        # A filled or labelled box grabs its whole area, like a frame body; an
        # empty outline grabs only its border, so an annotation rectangle
        # drawn around some nodes doesn't swallow every click inside it.
        if s.fill or s.text or s.kind == "text" or self.isSelected():
            return outline
        pen = QPen(Qt.black, max(10.0, s.stroke_width + 8))
        band = QPainterPathStroker(pen).createStroke(outline)
        for p in self._handle_points():
            band.addRect(QRectF(p.x() - HANDLE, p.y() - HANDLE,
                                2 * HANDLE, 2 * HANDLE))
        return band

    def _box_path(self) -> QPainterPath:
        w, h, path = self._w, self._h, QPainterPath()
        kind = self.shape_model.kind
        if kind == "ellipse":
            path.addEllipse(0, 0, w, h)
        elif kind == "rounded":
            r = min(w, h) * 0.18
            path.addRoundedRect(0, 0, w, h, r, r)
        elif kind == "diamond":
            path.addPolygon(QPolygonF([
                QPointF(w / 2, 0), QPointF(w, h / 2),
                QPointF(w / 2, h), QPointF(0, h / 2)]))
            path.closeSubpath()
        elif kind == "triangle":
            path.addPolygon(QPolygonF([
                QPointF(w / 2, 0), QPointF(w, h), QPointF(0, h)]))
            path.closeSubpath()
        else:  # rect, text
            path.addRect(0, 0, w, h)
        return path

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        s = self.shape_model
        if s.kind in LINE_KINDS:
            self._paint_line(painter)
        elif s.kind == "text":
            if s.fill:
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._fill_brush())
                painter.drawRect(QRectF(0, 0, self._w, self._h))
            self._paint_text(painter)
        else:
            path = self._box_path()
            painter.setPen(self._pen())
            painter.setBrush(self._fill_brush())
            painter.drawPath(path)
            self._paint_text(painter)
        if self.isSelected():
            self._paint_selection(painter)

    def _paint_line(self, painter: QPainter) -> None:
        a, b = self._endpoints()
        painter.setPen(self._pen())
        painter.drawLine(a, b)
        if self.shape_model.kind == "arrow":
            line = QLineF(a, b)
            if line.length() < 1e-6:
                return
            u = QPointF(line.dx() / line.length(), line.dy() / line.length())
            n = QPointF(-u.y(), u.x())
            base = QPointF(b.x() - u.x() * _ARROW_HEAD,
                           b.y() - u.y() * _ARROW_HEAD)
            half = _ARROW_HEAD * _ARROW_HALF
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(self._stroke_color()))
            painter.drawPolygon(QPolygonF([
                b,
                QPointF(base.x() + n.x() * half, base.y() + n.y() * half),
                QPointF(base.x() - n.x() * half, base.y() - n.y() * half)]))

    def _paint_text(self, painter: QPainter) -> None:
        s = self.shape_model
        if not s.text:
            return
        font = QFont()
        if s.font_size > 0:
            font.setPointSizeF(s.font_size)
        painter.setFont(font)
        painter.setPen(QPen(self._text_color()))
        inset = 6.0
        rect = QRectF(inset, inset,
                      max(1.0, self._w - 2 * inset),
                      max(1.0, self._h - 2 * inset))
        painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, s.text)

    def _handle_points(self) -> list[QPointF]:
        if self.shape_model.kind in LINE_KINDS:
            a, b = self._endpoints()
            return [a, b]
        return [QPointF(ux * self._w, uy * self._h)
                for ux, uy in _BOX_HANDLES]

    def _paint_selection(self, painter: QPainter) -> None:
        pen = QPen(theme.SELECTION_OUTLINE, 1.0, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if self.shape_model.kind not in LINE_KINDS:
            painter.drawRect(QRectF(0, 0, self._w, self._h))
        painter.setPen(QPen(theme.SELECTION_OUTLINE, 1.0))
        painter.setBrush(QBrush(QColor("#1b1c20")))
        for p in self._handle_points():
            painter.drawRect(QRectF(p.x() - HANDLE, p.y() - HANDLE,
                                    2 * HANDLE, 2 * HANDLE))

    # --------------------------------------------------------------- mouse

    def _handle_at(self, pos: QPointF) -> Optional[int]:
        if not self.isSelected():
            return None
        for i, p in enumerate(self._handle_points()):
            if (abs(pos.x() - p.x()) <= HANDLE + 1
                    and abs(pos.y() - p.y()) <= HANDLE + 1):
                return i
        return None

    def hoverMoveEvent(self, event) -> None:
        i = self._handle_at(event.pos())
        if i is None:
            self.unsetCursor()
        elif self.shape_model.kind in LINE_KINDS:
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(_BOX_CURSORS[i])
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._press_pos = self.pos()
        self._press_size = (self._w, self._h)
        self._press_scene = event.scenePos()
        self._press_flip = self.shape_model.flip
        self._moved = False
        self._grab = self._handle_at(event.pos())
        if self._grab is not None:
            event.accept()
            return
        scene = self.scene()
        if (event.button() == Qt.LeftButton and self.isSelected()
                and scene is not None
                and len(scene._selected_movables()) > 1):
            super().mousePressEvent(event)
            self._group_starts = scene.begin_group_drag()
            return
        self._dragging = event.button() == Qt.LeftButton
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._grab is None:
            super().mouseMoveEvent(event)
            return
        self._moved = True
        parent_pos = event.scenePos()   # scene == parent for a top-level item
        if self.shape_model.kind in LINE_KINDS:
            self._drag_endpoint(parent_pos)
        else:
            self._drag_box_handle(parent_pos)
        event.accept()

    def _drag_endpoint(self, parent_pos: QPointF) -> None:
        a, b = self._endpoints()
        a = a + self._press_pos
        b = b + self._press_pos
        if self._grab == 0:
            a = parent_pos
        else:
            b = parent_pos
        x0, x1 = sorted((a.x(), b.x()))
        y0, y1 = sorted((a.y(), b.y()))
        w = max(MIN_SIZE, x1 - x0)
        h = max(1.0, y1 - y0)
        flip = (a.x() < b.x()) != (a.y() < b.y())
        self.prepareGeometryChange()
        self.setPos(x0, y0)
        self._w, self._h = w, h
        self.shape_model.flip = flip
        self.update()

    def _drag_box_handle(self, parent_pos: QPointF) -> None:
        ux, uy = _BOX_HANDLES[self._grab]
        px, py = self._press_pos.x(), self._press_pos.y()
        pw, ph = self._press_size
        left, top, right, bottom = px, py, px + pw, py + ph
        if ux == 0:
            left = min(parent_pos.x(), right - MIN_SIZE)
        elif ux == 1:
            right = max(parent_pos.x(), left + MIN_SIZE)
        if uy == 0:
            top = min(parent_pos.y(), bottom - MIN_SIZE)
        elif uy == 1:
            bottom = max(parent_pos.y(), top + MIN_SIZE)
        self.prepareGeometryChange()
        self.setPos(left, top)
        self._w, self._h = right - left, bottom - top
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        scene = self.scene()
        if self._group_starts is not None and scene is not None:
            scene.commit_group_move(self._group_starts)
            self._group_starts = None
            self._dragging = False
            super().mouseReleaseEvent(event)
            return
        if self._grab is not None:
            self._grab = None
            if self._moved and scene is not None:
                scene.push_shape_rect(self.shape_model.id, self.pos(),
                                      (self._w, self._h),
                                      flip=self.shape_model.flip)
            event.accept()
            return
        self._dragging = False
        super().mouseReleaseEvent(event)
        if scene is not None and self.pos() != self._press_pos:
            scene.push_shape_rect(self.shape_model.id, self.pos(),
                                  (self._w, self._h))

    def mouseDoubleClickEvent(self, event) -> None:
        if self.shape_model.kind in LINE_KINDS:
            super().mouseDoubleClickEvent(event)
            return
        scene = self.scene()
        text, ok = QInputDialog.getMultiLineText(
            None, "Shape text", "Label:", self.shape_model.text)
        if ok and scene is not None and text != self.shape_model.text:
            scene.push_shape_text(self.shape_model.id, text)
        event.accept()
