"""Comment frames: translucent labeled regions that move their contained
nodes with them."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QInputDialog

from flograph.core import Frame

from .. import theme
from .grid import EDGE_MARGIN, grid_step, snap, snap_point, snapping_active

TITLE_H = 24.0
HANDLE = 14.0
RUN_BTN = 18.0


class FrameItem(QGraphicsObject):
    run_requested = Signal(str)  # frame_id — the run glyph was clicked

    def __init__(self, frame: Frame) -> None:
        super().__init__()
        self.frame = frame
        self.setZValue(-10)
        self.setFlags(QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        # set before setPos — ItemSendsGeometryChanges makes setPos fire
        # itemChange, which reads _dragging
        self._dragging = False  # a move is in progress (snap gate)
        self.setPos(frame.rect[0], frame.rect[1])
        self._size = (frame.rect[2], frame.rect[3])
        self._resizing = False
        self._resize_edge = "corner"  # which edge/corner the drag grabbed
        self._press_scene_pos = QPointF()
        self._press_size = self._size
        self._press_pos = QPointF()
        self._grabbed: list = []  # (node_item, offset)
        self._group_starts: dict | None = None  # multi-selection drag snapshot
        self._hover_run = False
        self._run_pressed = False

    # ------------------------------------------------------------- geometry

    def sync_from_model(self) -> None:
        x, y, w, h = self.frame.rect
        self.prepareGeometryChange()
        if (self.pos().x(), self.pos().y()) != (x, y):
            self.setPos(x, y)
        self._size = (w, h)
        self.update()

    def scene_rect(self) -> QRectF:
        return QRectF(self.pos().x(), self.pos().y(), *self._size)

    def boundingRect(self) -> QRectF:
        return QRectF(-1, -1, self._size[0] + 2, self._size[1] + 2)

    def _handle_rect(self) -> QRectF:
        w, h = self._size
        return QRectF(w - HANDLE, h - HANDLE, HANDLE, HANDLE)

    def _edge_at(self, pos: QPointF) -> str | None:
        """Which resize edge/corner (if any) a point grabs: "right",
        "bottom", "left", "corner" (bottom-right), or None."""
        w, h = self._size
        near_right = w - EDGE_MARGIN <= pos.x() <= w + EDGE_MARGIN
        near_bottom = h - EDGE_MARGIN <= pos.y() <= h + EDGE_MARGIN
        near_left = -EDGE_MARGIN <= pos.x() <= EDGE_MARGIN
        within_h = -EDGE_MARGIN <= pos.y() <= h + EDGE_MARGIN
        within_w = -EDGE_MARGIN <= pos.x() <= w + EDGE_MARGIN
        if self._handle_rect().contains(pos) or (near_right and near_bottom):
            return "corner"
        if near_right and within_h:
            return "right"
        if near_bottom and within_w:
            return "bottom"
        if near_left and within_h:
            return "left"
        return None

    def _run_button_rect(self) -> QRectF:
        w, _h = self._size
        return QRectF(w - RUN_BTN - 4.0, (TITLE_H - RUN_BTN) / 2, RUN_BTN, RUN_BTN)

    # ------------------------------------------------------------- painting

    def paint(self, painter: QPainter, option, widget=None) -> None:
        w, h = self._size
        body = QRectF(0, 0, w, h)
        color = QColor(self.frame.color)
        fill = QColor(color)
        fill.setAlphaF(0.18)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(theme.SELECTION_OUTLINE if self.isSelected()
                            else color, 1.5))
        painter.drawRoundedRect(body, 6, 6)

        title_bg = QColor(color)
        title_bg.setAlphaF(0.45)
        painter.setBrush(QBrush(title_bg))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(0, 0, w, TITLE_H), 6, 6)

        painter.setPen(QPen(theme.FRAME_TITLE))
        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(9.0)
        painter.setFont(font)
        painter.drawText(QRectF(10, 0, w - 20 - RUN_BTN - 6, TITLE_H),
                         Qt.AlignVCenter | Qt.AlignLeft, self.frame.title)

        btn = self._run_button_rect()
        chip = QColor(color)
        chip.setAlphaF(0.65 if self._hover_run else 0.4)
        painter.setBrush(QBrush(chip))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(btn, 4, 4)
        painter.setBrush(QBrush(theme.FRAME_TITLE))
        tri = QPainterPath()
        cx, cy = btn.center().x(), btn.center().y()
        tri.moveTo(cx - 3, cy - 5)
        tri.lineTo(cx - 3, cy + 5)
        tri.lineTo(cx + 5, cy)
        tri.closeSubpath()
        painter.drawPath(tri)

        painter.setPen(QPen(color, 1.2))
        hr = self._handle_rect()
        for i in (4.0, 8.0, 12.0):
            painter.drawLine(QPointF(hr.right() - i, hr.bottom() - 2),
                             QPointF(hr.right() - 2, hr.bottom() - i))

    # ------------------------------------------------------------ behaviour

    def hoverMoveEvent(self, event) -> None:
        hovering = self._run_button_rect().contains(event.pos())
        if hovering != self._hover_run:
            self._hover_run = hovering
            self.setToolTip("Run the nodes in this frame" if hovering else "")
            self.update()
        if hovering:
            self.setCursor(Qt.PointingHandCursor)
        else:
            edge = self._edge_at(event.pos())
            if edge == "corner":
                self.setCursor(Qt.SizeFDiagCursor)
            elif edge in ("right", "left"):
                self.setCursor(Qt.SizeHorCursor)
            elif edge == "bottom":
                self.setCursor(Qt.SizeVerCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        if self._hover_run:
            self._hover_run = False
            self.update()
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self._dragging \
                and snapping_active(self.scene()):
            step = grid_step(self.scene())
            x, y = snap_point(value.x(), value.y(), step)
            return QPointF(x, y)
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        if self._run_button_rect().contains(event.pos()):
            # emit on release, button-style; without swallowing the drag
            # here a slightly sloppy click would also move the frame
            self._run_pressed = True
            event.accept()
            return
        self._press_scene_pos = event.scenePos()
        self._press_pos = self.pos()
        self._press_size = self._size
        edge = self._edge_at(event.pos())
        if edge is not None:
            self._resizing = True
            self._resize_edge = edge
            event.accept()
            return
        scene = self.scene()
        self._grabbed = []
        if (event.button() == Qt.LeftButton and self.isSelected()
                and scene is not None and len(scene._selected_movables()) > 1):
            # Part of a multi-selection: move as a uniform group so every
            # selected node/frame snaps and commits together. Skip the
            # content-grab — a node that's both inside and independently
            # selected would otherwise be moved twice.
            super().mousePressEvent(event)
            self._group_starts = scene.begin_group_drag()
            return
        # Single-frame drag: carry the nodes whose centers sit inside.
        rect = self.scene_rect()
        for item in scene.node_items.values():
            if rect.contains(item.sceneBoundingRect().center()):
                self._grabbed.append((item, item.pos() - self.pos()))
        if event.button() == Qt.LeftButton:
            self._dragging = True  # snap the frame's position while moving
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._run_pressed:
            event.accept()
            return
        if self._resizing:
            delta = event.scenePos() - self._press_scene_pos
            edge = self._resize_edge
            press_w, press_h = self._press_size
            width, height = press_w, press_h
            if edge in ("right", "corner"):
                width = press_w + delta.x()
            if edge in ("bottom", "corner"):
                height = press_h + delta.y()
            if edge == "left":
                width = press_w - delta.x()
            if snapping_active(self.scene(), event.modifiers()):
                step = grid_step(self.scene())
                width = snap(width, step)
                height = snap(height, step)
            width = max(120.0, width)
            height = max(60.0, height)
            if edge == "left":
                self.setPos(self._press_pos.x() + press_w - width,
                           self.pos().y())
            self.prepareGeometryChange()
            self._size = (width, height)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)
        for item, offset in self._grabbed:
            item.setPos(self.pos() + offset)

    def mouseReleaseEvent(self, event) -> None:
        scene = self.scene()
        self._dragging = False
        if self._run_pressed:
            self._run_pressed = False
            if self._run_button_rect().contains(event.pos()):
                self.run_requested.emit(self.frame.id)
            event.accept()
            return
        if self._resizing:
            self._resizing = False
            self._resize_edge = None
            scene.push_frame_rect(self.frame.id, self.pos(), self._size)
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if self._group_starts is not None:
            # Multi-selection drag: the scene commits the whole selection.
            scene.commit_group_move(self._group_starts)
            self._group_starts = None
            return
        if self.pos() != self._press_pos:
            moves = {}
            for item, offset in self._grabbed:
                old = self._press_pos + offset
                moves[item.node.id] = ((old.x(), old.y()),
                                       (item.pos().x(), item.pos().y()))
            scene.push_frame_move(self.frame.id, self.pos(), self._size,
                                  moves)
        self._grabbed = []

    def mouseDoubleClickEvent(self, event) -> None:
        if self._run_button_rect().contains(event.pos()):
            event.accept()
            return
        title, ok = QInputDialog.getText(None, "Frame title", "Title:",
                                         text=self.frame.title)
        if ok and title.strip():
            self.scene().push_frame_title(self.frame.id, title.strip())
        event.accept()
